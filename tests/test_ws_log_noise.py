"""A port check should not look like an ARGO failure.

Anything that opens the websocket port and closes it without speaking HTTP
- a port check, a scanner, a browser probing - made the websockets library
log "opening handshake failed" at ERROR with a 30-line chained traceback.
Real errors were buried under it.
"""

import logging

from main import _QuietFailedHandshake


def _record(message, exc=None):
    record = logging.LogRecord(
        "websockets.server", logging.ERROR, __file__, 1, message, (), None
    )
    if exc is not None:
        record.exc_info = (type(exc), exc, None)
    return record


class InvalidMessage(Exception):
    """Same name as the websockets exception the filter matches on."""


def test_a_probe_is_demoted_to_one_debug_line():
    record = _record("opening handshake failed", InvalidMessage("no request"))

    assert _QuietFailedHandshake().filter(record) is True
    assert record.levelno == logging.DEBUG
    assert record.exc_info is None
    assert "closed before sending a request" in record.msg


def test_a_real_handshake_error_keeps_its_traceback():
    exc = ValueError("something actually went wrong")
    record = _record("opening handshake failed", exc)

    assert _QuietFailedHandshake().filter(record) is True
    assert record.levelno == logging.ERROR
    assert record.exc_info is not None


def test_unrelated_records_pass_through_untouched():
    record = _record("connection open")

    assert _QuietFailedHandshake().filter(record) is True
    assert record.levelno == logging.ERROR
    assert record.msg == "connection open"
