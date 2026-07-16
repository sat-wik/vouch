from vouch.capture import (
    accumulate_anthropic,
    accumulate_openai_chat,
    accumulate_openai_responses,
)


def test_accumulate_openai_chat_stream():
    raw = "\n".join(
        [
            'data: {"model": "gpt-4o", "choices": [{"delta": {"role": "assistant"}}]}',
            'data: {"model": "gpt-4o", "choices": [{"delta": {"content": "Hel"}}]}',
            'data: {"model": "gpt-4o", "choices": [{"delta": {"content": "lo"}}]}',
            'data: {"model": "gpt-4o", "choices": [], "usage": {"prompt_tokens": 9, "completion_tokens": 2}}',
            "data: [DONE]",
        ]
    )
    out = accumulate_openai_chat(raw)
    assert out["choices"][0]["message"]["content"] == "Hello"
    assert out["model"] == "gpt-4o"
    assert out["usage"]["prompt_tokens"] == 9


def test_accumulate_anthropic_stream():
    raw = "\n".join(
        [
            'data: {"type": "message_start", "message": {"model": "claude-opus-4-8", "usage": {"input_tokens": 12}}}',
            'data: {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}',
            'data: {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Bonj"}}',
            'data: {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "our"}}',
            'data: {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 4}}',
            'data: {"type": "message_stop"}',
        ]
    )
    out = accumulate_anthropic(raw)
    assert out["content"][0]["text"] == "Bonjour"
    assert out["model"] == "claude-opus-4-8"
    assert out["usage"] == {"input_tokens": 12, "output_tokens": 4}


def test_accumulate_responses_stream_prefers_completed_object():
    raw = "\n".join(
        [
            'data: {"type": "response.output_text.delta", "delta": "par"}',
            'data: {"type": "response.output_text.delta", "delta": "tial"}',
            'data: {"type": "response.completed", "response": {"output_text": "full text", "usage": {"input_tokens": 5}}}',
        ]
    )
    out = accumulate_openai_responses(raw)
    assert out["output_text"] == "full text"


def test_accumulate_responses_stream_falls_back_to_deltas():
    raw = 'data: {"type": "response.output_text.delta", "delta": "only deltas"}'
    assert accumulate_openai_responses(raw)["output_text"] == "only deltas"


def test_captured_records_are_ingestable(tmp_path):
    """The whole point of Tollgate: what it writes, `vouch analyze --logs` reads."""
    from vouch.capture import log_record
    from vouch.ingest import load_openai_jsonl

    path = tmp_path / "captured.jsonl"
    log_record(
        str(path),
        "/v1/messages",
        {
            "model": "claude-opus-4-8",
            "system": "Summarize support tickets.",
            "messages": [{"role": "user", "content": "ticket text"}],
        },
        {
            "model": "claude-opus-4-8",
            "content": [{"type": "text", "text": "summary here"}],
            "usage": {"input_tokens": 30, "output_tokens": 8},
        },
    )
    records = load_openai_jsonl(path)
    assert len(records) == 1
    rec = records[0]
    assert rec.system_prompt == "Summarize support tickets."
    assert rec.response_text == "summary here"
    assert rec.input_tokens == 30
    assert rec.output_tokens == 8
