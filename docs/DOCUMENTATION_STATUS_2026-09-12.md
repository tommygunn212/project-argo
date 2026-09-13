# Documentation status — v1.9.1

Updated: 2026-09-12

This repository contains long-lived design notes, milestone records, and current operating documentation. They serve different purposes and should not be read as one contemporaneous release claim.

## Current references

- Root `README.md`, `FEATURES.md`, `GETTING_STARTED.md`, `SYSTEM_OVERVIEW.md`, `CHANGELOG.md`, and `VERSION` describe the v1.9.1 checkpoint.
- `docs/VOICE_AUDIT_FIX_STATUS_2026-09-12.md` is the authoritative record for the current classic-voice repair scope, targeted verification, and remaining limits.
- `docs/ARGO_NEXT_UPGRADES.md` tracks first-pass implementations and deliberately deferred product work.
- `docs/TODO.md` is the active short backlog.
- `TEST_VERIFICATION_COMMANDS.md` supplies the v1.9.1 focused regression command. It does not claim a full-suite count.

## Historical records

Files whose names include `COMPLETE`, dated milestone reports, older release notes, archived material, and `TEST_DEBT.md` preserve evidence and rationale from their stated dates. Do not combine their historical test counts, latency figures, or completion labels with the v1.9.1 state.

## Verified checkpoint

On 2026-09-12, the focused regression command completed with 141 Python tests passing. `tests/test_cortana_avatar.cjs` completed with 4 passing JavaScript checks. The repaired classic TTS path was also exercised once against the selected output device, but that run did not record a microphone turn and does not establish end-to-end latency or audible onset.

## Open validation

Before calling voice work fully closed, perform and record a real microphone turn, physical-device interruption, output-underrun investigation, and separate latency measurements for endpointing, network/SDK, device write, and audible onset.

## Repair and code handoff boundary

ARGO recognizes plain-language self-repair requests, runs its supported health checks, and can perform only a displayed low-risk runtime repair after approval. It rechecks afterward. For a code-level issue, the System panel writes an auditable request under `runtime/code_requests/`; a separate approval is required before local Codex dispatch. The dispatcher uses Astra with high reasoning, works only in the ARGO workspace, and instructs Codex not to commit, push, delete unrelated files, or modify external systems. A completed agent process still needs review of its diff and reported tests; process-status polling and review UI remain planned.
