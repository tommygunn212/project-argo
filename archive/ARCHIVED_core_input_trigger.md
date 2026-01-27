The original `core/input_trigger.py` has been archived as part of the Gemini Build Studio fixes.

Full historic copies are available in backups under `backups/milestone_20260120_002245/core/input_trigger.py`.

Rationale: Input-trigger logic has been consolidated into `core/audio_manager.py` (single mic owner) to avoid multiple mic opens and conflicting implementations.
