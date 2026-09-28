from wrapper import argo
from wrapper import cli_policy


def test_cli_policy_is_reexported_by_argo():
    assert argo.classify_input is cli_policy.classify_input
    assert argo.validate_cli_format is cli_policy.validate_cli_format


def test_input_and_verbosity_classification_contracts():
    assert argo.classify_input("") == "empty"
    assert argo.classify_input("hello") == "ambiguous"
    assert argo.classify_input("what is gravity?") == "valid"
    assert argo.classify_verbosity("give me a detailed explanation of gravity") == "long"
    assert argo.classify_verbosity("what is gravity?") == "short"


def test_cli_format_rejects_markdown_headers_but_accepts_plain_text():
    assert argo.validate_cli_format("Plain answer", "cli") == (True, "")
    valid, reason = argo.validate_cli_format("# Heading", "cli")
    assert valid is False
    assert "Section header" in reason
