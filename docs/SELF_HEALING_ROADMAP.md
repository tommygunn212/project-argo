# ARGO Self-Healing Roadmap

## Vision: ARGO That Can Fix Itself

This document outlines the path to making ARGO self-diagnosing and self-repairing. The goal is for ARGO to detect issues, understand what's wrong, and either fix itself or guide the user through resolution.

---

## Current Capabilities (v1.6.24)

### What ARGO Already Knows

| Capability | Status | File |
|------------|--------|------|
| System health (CPU/RAM/temps) | ✅ Working | `system_health.py` |
| Hardware identification | ✅ Working | `system_health.py` |
| State machine enforcement | ✅ Working | `core/pipeline.py` |
| Error logging | ✅ Working | All core modules |
| Barge-in recovery | ✅ Working | `core/pipeline.py` |
| Audio ownership tracking | ✅ Working | `core/audio_owner.py` |

### What ARGO Can't Do Yet

- Detect when its own components are failing
- Restart individual subsystems (STT, TTS, LLM)
- Diagnose why a command didn't work
- Suggest fixes for common problems
- Apply patches or updates to itself

---

## Phase 1: Diagnostic Awareness (Easy Wins)

### 1.1 Component Health Checks

Add heartbeat/health checks for each critical component:

```python
# core/self_diagnostics.py

class SystemDiagnostics:
    def check_all(self) -> dict:
        return {
            "whisper": self._check_whisper(),     # STT working?
            "ollama": self._check_ollama(),       # LLM responding?
            "piper": self._check_piper(),         # TTS working?
            "audio_devices": self._check_audio(), # Mic/speaker OK?
            "disk_space": self._check_disk(),     # Enough space?
            "memory": self._check_memory(),       # RAM OK?
        }
    
    def _check_ollama(self) -> dict:
        # Ping Ollama, check model loaded
        try:
            response = requests.get("http://localhost:11434/api/tags")
            return {"status": "ok", "models": response.json()}
        except:
            return {"status": "error", "fix": "Run: ollama serve"}
    
    def _check_whisper(self) -> dict:
        # Check if Whisper model file exists and is loadable
        ...
    
    def _check_piper(self) -> dict:
        # Check if Piper binary and voice model exist
        ...
```

**Implementation effort:** 2-3 hours  
**Benefit:** ARGO can tell you "Ollama is not running" instead of failing silently

### 1.2 Error Message Interpretation

Map common errors to human-readable explanations:

```python
ERROR_EXPLANATIONS = {
    "Connection refused": {
        "cause": "Ollama isn't running",
        "fix": "Run 'ollama serve' in a terminal, or restart your computer"
    },
    "CUDA out of memory": {
        "cause": "GPU memory is full",
        "fix": "Close other GPU applications, or use a smaller model"
    },
    "No audio devices found": {
        "cause": "No microphone detected",
        "fix": "Check your microphone is plugged in and not muted"
    },
    "Model not found": {
        "cause": "The neural network model isn't downloaded",
        "fix": "Run: ollama pull qwen2.5:7b"
    }
}
```

**Implementation effort:** 1-2 hours  
**Benefit:** Instead of cryptic errors, ARGO says "I can't hear you because no microphone is connected"

---

## Phase 2: Assisted Recovery (Medium Effort)

### ⚠️ CRITICAL CONSTRAINT: Permission Required

Phase 2 is **assisted recovery**, NOT autonomous fixing.

**The Rule:**
> "Hey, this usually fixes it. Want me to do it?"
> 
> NOT: "I fixed myself while you weren't looking."

| ✅ ALLOWED | ❌ NOT ALLOWED |
|-----------|---------------|
| Restart a service | Edit configs |
| Retry a failed call | Touch code |
| Re-initialize audio | Change behavior permanently |
| Recheck a device | "Optimize" anything |

**Every recovery action MUST:**
1. Detect the problem
2. Propose the fix (with explanation)
3. **Ask permission** (UI button or voice confirmation)
4. Execute only after YES
5. Report result

### 2.1 Component Restart (With Permission)

```python
class AssistedRecovery:
    async def propose_restart_stt(self) -> dict:
        """Propose STT restart - does NOT execute"""
        return {
            "action": "restart_stt",
            "problem": "Speech recognition stopped responding",
            "proposal": "Restart the speech recognition engine",
            "reversible": True,
            "risk": "low",
            "requires_permission": True  # ALWAYS TRUE
        }
    
    async def execute_if_approved(self, action: str, approved: bool):
        """Only execute if user explicitly approved"""
        if not approved:
            return {"status": "cancelled", "reason": "User declined"}
        
        if action == "restart_stt":
            self.pipeline.stt_engine = None
            await asyncio.sleep(0.5)
            self.pipeline._init_stt_engine()
            return {"status": "success", "message": "Speech recognition restarted"}
        
        # ... other approved actions
```

**UI Flow:**
```
┌─────────────────────────────────────────────┐
│ ⚠️ Problem Detected                         │
│                                             │
│ Ollama is not responding.                   │
│                                             │
│ Suggested fix: Restart Ollama service       │
│                                             │
│ [Yes, do it]  [No, I'll handle it]         │
└─────────────────────────────────────────────┘
```

**Voice flow:**
```
ARGO: "Ollama isn't responding. Want me to restart it?"
User: "Yes" / "Go ahead" / "Do it"
ARGO: "Restarting Ollama... Done. It's back up."
```

### 2.2 Retry Logic (Transparent, Not Silent)

When something fails, ARGO proposes retry - does NOT auto-retry silently:

```python
async def handle_failure(self, operation: str, error: Exception):
    """Propose retry - never silent retry"""
    
    # Broadcast failure to UI
    self.broadcast("recovery_prompt", {
        "operation": operation,
        "error": str(error),
        "proposal": f"Retry {operation}?",
        "options": ["retry", "skip", "cancel"]
    })
    
    # Wait for user decision - NO automatic action
    decision = await self.wait_for_user_decision(timeout=30)
    
    if decision == "retry":
        return await self.retry_operation(operation)
    elif decision == "skip":
        return {"status": "skipped"}
    else:
        return {"status": "cancelled"}
```

### 2.3 Dependency Check (Propose, Don't Auto-Start)

```python
def check_ollama(self) -> dict:
    """Check if Ollama is running - propose fix, don't auto-fix"""
    if self._is_ollama_running():
        return {"status": "ok"}
    
    # DON'T auto-start. Propose instead.
    return {
        "status": "not_running",
        "problem": "Ollama is not running",
        "proposal": "Start Ollama service",
        "command": "ollama serve",  # Show what would run
        "requires_permission": True
    }
```

### 2.4 Allowed Recovery Actions (Exhaustive List)

Only these actions are permitted, and ALL require permission:

| Action | What It Does | Reversible? |
|--------|--------------|-------------|
| `restart_stt` | Reinitialize Whisper | ✅ Yes |
| `restart_tts` | Reinitialize Piper | ✅ Yes |
| `restart_ollama` | Restart Ollama process | ✅ Yes |
| `reinit_audio` | Reopen audio devices | ✅ Yes |
| `retry_last` | Retry last failed operation | ✅ Yes |
| `clear_audio_buffer` | Flush stuck audio | ✅ Yes |
| `reset_state_machine` | Return to IDLE state | ✅ Yes |

**Explicitly FORBIDDEN:**
- ❌ Edit config.json
- ❌ Modify any .py file
- ❌ Change user preferences
- ❌ Download/update anything
- ❌ Delete any file
- ❌ "Optimize" settings
- ❌ Any action without permission prompt

---

## Phase 3: Codebase Self-Knowledge (For Developers)

### 3.1 Architecture Awareness

ARGO should be able to answer questions about itself:

- "How does your audio system work?"
- "What's your state machine?"
- "Show me your intent parser logic"

**Implementation:**

```python
# core/self_knowledge.py

class SelfKnowledge:
    def __init__(self):
        self.docs = self._load_documentation()
    
    def _load_documentation(self):
        """Load all .md files into searchable index"""
        docs = {}
        for md_file in Path(".").glob("**/*.md"):
            docs[md_file.stem] = md_file.read_text()
        return docs
    
    def query(self, question: str) -> str:
        """Find relevant documentation for question"""
        # Simple keyword matching or embed-based search
        ...
```

### 3.2 Log Analysis

ARGO should understand its own logs:

```python
def analyze_recent_errors(self, minutes: int = 30) -> str:
    """Parse recent logs and explain what went wrong"""
    recent_errors = self._get_log_entries(level="ERROR", since=minutes)
    
    if not recent_errors:
        return "No errors in the last 30 minutes"
    
    # Categorize and explain
    explanations = []
    for error in recent_errors:
        if "timeout" in error.lower():
            explanations.append("Network timeout - check your connection")
        elif "file not found" in error.lower():
            explanations.append("Missing file - may need to reinstall")
        ...
    
    return "\n".join(explanations)
```

**Voice command:** "ARGO, what went wrong?"

---

## Phase 4: Self-Patching (Advanced)

### 4.1 Configuration Auto-Correction

ARGO can detect and fix configuration issues:

```python
def validate_config(self) -> list[str]:
    """Check config.json for common problems"""
    issues = []
    
    # Check audio device exists
    if not self._device_exists(self.config["audio_output_device"]):
        issues.append("Audio output device not found")
        # Auto-fix: switch to default
        self.config["audio_output_device"] = self._get_default_output()
    
    # Check model exists
    if not self._model_downloaded(self.config["ollama_model"]):
        issues.append(f"Model {self.config['ollama_model']} not downloaded")
        # Auto-fix: download it
        subprocess.run(["ollama", "pull", self.config["ollama_model"]])
    
    return issues
```

### 4.2 Safe Code Updates

ARGO could apply known-safe patches:

```python
# VERY CAREFUL - Only pre-approved patches
SAFE_PATCHES = {
    "fix_audio_buffer_size": {
        "file": "core/pipeline.py",
        "search": "buffer_size = 1024",
        "replace": "buffer_size = 2048",
        "reason": "Fixes audio crackling on slow systems"
    }
}

def apply_safe_patch(self, patch_id: str) -> str:
    if patch_id not in SAFE_PATCHES:
        return "Unknown patch"
    
    patch = SAFE_PATCHES[patch_id]
    # Create backup, apply patch, test, rollback if fails
    ...
```

**⚠️ Risk Level: HIGH** - Requires extensive testing and safeguards

---

## Phase 5: Full Autonomy (Future Vision)

### 5.1 Self-Updating

ARGO could update itself when new versions are available:

```python
def check_for_updates(self) -> dict:
    """Check GitHub for new releases"""
    current = self._get_version()
    latest = self._get_latest_github_release()
    
    if latest > current:
        return {
            "update_available": True,
            "current": current,
            "latest": latest,
            "changelog": self._get_changelog()
        }
```

### 5.2 Learning From Failures

Track what goes wrong and improve:

```python
class FailureMemory:
    """Remember what failed and what fixed it"""
    
    def record_failure(self, context: str, error: str, resolution: str):
        self.db.store({
            "timestamp": datetime.now(),
            "context": context,
            "error": error,
            "resolution": resolution
        })
    
    def suggest_fix(self, error: str) -> str:
        """Look up what fixed this error before"""
        similar = self.db.find_similar(error)
        if similar:
            return f"Last time this happened, we fixed it by: {similar.resolution}"
```

---

## Implementation Priority

| Phase | Priority | Effort | Impact |
|-------|----------|--------|--------|
| 1.1 Component health checks | 🔴 High | 2-3 hrs | Know what's broken |
| 1.2 Error explanations | 🔴 High | 1-2 hrs | Users understand problems |
| 2.1 Component restart | 🟡 Medium | 4-6 hrs | Recover without restart |
| 2.2 Automatic retry | 🟡 Medium | 2-3 hrs | Resilience |
| 2.3 Dependency auto-start | 🟡 Medium | 2-3 hrs | Less manual setup |
| 3.1 Architecture awareness | 🟢 Low | 4-6 hrs | Answer meta questions |
| 3.2 Log analysis | 🟢 Low | 3-4 hrs | Debug assistance |
| 4.x Self-patching | ⚪ Future | 10+ hrs | Risky, needs safeguards |
| 5.x Full autonomy | ⚪ Future | 20+ hrs | Long-term vision |

---

## Quick Start: Phase 1

To implement Phase 1 (diagnostic awareness) immediately:

1. Create `core/self_diagnostics.py`
2. Add health check endpoints to WebSocket
3. Add "run diagnostics" voice command
4. Display results in UI status panel

**Voice commands to add:**
- "ARGO, run diagnostics"
- "ARGO, what's your status?"
- "ARGO, are you okay?"
- "ARGO, check yourself"

---

## Safety Constraints

### The Prime Directive

> **ARGO never fixes itself while you aren't looking.**

Any recovery action MUST follow this flow:

```
Detect → Propose → Ask → (User says Yes) → Execute → Report
                    ↓
              (User says No) → Do nothing
```

### Non-Negotiable Rules

1. **Permission Required** - EVERY action needs explicit user approval
2. **Reversible Only** - Only actions that can be undone
3. **Boring Only** - Restarts and retries, not "improvements"
4. **Transparent** - User sees exactly what will happen before it happens
5. **Auditable** - Full log of what was proposed, approved, and executed
6. **Fail Safe** - If unsure, propose nothing
7. **No Silent Actions** - Never do anything without UI/voice confirmation

### Forbidden Forever

These are NEVER allowed, regardless of phase:

- ❌ Modify source code (.py files)
- ❌ Edit configuration without explicit permission
- ❌ Change user preferences silently
- ❌ "Optimize" or "improve" anything
- ❌ Download updates without asking
- ❌ Delete or move files
- ❌ Learn and adapt behavior autonomously
- ❌ Any permanent state change without consent

### The Test

Before implementing any recovery feature, ask:

> "If ARGO did this while I was away, would I be confused or upset?"

If YES → Don't allow it.  
If NO → It might be okay, but still require permission.

---

## Related Documents

- [ARCHITECTURE.md](../ARCHITECTURE.md) - System overview
- [FEATURES.md](../FEATURES.md) - Current capabilities
- [SYSTEM_OVERVIEW.md](../SYSTEM_OVERVIEW.md) - Layer responsibilities
- [INSTRUMENTATION_GUIDE.md](../INSTRUMENTATION_GUIDE.md) - Logging and telemetry

---

*Document created: 2026-02-04*  
*Last updated: 2026-02-04*  
*Status: ROADMAP (not yet implemented)*
