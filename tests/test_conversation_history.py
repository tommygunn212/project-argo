from wrapper import conversation_history as history


def _append(session_id: str, prompt: str, response: str) -> None:
    history._append_daily_log(
        timestamp_iso="2026-09-28T01:00:00",
        session_id=session_id,
        user_prompt=prompt,
        model_response=response,
        active_mode=None,
        replay_n=None,
        replay_session=False,
    )


def test_history_round_trip_and_corrupt_line_tolerance(monkeypatch, tmp_path):
    monkeypatch.setattr(history, "_get_log_dir", lambda: str(tmp_path))
    _append("session-a", "first question", "first answer")
    _append("session-b", "second question", "second answer")
    with (tmp_path / "2026-09-28.log").open("a", encoding="utf-8") as stream:
        stream.write("not-json\n")

    assert [item["user_prompt"] for item in history.get_last_n_entries(2)] == [
        "first question",
        "second question",
    ]
    assert [item["model_response"] for item in history.get_session_entries("session-a")] == [
        "first answer"
    ]


def test_replay_filter_keeps_latest_exchange_and_reports_removed_types():
    entries = [{"id": value} for value in range(4)]
    filtered, stats = history.filter_replay_entries(
        entries,
        "continuation",
        ["meta", "instruction", "other", "meta"],
    )

    assert filtered == [entries[1], entries[2], entries[3]]
    assert stats == {
        "entries_available": 4,
        "entries_filtered": 1,
        "filtered_types": ["meta"],
    }


def test_recall_detection_and_formatting_are_deterministic():
    assert history.detect_recall_query("list the last 3 things we discussed") == (True, 3)
    assert history.detect_recall_query("turn on the kitchen light") == (False, None)

    result = history.format_recall_response(
        [{"user_input": "alpha"}, {"user_input": "beta"}],
        count=2,
    )
    assert result == "Recent topics:\n1. beta\n2. alpha"
    assert history.validate_voice_compliance("  concise answer  ") == "concise answer"
