from core.roadmap_catalog import search_argo_roadmap


def test_roadmap_defaults_to_open_work_and_names_sources():
    result = search_argo_roadmap()
    assert result["ok"] is True
    assert result["items"]
    assert all(item["kind"] != "planned capability" for item in result["items"])
    assert all(item["line"] > 0 and item["source"] for item in result["items"])
    assert "not proof" in result["note"]


def test_roadmap_finds_specific_capability_without_claiming_implementation():
    result = search_argo_roadmap("robot vacuum")
    assert any("Robot vacuum control" in item["title"] for item in result["items"])
    assert all(item["kind"] == "planned capability" for item in result["items"])
