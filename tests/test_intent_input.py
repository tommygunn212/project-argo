from core.intent_input import (
    apply_phonetic_fixes,
    normalize_for_rules,
    normalize_phrase,
    strip_wake_prefix,
)


def test_rule_normalization_standardizes_quotes_and_volume_aliases():
    normalized = normalize_for_rules("Turn the “Sound” up")

    assert normalized == 'turn the "volume" up'


def test_phrase_normalization_does_not_apply_domain_aliases():
    assert normalize_phrase("  It’s SOUND  ") == "it's sound"


def test_phonetic_repairs_remain_deterministic():
    assert apply_phonetic_fixes("porcupine led like") == "argo led light"
    assert apply_phonetic_fixes("pocket point sees ducts") == "argo sees ducks"


def test_repeated_wake_prefix_is_removed_from_raw_and_normalized_text():
    prepared = strip_wake_prefix("Argo, argo play Bowie", "argo, argo play bowie")

    assert prepared.original == "play Bowie"
    assert prepared.normalized == "play bowie"
    assert prepared.tokens == ("play", "bowie")
    assert prepared.first_word == "play"


def test_empty_post_wake_text_has_no_first_word():
    prepared = strip_wake_prefix("Argo,", "argo,")

    assert prepared.original == ""
    assert prepared.tokens == ()
    assert prepared.first_word == ""
