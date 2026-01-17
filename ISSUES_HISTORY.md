# ARGO GitHub Issues — Development History

This document contains all major issues encountered during ARGO development, how they were solved, and templates for future issues.

---

## CLOSED ISSUES

### 1. Voice System Not Following Example-Based Guidance

**Status:** CLOSED (Solved)

**Problem:**
Model was generating verbose, essay-like responses despite example-based SYSTEM prompt. Argo was improvising beyond the provided examples, ignoring guidance on warm/confident tone.

**What We Tried:**
1. Hardened SYSTEM prompt with absolute rules and constraints
2. Added aggressive trimming validator to enforce style
3. Increased prompt specificity about tone

**Result:**
User feedback: "I don't mind long explanations on local system (no token costs). Relax the constraints."

**Solution:**
Reverted to guidance-based prompt instead of hard rules. Simplified validator to pass-through safety net ("traction control" — only tightens if model drifts). Restored three vivid examples (cats, fridge, coffee) that work better than abstract constraints.

**Outcome:**
Model now generates appropriate responses within example boundaries. Voice compliance is guidance-based, not authoritarian.

---

### 2. Recall Mode Returning Narratives Instead of Deterministic Lists

**Status:** CLOSED (Solved)

**Problem:**
When users asked recall queries ("What did we discuss?"), ARGO was answering with narrative explanations instead of formatted lists. This violated recall mode's deterministic contract.

**What We Tried:**
1. Generic pattern matching for recall detection
2. Reusing generation pipeline for recall responses

**Solution:**
Implemented three-part recall system:
1. Strict meta-query pattern detection (15+ trigger phrases)
2. Count extraction ("last 3 things" → count=3)
3. Deterministic list formatting with early return before model inference
4. No model re-inference for recall mode

**Outcome:**
Recall queries now return deterministic, formatted lists. Model is never invoked for recall — prevents hallucination and ensures consistency.

---

### 3. Recall Queries Being Stored in Memory

**Status:** CLOSED (Solved)

**Problem:**
Memory was storing recall queries along with regular interactions, polluting the memory system with meta-conversation instead of substantive context.

**Solution:**
Added memory hygiene rule: Recall queries never reach `store_interaction()`. Early return in recall mode prevents storage entirely.

**Outcome:**
Memory stays clean. Recall conversations don't clutter context retrieval.

---

### 4. Module Organization Chaos

**Status:** CLOSED (Solved)

**Problem:**
Modules scattered at repo root with inconsistent naming:
- `argo_memory.py`
- `argo_prefs.py`
- `conversation_browser.py`

Made structure unclear and maintenance difficult.

**Solution:**
Reorganized into `wrapper/` directory with standard names:
- `wrapper/memory.py`
- `wrapper/prefs.py`
- `wrapper/browsing.py`
- `wrapper/argo.py` (main)

**Outcome:**
Clean package structure. New contributors immediately understand layout.

---

### 5. Broken Import Paths After Module Reorganization

**Status:** CLOSED (Solved)

**Problem:**
After moving modules, old import statements broke throughout codebase.

**Solution:**
Updated all imports in `argo.py`:
- Old: `from argo_memory import ...`
- New: `from memory import ...`

**Outcome:**
System imports successfully from any location. Relative paths work correctly.

---

### 6. Documentation Gap for New Users

**Status:** CLOSED (Solved)

**Problem:**
No clear setup instructions. No architecture overview. Repository unclear to someone who didn't build it.

**Solution:**
Created:
1. `README.md` — Sharp, authority-focused intro
2. `ARCHITECTURE.md` — Technical system design
3. `CHANGELOG.md` — Release history
4. `docs/README.md` — Documentation index
5. `docs/specs/master-feature-list.md` — 200-item scope doc
6. `docs/architecture/raspberry-pi-node.md` — Peripheral design
7. `docs/usage/cli.md` — Command reference

**Outcome:**
New users can understand system from README and navigate to detailed docs without questions.

---

### 7. Requirements.txt Not Tracked in Git

**Status:** CLOSED (Solved)

**Problem:**
`requirements.txt` was in `.gitignore`, making dependency versions untraceable.

**Solution:**
Removed from `.gitignore`. Added to git tracking.

**Outcome:**
Dependencies explicit and version-controlled. Setup reproducible.

---

### 8. License Messaging Was Legally Unclear

**Status:** CLOSED (Solved)

**Problem:**
README claimed "MIT License (Non-Commercial)" which is:
1. Not valid MIT
2. Legally contradictory
3. Confusing to potential users

**Solution:**
Created proper `ARGO Non-Commercial License v1.0`:
- Clear non-commercial permissions
- Explicit commercial licensing requirement
- Plain language, no legal cosplay
- Updated README with dual-licensing explanation
- Added LICENSE file with full terms

**Outcome:**
No ambiguity. Open-source users welcome. Companies know exactly when to contact for licensing.

---

### 9. README Had Duplicated Sections

**Status:** CLOSED (Solved)

**Problem:**
README had two separate "Licensing" sections with different language.
CLI examples (Conversation browsing, Exiting) embedded in README instead of docs.
Mixed architecture explanations scattered through document.

**Solution:**
1. Removed duplicate Licensing sections — kept one, legally accurate version
2. Moved CLI examples to `docs/usage/cli.md`
3. Consolidated Architecture section
4. Single pointer to usage docs instead of inline help

**Outcome:**
README no longer reads like it accreted over time. Clean, focused document.

---

### 10. README Was Apologetic and Polite

**Status:** CLOSED (Solved)

**Problem:**
Language was too soft:
- "designed to"
- "can assist with"
- "is a tool that"
- "represents the foundation"

Tone was asking permission to exist instead of asserting authority.

**Solution:**
Sharpened to declarative language:
- "does not guess intent"
- "does not execute silently"
- Removed repetition
- Changed explanations to statements of fact
- Condensed capabilities to bullet list

**Outcome:**
README reads like software with opinions, not a demo trying to be liked. Companies take it seriously.

---

## OPEN ISSUE TEMPLATE

Use this template for new issues:

```markdown
### [Issue Title]

**Status:** OPEN

**Problem:**
[What's not working or what needs to be addressed?]

**What We've Tried:**
1. [Attempt 1]
2. [Attempt 2]
3. [Attempt 3]

**Current Understanding:**
[What do we know about the root cause?]

**Proposed Solution:**
[What do we think will work?]

**Success Criteria:**
- [ ] Criterion 1
- [ ] Criterion 2
- [ ] Criterion 3
```

---

## CLOSED ISSUE TEMPLATE

When closing an issue:

```markdown
### [Issue Title]

**Status:** CLOSED (Solved)

**Problem:**
[Original problem statement]

**What We Tried:**
1. [Attempt 1]
2. [Attempt 2]

**Solution:**
[What actually worked]

**Outcome:**
[What changed as a result]

**Commit(s):**
[Link to relevant commits]
```

---

## Future Issues

When creating new issues, ask:

1. **Is this a design decision or a problem?** (Design decisions become closed issues with context)
2. **Is this well-scoped?** (Vague issues get closed immediately)
3. **Is this intentional or accidental?** (Accidental problems get fixed quietly; intentional limits get documented)

Keep public issues focused on:
- Architecture decisions
- Design constraints
- Solved problems with clear reasoning
- Known limitations by design
