# Test Debt Tracker

This document tracks known test failures that are non-blocking for release.

**Last updated:** v1.6.1 (2026-02-02)

---

## Summary

| Metric | Count |
|--------|-------|
| Tests Passing | 451 |
| Tests Failing | 12 |
| Tests Skipped | 5 |

---

## Known Failures by Category

### 1. test_stt_hardening.py (Category: Outdated Signature)

**Issue:** Function signature changed, test not updated.

**Files:**
- `tests/test_stt_hardening.py`

**Status:** Needs test update to match current API.

---

### 2. test_clarification_gate.py (Category: Assertion Mismatch)

**Issue:** Expected vs actual clarification response text differs.

**Files:**
- `tests/test_clarification_gate.py`

**Status:** Assertions need to be updated to match current clarification prompt format.

---

### 3. test_confirmable_identity_memory.py (Category: Harness Issues)

**Issue:** Test harness setup/teardown issues causing intermittent failures.

**Files:**
- `tests/test_confirmable_identity_memory.py`

**Status:** Harness needs refactoring for reliability.

---

### 4. test_piper_integration.py (Category: Environment Configuration)

**Issue:** Piper executable path not configured in test environment.

**Files:**
- `tests/test_piper_integration.py`

**Status:** Needs CI/test environment setup or skip decoration.

---

### 5. test_coordinator_v1.py / test_coordinator_v2.py (Category: Integration Test Issues)

**Issue:** Legacy coordinator tests not aligned with v3 architecture.

**Files:**
- `tests/test_coordinator_v1.py`
- `tests/test_coordinator_v2.py`

**Status:** Consider deprecation or update to v3 patterns.

---

## GitHub Issues (To Be Created)

When migrating to GitHub issue tracking, create issues for each category:

1. **[Test Debt] Update test_stt_hardening.py signature**
2. **[Test Debt] Fix test_clarification_gate.py assertions**
3. **[Test Debt] Refactor test_confirmable_identity_memory.py harness**
4. **[Test Debt] Configure Piper in test environment**
5. **[Test Debt] Deprecate or update legacy coordinator tests**

---

## Resolution Priority

| Priority | Category | Effort |
|----------|----------|--------|
| P2 | Outdated Signature | Low |
| P2 | Assertion Mismatch | Low |
| P3 | Harness Issues | Medium |
| P3 | Environment Config | Medium |
| P4 | Legacy Tests | High |

---

## Notes

- These failures are **pre-existing** and do not block v1.6.1 release.
- All 451 passing tests confirm core functionality works correctly.
- Skipped tests are intentional (e.g., hardware-dependent tests in CI).
