import logging
import threading

from wrapper.audio_output import AudioOutputBridge


def test_disabled_bridge_is_a_noop(monkeypatch):
    bridge = AudioOutputBridge(
        lambda: object(), enabled=False, piper_enabled=True, logger=logging.getLogger()
    )
    monkeypatch.setattr(bridge, "_start", lambda: (_ for _ in ()).throw(AssertionError()))

    bridge.send("hello")

    assert bridge._queue.empty()


def test_enabled_bridge_starts_and_queues_capped_text(monkeypatch):
    bridge = AudioOutputBridge(
        lambda: object(),
        enabled=True,
        piper_enabled=True,
        logger=logging.getLogger(),
        max_chars=5,
    )
    started = []
    monkeypatch.setattr(bridge, "_start", lambda: started.append(True))

    bridge.send("abcdefgh")

    assert started == [True]
    assert bridge._queue.get_nowait() == "abcde"


def test_bridge_requires_sink_and_both_feature_flags():
    logger = logging.getLogger()

    assert not AudioOutputBridge(None, enabled=True, piper_enabled=True, logger=logger).available
    assert not AudioOutputBridge(lambda: None, enabled=False, piper_enabled=True, logger=logger).available
    assert not AudioOutputBridge(lambda: None, enabled=True, piper_enabled=False, logger=logger).available


def test_worker_delivers_queued_text():
    delivered = []
    completed = threading.Event()

    class Sink:
        async def send(self, text):
            delivered.append(text)
            completed.set()

    bridge = AudioOutputBridge(
        Sink, enabled=True, piper_enabled=True, logger=logging.getLogger()
    )

    bridge.send("hello")
    assert completed.wait(2)
    bridge._queue.put(None)
    bridge._thread.join(timeout=2)

    assert delivered == ["hello"]
    assert not bridge._thread.is_alive()
