from unittest.mock import Mock

from core.streaming_tts_worker import StreamingTTSWorker


class FakeThread:
    def __init__(self, *, target, daemon):
        self.target = target
        self.daemon = daemon
        self.started = False
        self.alive = False
        self.join_calls = 0

    def start(self):
        self.started = True
        self.alive = True

    def is_alive(self):
        return self.alive

    def join(self, timeout):
        self.join_calls += 1


def test_disabled_worker_never_starts_consumer_thread():
    thread = None

    def factory(**kwargs):
        nonlocal thread
        thread = FakeThread(**kwargs)
        return thread

    worker = StreamingTTSWorker(Mock(), enabled=False, thread_factory=factory)
    worker.start()
    worker.finish(stop_signal=Mock(is_set=lambda: False), stop_tts=Mock(), logger=Mock())

    assert thread.started is False
    assert worker.queue.get_nowait() is None


def test_interrupt_drains_sentences_and_forces_slow_worker_stop():
    clock = iter([0.0, 0.0, 0.8])
    stop_tts = Mock()
    worker = StreamingTTSWorker(Mock(), enabled=True, thread_factory=FakeThread)
    worker.start()
    worker.enqueue("discard me")

    worker.finish(
        stop_signal=Mock(is_set=lambda: True),
        stop_tts=stop_tts,
        logger=Mock(),
        time_fn=lambda: next(clock),
    )

    assert worker.queue.get_nowait() is None
    stop_tts.assert_called_once_with()


def test_normal_timeout_forces_stop_without_draining_sentences():
    clock = iter([0.0, 31.0])
    stop_tts = Mock()
    worker = StreamingTTSWorker(Mock(), enabled=True, thread_factory=FakeThread)
    worker.start()
    worker.enqueue("keep me")

    worker.finish(
        stop_signal=Mock(is_set=lambda: False),
        stop_tts=stop_tts,
        logger=Mock(),
        time_fn=lambda: next(clock),
    )

    assert worker.queue.get_nowait() == "keep me"
    assert worker.queue.get_nowait() is None
    stop_tts.assert_called_once_with()
