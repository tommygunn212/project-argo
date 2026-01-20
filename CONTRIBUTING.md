# Contributing to ARGO

**ARGO v1.0.0 is complete and stable.** This document outlines how to contribute responsibly while maintaining the system's integrity.

## Current Status

ARGO v1.0.0 is **production-ready, feature-locked**:
- ✅ All 7 layers working
- ✅ Bounded loop (max 3 interactions)
- ✅ Fully tested (3/3 integration tests passing)
- ✅ Fully documented

**NO new features until Milestone 2 is authorized.**

---

## What You Can Contribute

### ✅ Bug Fixes

Only for genuine bugs (not design changes):
- Feature: X doesn't work
- Expected: Y
- Actual: Z
- Root cause: [analysis]

**Process:**
1. Open issue with clear description
2. Propose minimal fix
3. Verify all 3 tests still pass
4. Submit PR with clear message

### ✅ Documentation Improvements

- Clarifications to existing docs
- Typo fixes
- Adding examples
- Expanding troubleshooting

**Process:**
1. Fork repository
2. Edit `.md` files
3. Submit PR

### ✅ Test Improvements

- Additional tests for existing layers
- Edge case testing
- Performance benchmarks

**Constraint:** Tests must use same patterns as `test_coordinator_v3_simulated.py` (simulated, no real hardware required)

### ✅ Optimization (Data-Driven Only)

- Only if you have measurements proving improvement
- Must be >= 5% improvement to be merged
- Must not break existing behavior
- Must not add new dependencies

See [ARCHITECTURE.md](ARCHITECTURE.md) for latency benchmarking approach.

---

## What You Cannot Contribute (v1.0.0)

### ❌ New Features

Session memory, multi-device, personality, tool calling — these are planned for future milestones, not v1.0.0.

### ❌ Architecture Changes

The 7-layer design is locked. No:
- Adding/removing layers
- Changing layer responsibilities
- Implicit dependencies
- Hidden state

### ❌ Code Refactoring "While We're Here"

ARGO is stable. No cosmetic refactoring unless:
- Fixes a specific bug, AND
- All tests still pass

### ❌ New Dependencies

External libraries require justification:
- Why not built-in?
- Why not existing dependency?
- Production-proven?
- Security implications?

### ❌ Configuration Proliferation

.env is intentionally minimal. New settings only if essential.

### ❌ Polishing

Font sizes, color schemes, UI improvements — out of scope for v1.0.0. System is functional, not beautiful.

---

## How to Contribute

### 1. Fork & Clone

```powershell
git clone https://github.com/yourusername/argo.git
cd argo
```

### 2. Create Feature Branch

```powershell
git checkout -b bugfix/issue-description
# or
git checkout -b docs/improvement-description
```

### 3. Make Changes

Follow existing patterns:
- **Code:** Match style in `core/coordinator.py`
- **Docs:** Match style in [README.md](README.md)
- **Tests:** Match style in `test_coordinator_v3_simulated.py`

### 4. Verify Tests Pass

```powershell
python test_coordinator_v3_simulated.py
# Expected: 3/3 PASSED
```

### 5. Verify No Secrets

```powershell
# Check for hardcoded keys
git diff --cached | grep -i "key\|token\|secret"
```

### 6. Commit

```powershell
git commit -m "type: brief description

Detailed explanation of change and why.
Reference any issues or discussions.

No breaking changes.
All tests passing.
"
```

### 7. Submit PR

Include:
- What changed
- Why it changed
- Tests run
- No new dependencies
- No secrets committed

---

## Code Style

### Python

- **Formatting:** 2-space indentation, Python 3.10+
- **Comments:** Explain *why*, not *what*
- **Functions:** Single responsibility (< 50 lines typical)
- **Error handling:** Explicit, never silent
- **Logging:** Use existing logger pattern

Example:
```python
class InputTrigger:
    """Wake word detection (Porcupine)."""
    
    def on_trigger(self, callback):
        """
        Activate wake word detection.
        
        Args:
            callback: Function to invoke on detection
        """
        self.logger.info("[on_trigger] Initializing Porcupine...")
        # Implementation
```

### Documentation

- **Markdown:** GitHub-flavored Markdown
- **Headings:** Clear hierarchy (#, ##, ###)
- **Code blocks:** Specify language (```python, ```powershell)
- **Links:** Relative paths ([README.md](README.md))
- **Tone:** Professional, fact-based, no marketing

### Git Commits

- **Message format:** `type: description`
- **Types:** `fix:`, `docs:`, `test:`, `refactor:` (rare)
- **Body:** Explain *why* in 1-2 sentences
- **No large commits:** Break into logical units

---

## Testing Requirements

### Before Submitting PR

```powershell
# Run integration tests
python test_coordinator_v3_simulated.py

# Verify with real hardware (if applicable)
python run_coordinator_v3.py
```

### Expected Results

```
test_loop_max_interactions PASSED
test_stop_keyword_exits_early PASSED
test_independent_turns PASSED

All tests: 3/3 PASSED
```

### If You Break Tests

Don't submit PR. Fix the issue:
1. Revert change
2. Identify root cause
3. Make minimal fix
4. Verify tests pass
5. Re-attempt PR

---

## Review Process

Your PR will be reviewed for:

✅ **Correctness:** Does it actually fix/improve the issue?  
✅ **Alignment:** Does it fit ARGO's philosophy (boundaries, dumb before smart)?  
✅ **Tests:** Do all tests pass?  
✅ **Documentation:** Is the change documented?  
✅ **No Regressions:** Does it break existing behavior?  
✅ **No Secrets:** Are there hardcoded keys or passwords?  

---

## Roadmap & Future Contributions

**Milestone 2: Session Memory** (planned, not started)
- Optional per-session context
- Explicit opt-in only
- No cross-session memory

**Milestone 3: Multi-Device** (planned)
- Multiple Coordinators
- Device coordination
- Fault tolerance

**Milestone 4: Personality Layer** (optional, last)
- Custom voice personas
- Tone customization

When these milestones are authorized, contributions will be invited. Until then, they're out of scope.

---

## Questions?

Before asking, check:
1. [README.md](README.md) — System overview
2. [ARCHITECTURE.md](ARCHITECTURE.md) — Design philosophy
3. [FAQ.md](FAQ.md) — Common questions
4. [TROUBLESHOOTING.md](TROUBLESHOOTING.md) — Common issues

---

## Code of Conduct

- **Respectful:** Treat all contributors with respect
- **Constructive:** Feedback is about the code, not the person
- **Collaborative:** We're building something together
- **Patient:** ARGO is intentionally conservative. Feature requests may be declined.

---

## License

By contributing, you agree that your contributions will be licensed under the same license as ARGO (see [LICENSE](LICENSE)).

---

## Thank You

Contributing to ARGO means helping maintain a predictable, debuggable, trustworthy voice system. This discipline is what makes v1.0.0 production-ready.

We appreciate your help in keeping ARGO stable and excellent.
