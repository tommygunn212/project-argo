from types import SimpleNamespace

from core.pipeline import ArgoPipeline
from core.pipeline_memory import PipelineMemoryMixin


def test_pipeline_composes_memory_service_and_preserves_public_facade():
    assert not issubclass(ArgoPipeline, PipelineMemoryMixin)
    pipeline = object.__new__(ArgoPipeline)
    calls = []
    pipeline._memory_service = SimpleNamespace(
        _parse_memory_write=lambda *args, **kwargs: calls.append(("parse", args, kwargs)) or {"ok": True},
        _handle_memory_command=lambda *args, **kwargs: calls.append(("handle", args, kwargs)) or True,
    )

    assert pipeline._parse_memory_write("remember this") == {"ok": True}
    assert pipeline._handle_memory_command("remember this", "id", False, {}) is True
    assert [name for name, _args, _kwargs in calls] == ["parse", "handle"]
