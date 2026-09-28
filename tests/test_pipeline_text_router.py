from types import SimpleNamespace
from unittest.mock import Mock

import core.pipeline_text_router as router


def _host(repair_service):
    return SimpleNamespace(
        logger=Mock(),
        strict_lab_mode=False,
        _current_stt_confidence=1.0,
        _intent_parser=SimpleNamespace(parse=Mock(return_value=None)),
        repair_service=repair_service,
        _deliver_canonical_response=Mock(return_value=True),
        _classify_request_kind=Mock(return_value="conversation"),
    )


def test_repair_result_short_circuits_all_intent_stages(monkeypatch):
    host = _host(SimpleNamespace(handle_text=Mock(return_value={"message": "fixed"})))
    monkeypatch.setattr(
        router,
        "dispatch_early_status",
        Mock(side_effect=AssertionError("intent routing must not run")),
    )

    router.route_user_text(host, " repair argo ", 1.0, interaction_id="turn-1")

    host.repair_service.handle_text.assert_called_once_with("repair argo")
    host._intent_parser.parse.assert_not_called()
    host._deliver_canonical_response.assert_called_once_with(
        "fixed",
        "turn-1",
        False,
        None,
        enforce_confidence=False,
        force_tts=True,
    )


def test_replay_skips_repair_service_and_reaches_early_status(monkeypatch):
    host = _host(SimpleNamespace(handle_text=Mock(return_value={"message": "fixed"})))
    early_status = Mock(return_value=True)
    monkeypatch.setattr(router, "dispatch_early_status", early_status)

    router.route_user_text(host, "repair argo", 0.7, replay_mode=True)

    host.repair_service.handle_text.assert_not_called()
    host._intent_parser.parse.assert_called_once_with("repair argo")
    early_status.assert_called_once()
    assert host._current_stt_confidence == 0.7
