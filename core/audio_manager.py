
"""
AudioManager: Queue-Based Audio Input/Output

Responsibilities:
- Manage sounddevice InputStream and OutputStream
- Buffer audio frames in a queue (non-blocking)
- Maintain ring buffer for pre-roll
- Provide synchronous read_frame() for main loop
- Handle forceful playback stopping for barge-in
"""

import sounddevice as sd
import numpy as np
import threading
import queue
import logging
import collections

# Input Constants
INPUT_SAMPLE_RATE = 16000
BLOCK_SIZE = 512
CHANNELS = 1
INPUT_DTYPE = 'float32'
PRE_ROLL_SECONDS = 0.5

# Output Constants (Piper default)
OUTPUT_SAMPLE_RATE = 22050
OUTPUT_DTYPE = 'int16'

class AudioManager:
    def __init__(self, input_device_index=None, output_device_index=None):
        self.logger = logging.getLogger("ARGO.Audio")
        self.running = False
        
        # Log available audio devices
        self.logger.info("[AUDIO] === Available Audio Devices ===")
        try:
            devices = sd.query_devices()
            for i, dev in enumerate(devices):
                name = dev['name'] if isinstance(dev, dict) else str(dev)
                inp = dev.get('max_input_channels', 0) if isinstance(dev, dict) else 0
                self.logger.info(f"[AUDIO]   Device {i}: {name} ({inp} input channels)")
        except Exception as e:
            self.logger.warning(f"[AUDIO] Could not list devices: {e}")
        self.logger.info(f"[AUDIO] Using input device: {input_device_index}")
        self.logger.info(f"[AUDIO] Using output device: {output_device_index}")
        self.logger.info("[AUDIO] ================================")
        
        # Audio Data Queue
        self.input_queue = queue.Queue()
        
        # Ring Buffer for Pre-roll
        maxlen = int(PRE_ROLL_SECONDS * INPUT_SAMPLE_RATE / BLOCK_SIZE)
        self.ring_buffer = collections.deque(maxlen=maxlen)
        
        # Streams
        self.input_stream = None
        self.output_stream = None
        self._input_device_index = input_device_index
        self._output_device_index = output_device_index


    def start(self):
        """Starts audio streams."""
        if self.running:
            return

        self.logger.info(f"Audio Manager Starting...")
        try:
            # 1. Input Stream
            self.input_stream = sd.InputStream(
                device=self._input_device_index,
                channels=CHANNELS,
                samplerate=INPUT_SAMPLE_RATE,
                callback=self._audio_callback,
                blocksize=BLOCK_SIZE,
                dtype=INPUT_DTYPE
            )
            self.input_stream.start()
            self.running = True
        except Exception as e:
            self.logger.critical(f"Audio Input Init Failed: {e}")
            raise

    def _ensure_output_stream(self):
        """Lazy initializer for output stream to handle stops/restarts."""
        if self.output_stream is None or not self.output_stream.active:
            try:
                self.output_stream = sd.OutputStream(
                    device=self._output_device_index,
                    channels=CHANNELS,
                    samplerate=OUTPUT_SAMPLE_RATE,
                    dtype=OUTPUT_DTYPE
                )
                self.output_stream.start()
            except Exception as e:
                self.logger.error(f"Failed to start output stream: {e}")

    def stop(self):
        self.running = False
        if self.input_stream:
            self.input_stream.stop()
            self.input_stream.close()
        self.stop_playback()

    def _audio_callback(self, indata, frames, time_info, status):
        """Audio callback (runs in background thread)."""
        if status:
            pass # Ignore underflows/overflows in logs to reduce noise
        
        data = indata.copy()
        self.input_queue.put(data)

    def read_frame(self):
        """Blocking read for main loop. Returns 512 samples."""
        try:
            frame = self.input_queue.get(timeout=1.0)
            self.ring_buffer.append(frame)
            return frame
        except queue.Empty:
            return None

    def play_chunk(self, data):
        """Play raw PCM audio. Blocking write to stream."""
        self._ensure_output_stream()
        if self.output_stream:
            try:
                self.output_stream.write(data)
            except Exception as e:
                self.logger.error(f"Write error: {e}")

    def stop_playback(self):
        """Forcefully stop playback by killing the stream."""
        if self.output_stream:
            try:
                # Abort drops buffers immediately
                self.output_stream.abort() 
                self.output_stream.close()
            except Exception as e:
                self.logger.error(f"Stop playback error: {e}")
            finally:
                self.output_stream = None
        self.logger.info("Audio playback flushed/stopped.")

    def get_preroll(self):
        if not self.ring_buffer:
            return np.array([], dtype=INPUT_DTYPE)
        return np.concatenate(list(self.ring_buffer))

    def clear_buffers(self):
        with self.input_queue.mutex:
            self.input_queue.queue.clear()
        self.ring_buffer.clear()
