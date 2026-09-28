import wrapper.runtime_composition as composition


def test_voice_mode_is_stateless_and_does_not_query_memory(monkeypatch):
    monkeypatch.setattr(
        composition,
        "find_relevant_memory",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("voice mode queried memory")
        ),
    )
    monkeypatch.setattr(composition, "detect_recall_query", lambda _text: (False, None))

    result = composition.prepare_conversation(
        "hello", prefs={"verbosity": "short"}, voice_mode=True
    )

    assert result.composed_input == "hello"
    assert result.is_recall is False


def test_text_mode_composes_preferences_history_and_current_input(monkeypatch):
    monkeypatch.setattr(composition, "detect_recall_query", lambda _text: (False, None))
    monkeypatch.setattr(composition, "build_pref_block", lambda _prefs: "PREFS\n")
    monkeypatch.setattr(
        composition,
        "find_relevant_memory",
        lambda _text, top_n: [{"user_input": "past", "model_response": "answer"}],
    )

    result = composition.prepare_conversation("current", prefs={}, voice_mode=False)

    assert result.composed_input == (
        "PREFS\nFrom your history:\nPast: past\nResponse: answer\n\ncurrent"
    )


def test_recall_is_deterministic_and_skips_similarity_search(monkeypatch):
    monkeypatch.setattr(composition, "detect_recall_query", lambda _text: (True, 3))
    monkeypatch.setattr(composition, "load_memory", lambda: ["stored"])
    monkeypatch.setattr(
        composition,
        "format_recall_response",
        lambda memory, count, prefs: f"recall:{memory}:{count}:{prefs['tone']}",
    )
    monkeypatch.setattr(
        composition,
        "find_relevant_memory",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("recall used similarity search")
        ),
    )

    result = composition.prepare_conversation(
        "what did we discuss", prefs={"tone": "plain"}, voice_mode=False
    )

    assert result.is_recall is True
    assert result.recall_output == "recall:['stored']:3:plain"


def test_preference_update_is_persisted(monkeypatch):
    saved = []
    monkeypatch.setattr(composition, "load_prefs", lambda: {"old": True})
    monkeypatch.setattr(
        composition,
        "update_prefs",
        lambda text, prefs: {"text": text, "previous": prefs},
    )
    monkeypatch.setattr(composition, "save_prefs", saved.append)

    prefs = composition.update_preferences("be concise")

    assert prefs == {"text": "be concise", "previous": {"old": True}}
    assert saved == [prefs]
