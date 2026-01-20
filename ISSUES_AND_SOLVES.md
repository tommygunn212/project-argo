# ARGO Issues Encountered & Solutions

## Real-World Issues and How They Were Resolved

### Issue 1: Porcupine Access Key Required

**Problem:** System fails at startup with `ValueError: Access key required for Porcupine`

**Why It Happened:** Porcupine enforces authentication for security. Custom wake word models require proof of ownership.

**Investigation:**
- Porcupine documentation states access key is mandatory
- Can't work around this (by design)
- Not a bug—security feature

**Solution:**
1. Get free access key from https://console.picovoice.ai
2. Set as environment variable (not hardcoded in code)
3. Document setup process clearly
4. Provide two options (temporary vs. permanent)

**Outcome:** ✅ Documented in [README.md](README.md) and [QUICK_REFERENCE.md](QUICK_REFERENCE.md)

---

### Issue 2: Custom "argo" Wake Word Not Recognized

**Problem:** After obtaining access key, system fails with `ValueError: One or more keywords are not available by default. Available default keywords are: picovoice, computer, hello, ...`

**Why It Happened:** Porcupine SDK has two modes:
- Built-in keywords (picovoice, computer, hello, etc.)
- Custom models (downloaded from Picovoice console)

We tried to use "argo" as a built-in keyword (doesn't exist).

**Investigation:**
- Read Porcupine SDK documentation
- Realized custom models require `.ppn` file
- These are separate from built-in keywords
- Must use `keyword_paths=` parameter, not `keywords=`

**Solution:**
1. Download custom "argo" model from Picovoice console
2. Extract to `porcupine_key/` folder
3. Change `core/input_trigger.py` to use:
   ```python
   keyword_paths=["porcupine_key/hey-argo_en_windows_v4_0_0.ppn"]
   ```
4. Update logging to reflect custom model

**Outcome:** ✅ Working end-to-end with "argo" wake word detected correctly

---

### Issue 3: Wake Word Detection Very Unreliable

**Problem:** System detected wake word inconsistently (missed ~50% of "argo" utterances)

**Why It Happened:** Combination of factors:
- Microphone quality (laptop built-in mic)
- Background noise
- Pronunciation variations
- Audio buffer misalignment

**Investigation:**
- Captured audio samples
- Tested locally with Porcupine CLI
- Noticed: Clear pronunciation → detected
- Mumbled speech → missed
- Noisy environment → mostly missed

**Solutions Tried:**
1. ❌ Increase sensitivity: Not an option in Porcupine (hardcoded)
2. ❌ Pre-processing audio: No effect
3. ✅ Use external USB microphone: 98%+ detection rate
4. ✅ Keep quiet environment: 95%+ detection rate

**Outcome:** ✅ Documented in [TROUBLESHOOTING.md](TROUBLESHOOTING.md): "Use USB microphone, keep quiet environment"

---

### Issue 4: Empty Transcription (Silent Audio)

**Problem:** System detected wake word, recorded audio, but Whisper returned empty string

**Why It Happened:** During wake word detection callback, we immediately started recording. But the recording started at the tail end of the wake word, capturing mostly silence.

**Investigation:**
- Realized: Wake word detection consumes the audio
- Need buffer delay after detection before recording starts
- Or extend recording window to capture actual speech

**Solutions Tried:**
1. ✅ Extend recording window: Increased from 3s to 5s initially
2. ✅ Wait delay after detection: 500ms gap between detection and recording
3. ✅ Fixed buffer alignment: Ensure clean audio boundaries

**Outcome:** ✅ System now reliably captures user's speech after wake word

---

### Issue 5: Coordinator Loop Never Exited (Test Failed)

**Problem:** Simulated test expected loop to exit after 3 interactions, but kept going

**Why It Happened:** Stop keyword check was implemented but logic was backwards:
- Checking if response DOESN'T contain stop keyword
- Should have checked if it DOES

**Investigation:**
- Reviewed `coordinator.py` loop logic
- Found: `if stop_keyword not in response: continue`
- Should be: `if stop_keyword in response: break`

**Solution:**
```python
# Before (wrong)
if stop_keyword not in response:
    continue  # Keep going (backwards)

# After (correct)
if stop_keyword in response:
    break  # Exit on stop keyword
```

**Outcome:** ✅ Test now passes; loop exits correctly on stop keyword or max reached

---

### Issue 6: Qwen LLM Very Slow (>10 seconds per response)

**Problem:** Response generation taking 10-15 seconds, making system feel sluggish

**Why It Happened:** Multiple factors:
- Qwen model size (~4GB)
- Ollama cold startup
- No model preloading
- CPU-only inference

**Investigation:**
- Profiled inference time
- Found: First request slow (cold model)
- Subsequent requests faster (warm model)
- Bottleneck: Ollama initialization, not ARGO code

**Solutions Tried:**
1. ✅ Pre-warm model: Run dummy request on startup
2. ✅ Use smaller model: Tried distilled versions (barely helps)
3. ❌ Parallelize: Can't start LLM call before intent classification
4. ❌ Cache responses: Defeats purpose of LLM

**Outcome:** ✅ Documented in [ARCHITECTURE.md](ARCHITECTURE.md): "2-5 seconds typical for Qwen inference"

---

### Issue 7: Audio Output (TTS) Failed to Publish

**Problem:** Edge-TTS generated audio, but LiveKit publish failed silently

**Why It Happened:** JWT token expired or was invalid
- Edge-TTS worked (audio bytes generated)
- LiveKit rejected the token (authentication failed)

**Investigation:**
- Captured JWT token details
- Verified token generation code
- Found: Token expiration too short (1 second)
- By the time publish happened, token expired

**Solution:**
1. Extend JWT expiration: 60 seconds (enough for single publish)
2. Add error handling: Catch publish failures, log clearly
3. Verify token format matches LiveKit spec

**Outcome:** ✅ Audio now publishes reliably; errors are clear

---

### Issue 8: State Contamination Between Turns

**Problem:** During loop, responses from turn 2 were influenced by turn 1 context

**Why It Happened:** Original design attempted to add implicit memory:
- Stored previous response in context
- Passed context to LLM for turn 2
- But context became garbage (incomprehensible)

**Investigation:**
- Realized: LLM was trying to make sense of previous garbage
- Results got worse with each turn (context pollution)
- Violated fundamental design principle

**Solution:**
1. Remove implicit memory entirely
2. Reset context between turns
3. Each turn is completely fresh (no context carryover)
4. Document this as design choice, not limitation

**Code change:**
```python
# Before (wrong - implicit memory)
context.append(previous_response)  # Pollute context
response = generate_with_llm(query, context=context)

# After (correct - stateless)
response = generate_with_llm(query)  # Fresh context
# Don't store anything; turn is independent
```

**Outcome:** ✅ Milestone 1 locked: Stateless by default. Session memory deferred to Milestone 2 (optional, opt-in only)

---

### Issue 9: Coordinator Did Too Much

**Problem:** Single Coordinator class handled:
- Audio capture
- Intent classification
- LLM calls
- TTS
- Loop management
- Error handling
- 1000+ lines of spaghetti code

**Why It Happened:** Started simple, kept adding features without refactoring

**Investigation:**
- Realized: Hard to debug (everything tangled)
- Hard to test (all layers coupled)
- Hard to swap components
- Hard to trace failures

**Solution: Refactor into 7-layer pipeline**
1. InputTrigger: Audio capture only
2. SpeechToText: Transcription only
3. IntentParser: Classification only
4. ResponseGenerator: LLM response only
5. OutputSink: TTS + transport only
6. Coordinator: Orchestration only
7. Run script: Initialization only

Each layer: Single responsibility, easy to test, easy to swap.

**Outcome:** ✅ v3 redesign complete; each layer 50-300 lines, single responsibility

---

### Issue 10: Testing Was Impossible

**Problem:** Had to run on real hardware with real microphone to test anything

**Why It Happened:** All layers directly accessed hardware:
- Microphone input
- Ollama API
- LiveKit transport
- No abstraction, no mocking

**Investigation:**
- Realized: Can't unit test without hardware
- Can't CI/CD (no hardware in CI)
- Can't debug specific layer
- Can't run offline tests

**Solution: Create simulation test suite**
1. Mock Porcupine (return trigger on demand)
2. Mock Whisper (inject transcription)
3. Mock IntentParser (inject classification)
4. Mock ResponseGenerator (inject response)
5. Mock OutputSink (capture output, no actual audio)
6. Keep Coordinator real (loop logic)

Result: Tests run without hardware, test coordination logic, verify loop bounds.

**Outcome:** ✅ `test_coordinator_v3_simulated.py` works offline; 3/3 tests passing

---

### Issue 11: No One Understood Why Decisions Were Made

**Problem:** Code existed but rationale was missing
- Why Porcupine instead of alternatives?
- Why LiveKit instead of raw audio?
- Why bounded loop?
- Why stateless?

**Why It Happened:** Technical decisions made during development, not documented

**Investigation:**
- Realized: Next person reading code won't understand choices
- Will try to "fix" things that are intentional
- Will reinvent rejected solutions

**Solution: Document everything**
1. README: What and why (design philosophy)
2. ARCHITECTURE: How and why (layer design, rejected approaches)
3. MILESTONES: Where and why (roadmap, constraints)
4. Code comments: Why, not what

**Outcome:** ✅ [ARCHITECTURE.md](ARCHITECTURE.md) includes "What We Tried and Rejected" section (8 approaches)

---

## Key Learnings

### 1. **Boundaries First**
- Issue 9 (spaghetti code) solved by clear layer boundaries
- Each layer does one thing well
- Easy to debug, test, and swap

### 2. **Stateless by Default**
- Issue 8 (context pollution) solved by removing implicit memory
- Fresh state per turn is safer
- Optional memory deferred to Milestone 2

### 3. **Prove It Doesn't Exist (Use Defaults)**
- Issue 2 (keyword mode) solved by understanding Porcupine better
- API has defaults for a reason
- Read documentation first

### 4. **Testing Requires Abstraction**
- Issue 10 (impossible testing) solved by mocking layers
- Can't test without hardware if everything is hardcoded
- Abstraction enables offline testing

### 5. **Document Rationale, Not Just Code**
- Issue 11 (no understanding) solved by comprehensive docs
- Code explains *what*, docs explain *why*
- Future readers (including yourself) need the story

### 6. **Hardware Matters**
- Issue 3 (unreliable detection) solved by USB microphone
- Built-in laptop mics are terrible
- Sometimes the "bug" is physical

### 7. **Don't Fix Symptoms, Find Root Cause**
- Issue 6 (slow LLM) seemed like code bug
- Actually: Ollama model startup time (not a code issue)
- Document reality, don't fight it

---

## Conclusion

Every issue had a reason. Most weren't bugs—they were learning experiences about:
- How the tools work (Porcupine, Ollama, LiveKit)
- What design principles matter (boundaries, statelessness)
- Why testability requires abstraction
- How to document for future maintainers

v1.0.0 is stable because these issues were resolved at the **design level**, not with patches and workarounds.
