from vouch.normalize import SLOT, detect_templates, mask_static


def test_mask_static_uuid_timestamp_email():
    text = (
        "Request 550e8400-e29b-41d4-a716-446655440000 at 2026-07-16T10:00:00Z "
        "from user@example.com order 123456"
    )
    masked = mask_static(text)
    assert "<uuid>" in masked
    assert "<ts>" in masked
    assert "<email>" in masked
    assert "<num>" in masked
    assert "550e8400" not in masked


def test_detect_templates_masks_interpolated_variable():
    prompts = [
        "Classify the sentiment of this review for store alpha",
        "Classify the sentiment of this review for store beta",
        "Classify the sentiment of this review for store gamma",
    ]
    templates = detect_templates(prompts)
    assert len(set(templates)) == 1
    assert templates[0].endswith(SLOT)
    assert templates[0].startswith("Classify the sentiment")


def test_detect_templates_keeps_distinct_tasks_apart():
    prompts = [
        "Classify the sentiment of this review",
        "Summarize the following meeting transcript",
    ]
    templates = detect_templates(prompts)
    assert templates[0] != templates[1]
    assert SLOT not in templates[0]


def test_detect_templates_low_cardinality_slot_many_calls():
    # 4 distinct values across 60 calls is still a slot — what matters is the
    # share of calls deviating from the modal value, not value cardinality.
    stores = ["alpha", "beta", "gamma", "delta"] * 15
    prompts = [f"Classify reviews for store {s} today" for s in stores]
    templates = detect_templates(prompts)
    assert len(set(templates)) == 1
    assert SLOT in templates[0]


def test_detect_templates_singleton_unchanged():
    assert detect_templates(["only one prompt"]) == ["only one prompt"]
