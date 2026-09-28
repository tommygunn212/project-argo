from pathlib import Path

import core.music_player as music_player
from wrapper.preflight import (
    ARGO_LAW_TEXT,
    GATES_TEXT,
    dispatch_governance,
    dispatch_music_volume,
    dispatch_self_knowledge,
    neural_terminology_sink,
)


def test_volume_query_does_not_mutate_volume(monkeypatch):
    outputs = []
    mutations = []
    monkeypatch.setattr(music_player, "get_volume_percent", lambda: 42)
    monkeypatch.setattr(
        music_player,
        "set_volume_percent",
        lambda value: mutations.append(("set", value)),
    )
    monkeypatch.setattr(
        music_player,
        "adjust_volume_percent",
        lambda value: mutations.append(("adjust", value)),
    )

    assert dispatch_music_volume("what is the volume", outputs.append) is True
    assert outputs == ["Music volume: 42%"]
    assert mutations == []


def test_volume_change_is_deterministic(monkeypatch):
    outputs = []
    changes = []
    monkeypatch.setattr(music_player, "get_volume_percent", lambda: 65)
    monkeypatch.setattr(
        music_player,
        "set_volume_percent",
        lambda value: changes.append(value),
    )

    assert dispatch_music_volume("set volume to 65%", outputs.append) is True
    assert changes == [65]
    assert outputs == ["Music volume set to 65%"]


def test_unrelated_text_falls_through_volume_dispatch():
    outputs = []

    assert dispatch_music_volume("explain quantum mechanics", outputs.append) is False
    assert outputs == []


def test_self_knowledge_reads_repository_document(tmp_path: Path):
    outputs = []
    (tmp_path / "ARCHITECTURE.md").write_text("canonical architecture", encoding="utf-8")

    assert dispatch_self_knowledge("explain argo", outputs.append, tmp_path) is True
    assert outputs == ["canonical architecture"]


def test_self_knowledge_reports_missing_document(tmp_path: Path):
    outputs = []

    assert dispatch_self_knowledge("argo features", outputs.append, tmp_path) is True
    assert outputs[0].startswith("[ERROR] Could not load canonical documentation: FEATURES.md")


def test_terminology_wrapper_preserves_legacy_replacement_behavior():
    outputs = []
    sink = neural_terminology_sink(outputs.append)

    sink("AI and ai and Ai")

    assert outputs == ["neural network and neural network and neural network"]


def test_governance_dispatches_laws_and_gates():
    law_outputs = []
    gate_outputs = []

    assert dispatch_governance("what are your laws", law_outputs.append) is True
    assert dispatch_governance("explain the five gates", gate_outputs.append) is True
    assert law_outputs == [ARGO_LAW_TEXT]
    assert gate_outputs == [GATES_TEXT]


def test_unrelated_text_falls_through_governance_dispatch():
    outputs = []

    assert dispatch_governance("how is the weather", outputs.append) is False
    assert outputs == []
