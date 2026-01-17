# FROZEN ARCHITECTURAL LAYERS

## Constitutional Decree

Effective immediately, the following layers are **OFFICIALLY FROZEN**:

- ✅ **v1.0.0** - TranscriptionArtifact (Whisper integration)
- ✅ **v1.1.0** - IntentArtifact (Grammar-based parsing)
- ✅ **v1.2.0** - ExecutionPlanArtifact (Planning & risk analysis)
- ✅ **v1.3.0-alpha** - Dry-Run Execution Engine (Symbolic validation)

## Immutability Contract

These layers will **NOT** receive:

```
❌ Refactors
❌ "Small improvements"
❌ Performance tuning
❌ Behavior changes
❌ Optimization passes
❌ Code cleanup
❌ API adjustments
```

## Why This Matters

These layers form the **safety constitution** of ARGO:

1. **TranscriptionArtifact** - Proves what the user said
2. **IntentArtifact** - Proves what the user intended
3. **ExecutionPlanArtifact** - Proves what will happen
4. **DryRunExecutionReport** - Proves it's safe before it happens

If v1.4.0 (Real Execution) needs something different, **v1.4.0 adapts**.

The safety chain does not bend.

## Alpha Labeling Clarification

**v1.3.0-alpha** is correctly labeled as **alpha**.

NOT because the code is unstable.

**Because the power is intentionally disabled.**

```
v1.3.0-alpha = Safety layer complete, execution disabled
            = Dry-run only, zero side effects, fully tested
            = Ready to validate, not ready to act
```

This is honest labeling: "Alpha" means "foundational capability, full power withheld."

## Versioning Rule

All future versions will:

- ✅ Build ON TOP of these frozen layers
- ✅ Use their APIs and guarantees
- ✅ NEVER modify their behavior
- ✅ NEVER change their interfaces

v1.4.0 will add **execution capability**, not replace validation capability.

## Test Guarantees

All frozen layers have:

- ✅ 100% test coverage on critical paths
- ✅ Explicit zero-side-effects tests
- ✅ Full chain traceability tests
- ✅ Safety analysis tests
- ✅ Integration tests

These tests **will not be modified**. If a test fails in v1.4.0+, the issue is in the new layer, not the test.

## Enforcement

This frozen status is enforced by:

1. **Code Review** - Any PR modifying these layers gets rejected
2. **Test Suite** - All tests for these layers must pass, always
3. **Documentation** - This file and the architecture constitution
4. **Git History** - Commits to frozen layers only add, never modify

## What This Enables

By freezing these layers, v1.4.0 can safely:

- Add real execution without risk to the safety chain
- Replace subsystems (Ollama → other LLM models)
- Add new capabilities (file I/O, network, OS integration)
- Scale to production use
- Adapt to new requirements

All while the safety chain remains absolutely trustworthy.

## The Constitution Stands

From [docs/architecture/artifact-chain.md](docs/architecture/artifact-chain.md):

> **Invariant 1**: No artifact without explicit confirmation
> **Invariant 2**: Artifacts never persist across restarts (logs permanent)
> **Invariant 3**: Linear information flow (no shortcuts, no backtracking)
> **Invariant 4**: Each artifact answers ONE question, then stops

These invariants are now **law**. Not suggestions. Not guidelines. Law.

---

**Frozen as of**: January 17, 2026 (commit f7f7b61)

**Frozen for**: All future development

**Frozen until**: The entire architecture is redesigned (v2.0+)

---

**Any change to a frozen layer requires a new major version and explicit constitutional amendment.**

