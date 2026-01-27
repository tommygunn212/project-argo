The original `core/wake_word_detector.py` has been archived as part of the Gemini Build Studio fixes.

Full historic copies are available in backups under `backups/milestone_20260120_002245/core/wake_word_detector.py`.

Rationale: Subprocess-based and multi-instance wake detectors were removed. A single Porcupine instance lives in `core/audio_manager.py`.
