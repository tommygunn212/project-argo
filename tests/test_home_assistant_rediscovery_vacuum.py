"""tools/home_assistant.py: finds the HA VM again after its address moves, and drives the Roomba/Braava."""

import pytest

from tools import home_assistant as H


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(H, "_RESOLVED_URL_FILE", tmp_path / "home_assistant_url.txt")
    conf = {"url": "http://172.26.52.139:8123", "token": "t"}
    monkeypatch.setattr(H, "_load_ha_config", lambda: conf)
    return conf


def test_a_moved_vm_is_found_by_mdns_and_remembered(cfg, monkeypatch):
    calls = []

    def send(method, url, path, body, token, conf, timeout):
        calls.append(url)
        if "172.26.52.139" in url:
            raise H._Unreachable("timed out")
        return {"ok": url}

    monkeypatch.setattr(H, "_ha_send", send)
    monkeypatch.setattr("socket.getaddrinfo", lambda host, port, fam: [(2, 1, 6, "", ("172.22.100.209", 0))])
    assert H._ha_request("GET", "states") == {"ok": "http://172.22.100.209:8123"}
    assert calls == ["http://172.26.52.139:8123", "http://172.22.100.209:8123"]
    # Next time it goes straight to the remembered address.
    calls.clear()
    H._ha_request("GET", "states")
    assert calls == ["http://172.22.100.209:8123"]


def test_unreachable_everywhere_is_a_clear_error(cfg, monkeypatch):
    def send(*a, **k):
        raise H._Unreachable("timed out")

    monkeypatch.setattr(H, "_ha_send", send)
    monkeypatch.setattr("socket.getaddrinfo", lambda *a: (_ for _ in ()).throw(OSError("no mdns")))
    with pytest.raises(RuntimeError, match="Cannot reach Home Assistant"):
        H._ha_request("GET", "states")


def test_same_address_from_mdns_does_not_loop(cfg, monkeypatch):
    def send(*a, **k):
        raise H._Unreachable("refused")

    monkeypatch.setattr(H, "_ha_send", send)
    monkeypatch.setattr("socket.getaddrinfo", lambda *a: [(2, 1, 6, "", ("172.26.52.139", 0))])
    with pytest.raises(RuntimeError):
        H._ha_request("GET", "states")
    assert not H._RESOLVED_URL_FILE.exists()


@pytest.mark.parametrize("text,action,device", [
    ("start the roomba", "vacuum_start", "roomba"),
    ("roomba go clean the living room", "vacuum_start", "roomba"),
    ("stop the vacuum", "vacuum_stop", "roomba"),
    ("send the roomba home", "vacuum_dock", "roomba"),
    ("start the braava", "vacuum_start", "braava"),
    ("mop the kitchen", "vacuum_start", "braava"),
])
def test_vacuum_commands_parse(text, action, device):
    parsed = H.parse_smart_home_command(text)
    assert (parsed["action"], parsed["device"], parsed["domain"]) == (action, device, "vacuum")


def test_lights_are_not_mistaken_for_the_vacuum():
    assert H.parse_smart_home_command("turn on the living room light")["domain"] != "vacuum"


def test_vacuum_command_calls_the_right_service(monkeypatch):
    posted = []
    monkeypatch.setattr(H, "_ha_post", lambda path, body=None: posted.append((path, body)) or {})
    monkeypatch.setattr(H, "_get_friendly_name", lambda eid: "Roomba")
    assert H.vacuum_command("vacuum.roomba", "vacuum_dock") == "Roomba is heading back to its dock."
    assert posted == [("services/vacuum/return_to_base", {"entity_id": "vacuum.roomba"})]
