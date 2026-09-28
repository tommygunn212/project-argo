"""Storage contract for local, untracked wrapper preferences."""

import json

from wrapper import prefs


def test_missing_preferences_file_is_created_with_defaults(tmp_path, monkeypatch):
    preference_file = tmp_path / "user_preferences.json"
    monkeypatch.setattr(prefs, "PREF_FILE", preference_file)

    loaded = prefs.load_prefs()

    assert loaded == prefs.DEFAULT_PREFS
    assert loaded is not prefs.DEFAULT_PREFS
    assert json.loads(preference_file.read_text(encoding="utf-8")) == prefs.DEFAULT_PREFS


def test_saved_preferences_round_trip(tmp_path, monkeypatch):
    preference_file = tmp_path / "user_preferences.json"
    monkeypatch.setattr(prefs, "PREF_FILE", preference_file)
    expected = {
        "tone": "casual",
        "verbosity": "concise",
        "humor": None,
        "structure": "bullets",
    }

    prefs.save_prefs(expected)

    assert prefs.load_prefs() == expected


def test_invalid_preferences_file_falls_back_without_overwriting(tmp_path, monkeypatch):
    preference_file = tmp_path / "user_preferences.json"
    preference_file.write_text("not-json", encoding="utf-8")
    monkeypatch.setattr(prefs, "PREF_FILE", preference_file)

    assert prefs.load_prefs() == prefs.DEFAULT_PREFS
    assert preference_file.read_text(encoding="utf-8") == "not-json"

