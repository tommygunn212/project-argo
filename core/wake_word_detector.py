class WakeWordRequest:
    def __init__(self, word: str):
        self.word = word


class WakeWordDetector:
    def __init__(self):
        self._paused = False

    def start(self):
        pass

    def stop(self):
        pass

    def pause(self):
        self._paused = True

    def resume(self):
        self._paused = False
