# Quick Start: Latency Baseline Measurement

## Current Status
✅ Latency framework integrated and tested  
✅ Ready to collect baseline measurements  
⏳ Next: Run 5 iterations × 4 scenarios × 3 profiles

---

## How to Run a Measurement

### 1. Start the App
```powershell
cd i:\argo\input_shell
python app.py
# App runs on http://localhost:8000
```

### 2. Open UI
```
http://localhost:8000
```

### 3. Run One Test Scenario

#### Text Question
1. Type in input field: "How do you make eggs?"
2. Click "Submit"
3. View result (Q&A, no actions)
4. Check logs for checkpoint timings

#### Text Command
1. Type: "Turn on kitchen lights"
2. Click "Submit"
3. Confirm intent
4. Confirm plan
5. Execute
6. Check logs

#### Voice PTT (Press-to-Talk)
1. Click mic button, speak, release
2. Confirm transcript
3. (Q&A or Command path continues)

#### Voice Q&A
1. Click mic button, ask question, release
2. View answer
3. Check logs

### 4. Extract Checkpoint Timings from Logs

Look for lines like:
```
[LATENCY] input_received: 0ms
[LATENCY] transcription_complete: 1250ms
[LATENCY] intent_classified: 1500ms
[LATENCY] model_selected: 1600ms
[LATENCY] ollama_request_start: 1610ms
[LATENCY] first_token_received: 2100ms
[LATENCY] stream_complete: 3200ms
[LATENCY] processing_complete: 3250ms
```

### 5. Calculate Deltas
```
transcription_complete - input_received = Whisper time
first_token_received - ollama_request_start = TTFT (Time-to-First-Token)
processing_complete - input_received = Total time
```

### 6. Record in Spreadsheet
Create a CSV with columns:
- Scenario (text_question, text_command, voice_ptt, voice_qa)
- Profile (FAST, ARGO, VOICE)
- Run (1-5)
- Input_to_Transcription
- Transcription_to_Intent
- Intent_to_Model
- Model_to_Ollama
- Ollama_to_FirstToken
- FirstToken_to_Complete
- Total_Time

---

## Changing Profiles

Edit `.env`:
```dotenv
ARGO_LATENCY_PROFILE=FAST   # Change to FAST, ARGO, or VOICE
```

Then restart the app.

---

## What to Look For

### Good Baseline Metrics
- Text question: ≤2s total (Q&A only, no execution)
- Text command: ≤10s total (ARGO profile)
- Voice PTT: ≤4s (Whisper + intent classification)
- Voice Q&A: ≤3s (Whisper + Q&A)

### Red Flags
- Any checkpoint gap > 500ms that isn't intentional
- First token taking > 3s (suggests model load issue)
- Total response time consistently > budget

### Next Steps After Measurement
1. Average the 5 runs for each scenario
2. Create summary table in latency_report.md
3. Identify slowest checkpoint delta
4. Optimize that specific path

---

## Troubleshooting

### No checkpoint logs showing up
1. Set `ARGO_LOG_LATENCY=true` in .env
2. Check that logging level is DEBUG or lower
3. Restart app

### App won't start
1. Check that latency_controller.py is in runtime/
2. Check that .env exists in workspace root
3. Run: `python -m pytest tests/test_latency.py` to verify integration

### Tests failing
Run: `python -m pytest tests/test_latency.py -v` to diagnose

---

## Data Collection Template

Create a file: `measurements.csv`

```csv
Scenario,Profile,Run,InputToTranscription,TranscriptionToIntent,IntentToModel,ModelToOllama,OllamaToFirstToken,FirstTokenToComplete,TotalTime
text_question,FAST,1,1200,50,10,5,800,1000,3065
text_question,FAST,2,1180,45,12,6,820,1050,3113
...
```

---

## Minimum Viable Baseline

To establish baselines, you need AT LEAST:
- 5 runs of each scenario = 20 data points
- Per profile (FAST, ARGO, VOICE) = 60 total
- Takes ~5-10 minutes to collect

Recommended:
- 10 runs × 4 scenarios × 3 profiles = 120 data points
- Takes ~15-20 minutes to collect
- Much more reliable averages

---

## Next: Automated Measurement Script

Once manual baseline is collected, we can create a Python script to:
1. Trigger endpoints via API
2. Parse logs automatically
3. Generate latency_report.md with measurements
4. Create charts

For now, manual collection gives us understanding of the system.

