import wrapper.replay_context as replay


def test_voice_mode_is_always_stateless(monkeypatch):
    monkeypatch.setattr(
        replay,
        "get_session_entries",
        lambda session_id: (_ for _ in ()).throw(AssertionError("unexpected session load")),
    )
    monkeypatch.setattr(
        replay,
        "get_last_n_entries",
        lambda count: (_ for _ in ()).throw(AssertionError("unexpected history load")),
    )

    result = replay.build_replay_context(
        session_id="session-1",
        replay_n=5,
        replay_session=True,
        replay_reason="continuation",
        voice_mode=True,
    )

    assert result == replay.ReplayContext()


def test_no_replay_request_returns_weak_empty_context():
    result = replay.build_replay_context(
        session_id="session-1",
        replay_n=None,
        replay_session=False,
        replay_reason="continuation",
        voice_mode=False,
    )

    assert result.block == ""
    assert result.policy is None
    assert result.context_strength == "weak"


def test_session_replay_filters_then_budgets_and_formats(monkeypatch):
    entries = [
        {"user_prompt": "first question", "model_response": "first answer"},
        {"user_prompt": "second question", "model_response": "second answer"},
    ]
    calls = []
    monkeypatch.setattr(replay, "get_session_entries", lambda session_id: entries.copy())
    monkeypatch.setattr(
        replay,
        "classify_entry_type",
        lambda user, model: f"type:{user}",
    )

    def filter_entries(values, reason, entry_types):
        calls.append(("filter", reason, entry_types.copy()))
        return values[1:], {"filtered": 1}

    def budget_entries(values, max_chars):
        calls.append(("budget", max_chars, values.copy()))
        return values, {"kept": len(values)}

    monkeypatch.setattr(replay, "filter_replay_entries", filter_entries)
    monkeypatch.setattr(replay, "apply_replay_budget", budget_entries)
    monkeypatch.setattr(
        replay,
        "classify_context_strength",
        lambda policy, types: "strong",
    )

    result = replay.build_replay_context(
        session_id="session-1",
        replay_n=None,
        replay_session=True,
        replay_reason="continuation",
        voice_mode=False,
    )

    assert calls[0] == (
        "filter",
        "continuation",
        ["type:first question", "type:second question"],
    )
    assert calls[1][0:2] == ("budget", 5500)
    assert result.block == "User: second question\nAssistant: second answer\n\n"
    assert result.policy == {
        "filtered": 1,
        "kept": 1,
        "reason": "continuation",
        "context_strength": "strong",
    }
    assert result.context_strength == "strong"


def test_last_n_replay_uses_requested_count(monkeypatch):
    counts = []
    monkeypatch.setattr(
        replay,
        "get_last_n_entries",
        lambda count: counts.append(count) or [],
    )

    result = replay.build_replay_context(
        session_id="session-1",
        replay_n=3,
        replay_session=False,
        replay_reason="reference",
        voice_mode=False,
    )

    assert counts == [3]
    assert result == replay.ReplayContext()
