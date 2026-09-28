from types import SimpleNamespace

import wrapper.post_generation as post


class _DriftMonitor:
    def __init__(self):
        self.flags = []
        self.logged = []

    def flag_signal(self, *args, **kwargs):
        self.flags.append((args, kwargs))

    def log_interaction(self, **kwargs):
        self.logged.append(kwargs)

    def detect_violations(self):
        return [{"type": "unsupported_certainty"}]

    def detect_drift(self):
        return [{
            "signal": "verbosity_drift",
            "corrective_action": {"force_verbosity": "short"},
            "duration_turns": 2,
        }]


def _prompt(monitor):
    return SimpleNamespace(
        execution_context="cli",
        query_type="factual",
        has_canonical_knowledge=False,
        is_casual_question=False,
        primary_frame="factual",
        drift_monitor=monitor,
        behavior_profile={
            "verbosity_override": None,
            "explanation_depth": "brief",
            "correction_style": "direct",
        },
        classified_verbosity="short",
        uncertainty_enforcement={"required": True},
    )


def test_audit_records_drift_log_and_strips_history_prefix(monkeypatch):
    monitor = _DriftMonitor()
    daily = []
    memory = []
    familiarity = []
    monkeypatch.setattr(post, "validate_cli_format", lambda *_: (True, ""))
    monkeypatch.setattr(post, "validate_scope", lambda *_: (False, "expanded"))
    monkeypatch.setattr(
        post,
        "validate_personality_discipline",
        lambda *_: (True, "", False),
    )
    monkeypatch.setattr(post, "validate_human_first_sentence", lambda *_: (True, ""))
    monkeypatch.setattr(post, "detect_plausible_hallucination", lambda *_: (True, ""))
    monkeypatch.setattr(post, "update_familiarity", lambda *args: familiarity.append(args))
    monkeypatch.setattr(post, "_append_daily_log", lambda **kwargs: daily.append(kwargs))
    monkeypatch.setattr(post, "store_interaction", lambda *args: memory.append(args))

    post.audit_and_record_response(
        user_input="From your history:\nPast material\n\nOriginal question",
        output="Answer",
        prompt=_prompt(monitor),
        session_id="session-1",
        active_mode=None,
        replay_n=2,
        replay_session=False,
        replay_policy={"reason": "continuation"},
        persona="neutral",
    )

    assert familiarity == [(True,)]
    assert monitor.logged[0]["model_response"] == "Answer"
    assert monitor.flags[0][0][0] == "scope_expansion"
    assert monitor.flags[1][0][0] == "verbosity_drift"
    assert daily[0]["honesty_enforcement"] == {
        "uncertainty_enforced": True,
        "violations_detected": 1,
        "drift_signals_detected": 1,
        "violations": ["unsupported_certainty"],
        "drift_signals": ["verbosity_drift"],
    }
    assert memory == [("Original question", "Answer")]


def test_hard_personality_and_frame_failures_both_demote_familiarity(monkeypatch):
    monitor = _DriftMonitor()
    familiarity = []
    monkeypatch.setattr(post, "validate_cli_format", lambda *_: (True, ""))
    monkeypatch.setattr(post, "validate_scope", lambda *_: (True, ""))
    monkeypatch.setattr(
        post,
        "validate_personality_discipline",
        lambda *_: (False, "academic opener", False),
    )
    monkeypatch.setattr(post, "validate_human_first_sentence", lambda *_: (False, "bad frame"))
    monkeypatch.setattr(post, "detect_plausible_hallucination", lambda *_: (False, "ungrounded"))
    monkeypatch.setattr(post, "update_familiarity", lambda *args: familiarity.append(args))
    monkeypatch.setattr(post, "_append_daily_log", lambda **_kwargs: None)
    monkeypatch.setattr(post, "store_interaction", lambda *_args: None)

    post.audit_and_record_response(
        user_input="Question",
        output="Answer",
        prompt=_prompt(monitor),
        session_id="session-1",
        active_mode=None,
        replay_n=None,
        replay_session=False,
        replay_policy=None,
        persona="neutral",
    )

    assert familiarity == [
        (False, "personality_discipline"),
        (False, "frame_blending"),
    ]
