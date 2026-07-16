import json

from vouch.ingest import load_claude_code


def _write_transcript(base, project, name, records):
    d = base / project
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.jsonl").write_text(
        "\n".join(json.dumps(r) for r in records) + "\n"
    )


def _assistant(uuid, parent, model="claude-opus-4-8", text="ok", sidechain=False):
    rec = {
        "type": "assistant",
        "uuid": uuid,
        "parentUuid": parent,
        "sessionId": "s1",
        "timestamp": "2026-07-16T10:00:00Z",
        "message": {
            "model": model,
            "content": [{"type": "text", "text": text}],
            "usage": {
                "input_tokens": 100,
                "cache_read_input_tokens": 900,
                "output_tokens": 50,
            },
        },
    }
    if sidechain:
        rec["isSidechain"] = True
    return rec


def _user(uuid, parent, text):
    return {
        "type": "user",
        "uuid": uuid,
        "parentUuid": parent,
        "message": {"role": "user", "content": text},
    }


def test_main_loop_command_and_sidechain_hints(tmp_path):
    records = [
        _user("u1", None, "fix the bug in auth.py"),
        _assistant("a1", "u1"),
        _user("u2", "a1", "<command-name>/code-review</command-name> args"),
        _assistant("a2", "u2"),
    ]
    _write_transcript(tmp_path, "proj-main", "t1", records)

    sidechain = [
        _user("su1", None, "Explore the codebase at /tmp/foo"),
        _assistant("sa1", "su1", sidechain=True),
    ]
    _write_transcript(tmp_path, "proj-side", "t2", sidechain)

    out = load_claude_code(str(tmp_path))
    hints = sorted(r.task_hint for r in out)
    assert hints == ["agent:explore", "command:code-review", "main:agentic-loop"]

    main = next(r for r in out if r.task_hint == "main:agentic-loop")
    assert main.input_tokens == 1000  # includes cached tokens
    assert main.output_tokens == 50
    assert main.model == "claude-opus-4-8"


def test_synthetic_and_non_assistant_records_skipped(tmp_path):
    records = [
        _user("u1", None, "hello"),
        _assistant("a1", "u1", model="<synthetic>"),
        {"type": "summary", "uuid": "x"},
    ]
    _write_transcript(tmp_path, "proj", "t", records)
    assert load_claude_code(str(tmp_path)) == []
