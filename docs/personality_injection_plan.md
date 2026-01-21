**Personality Injection Plan (Design Only)**

Where personality should live
- Post-generation shaping layer: a small, deterministic transformer between `LLMResponseGenerator.generate()` output and the final output sink. This layer receives the raw response string and optional metadata (intent type, adaptation mode) and applies lightweight, rule-driven adjustments.

Goals and scope
- Purpose: add subtle human feel without altering facts or control flow.
- Scale: mild humor, occasional dry wit, confident phrasing, and small conversational connectors.
- Safety: never override factual content, never change command semantics, never inject follow-ups that alter execution.

Allowed behaviors (examples)
- Mild rephrasing: "That's correct." → "Yep, that's right."
- Short humorous taglines after safe, non-sensitive answers (rare): "Like a pro."
- Confident closers: append a concise one-line summary where appropriate.

Forbidden behaviors (hard constraints)
- Do NOT modify factual assertions or numerical answers.
- Do NOT change or delay command execution or commit semantics.
- Do NOT trigger on every response; must be conditional and sparse.
- Do NOT introduce new intents, memory, or external calls.

Control & determinism
- Feature gated via configuration flag and per-session enablement.
- Deterministic rule order: personality rules apply in a fixed sequence to ensure reproducibility.
- Rate-limiting: apply personality at most once every N responses (configurable) to avoid overuse.

Safety & testing
- Unit tests for: non-interference with commands, no factual edits, rate limit enforcement.
- Run behind an approval gate: plan only; implement after explicit human sign-off.

Implementation notes (high-level, no code)
- Keep as a pure text transform function: input (response, intent, meta) → output (response').
- Avoid ML or heuristics that require tuning pre-launch. Use deterministic templates and small rules.

Review checklist before implementation
- Confirm list of phrase patterns allowed for humor.
- Confirm gating and config defaults (off in baseline).
- Approve tests ensuring no factual mutation.

Status: Design ready. No code changes performed.