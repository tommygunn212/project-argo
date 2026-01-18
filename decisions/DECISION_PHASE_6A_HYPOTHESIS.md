Hypothesis: Ollama Request Startup Overhead

What might be causing the delay:
- HTTP client recreation on each request (connection overhead)
- No connection pooling/reuse
- Request serialization/deserialization per call

What will be changed:
- Add connection pooling to ollama HTTP calls
- Reuse session across multiple requests
- Single global session instance

What will NOT be touched:
- LatencyController API (no changes)
- Budget definitions or thresholds
- Regression guard or enforcer logic
- Any non-Ollama code paths
