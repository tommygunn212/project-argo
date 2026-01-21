# GUI Fix - Component Initialization

## Problem
The GUI was trying to create a Coordinator with no arguments:
```python
self.coordinator = Coordinator()  # ERROR - missing 5 required arguments
```

But Coordinator requires 5 dependencies to initialize:
- input_trigger (wake word detector)
- speech_to_text (Whisper)
- intent_parser (rule-based)
- response_generator (LLM)
- output_sink (TTS)

## Solution
Modified `gui_launcher.py` to properly initialize all components before creating the Coordinator.

### Changes Made

1. **Removed premature Coordinator import** at top of file
   - Moved import to where it's needed (inside initialization)

2. **Created `_initialize_and_run()` method**
   - Initializes all 5 components
   - Imports Coordinator
   - Creates Coordinator with all dependencies
   - Calls `_run_coordinator()` to start the loop

3. **Updated `_on_start()` method**
   - Now calls `_initialize_and_run()` in background thread
   - Allows GUI to stay responsive during initialization

### Initialization Sequence

```
User clicks START
    ↓
_on_start() called
    ↓
Launch _initialize_and_run() in background thread
    ↓
Import components:
  - InputTrigger (Porcupine wake word)
  - SpeechToText (Whisper)
  - RuleBasedIntentParser
  - LLMResponseGenerator
  - OutputSink
    ↓
Create each component
    ↓
Create Coordinator with all components
    ↓
Run _run_coordinator() to start main loop
    ↓
Log shows initialization steps
    ↓
Light turns red (ready for wake word)
```

### Error Handling
If any component fails to initialize:
1. Exception is caught
2. Error logged with details
3. Traceback printed to log
4. GUI buttons reset to allow retry
5. User can click START again

## Testing
All components now:
- Import successfully
- Are available at initialization time
- Can be mocked for testing
- Work together properly

## Result
GUI now:
- Properly initializes ARGO system
- Shows component initialization in log
- Handles errors gracefully
- Can be restarted if something fails
- Ready to listen for wake word

Try it:
1. Double-click launch_gui.bat
2. Click START
3. Watch log for initialization messages
4. Light turns red when ready
5. Say "Argo"
