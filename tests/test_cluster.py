from vouch.cluster import auto_name, cluster_records
from vouch.models import LogRecord


def _rec(system=None, user="", model="claude-opus-4-8", hint=None):
    return LogRecord(
        model=model, system_prompt=system, first_user_message=user, task_hint=hint
    )


def test_same_prompt_with_template_slot_clusters_together():
    records = [
        _rec(system="Classify the sentiment of reviews for store alpha", user="great!"),
        _rec(system="Classify the sentiment of reviews for store beta", user="meh"),
        _rec(system="Classify the sentiment of reviews for store gamma", user="bad"),
        _rec(system="Summarize this meeting transcript into bullet points", user="..."),
    ]
    clusters = cluster_records(records)
    assert len(clusters) == 2
    assert clusters[0].calls == 3
    assert clusters[0].name.startswith("classify_sentiment")


def test_task_hint_wins_over_prompt_clustering():
    records = [
        _rec(hint="main:agentic-loop"),
        _rec(hint="main:agentic-loop"),
        _rec(hint="agent:explore"),
    ]
    clusters = cluster_records(records)
    assert [c.name for c in clusters] == ["main:agentic-loop", "agent:explore"]


def test_incumbent_is_dominant_model():
    records = [
        _rec(hint="x", model="claude-sonnet-4-6"),
        _rec(hint="x", model="claude-sonnet-4-6"),
        _rec(hint="x", model="claude-opus-4-8"),
    ]
    assert cluster_records(records)[0].incumbent == "claude-sonnet-4-6"


def test_auto_name_strips_boilerplate():
    assert auto_name("You are a helpful assistant. Classify things.") == "helpful_assistant"
    assert auto_name("Classify the sentiment of the review") == "classify_sentiment_review"
    assert auto_name("") == "cluster"
