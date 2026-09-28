import json

from core import config as config_module


def test_reloading_config_does_not_inherit_an_earlier_files_nested_values(tmp_path):
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    first.write_text(
        json.dumps({"audio": {"sample_rate": 48_000}}),
        encoding="utf-8",
    )
    second.write_text("{}", encoding="utf-8")

    assert config_module.load_config(str(first)).get("audio.sample_rate") == 48_000
    reloaded = config_module.load_config(str(second))

    assert reloaded.get("audio.sample_rate") == 16_000
    assert config_module._DEFAULT_CONFIG["audio"]["sample_rate"] == 16_000
