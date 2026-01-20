# TROUBLESHOOTING.md

Comprehensive troubleshooting guide for ARGO voice pipeline. Find your issue below and follow the fix.

---

## Quick Diagnostics

### Check All Systems Are Running

Run this before troubleshooting:

```powershell
# 1. Check Python
python --version

# 2. Check virtual environment is active (should show (.venv))
cd i:\argo
.\.venv\Scripts\Activate.ps1

# 3. Check Ollama
curl http://localhost:11434/api/tags

# 4. Check Porcupine access key
echo $env:PORCUPINE_ACCESS_KEY

# 5. Check audio devices
python -c "import sounddevice; print(sounddevice.query_devices())"

# 6. Test imports
python -c "from core.coordinator import Coordinator; print('OK')"
```

---

## Installation & Setup Issues

### Python Not Found

**Symptom:** `'python' is not recognized as an internal or external command`

**Fix:**
1. Download Python 3.9+ from https://www.python.org
2. During installation, **CHECK** "Add Python to PATH"
3. Restart PowerShell
4. Verify: `python --version`

---

### Virtual Environment Won't Activate

**Symptom:** `.\.venv\Scripts\Activate.ps1` doesn't work or shows error

**Fix (Windows PowerShell):**
```powershell
# Allow scripts to run
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

# Activate
.\.venv\Scripts\Activate.ps1

# You should see (.venv) at the start of your prompt
```

**If still not working:**
```powershell
# Delete and recreate
Remove-Item -Recurse .venv
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

---

### Missing Dependencies

**Symptom:** `ModuleNotFoundError: No module named 'sounddevice'` or similar

**Fix:**
```powershell
# Make sure virtual environment is active (see (.venv) prompt)
pip install -r requirements.txt

# Or install specific missing package
pip install sounddevice porcupine-pxp whisper piper-tts
```

**Verify installation:**
```powershell
python -c "import sounddevice, pvporcupine, whisper, piper; print('All OK')"
```

---

## Startup Issues

### Porcupine Access Key Not Found

**Symptom:**
```
[ERROR] Porcupine initialization failed
Unable to get access key
```

**Fix:**
1. Get free access key from https://console.picovoice.ai
2. Set environment variable:
   ```powershell
   $env:PORCUPINE_ACCESS_KEY = "your-access-key-here"
   ```
3. Make it permanent:
   ```powershell
   Add-Content $PROFILE "`n`$env:PORCUPINE_ACCESS_KEY = 'your-key-here'"
   ```
4. Restart PowerShell
5. Verify: `echo $env:PORCUPINE_ACCESS_KEY`

---

### Ollama Connection Refused

**Symptom:**
```
[ERROR] Ollama connection failed: Connection refused
```

**Fix:**
1. **Terminal 1:** Start Ollama service
   ```powershell
   ollama serve
   ```
   You should see: `Listening on 127.0.0.1:11434`

2. **Terminal 2:** Verify it's running
   ```powershell
   ollama list
   curl http://localhost:11434/api/tags
   ```

3. **Check if port 11434 is in use:**
   ```powershell
   netstat -ano | findstr :11434
   ```

4. **If port is in use by another process:**
   ```powershell
   # Find process ID from above command
   taskkill /PID <process-id> /F
   
   # Then restart Ollama
   ollama serve
   ```

---

### Model Not Found

**Symptom:**
```
[ERROR] Model 'argo:latest' not found
```

**Fix:**
1. Verify Ollama is running (see above)
2. Pull the model:
   ```powershell
   ollama pull argo:latest
   ```
3. Wait for download to complete (~2-5 minutes depending on model)
4. Verify it's installed:
   ```powershell
   ollama list
   ```

---

## Audio & Recording Issues

### No Microphone Detected

**Symptom:**
```
[ERROR] No input device found
[WARNING] Recording failed
```

**Fix:**

1. **List all audio devices:**
   ```powershell
   python -c "import sounddevice; print(sounddevice.query_devices())"
   ```

2. **Find your microphone** in the output (look for your device name)

3. **Use specific device** by editing `core/coordinator.py`:
   ```python
   # Find this line (around line 180):
   # self.input_stream = sd.InputStream(...)
   
   # Add device parameter:
   self.input_stream = sd.InputStream(device=2, ...)  # Use device index 2
   ```

4. **Test the device:**
   ```powershell
   python -c "
   import sounddevice as sd
   import numpy as np
   
   # Record 2 seconds from specific device
   audio = sd.rec(32000, samplerate=16000, channels=1, device=2)
   sd.wait()
   print(f'Recorded {len(audio)} samples')
   
   # Play back to verify
   sd.play(audio, samplerate=16000)
   sd.wait()
   print('Playback complete')
   "
   ```

---

### Recording Stops Too Early

**Symptom:**
- System records only 1-2 seconds even though you're still speaking
- Cuts off in the middle of sentences

**Fix:**

Adjust silence detection threshold in `core/coordinator.py`:

```python
# Find these parameters (around line 148):
SILENCE_DURATION = 1.5      # Seconds of silence to trigger stop
SILENCE_THRESHOLD = 500     # RMS level for detecting silence

# Try higher threshold (less sensitive, waits longer):
SILENCE_THRESHOLD = 700     # Increased from 500

# Or increase silence duration:
SILENCE_DURATION = 2.5      # Increased from 1.5
```

**Reference:**
- `SILENCE_THRESHOLD = 300` → Very sensitive (stops quickly, may cut off)
- `SILENCE_THRESHOLD = 500` → **Default** (balanced)
- `SILENCE_THRESHOLD = 800` → Insensitive (waits for more silence)

---

### Recording Won't Stop

**Symptom:**
- Recording continues for the full 15 seconds even after silence
- System seems stuck waiting for input

**Fix:**

Lower sensitivity in `core/coordinator.py`:

```python
# Make threshold lower (more sensitive to silence):
SILENCE_THRESHOLD = 300     # Decreased from 500

# Or decrease required silence duration:
SILENCE_DURATION = 0.8      # Decreased from 1.5
```

---

### No Audio Output / Silent Playback

**Symptom:**
- ARGO responds but you hear no audio
- Console shows TTS completed but no sound

**Fix:**

1. **Check audio devices:**
   ```powershell
   python -c "import sounddevice; print(sounddevice.default.device)"
   ```

2. **Test speaker:**
   ```powershell
   python -c "
   import sounddevice as sd
   import numpy as np
   
   # Generate 1kHz tone for 1 second
   sample_rate = 22050
   duration = 1
   freq = 1000
   t = np.linspace(0, duration, int(sample_rate * duration))
   tone = np.sin(2 * np.pi * freq * t) * 0.3
   
   # Play tone
   sd.play(tone, samplerate=sample_rate)
   sd.wait()
   print('If you heard a beep, speaker works')
   "
   ```

3. **Check Windows volume:**
   - Look for speaker icon in system tray
   - Make sure volume is not muted
   - Check application volume in Volume mixer

4. **Try different output device:**
   ```python
   # Edit core/coordinator.py
   import sounddevice as sd
   sd.default.device = (0, 1)  # (input_device, output_device)
   ```

---

### Squeal or Feedback

**Symptom:**
- High-pitched squeal or feedback during TTS playback
- Audio distortion or echo

**Fix:**

1. **Move microphone away** from speakers (cause: feedback loop)
2. **Reduce speaker volume** in Windows
3. **Use different speaker device:**
   ```powershell
   # List devices to find alternative
   python -c "import sounddevice; print(sounddevice.query_devices())"
   
   # Edit core/coordinator.py to use specific device
   sd.default.device = (2, 3)  # input=2, output=3
   ```

4. **Check for Echo Cancellation:**
   - Windows Settings → Sound → Advanced → App volume and device preferences
   - Disable echo cancellation for any active apps

---

## Transcription Issues

### Whisper Model Not Downloaded

**Symptom:**
```
[INFO] Downloading Whisper model (first time, ~2 minutes)...
[ERROR] Download failed or stuck
```

**Fix:**

1. **Pre-download the model:**
   ```powershell
   python -c "import whisper; model = whisper.load_model('base'); print('Downloaded')"
   ```

2. **Wait for download** (can take 2-5 minutes, ~140MB)

3. **If stuck or failed:**
   ```powershell
   # Delete cached model
   $cache_dir = "$env:USERPROFILE\.cache\whisper"
   Remove-Item -Recurse $cache_dir -ErrorAction SilentlyContinue
   
   # Retry download
   python -c "import whisper; model = whisper.load_model('base')"
   ```

---

### Audio Not Transcribed / Empty Transcription

**Symptom:**
```
[INFO] Transcribed: ""
[WARNING] Empty transcription, skipping
```

**Fix:**

1. **Verify recording worked:**
   ```powershell
   # Test recording directly
   python -c "
   import sounddevice as sd
   import numpy as np
   
   print('Recording 3 seconds...')
   audio = sd.rec(int(3 * 16000), samplerate=16000, channels=1)
   sd.wait()
   
   # Check if audio was captured
   rms = np.sqrt(np.mean(audio ** 2))
   print(f'RMS level: {rms}')
   if rms < 100:
       print('WARNING: Very quiet audio, microphone may not be working')
   else:
       print('Audio captured successfully')
   "
   ```

2. **Increase microphone level:**
   - Windows Settings → Sound → Volume mixer
   - Increase volume for your application

3. **Speak louder and closer** to microphone during testing

---

### Transcription Is Wrong

**Symptom:**
- ARGO consistently misunderstands what you say
- Transcription doesn't match spoken words

**Fix:**

1. **This is normal for base Whisper model** (especially with background noise)
2. **Improve audio quality:**
   - Use USB microphone instead of built-in
   - Reduce background noise
   - Speak clearly and directly into microphone
   - Reduce distance to microphone

3. **Try larger Whisper model** (more accurate but slower):
   ```powershell
   # In core/speech_to_text.py, change:
   model = whisper.load_model("base")
   # To:
   model = whisper.load_model("small")  # More accurate, slower
   ```

---

## TTS (Text-to-Speech) Issues

### Piper Executable Not Found

**Symptom:**
```
[ERROR] Piper executable not found at: audio/piper/piper/piper.exe
```

**Fix:**

1. **Verify piper exists:**
   ```powershell
   ls audio/piper/piper/piper.exe
   ```

2. **If not found, download it:**
   ```powershell
   # Option A: Using pip
   pip install piper-tts
   
   # Option B: Download voices/models
   python -m piper.download_voices --voice en_US-lessac-medium
   ```

3. **Check .env file:**
   ```powershell
   cat .env
   ```
   Should have: `PIPER_PATH=audio/piper/piper/piper.exe`

---

### TTS Audio Is Silent

**Symptom:**
- TTS completes but no audio is played

**Fix:**

1. **Check speaker settings** (see "No Audio Output" above)
2. **Verify Piper is working:**
   ```powershell
   # Test Piper directly
   $env:PIPER_PATH = "audio/piper/piper/piper.exe"
   $text = "Hello world"
   
   # On Windows (if installed in standard location):
   echo $text | & $env:PIPER_PATH --model en_US-lessac-medium | Out-Null
   ```

3. **Check audio device in output_sink.py:**
   ```python
   # Verify default output device is set correctly
   import sounddevice as sd
   print(sd.default.device)
   ```

---

### TTS Sounds Robotic or Unnatural

**Symptom:**
- Voice sounds very artificial or monotone

**Fix:**

1. **This is normal for offline TTS** (Piper uses ONNX, not high-end models)
2. **Try different voice model:**
   ```powershell
   # Download alternative voices
   python -m piper.download_voices --voice en_US-libritts-high
   python -m piper.download_voices --voice en_US-glow-tts
   
   # Edit .env to use new voice
   # PIPER_VOICE_MODEL=en_US-libritts-high
   ```

3. **For premium voices**, consider Deepgram Aura (requires API key):
   - See [RELEASE_NOTES_v1_0_0_COMPLETE.md](RELEASE_NOTES_v1_0_0_COMPLETE.md#alternative-tts-options)

---

## LLM Response Issues

### LLM Returns Empty Response

**Symptom:**
```
[INFO] LLM Response: ""
[WARNING] Empty response from Ollama
```

**Fix:**

1. **Verify Ollama is running:**
   ```powershell
   ollama list
   curl http://localhost:11434/api/tags
   ```

2. **Check model is installed:**
   ```powershell
   ollama show argo:latest
   ```

3. **Test Ollama directly:**
   ```powershell
   curl -X POST http://localhost:11434/api/generate -H "Content-Type: application/json" -d '{
     "model": "argo:latest",
     "prompt": "Say hello",
     "stream": false
   }'
   ```

---

### LLM Response Is Truncated

**Symptom:**
- ARGO only says "Sure" or very short responses
- Long answers get cut off at the beginning

**Fix:**

**This is fixed in v1.0.0**, but if you're seeing this:

1. **Check max_tokens in core/response_generator.py:**
   ```python
   # Should be:
   max_tokens: 2000
   ```

2. **If still truncated, increase it:**
   ```python
   max_tokens: 4000  # Or higher
   ```

---

### LLM Response Is Irrelevant

**Symptom:**
- ARGO gives wrong or nonsensical answers
- Responses don't match questions

**Fix:**

1. **Verify transcription is correct:**
   - Check what was transcribed in console output
   - If transcription is wrong, see [Transcription Issues](#transcription-issues)

2. **Check intent classification:**
   ```python
   # Edit core/intent_parser.py to see what intent was detected
   # Add debug output:
   print(f"Detected intent: {intent.type}")
   ```

3. **Try different LLM model:**
   ```powershell
   # Try different Ollama model (if installed)
   ollama pull mistral
   ollama pull neural-chat
   
   # Edit core/response_generator.py to use different model
   # model = "mistral"
   ```

---

## Performance Issues

### Latency Is Very High (>15 seconds)

**Symptom:**
- System takes much longer than normal to respond
- Each step (record, transcribe, generate, speak) is slow

**Fix:**

1. **Check CPU usage:**
   - Open Task Manager (Ctrl+Shift+Esc)
   - Look at CPU and RAM usage
   - If >90% CPU, close other applications

2. **Monitor each component:**
   - Console shows timing for each step
   - Look for which component is slowest
   - Address specific slow component (see below)

3. **Slow Recording?**
   - Reduce SILENCE_DURATION
   - Increase SILENCE_THRESHOLD

4. **Slow Transcription?**
   - Using smaller Whisper model (base)
   - Running on CPU (no GPU)
   - Try closing background applications

5. **Slow LLM Response?**
   - Reduce max_tokens
   - Verify Ollama is not competing for CPU
   - Try smaller LLM model

6. **Slow TTS?**
   - Using high-quality Piper voice
   - Try simpler voice model

---

### High CPU Usage During Recording

**Symptom:**
- CPU jumps to 80-100% while recording

**Fix:**

This is normal for Whisper transcription, but you can:

1. **Run on GPU** (if available):
   ```python
   # Edit core/speech_to_text.py
   model = whisper.load_model("base", device="cuda")  # Use GPU
   ```

2. **Use smaller model:**
   ```python
   model = whisper.load_model("tiny")  # Faster, less accurate
   ```

---

### Recording Latency Too High

**Symptom:**
- System records even after saying stop
- Takes too long to start recording

**Fix:**

1. **Recording takes time because of silence detection**
   - Minimum is 1.5 seconds (default SILENCE_DURATION)
   - Shortest full interaction: ~1.5s record + transcribe + LLM + TTS = ~7s

2. **To speed up:**
   ```python
   # Edit core/coordinator.py
   SILENCE_DURATION = 1.0      # Shorter wait for silence
   SILENCE_THRESHOLD = 600     # More sensitive to silence
   ```

3. **Trade-off:** Shorter silence detection may cut off end of speech

---

## Session & Loop Issues

### System Exits After First Interaction

**Symptom:**
```
[INFO] Interaction 1 complete
[OK] Session ended
```
System stops after one response instead of listening for more

**Fix:**

1. **Check MAX_INTERACTIONS in core/coordinator.py:**
   ```python
   MAX_INTERACTIONS = 3  # Should be 3 or more
   ```

2. **If set to 1, increase it:**
   ```python
   MAX_INTERACTIONS = 5
   ```

3. **Did you say a stop word?** System stops on:
   - "stop"
   - "goodbye"
   - "quit"
   - "exit"

---

### System Won't Stop

**Symptom:**
- Can't exit with Ctrl+C
- "goodbye" doesn't work

**Fix:**

1. **Force exit with Ctrl+C** (may need multiple presses)
2. **If stuck, open Task Manager and kill Python:**
   ```powershell
   taskkill /IM python.exe /F
   ```

---

### Session Memory Not Working

**Symptom:**
- ARGO doesn't remember previous interactions
- Each answer is independent

**Fix:**

1. **Check session memory is initialized:**
   ```python
   # core/coordinator.py should have:
   self.memory = SessionMemory(max_turns=3)
   ```

2. **Verify conversation history is being used:**
   ```python
   # core/response_generator.py should include:
   history = self.memory.get_context()
   ```

---

## Advanced Troubleshooting

### Debug Output

Enable verbose logging:

```python
# Edit core/coordinator.py, add at top:
import logging
logging.basicConfig(level=logging.DEBUG)

# Now run:
python run_coordinator_v2.py
```

---

### Test Individual Components

**Test Recording:**
```powershell
python -c "
import sounddevice as sd
import numpy as np

audio = sd.rec(int(3 * 16000), samplerate=16000, channels=1)
sd.wait()
print(f'Recorded {len(audio)} samples')
"
```

**Test Transcription:**
```powershell
python -c "
import whisper
model = whisper.load_model('base')
result = model.transcribe('test.wav')  # You need a test.wav file
print(result['text'])
"
```

**Test LLM:**
```powershell
python -c "
import requests
response = requests.post('http://localhost:11434/api/generate', json={
    'model': 'argo:latest',
    'prompt': 'Hello',
    'stream': False
})
print(response.json()['response'])
"
```

**Test TTS:**
```powershell
python -c "
from core.output_sink import PiperOutputSink
import asyncio

async def test():
    tts = PiperOutputSink()
    await tts.speak('Hello world')

asyncio.run(test())
"
```

---

## Still Having Issues?

1. **Check console output** for error messages
2. **Review logs** in `logs/` directory (if available)
3. **Search** [ISSUES_RESOLVED.md](ISSUES_RESOLVED.md) for your issue
4. **Check** [RELEASE_NOTES_v1_0_0_COMPLETE.md](RELEASE_NOTES_v1_0_0_COMPLETE.md) for known issues
5. **File an issue** on GitHub with:
   - Your OS (Windows version)
   - Python version
   - Error message (full console output)
   - Steps to reproduce

---

**Last Updated:** January 20, 2026  
**Version:** v1.0.0-voice-complete
