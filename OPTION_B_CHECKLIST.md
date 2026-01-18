# Option B: Confidence Burn-In Checklist

**Start Date**: ________________  
**End Date**: ________________  
**Total Hours**: ________________  

---

## Pre-Flight Checks

- [ ] All Phase 7B code committed and pushed
- [ ] `option_b_logger.py` created and functional
- [ ] ARGO system running without errors
- [ ] Microphone working
- [ ] Audio output working
- [ ] Terminal logging visible

---

## Tier 1: Basic Q&A (5 minimum)

**Expected**: All 5 conversations execute perfectly  
**Success bar**: 5/5 clean responses

| # | Question | Wake OK | Answer Once | Stop Clean | Silent After | Idle State | Status | Notes |
|---|----------|---------|------------|-----------|--------------|-----------|--------|-------|
| 1 | "ARGO, how do I make eggs?" | ☐ | ☐ | ☐ | ☐ | ☐ | | |
| 2 | "ARGO, what time is it?" | ☐ | ☐ | ☐ | ☐ | ☐ | | |
| 3 | "ARGO, explain SSH." | ☐ | ☐ | ☐ | ☐ | ☐ | | |
| 4 | "ARGO, what's the capital of France?" | ☐ | ☐ | ☐ | ☐ | ☐ | | |
| 5 | "ARGO, who invented the internet?" | ☐ | ☐ | ☐ | ☐ | ☐ | | |

**Tier 1 Result**: ___/5 PASSED

---

## Tier 2: Interruption Test (3 minimum)

**Expected**: All 3 interruptions halt audio immediately  
**Success bar**: 3/3 <100ms stop latency

| # | Scenario | Audio Halts <50ms | No Tail Audio | State OK | New Q Handled | Status | Notes |
|---|----------|------------------|---------------|----------|---------------|--------|-------|
| 1 | Mid-response STOP | ☐ | ☐ | ☐ | ☐ | | |
| 2 | Mid-response STOP | ☐ | ☐ | ☐ | ☐ | | |
| 3 | Mid-response STOP | ☐ | ☐ | ☐ | ☐ | | |

**Tier 2 Result**: ___/3 PASSED

**STOP Latency Data**:
- Test 1: ___ms
- Test 2: ___ms
- Test 3: ___ms
- Average: ___ms (should be <50ms)

---

## Tier 3: Silence Discipline (3 minimum)

**Expected**: 15+ seconds of absolute silence after answer  
**Success bar**: 3/3 no unsolicited speech

| # | Session | 15s Silence | No Prompts | No Re-speak | LISTENING State | Status | Notes |
|---|---------|------------|-----------|-------------|-----------------|--------|-------|
| 1 | | ☐ | ☐ | ☐ | ☐ | | |
| 2 | | ☐ | ☐ | ☐ | ☐ | | |
| 3 | | ☐ | ☐ | ☐ | ☐ | | |

**Tier 3 Result**: ___/3 PASSED

---

## Tier 4: Sleep Authority (3 minimum)

**Expected**: "go to sleep" closes mic completely  
**Success bar**: 3/3 mic closure verified

| # | Session | Sleep Immediate | Mic Closed | No Tail Audio | Verification Q Ignored | Status | Notes |
|---|---------|-----------------|-----------|---------------|----------------------|--------|-------|
| 1 | | ☐ | ☐ | ☐ | ☐ | | |
| 2 | | ☐ | ☐ | ☐ | ☐ | | |
| 3 | | ☐ | ☐ | ☐ | ☐ | | |

**Tier 4 Result**: ___/3 PASSED

---

## Anomaly Log

**Critical Anomalies** (blocks progression):

| Date/Time | Tier | Issue | Reproducible | Notes |
|-----------|------|-------|--------------|-------|
| | | | | |
| | | | | |

**High Severity Anomalies** (noted but non-blocking):

| Date/Time | Tier | Issue | Reproducible | Notes |
|-----------|------|-------|--------------|-------|
| | | | | |

**Low Severity Anomalies** (observations):

| Date/Time | Tier | Issue | Notes |
|-----------|------|-------|-------|
| | | | |

---

## Subjective Observations

### Did the system feel natural?

- ☐ Yes, completely
- ☐ Mostly yes
- ☐ Some awkwardness
- ☐ Notable issues

**Notes**: ________________________________________________________________

### Any moments of user annoyance?

- ☐ No, system worked perfectly
- ☐ Minor hiccup but recovered
- ☐ Noticeable delay
- ☐ Frustrating behavior

**Notes**: ________________________________________________________________

### Any surprising or unexpected moments?

- ☐ No surprises, predictable
- ☐ One minor surprise
- ☐ Several surprises
- ☐ Major unexpected behavior

**Notes**: ________________________________________________________________

### Overall confidence level

- ☐ Fully confident (95%+)
- ☐ Very confident (80-95%)
- ☐ Moderately confident (60-80%)
- ☐ Concerns remain (<60%)

**Rating**: ___/100%

---

## Summary

### Tier Scorecard

| Tier | Tests | Passed | Status |
|------|-------|--------|--------|
| 1: Q&A | 5 | ___/5 | ☐ PASS ☐ FAIL |
| 2: Interruption | 3 | ___/3 | ☐ PASS ☐ FAIL |
| 3: Silence | 3 | ___/3 | ☐ PASS ☐ FAIL |
| 4: Sleep | 3 | ___/3 | ☐ PASS ☐ FAIL |

**Overall Result**: ☐ PASS (all tiers 3+/3) ☐ FAIL (any tier <3/3)

### Critical Issues Found

- [ ] None (proceed to Phase 7A-2)
- [ ] Yes (document and pause)

**Issues**:
1. ________________________________________________________________
2. ________________________________________________________________
3. ________________________________________________________________

### Final Assessment

**System feels**:
- [ ] Boring and reliable ✅
- [ ] Mostly reliable with minor issues
- [ ] Needs work before production

**Ready for Phase 7A-2 Audio Streaming**: ☐ YES ☐ NO

---

## Sign-Off

**Observer**: ________________________  
**Date Completed**: ________________________  
**Total Sessions**: ________  
**Total Interactions**: ________  

**Approval to proceed**:

- [ ] APPROVED - All tiers passed, no critical issues
- [ ] CONDITIONAL - Minor issues noted, acceptable for Phase 7A-2
- [ ] BLOCKED - Critical issues found, investigation needed

**Notes**: ________________________________________________________________

___________________________________________________________________
