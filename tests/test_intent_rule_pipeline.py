from types import SimpleNamespace
from unittest.mock import Mock

import core.intent_rule_pipeline as rules


def _context():
    return SimpleNamespace(
        serious_mode=False,
        serious_mode_keywords=("urgent",),
        sleep_phrases=("sleep",),
        develop_phrases=("build",),
        tech_keywords=("python",),
        question_words=("what",),
        greeting_keywords=("hello",),
        command_words=("open",),
        _parse_music_intent=Mock(return_value=None),
    )


def test_must_pass_short_circuits_before_phonetic_rewrite(monkeypatch):
    expected = object()
    monkeypatch.setattr(rules, "parse_must_pass_knowledge", lambda *_: expected)
    monkeypatch.setattr(
        rules,
        "apply_phonetic_fixes",
        Mock(side_effect=AssertionError("phonetic rewrite must not run")),
    )

    assert rules.parse_intent_rules(_context(), "required phrase") is expected


def test_full_system_detection_runs_before_wake_prefix_stripping(monkeypatch):
    expected = object()
    monkeypatch.setattr(rules, "parse_must_pass_knowledge", lambda *_: None)
    monkeypatch.setattr(rules, "apply_phonetic_fixes", lambda text: text)
    monkeypatch.setattr(rules, "parse_full_system_status", lambda *_: expected)
    monkeypatch.setattr(
        rules,
        "strip_wake_prefix",
        Mock(side_effect=AssertionError("wake stripping must not run")),
    )

    assert rules.parse_intent_rules(_context(), "Argo system status") is expected


def test_domain_rule_short_circuits_before_music(monkeypatch):
    expected = object()
    context = _context()
    prepared = SimpleNamespace(
        original="play the living room lights",
        normalized="play the living room lights",
        tokens=["play", "the", "living", "room", "lights"],
        first_word="play",
    )
    monkeypatch.setattr(rules, "parse_must_pass_knowledge", lambda *_: None)
    monkeypatch.setattr(rules, "apply_phonetic_fixes", lambda text: text)
    monkeypatch.setattr(rules, "parse_full_system_status", lambda *_: None)
    monkeypatch.setattr(rules, "strip_wake_prefix", lambda *_: prepared)
    monkeypatch.setattr(rules, "parse_control_intent", lambda *_: None)
    monkeypatch.setattr(rules, "parse_domain_intent", lambda *_: expected)

    assert rules.parse_intent_rules(context, prepared.original) is expected
    context._parse_music_intent.assert_not_called()
