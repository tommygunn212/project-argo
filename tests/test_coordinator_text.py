import pytest

from core.coordinator_text import (
    extract_code_block,
    infer_sandbox_filename,
    levenshtein_distance,
    similarity_ratio,
    strip_code_blocks,
)


def test_code_block_helpers_preserve_first_python_fence():
    text = "Intro\n```python\nprint('hi')\n```\nAfter"

    assert extract_code_block(text) == "print('hi')"
    assert strip_code_blocks(text) == "Intro\n\nAfter"


@pytest.mark.parametrize(
    ("user_text", "response_text", "expected"),
    [
        ("write code", "Save as report.py", "report.py"),
        ("make custom.py", "Here you go", "custom.py"),
        ("check disk space", "", "storage_check.py"),
        ("monitor cpu", "", "cpu_monitor.py"),
        ("write a tool", "", "sandbox_tool.py"),
    ],
)
def test_filename_inference_order(user_text, response_text, expected):
    assert infer_sandbox_filename(user_text, response_text) == expected


def test_similarity_helpers_preserve_normalization_and_distance():
    assert levenshtein_distance("kitten", "sitting") == 3
    assert similarity_ratio(" Hello ", "hello") == 1.0
    assert similarity_ratio("", "hello") == 0.0
    assert similarity_ratio("cat", "cut") == pytest.approx(2 / 3)
