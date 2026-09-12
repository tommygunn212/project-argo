"""Optional retrieval that cannot hold a voice turn past its shared deadline."""
from concurrent.futures import ThreadPoolExecutor, wait
import threading
import time


class BoundedContext:
    def __init__(self):
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="voice-context")
        self.active = {}
        self.lock = threading.Lock()

    def fetch(self, jobs, timeout=5.0, stop=None):
        if stop and stop.is_set():
            return {}, list(jobs)
        current = {}
        with self.lock:
            for name, job in jobs.items():
                previous = self.active.get(name)
                # A hung dependency gets one slot, not another thread per turn.
                if previous is not None and not previous.done():
                    continue
                current[name] = self.active[name] = self.pool.submit(job)
        deadline = time.monotonic() + timeout
        pending = set(current.values())
        while pending and not (stop and stop.is_set()):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            _, pending = wait(pending, timeout=min(remaining, 0.05))
        results, missing = {}, []
        for name in jobs:
            future = current.get(name)
            if future is not None and future.done() and not future.cancelled():
                try:
                    results[name] = future.result()
                    continue
                except Exception:
                    pass
            if future is not None:
                future.cancel()
            missing.append(name)
        return results, missing

    def close(self):
        self.pool.shutdown(wait=False, cancel_futures=True)
