# Contributing to ARGO

ARGO is an actively developed local voice assistant. Read [AGENTS.md](AGENTS.md)
before changing code; it documents the current architecture, the two voice
paths, safety invariants, and the verification required for runtime work.

## Development setup

- Windows repository: `I:\argo`
- Python environment: `I:\argo\.venv`
- Dashboard: `http://localhost:8000/v2`
- Smooth Voice worker: `livekit_realtime_agent.py`
- Classic fallback: `core/pipeline.py`

Keep `.env` and `config.json` local. Never commit, print, or copy their values
into reports or generated context bundles.

## Change discipline

1. Check whether the capability already exists. Search `core/voice/`,
   `core/realtime_tools/`, and the test suite before adding another path.
2. Preserve public facades while extracting internals. Prefer small services
   with explicit Protocols or dependency objects over broad untyped hosts.
3. Add characterization and negative-control tests before changing weakly
   covered behavior.
4. Keep structural moves separate from behavior changes.
5. Read changed files back from disk, import affected modules, and run focused
   tests before committing.
6. Commit each cohesive change atomically.

Do not weaken the invariants in `AGENTS.md`. In particular:

- BVC noise cancellation remains off for the self-hosted LiveKit server.
- Smooth Voice and Classic Voice must not own the microphone simultaneously.
- Parentless Python processes are never killed without ARGO-specific evidence.
- Only explicitly confirmed memory may enter system instructions.
- Remembered text remains untrusted and is sanitized on read.
- File removal continues to use quarantine rather than permanent deletion.

## Verification

Run focused tests for the changed component first. At a major boundary run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q --tb=line
node --test tests\test_avatar_motion.cjs
.\.venv\Scripts\python.exe -m pip check
```

`py_compile` is only a syntax check. Import changed modules as part of the
verification. For voice-runtime completion, restart the complete stack with
`RESTART_ARGO.bat`, confirm a new worker registration, require a real
`session_start` event, and run `tools\prove_voice.py`.

## Pull requests and reviews

Describe:

- the behavior or maintainability problem;
- the exact files and boundaries changed;
- tests and runtime evidence collected;
- known limitations or validation that still requires physical hardware.

Do not claim live audio, microphone, avatar, or external-service success from
unit tests alone. Preserve unrelated working-tree changes and never include
Tommy's local experiments unless they are explicitly in scope.
