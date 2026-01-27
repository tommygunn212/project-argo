#!/usr/bin/env python3
"""
ARGO GUI Launcher - Simple one-button interface with status lights and log display

Features:
- START button to begin recording
- Red light = Ready (waiting for wake word)
- Green light = Recording/Listening
- Text box shows real-time logs and errors
"""

import tkinter as tk
from tkinter import scrolledtext
import threading
import queue
import logging
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

# Load environment variables first
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

# Add argo to path
sys.path.insert(0, r'i:\argo')


class StatusLight:
    """Visual status indicator (red/green circle)."""
    
    def __init__(self, canvas, x, y, size=40):
        self.canvas = canvas
        self.x = x
        self.y = y
        self.size = size
        self.oval = canvas.create_oval(
            x - size//2, y - size//2,
            x + size//2, y + size//2,
            fill='red', outline='black', width=2
        )
        self.state = 'ready'  # 'ready' = red, 'recording' = green
    
    def set_ready(self):
        """Set light to red (ready)."""
        if self.state != 'ready':
            self.canvas.itemconfig(self.oval, fill='red')
            self.state = 'ready'
    
    def set_recording(self):
        """Set light to green (recording)."""
        if self.state != 'recording':
            self.canvas.itemconfig(self.oval, fill='lime')
            self.state = 'recording'


class LogHandler(logging.Handler):
    """Logging handler that sends messages to GUI text box."""
    
    def __init__(self, queue):
        super().__init__()
        self.queue = queue
    
    def emit(self, record):
        msg = self.format(record)
        self.queue.put(msg)


class ArgoGUI:
    """ARGO GUI interface."""
    
    def __init__(self, root):
        self.root = root
        self.root.title("ARGO - One-Button Voice Assistant")
        self.root.geometry("600x500")
        self.root.resizable(False, False)
        
        # Message queue for logging
        self.log_queue = queue.Queue()
        
        # Coordinator and thread
        self.coordinator = None
        self.coordinator_thread = None
        self.running = False
        
        # Create GUI elements
        self._create_widgets()
        
        # Setup logging
        self._setup_logging()
        
        # Start log update loop
        self._update_logs()
    
    def _create_widgets(self):
        """Create GUI elements."""
        # Title
        title = tk.Label(
            self.root,
            text="ARGO Voice Assistant",
            font=("Arial", 18, "bold"),
            fg="#333"
        )
        title.pack(pady=10)
        
        # Status section
        status_frame = tk.Frame(self.root)
        status_frame.pack(pady=10)
        
        # Status light canvas
        canvas = tk.Canvas(status_frame, width=100, height=100, bg="white", highlightthickness=0)
        canvas.pack()
        self.light = StatusLight(canvas, 50, 50, size=40)
        
        # Status text
        self.status_label = tk.Label(
            status_frame,
            text="Ready",
            font=("Arial", 12),
            fg="#666"
        )
        self.status_label.pack(pady=5)
        
        # Button frame
        button_frame = tk.Frame(self.root)
        button_frame.pack(pady=10)
        
        # Start button
        self.start_button = tk.Button(
            button_frame,
            text="START",
            font=("Arial", 14, "bold"),
            bg="#4CAF50",
            fg="white",
            padx=30,
            pady=10,
            command=self._on_start,
            width=15
        )
        self.start_button.pack(side=tk.LEFT, padx=5)
        
        # Stop button
        self.stop_button = tk.Button(
            button_frame,
            text="STOP",
            font=("Arial", 14, "bold"),
            bg="#f44336",
            fg="white",
            padx=30,
            pady=10,
            command=self._on_stop,
            width=15,
            state=tk.DISABLED
        )
        self.stop_button.pack(side=tk.LEFT, padx=5)
        
        # Log display label
        log_label = tk.Label(
            self.root,
            text="Activity Log:",
            font=("Arial", 10, "bold"),
            anchor="w",
            padx=10
        )
        log_label.pack(fill=tk.X, padx=10, pady=(5, 0))
        
        # Log text area
        self.log_text = scrolledtext.ScrolledText(
            self.root,
            height=12,
            width=70,
            font=("Courier", 8),
            bg="#f5f5f5",
            wrap=tk.WORD
        )
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # Make log read-only
        self.log_text.config(state=tk.DISABLED)
    
    def _setup_logging(self):
        """Setup logging to send messages to GUI."""
        # Create logger
        logger = logging.getLogger()
        logger.setLevel(logging.DEBUG)
        
        # Remove existing handlers
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
        
        # Add GUI handler
        gui_handler = LogHandler(self.log_queue)
        gui_handler.setFormatter(logging.Formatter(
            '%(asctime)s [%(levelname)s] %(message)s',
            datefmt='%H:%M:%S'
        ))
        logger.addHandler(gui_handler)
        
        # Also add console handler for debugging
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(logging.Formatter(
            '%(asctime)s [%(levelname)s] %(message)s',
            datefmt='%H:%M:%S'
        ))
        logger.addHandler(console_handler)
    
    def _log_crash(self, exc_type: str, exc_value: str, exc_tb: str) -> None:
        """Log crash to both file and GUI."""
        crash_log_path = Path("logs") / "gui_crash.log"
        Path("logs").mkdir(exist_ok=True)
        with open(crash_log_path, 'a') as f:
            f.write(f"\n{'='*80}\n")
            f.write(f"CRASH AT: {datetime.now().isoformat()}\n")
            f.write(f"{'='*80}\n")
            f.write(f"Exception Type: {exc_type}\n")
            f.write(f"Exception Value: {exc_value}\n")
            f.write(f"Traceback:\n{exc_tb}\n")
        
        # Log to GUI
        logging.error(f"[CRASH] {exc_type}: {exc_value}")
        logging.error(f"[CRASH] Full traceback written to logs/gui_crash.log")
    
    def _update_logs(self):
        """Update log display from queue."""
        try:
            while not self.log_queue.empty():
                msg = self.log_queue.get_nowait()
                self.log_text.config(state=tk.NORMAL)
                self.log_text.insert(tk.END, msg + "\n")
                self.log_text.see(tk.END)
                self.log_text.config(state=tk.DISABLED)
        except queue.Empty:
            pass
        
        # Schedule next update
        self.root.after(100, self._update_logs)
    
    def _on_start(self):
        """Start ARGO."""
        if self.running:
            logging.info("[GUI] Already running")
            return
        
        logging.info("[GUI] Starting ARGO...")
        self.start_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)
        self.running = True
        
        # Set light to ready
        self.light.set_ready()
        self.status_label.config(text="Ready - Waiting for wake word", fg="#2196F3")
        
        # Start coordinator in background thread
        self.coordinator_thread = threading.Thread(
            target=self._initialize_and_run,
            daemon=True
        )
        self.coordinator_thread.start()
    
    def _on_stop(self):
        """Stop ARGO."""
        if not self.running:
            return
        
        logging.info("[GUI] Stopping ARGO...")
        self.running = False
        self.start_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)
        
        # Set light to ready
        self.light.set_ready()
        self.status_label.config(text="Stopped", fg="#666")
        
        # Stop coordinator
        if self.coordinator:
            self.coordinator.stop()
    
    def _initialize_and_run(self):
        """Initialize all ARGO components and run the coordinator (UNKILLABLE)."""
        try:
            # CRITICAL: Lock input device BEFORE any component initialization
            # This must happen before PorcupineWakeWordTrigger is created
            import sounddevice as sd
            from core.config import get_config
            try:
                config = get_config()
                input_device_index = config.get("audio.input_device_index", None)
                if input_device_index is not None:
                    sd.default.device = (input_device_index, None)
                    logging.info(
                        f"[GUI] Input device locked to index {input_device_index}"
                    )
                else:
                    logging.warning("[GUI] Input device not set in config")
            except Exception as e:
                logging.warning(f"[GUI] Could not lock device: {e}")
            
            logging.info("[GUI] Initializing ARGO components...")
            
            # Import all required components
            from core.input_trigger import PorcupineWakeWordTrigger
            from core.speech_to_text import WhisperSTT
            from core.intent_parser import RuleBasedIntentParser
            from core.response_generator import LLMResponseGenerator
            from core.output_sink import get_output_sink
            from core.coordinator import Coordinator
            
            # Initialize components
            logging.info("[GUI] Creating InputTrigger (wake word detector)...")
            input_trigger = PorcupineWakeWordTrigger()
            
            logging.info("[GUI] Creating SpeechToText (Whisper)...")
            speech_to_text = WhisperSTT()
            
            logging.info("[GUI] Creating IntentParser...")
            intent_parser = RuleBasedIntentParser()
            
            logging.info("[GUI] Creating ResponseGenerator (LLM)...")
            response_generator = LLMResponseGenerator()
            
            logging.info("[GUI] Creating OutputSink (TTS)...")
            # Use get_output_sink() factory to enable graceful fallback if Piper fails
            output_sink = get_output_sink()
            
            # Create coordinator
            logging.info("[GUI] Creating Coordinator...")
            self.coordinator = Coordinator(
                input_trigger=input_trigger,
                speech_to_text=speech_to_text,
                intent_parser=intent_parser,
                response_generator=response_generator,
                output_sink=output_sink
            )
            
            logging.info("[GUI] ARGO components initialized successfully")
            
            # Run coordinator with callbacks
            self._run_coordinator()
        
        except SystemExit as e:
            logging.error(f"[SYSTEM_EXIT] SystemExit intercepted: {e}")
            self._log_crash("SystemExit", str(e), traceback.format_exc())
            self.running = False
            self.start_button.config(state=tk.NORMAL)
            self.stop_button.config(state=tk.DISABLED)
        except KeyboardInterrupt as e:
            logging.warning(f"[KEYBOARD_INTERRUPT] User interrupted")
            self.running = False
            self.start_button.config(state=tk.NORMAL)
            self.stop_button.config(state=tk.DISABLED)
        except Exception as e:
            logging.error(f"[GUI] Initialization FATAL: {type(e).__name__}: {e}")
            self._log_crash(type(e).__name__, str(e), traceback.format_exc())
            self.running = False
            self.start_button.config(state=tk.NORMAL)
            self.stop_button.config(state=tk.DISABLED)
    
    def _run_coordinator(self):
        """Run coordinator in background thread (UNKILLABLE)."""
        try:
            logging.info("[GUI] Coordinator thread started")
            
            # Add state change callbacks to coordinator
            if hasattr(self.coordinator, 'on_recording_start'):
                self.coordinator.on_recording_start = self._on_recording_start
            if hasattr(self.coordinator, 'on_recording_stop'):
                self.coordinator.on_recording_stop = self._on_recording_stop
            
            # Run main loop
            self.coordinator.run()
        
        except SystemExit as e:
            logging.error(f"[COORDINATOR] SystemExit intercepted: {e}")
            self._log_crash("SystemExit (Coordinator)", str(e), traceback.format_exc())
        except KeyboardInterrupt as e:
            logging.warning(f"[COORDINATOR] KeyboardInterrupt detected")
        except Exception as e:
            logging.error(f"[COORDINATOR] FATAL: {type(e).__name__}: {e}")
            self._log_crash(f"Coordinator-{type(e).__name__}", str(e), traceback.format_exc())
        finally:
            self.running = False
            self.start_button.config(state=tk.NORMAL)
            self.stop_button.config(state=tk.DISABLED)
            self.light.set_ready()
            self.status_label.config(text="Stopped (check logs)", fg="#f44336")
            logging.info("[GUI] Coordinator thread ended")
    
    def _on_recording_start(self):
        """Called when recording starts."""
        self.root.after(0, lambda: self._update_recording_status(True))
    
    def _on_recording_stop(self):
        """Called when recording stops."""
        self.root.after(0, lambda: self._update_recording_status(False))
    
    def _update_recording_status(self, is_recording):
        """Update GUI when recording status changes."""
        if is_recording:
            self.light.set_recording()
            self.status_label.config(text="Recording - Listening...", fg="#ff9800")
            logging.info("[GUI] Recording started (green light)")
        else:
            self.light.set_ready()
            self.status_label.config(text="Ready - Waiting for wake word", fg="#2196F3")
            logging.info("[GUI] Recording stopped (red light)")


def main():
    """Main entry point."""
    logging.basicConfig(level=logging.INFO)
    logging.info("[Main] Starting ARGO GUI Launcher")
    
    root = tk.Tk()
    gui = ArgoGUI(root)
    
    logging.info("[Main] GUI initialized - waiting for user interaction")
    root.mainloop()


if __name__ == "__main__":
    main()
