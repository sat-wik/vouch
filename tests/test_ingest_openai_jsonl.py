import json

from vouch.ingest import load_openai_jsonl


def test_load_wrapped_and_flat_shapes(tmp_path):
    lines = [
        {
            "request": {
                "model": "gpt-4o",
                "messages": [
                    {"role": "system", "content": "Extract invoice fields as JSON."},
                    {"role": "user", "content": "Invoice #123 ..."},
                ],
            },
            "response": {
                "choices": [{"message": {"role": "assistant", "content": '{"total": 5}'}}],
                "usage": {"prompt_tokens": 40, "completion_tokens": 10},
            },
        },
        {
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "no system prompt here"}],
        },
        {"not": "a request"},
    ]
    path = tmp_path / "logs.jsonl"
    path.write_text("\n".join(json.dumps(x) for x in lines) + "\n")

    records = load_openai_jsonl(path)
    assert len(records) == 2

    first = records[0]
    assert first.model == "gpt-4o"
    assert first.system_prompt == "Extract invoice fields as JSON."
    assert first.first_user_message.startswith("Invoice")
    assert first.response_text == '{"total": 5}'
    assert first.input_tokens == 40
    assert first.output_tokens == 10

    second = records[1]
    assert second.system_prompt is None
    assert second.first_user_message == "no system prompt here"
