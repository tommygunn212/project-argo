"""Bounded-memory, continuous PCM resampling across arbitrary network chunks."""

from math import gcd
import numpy as np
from scipy.signal import firwin, upfirdn


class StreamingResampler:
    """Causal polyphase FIR with overlap carried across calls, not FFT seams.

    Keeps the short filter delay (under 1 ms at 24 -> 44.1/48 kHz) and flushes
    its tail at EOF. No audio is independently padded or reset per network chunk.
    """

    def __init__(self, source_rate, target_rate):
        factor = gcd(int(source_rate), int(target_rate))
        self.up, self.down = int(target_rate) // factor, int(source_rate) // factor
        rate = max(self.up, self.down)
        self.taps = firwin(20 * rate + 1, 1 / rate).astype(np.float32) * self.up if rate > 1 else None
        self.pending = np.empty(0, dtype=np.float32)
        self.tail = np.empty(0, dtype=np.float32)
        self.total_in = self.total_out = 0

    def process(self, samples, final=False):
        samples = np.asarray(samples, dtype=np.float32)
        if self.taps is None:
            return samples
        self.total_in += len(samples)
        data = np.concatenate((self.pending, samples))
        count = len(data) // self.down * self.down
        if final and len(data) % self.down:
            count += self.down
            data = np.pad(data, (0, count - len(data)))
        self.pending = data[count:].copy()
        if count:
            block = upfirdn(self.taps, data[:count], up=self.up, down=self.down).astype(np.float32)
            if len(block) < len(self.tail):
                block = np.pad(block, (0, len(self.tail) - len(block)))
            block[:len(self.tail)] += self.tail
            stable = count * self.up // self.down
            result, self.tail = block[:stable], block[stable:].copy()
        else:
            result = np.empty(0, dtype=np.float32)
        if final:
            result = np.concatenate((result, self.tail))
            length = ((self.total_in - 1) * self.up + len(self.taps) - 1) // self.down + 1 if self.total_in else 0
            result = result[:max(0, length - self.total_out)]
            self.tail = np.empty(0, dtype=np.float32)
        self.total_out += len(result)
        return result
