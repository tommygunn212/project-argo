"""
INSTRUMENTATION GUIDE: Event Logging for Atomicity Verification

This document explains the comprehensive, millisecond-precision event logging
added to verify that the 7-step hardening creates an unbreakable barge-in flow.

All logs use the format: [HH:MM:SS.mmm] EVENT_NAME (key=value)

These logs are NON-NEGOTIABLE for proving correctness.
If logs are vague or missing, the test is invalid.

================================================================================
INSTRUMENTATION POINTS (EXACT LOCATIONS)
================================================================================

1. WAKE WORD DETECTED
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   Location: core/coordinator.py, on_trigger_detected() callback
   Log: [HH:MM:SS.mmm] WAKE_WORD detected (state=SPEAKING|LISTENING)
   
   Purpose:
     - Marks exact instant when wake word detected
     - Captures state machine state at wake time
     - Used to measure latency to AUDIO KILLED
   
   Example:
     [12:03:14.221] WAKE_WORD detected (state=SPEAKING)
   
   Proof: This timestamp is T0. All subsequent times in interrupt sequence
          are measured relative to T0.

2. INTERACTION ID INCREMENT
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   Location: core/coordinator.py, _next_interaction_id() method
   Log: [HH:MM:SS.mmm] INTERACTION_ID incremented (id=N)
   
   Purpose:
     - Proves monotonic ID increment
     - Mandatory for correlating all subsequent events to this wake word
     - Shows which interaction ID this wake word got
   
   Example:
     [12:03:14.230] INTERACTION_ID incremented (id=5)
   
   Proof: id=5 appears in all subsequent logs (TTS START, TTS STOP, etc.).
          Proves no ID reuse, no collision.

3. BARGE-IN ENTRY
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   Location: core/coordinator.py, _barge_in() method entry
   Log: [HH:MM:SS.mmm] BARGE_IN start
   
   Purpose:
     - Marks entry into atomic barge-in sequence
     - Signals that interrupt processing has begun
   
   Example:
     [12:03:14.229] BARGE_IN start
   
   Proof: Followed immediately by AUDIO KILLED (within < 10ms).
          Proves barge-in is atomic.

4. AUDIO HARD KILL
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   Location: core/coordinator.py, _barge_in() method, after audio_authority.hard_kill_output()
   Log: [HH:MM:SS.mmm] AUDIO KILLED
   
   Purpose:
     - Proves audio authority hard kill occurred
     - CRITICAL: Must appear before MIC OPEN in next recording
     - Proves speaker is invalidated, TTS cannot resume
   
   Example:
     [12:03:14.231] AUDIO KILLED
   
   Proof: If this log NEVER appears before MIC OPEN, system is broken.
          Latency from WAKE_WORD to AUDIO KILLED must be < 100ms.

5. STATE CHANGE
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   Location: core/coordinator.py, _on_state_change() callback
   Log: [HH:MM:SS.mmm] STATE_CHANGE old_state -> new_state
   
   Purpose:
     - Proves state transitions occur in strict order
     - Shows state machine consistency
     - Detects forbidden overlaps (e.g., LISTENING while SPEAKING)
   
   Examples:
     [12:03:14.232] STATE_CHANGE SPEAKING -> LISTENING (barge-in)
     [12:03:14.240] STATE_CHANGE LISTENING -> THINKING
     [12:03:14.250] STATE_CHANGE THINKING -> SPEAKING
   
   Proof: States must follow valid transitions:
          SLEEP → LISTENING → THINKING → SPEAKING → LISTENING
          No skips, no backwards, no overlaps.

6. TTS START
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   Location: core/output_sink.py, speak() method
   Log: [HH:MM:SS.mmm] TTS START (interaction_id=N)
   
   Purpose:
     - Marks when TTS begins for this interaction
     - Shows which interaction_id TTS is using
     - Enables detection of zombie callbacks (wrong interaction_id)
   
   Example:
     [12:03:14.500] TTS START (interaction_id=5)
   
   Proof: interaction_id=5 matches the ID from step 2.
          If TTS START appears with stale id=4 after id=5 was created,
          that's a zombie callback (must be blocked).

7. TTS STOP
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   Location: core/output_sink.py, stop_interrupt() method
   Log: [HH:MM:SS.mmm] TTS STOP (interaction_id=N)
   
   Purpose:
     - Marks when TTS is stopped on interrupt
     - Shows which interaction_id was stopped
     - Proves zombie callbacks are prevented (no TTS STOP after barge-in)
   
   Example:
     [12:03:14.350] TTS STOP (interaction_id=5)
   
   Proof: If TTS STOP appears AFTER AUDIO KILLED for a newer interaction,
          the old TTS is being killed (correct).
          If TTS STOP appears WITHOUT AUDIO KILLED before it, we have
          stale callbacks running (incorrect).

8. MIC OPEN
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   Location: core/coordinator.py, _record_with_silence_detection() after stream.start()
   Log: [HH:MM:SS.mmm] MIC OPEN
   
   Purpose:
     - Marks when microphone acquisition begins
     - Must NEVER appear before AUDIO KILLED in interrupt sequence
     - Proves no audio resource overlap
   
   Example:
     [12:03:14.340] MIC OPEN
   
   Proof: MIC OPEN timestamp (340ms) > AUDIO KILLED timestamp (231ms).
          If MIC OPEN < AUDIO KILLED, system is broken (speaker/mic overlap).

9. MIC CLOSE
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   Location: core/coordinator.py, _record_with_silence_detection() finally block
   Log: [HH:MM:SS.mmm] MIC CLOSE
   
   Purpose:
     - Marks when microphone is released
     - Completes the recording lifecycle
     - Shows clean acquisition/release pairs
   
   Example:
     [12:03:14.700] MIC CLOSE
   
   Proof: MIC OPEN ... MIC CLOSE form matched pairs.
          No MIC OPEN without MIC CLOSE (resource leak).

================================================================================
EXAMPLE LOG SEQUENCE: NORMAL INTERACTION
================================================================================

[12:03:14.000] STATE_CHANGE SLEEP -> LISTENING (wake)
[12:03:14.100] MIC OPEN
[12:03:14.300] INTERACTION_ID incremented (id=4)
[12:03:14.350] TTS START (interaction_id=4)
[12:03:14.900] MIC CLOSE
[12:03:15.000] TTS STOP (interaction_id=4)

Analysis:
  ✓ Wake word initiates LISTENING state
  ✓ Mic opens and closes cleanly (100-900ms)
  ✓ TTS starts and stops for interaction_id=4
  ✓ No overlaps (mic closed before TTS stop)
  ✓ All events use same interaction_id (no zombies)

================================================================================
EXAMPLE LOG SEQUENCE: INTERRUPT DURING TTS
================================================================================

[12:03:14.000] STATE_CHANGE SLEEP -> LISTENING (initial wake)
[12:03:14.100] MIC OPEN
[12:03:14.300] INTERACTION_ID incremented (id=4)
[12:03:14.350] TTS START (interaction_id=4)  ← Long response starting
[12:03:14.500] INTERACTION_ID incremented (id=5)  ← User says wake word
[12:03:14.501] WAKE_WORD detected (state=SPEAKING)  ← Mid-TTS
[12:03:14.502] BARGE_IN start
[12:03:14.503] AUDIO KILLED  ← TTS interrupted
[12:03:14.504] STATE_CHANGE SPEAKING -> LISTENING (barge-in)
[12:03:14.505] BARGE_IN complete
[12:03:14.600] TTS STOP (interaction_id=4)  ← Old TTS cleaned up
[12:03:14.700] MIC OPEN  ← New recording
[12:03:14.800] INTERACTION_ID incremented (id=5)  ← Not id=4
[12:03:14.850] TTS START (interaction_id=5)  ← New response
[12:03:15.000] MIC CLOSE
[12:03:15.100] TTS STOP (interaction_id=5)

Analysis:
  ✓ Interrupt latency: 501ms - 502ms = 1ms (well under 100ms)
  ✓ AUDIO KILLED (503ms) before new MIC OPEN (700ms)
  ✓ Old TTS STOP (interaction_id=4) blocked if after AUDIO KILLED (it is: 600 > 503)
  ✓ New interaction_id=5 used for new response (no reuse of id=4)
  ✓ State machine never overlaps (LISTENING before new THINKING)
  ✓ No zombie callbacks (old id=4 cannot speak after id=5 active)

================================================================================
TIMING ANALYSIS: HOW TO VERIFY ATOMICITY
================================================================================

Given raw logs from a run, you can verify:

1. INTERRUPT LATENCY < 100ms
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   Calculation: AUDIO_KILLED_time - WAKE_WORD_time
   
   Example:
     WAKE_WORD at [12:03:14.501]
     AUDIO KILLED at [12:03:14.503]
     Latency = 503 - 501 = 2ms ✓ (well under 100ms guarantee)
   
   Requirement: MUST be < 100ms

2. STRICT ORDERING (NO CAUSALITY VIOLATIONS)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   Rule: No event timestamp can violate logical ordering.
   
   Examples of violations:
     - STATE_CHANGE appears with timestamp before BARGE_IN start
     - TTS STOP appears before TTS START for same interaction_id
     - MIC OPEN appears before AUDIO KILLED
   
   Verification: Sort all logs by timestamp, check ordering matches causality

3. NO OVERLAP (NO SIMULTANEOUS STATES)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   Rule: Only one state active at a time; state transitions must be instant.
   
   State timeline:
     [time1] STATE_CHANGE ... -> LISTENING
     [time2 to timeN] (LISTENING active)
     [timeN+1] STATE_CHANGE LISTENING -> THINKING
   
   Violations:
     - Two STATE_CHANGE logs for the same state (e.g., both -> LISTENING)
     - STATE_CHANGE with same old/new state (state unchanged)
     - TIME GAP between state change and next event > 100ms (state held)

4. NO ZOMBIES (NO STALE INTERACTION IDS)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   Rule: After AUDIO KILLED (id=N), no TTS START with id < N.
   
   Example:
     [12:03:14.500] INTERACTION_ID incremented (id=5)
     [12:03:14.501] WAKE_WORD detected
     [12:03:14.502] AUDIO KILLED
     [12:03:14.600] TTS START (interaction_id=4)  ← VIOLATION!
   
   This means old TTS (id=4) is trying to start after newer id=5.
   Must be blocked. If this log appears, system is broken.
   
   Correct sequence:
     [12:03:14.500] INTERACTION_ID incremented (id=5)
     [12:03:14.502] AUDIO KILLED
     [12:03:14.600] TTS STOP (interaction_id=4)  ← Old stop
     [12:03:14.700] TTS START (interaction_id=5)  ← New start
   
   Verification: For each AUDIO KILLED, check no TTS START with lower id follows

5. RESOURCE OWNERSHIP (MIC/SPEAKER ISOLATION)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   Rule: MIC OPEN/CLOSE must not overlap with TTS START/STOP.
   
   Valid timeline:
     [t1] TTS START
     [t2] TTS STOP
     [t3] MIC OPEN
     [t4] MIC CLOSE
   
   Invalid (overlap):
     [t1] TTS START
     [t2] MIC OPEN  ← MIC opens while TTS playing!
   
   Verification: Check all TTS intervals [START, STOP] do not overlap
                 with any MIC intervals [OPEN, CLOSE]

================================================================================
LOGGING PROTOCOL (NON-NEGOTIABLE)
================================================================================

All instrumentation must:

1. Use EXACT Format
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   ✓ [HH:MM:SS.mmm] EVENT_NAME (key=value)
   
   ✗ [HH:MM:SS.ff] EVENT_NAME  (wrong format)
   ✗ 12:03:14.221 WAKE_WORD  (missing brackets)
   ✗ WAKE_WORD at 12:03:14  (no milliseconds)

2. Use Millisecond Precision
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   ✓ [12:03:14.221]  (milliseconds shown)
   ✓ [12:03:14.005]  (shows sub-second timing)
   
   ✗ [12:03:14]  (no milliseconds, too coarse)
   ✗ [12:03:14.2215]  (microseconds, too verbose)

3. Every Event Required
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   Do not skip events because they "don't matter" or are "too fast".
   All 9 event types MUST appear in logs.

4. No Debug Output
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   ✓ [12:03:14.221] AUDIO KILLED
   
   ✗ [12:03:14.221] AUDIO KILLED (took 5ms, piper_process.kill() returned None)
   
   Timestamps alone are sufficient. Extra details clutter analysis.

5. Log Must Be Permanent
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   Logs must go to persistent storage (file or logger).
   
   ✓ logger.info(f"[{ts}] {message}")  (goes to logs)
   ✓ print(f"[{ts}] {message}")  (goes to stdout/stderr)
   
   ✗ Local variable timestamps (lost when function returns)
   ✗ Memory-only buffers (lost on crash)

================================================================================
CONCLUSION
================================================================================

These 9 instrumentation points create an unbreakable audit trail of the
barge-in interrupt flow. Using timestamps alone, we can definitively prove:

  ✓ Interrupt is atomic (WAKE_WORD → AUDIO KILLED < 100ms)
  ✓ Ordering is strict (no causality violations)
  ✓ States never overlap (half-duplex enforced)
  ✓ Zombie callbacks are blocked (interaction_id validation)
  ✓ Resources are exclusive (audio_authority hard kill)

If any log is missing, vague, or out of order, the test is invalid.

These logs are NON-NEGOTIABLE.
"""

__version__ = "1.0-instrumentation"
__date__ = "2025-01-25"
