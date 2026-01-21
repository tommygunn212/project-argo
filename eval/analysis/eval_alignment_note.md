**Eval Alignment Note: Command-Inconsistent Metric Clarification**

Context
- During stabilization, `command_inconsistent` measured both harmful misfires and correct aborts (user-canceled/clarified flows). This conflation hides important distinctions.

Recommendation (no schema changes now)
- Split the metric into two tracked counts (record both in analysis pipelines):
  1) `command_aborted_correctly` — cases where an uncommitted command was canceled or user explicitly aborted and the system responded with a concise abort confirmation (e.g., "Okay, canceled."). This is a desired behavior.
  2) `command_misfire` — cases where a command executed or attempted execution despite ambiguity or interruption (undesired).

Why this split helps
- Detectability: distinguishes safe aborts from real failures.
- Sensitivity: avoids penalizing conservative behavior (aborts) while highlighting mis-executions for remediation.
- Analysis clarity: enables separate baselines and targets for safety (reduce misfires) and responsiveness (monitor abort rate).

Implementation notes (operational)
- Tag events during evaluation runs with an `action` field: e.g., `aborted`, `clarified`, `executed` (no schema change required in eval files now — this is a forward recommendation).
- For current reports, infer counts heuristically from `response` text: look for concise abort confirmations vs. execution acknowledgements.

Suggested short-term thresholds
- Aim for `command_misfire` ≈ 0
- Allow nonzero `command_aborted_correctly` (expected during clarification flows)

Next steps (proposal only)
- Adopt the two-count view in post-run analyses and dashboards.
- Use the split to prioritize fixes: reduce `command_misfire` first; then tune user experience around abort rates.

Status: Note recorded. No code or schema changes made.