
"""
AudioManager: Queue-Based Audio Input/Output

Responsibilities:
- Manage sounddevice InputStream and OutputStream
- Buffer audio frames in a queue (non-blocking)
- Maintain ring buffer for pre-roll
- Provide synchronous read_frame() for main loop
- Handle forceful playback stopping for barge-in
"""

# ============================================================================
# 1) IMPORTS
# ============================================================================
import sounddevice as sd
import numpy as np
import threading
import queue
import logging
import collections

from core.audio_owner import get_audio_owner

try:
    from core.instrumentation import log_event
except Exception:
    def log_event(event: str, stage: str = "", interaction_id: str = ""):
        pass

# ============================================================================
# 2) INPUT CONSTANTS
# ============================================================================
# Input Constants
INPUT_SAMPLE_RATE = 16000
BLOCK_SIZE = 512
CHANNELS = 1
INPUT_DTYPE = 'float32'
PRE_ROLL_SECONDS = 0.5

# ============================================================================
# 3) OUTPUT CONSTANTS (PIPER DEFAULT)
# ============================================================================
# Output Constants (Piper default)
OUTPUT_SAMPLE_RATE = 22050
OUTPUT_DTYPE = 'int16'

# ============================================================================
# 4) AUDIO MANAGER
# ============================================================================
class AudioManager:
    def __init__(self, input_device_index=None, output_device_index=None, on_owner_change=None):
        self.logger = logging.getLogger("ARGO.Audio")
        self.running = False

        # Audio ownership
        self._audio_owner = get_audio_owner()
        self._owner_lock = threading.Lock()
        self._on_owner_change = on_owner_change
        
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
        self._output_lock = threading.Lock()
        self._stop_playback_event = threading.Event()


    def _select_input_device(self, preferred_index):
        try:
            devices = sd.query_devices()
        except Exception:
            devices = []

        if preferred_index is not None:
            try:
                dev = sd.query_devices(preferred_index)
                if dev.get('max_input_channels', 0) > 0:
                    sd.check_input_settings(
                        device=preferred_index,
                        channels=CHANNELS,
                        samplerate=INPUT_SAMPLE_RATE,
                    )
                    return preferred_index
            except Exception:
                pass

        try:
            default_in = sd.default.device[0]
            if default_in is not None:
                dev = sd.query_devices(default_in)
                if dev.get('max_input_channels', 0) > 0:
                    sd.check_input_settings(
                        device=default_in,
                        channels=CHANNELS,
                        samplerate=INPUT_SAMPLE_RATE,
                    )
                    return default_in
        except Exception:
            pass

        for i, dev in enumerate(devices):
            if dev.get('max_input_channels', 0) > 0:
                try:
                    sd.check_input_settings(
                        device=i,
                        channels=CHANNELS,
                        samplerate=INPUT_SAMPLE_RATE,
                    )
                    return i
                except Exception:
                    continue
        return None

    def _select_output_device(self, preferred_index):
        try:
            devices = sd.query_devices()
        except Exception:
            devices = []

        if preferred_index is not None:
            try:
                dev = sd.query_devices(preferred_index)
                if dev.get('max_output_channels', 0) > 0:
                    sd.check_output_settings(
                        device=preferred_index,
                        channels=CHANNELS,
                        samplerate=OUTPUT_SAMPLE_RATE,
                    )
                    return preferred_index
            except Exception:
                pass

        try:
            default_out = sd.default.device[1]
            if default_out is not None:
                dev = sd.query_devices(default_out)
                if dev.get('max_output_channels', 0) > 0:
                    sd.check_output_settings(
                        device=default_out,
                        channels=CHANNELS,
                        samplerate=OUTPUT_SAMPLE_RATE,
                    )
                    return default_out
        except Exception:
            pass

        for i, dev in enumerate(devices):
            if dev.get('max_output_channels', 0) > 0:
                try:
                    sd.check_output_settings(
                        device=i,
                        channels=CHANNELS,
                        samplerate=OUTPUT_SAMPLE_RATE,
                    )
                    return i
                except Exception:
                    continue
        return None


    def start(self):
        """Starts audio streams."""
        if self.running:
            return

        self.logger.info(f"Audio Manager Starting...")
        try:
            preferred_input = self._input_device_index

            def _attempt_start_input(device_index, label):
                if device_index is None:
                    return False
                try:
                    self.input_stream = sd.InputStream(
                        device=device_index,
                        channels=CHANNELS,
                        samplerate=INPUT_SAMPLE_RATE,
                        callback=self._audio_callback,
                        blocksize=BLOCK_SIZE,
                        dtype=INPUT_DTYPE
                    )
                    self.input_stream.start()
                    self.running = True
                    self._input_device_index = device_index
                    self.logger.info(f"[AUDIO] Input device active ({label}): {device_index}")
                    return True
                except Exception as e:
                    self.logger.warning(f"[AUDIO] Input device failed ({label}={device_index}): {e}")
                    self.input_stream = None
                    return False

            if _attempt_start_input(preferred_input, "preferred"):
                return

            resolved_input = self._select_input_device(None if preferred_input is not None else preferred_input)
            if resolved_input != preferred_input:
                self.logger.warning(
                    f"[AUDIO] Input device fallback: {preferred_input} -> {resolved_input}"
                )

            if not _attempt_start_input(resolved_input, "fallback"):
                raise RuntimeError("No usable input device found")
        except Exception as e:
            self.logger.critical(f"Audio Input Init Failed: {e}")
            raise

    def _ensure_output_stream(self):
        """Lazy initializer for output stream to handle stops/restarts."""
        if self.output_stream is None or not self.output_stream.active:
            try:
                resolved_output = self._select_output_device(self._output_device_index)
                if resolved_output != self._output_device_index:
                    self.logger.warning(
                        f"[AUDIO] Output device fallback: {self._output_device_index} -> {resolved_output}"
                    )
                    self._output_device_index = resolved_output
                self.output_stream = sd.OutputStream(
                    device=self._output_device_index,
                    channels=CHANNELS,
                    samplerate=OUTPUT_SAMPLE_RATE,
                    dtype=OUTPUT_DTYPE
                )
                self.output_stream.start()
                self._stop_playback_event.clear()
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
        if self._stop_playback_event.is_set():
            return
        with self._output_lock:
            if self._stop_playback_event.is_set():
                return
            self._ensure_output_stream()
            if self.output_stream and getattr(self.output_stream, "active", False):
                try:
                    self.output_stream.write(data)
                except Exception as e:
                    self.logger.error(f"Write error: {e}")

    def stop_playback(self):
        """Forcefully stop playback by killing the stream."""
        self._stop_playback_event.set()
        with self._output_lock:
            if self.output_stream:
                try:
                    if getattr(self.output_stream, "active", False):
                        self.output_stream.stop()
                    self.output_stream.close()
                except Exception as e:
                    self.logger.error(f"Stop playback error: {e}")
                finally:
                    self.output_stream = None
        self.logger.info("Audio playback flushed/stopped.")

    def acquire_audio(self, owner: str, interaction_id: str = ""):
        with self._owner_lock:
            current_owner = self._audio_owner.get_owner()
            if current_owner and current_owner != owner:
                if current_owner == "MUSIC" and owner == "STT":
                    self._audio_owner.force_release("STT_PREEMPT")
                    log_event(
                        f"AUDIO_PREEMPT prior={current_owner} requested={owner}",
                        stage="audio",
                        interaction_id=interaction_id,
                    )
                    current_owner = None
                if current_owner:
                    log_event(
                        f"AUDIO_CONTESTED owner={current_owner} requested={owner}",
                        stage="audio",
                        interaction_id=interaction_id,
                    )
                    if self._on_owner_change:
                        self._on_owner_change(current_owner, True)
                    raise RuntimeError("Audio already owned")
            self._audio_owner.acquire(owner)
            log_event(
                f"AUDIO_ACQUIRED owner={owner}",
                stage="audio",
                interaction_id=interaction_id,
            )
            if self._on_owner_change:
                self._on_owner_change(owner, False)

    def release_audio(self, owner: str, interaction_id: str = ""):
        with self._owner_lock:
            if self._audio_owner.get_owner() == owner:
                self._audio_owner.release(owner)
                log_event(
                    f"AUDIO_RELEASED owner={owner}",
                    stage="audio",
                    interaction_id=interaction_id,
                )
                if self._on_owner_change:
                    self._on_owner_change("NONE", False)

    def force_release_audio(self, reason: str = "", interaction_id: str = ""):
        with self._owner_lock:
            prior = self._audio_owner.get_owner()
            if prior:
                self._audio_owner.force_release(reason)
                log_event(
                    f"AUDIO_FORCED_RELEASE prior={prior} reason={reason}",
                    stage="audio",
                    interaction_id=interaction_id,
                )
                if self._on_owner_change:
                    self._on_owner_change("NONE", True)

    def get_audio_owner(self) -> str:
        return self._audio_owner.get_owner() or "NONE"

    def get_preroll(self):
        if not self.ring_buffer:
            return np.array([], dtype=INPUT_DTYPE)
        return np.concatenate(list(self.ring_buffer))

    def clear_buffers(self):
        with self.input_queue.mutex:
            self.input_queue.queue.clear()
        self.ring_buffer.clear()
