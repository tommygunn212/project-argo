# ARGO GUI Launcher

Simple one-button interface to run ARGO with visual status lights and activity log.

## Features

- **START Button**: Launch ARGO with one click (no PowerShell needed)
- **Status Lights**:
  - 🔴 **Red Light** = Ready (waiting for wake word)
  - 🟢 **Green Light** = Recording (listening to user)
- **Activity Log**: Real-time display of all events, errors, and debug info
- **STOP Button**: Gracefully stop ARGO anytime

## Quick Start

### Option 1: Double-click the batch file
```
launch_gui.bat
```

### Option 2: Run from PowerShell
```powershell
cd I:\argo
python gui_launcher.py
```

## How to Use

1. **Click START** - ARGO initializes and enters listening mode (red light)
2. **Say wake word** (default: "Argo") - Light turns green while recording
3. **Ask a question** - Light returns to red after you finish
4. **ARGO responds** - See answer in speaker output
5. **Repeat** or **Click STOP** to exit

## Activity Log

The text box shows:
- Startup messages
- Wake word detections
- Recording start/stop events
- Transcribed text
- Intent classifications
- LLM responses
- Errors and warnings

**Useful for**:
- Debugging issues
- Copying error messages
- Understanding system flow
- Checking if voice was heard

## Status Light Meanings

| Light | State | Meaning |
|-------|-------|---------|
| 🔴 Red | Ready | Waiting for wake word ("Argo") |
| 🟢 Green | Recording | Actively listening to your voice |
| 🔴 Red | Processing | After you speak, processing your request |

## Troubleshooting

**Red light never turns green?**
- Check microphone is connected and working
- Make sure wake word "Argo" is spoken clearly
- Check log for "[InputTrigger]" messages

**Audio cuts off mid-sentence?**
- Check "MAX_RECORDING_DURATION" in log (~10 seconds max)
- Speak more slowly if sentences are too fast
- Longer silence = recording stops automatically

**No log output?**
- Logs appear as events happen (real-time)
- Give ARGO a moment to start
- Click START and wait 2-3 seconds

**Error messages in log?**
- Copy error text from log
- Check if Ollama is running (`ollama serve`)
- Verify audio devices are working

## Advanced

### Modify timeout values
Edit `core/coordinator.py`:
- `MAX_RECORDING_DURATION` - Max recording time (seconds)
- `SILENCE_TIMEOUT_SECONDS` - Wait time for silence before stopping

### Enable detailed metrics
Set environment variable:
```powershell
$env:ARGO_RECORD_DEBUG = "1"
python gui_launcher.py
```

### Change wake word
Edit `core/config.py` or modify config.json

## Architecture

```
launch_gui.bat
    ↓
gui_launcher.py (tkinter GUI)
    ↓
    ├─ START button → Coordinator.run() in background thread
    ├─ Callbacks → on_recording_start() / on_recording_stop()
    ├─ Light updates (Red ↔ Green)
    └─ Log display updates (real-time)
```

## Files

- `gui_launcher.py` - Main GUI application
- `launch_gui.bat` - Windows batch launcher
- `core/coordinator.py` - Modified to emit recording callbacks

## What Changed in Core

The Coordinator now has:
- `on_recording_start` callback (called when recording begins)
- `on_recording_stop` callback (called when recording ends)
- `stop()` method (gracefully stop the loop)
- Optional `on_status_update` callback for future use

These are completely **optional** and don't affect the normal command-line operation.

---

**Status**: Ready to use  
**Tested**: Yes  
**Dependencies**: tkinter (built-in Python)  
**Python Version**: 3.8+
