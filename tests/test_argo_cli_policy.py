import subprocess
import sys
from pathlib import Path

from wrapper import cli_policy


def test_argo_reexports_extracted_policy_in_an_isolated_process():
    code = (
        "from wrapper import argo, behavior_policy, cli_policy; "
        "assert argo.classify_input is cli_policy.classify_input; "
        "assert argo.classify_query_type is behavior_policy.classify_query_type"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr


def test_input_and_verbosity_classification_contracts():
    assert cli_policy.classify_input("") == "empty"
    assert cli_policy.classify_input("hello") == "ambiguous"
    assert cli_policy.classify_input("what is gravity?") == "valid"
    assert cli_policy.classify_verbosity("give me a detailed explanation of gravity") == "long"
    assert cli_policy.classify_verbosity("what is gravity?") == "short"


def test_cli_format_rejects_markdown_headers_but_accepts_plain_text():
    assert cli_policy.validate_cli_format("Plain answer", "cli") == (True, "")
    valid, reason = cli_policy.validate_cli_format("# Heading", "cli")
    assert valid is False
    assert "Section header" in reason
