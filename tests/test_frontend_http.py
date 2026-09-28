import json
import logging
import threading
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen

from core.frontend_http import build_frontend_handler


def _services(tmp_path, commands):
    return {
        "repo_root": tmp_path,
        "http_port": 8000,
        "ws_port": 8001,
        "logger": logging.getLogger("test.frontend_http"),
        "get_config": lambda: None,
        "env_enabled": lambda _name: False,
        "handle_control": commands.append,
        "hard_reset_pipeline": lambda _reason: {"ok": True},
        "broadcast_msg": lambda *_args: None,
        "note_smooth_voice_phase": lambda _phase: None,
        "set_listening_enabled": lambda _enabled: None,
        "get_current_status": lambda: "READY",
        "get_repair_bridge_token": lambda: None,
        "get_repair_service": lambda: None,
    }


def test_status_and_control_routes_use_injected_runtime(tmp_path):
    commands = []
    handler = build_frontend_handler(_services(tmp_path, commands))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        with urlopen(f"{base}/api/status", timeout=2) as response:
            status = json.load(response)
        request = Request(
            f"{base}/api/control",
            data=json.dumps({"command": "start", "data": {"source": "test"}}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=2) as response:
            control = json.load(response)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert status["status"] == "ok"
    assert status["ws_endpoint"] == "ws://127.0.0.1:8001/ws"
    assert control == {"ok": True, "status": "READY"}
    assert commands == [{"command": "start", "data": {"source": "test"}}]
