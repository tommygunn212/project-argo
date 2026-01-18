# Decision: Phase 6B-1 Measurement Boundary

## Measured Boundary

**Start:** ARGO hands control to Ollama
- Exact point: `requests.post(OLLAMA_URL, json=payload, timeout=60)` call in hal_chat.py
- This is the moment ARGO serializes the message and dispatches over HTTP

**End:** Ollama returns first token
- Exact point: Response JSON received and parsed
- Extracted via: `response.json()["message"]["content"]`
- This is the moment ARGO receives the first bytes of HAL's response

## Opaque Section

Everything between request dispatch and first token response is **internal to Ollama**.

Current black box:
- Model loading/warm state (if needed)
- Tokenizer initialization
- Prompt ingestion and processing
- Inference prefill phase
- First token generation
- Response serialization and transmission

This phase currently reports as single metric: `ollama_request_start` (~300ms = 49.8% of first-token latency)

## Sub-Phase Hypothesis (For Instrumentation Only)

No optimization targets yet. Probes will identify:

1. **Request → Acknowledgment** — Network latency + Ollama process scheduling
2. **Acknowledgment → Model Ready** — Model load time (if cold) or warm-up overhead
3. **Model Ready → Inference Start** — Tokenizer + prompt preparation
4. **Inference Start → First Token** — Actual inference compute
5. **Token → Response Sent** — Serialization + transmission back to ARGO

## Instrumentation Strategy

Non-invasive timing gates:
- Guard behind `OLLAMA_PROFILING` environment variable
- Probe inside hal_chat.py around the `requests.post()` call
- Capture timestamps at: dispatch, response received, content extracted
- Optional: Parse Ollama response timing metadata (if exposed)

## What Will NOT Change

- No behavior modifications
- No retries or caching
- No sleep statements
- No new dependencies
- No changes to latency_controller or budget_enforcer
- No changes to ARGO message flow

## Deliverable

docs/ollama_latency_breakdown.md

One table only:
- Sub-phase
- Avg (ms)
- P95 (ms)
- Notes (factual only)

Goal: Turn "Ollama is slow" into "Sub-phase X is slow, here's the data."
