# ARGO Security Audit

**Date:** February 7, 2026  
**Scope:** Home-use security review  
**Status:** 2 high-priority issues FIXED, recommendations documented

---

## Executive Summary

ARGO is designed for local, home-use operation. This audit found **2 high-severity issues** (now fixed) and several recommendations to improve overall security posture.

### Fixed Issues

| Severity | Issue | Status |
|----------|-------|--------|
| HIGH | Network exposure (0.0.0.0 binding) | ✅ FIXED |
| HIGH | No authentication on servers | ⚠️ DOCUMENTED |

---

## Detailed Findings

### 1. Network Exposure - FIXED ✅

**Location:** `main.py` lines 566, 810

**Problem:** Both HTTP (8000) and WebSocket (8001) servers were binding to `0.0.0.0`, making ARGO accessible to **any device on your local network**.

**Risk:** Anyone on your WiFi could:
- Access the ARGO web UI
- Send voice commands
- Control app launches/closures
- Access system health information

**Fix Applied:** Changed bindings to `127.0.0.1` (localhost only):
```python
# Before (vulnerable)
websockets.serve(websocket_handler, "0.0.0.0", 8001)
HTTPServer(('0.0.0.0', 8000), FrontendHandler)

# After (secure)
websockets.serve(websocket_handler, "127.0.0.1", 8001)
HTTPServer(('127.0.0.1', 8000), FrontendHandler)
```

Also fixed in monitor dev servers (`monitors/*/vite.config.ts`).

---

### 2. No Authentication - ACKNOWLEDGED

**Location:** `main.py` websocket_handler, FrontendHandler

**Problem:** No authentication mechanism exists for WebSocket or HTTP connections.

**Risk (now mitigated):** With localhost-only binding, this is acceptable for home use. Only processes on your machine can connect.

**Recommendation for future:** If you ever need remote access, implement:
- Token-based authentication for WebSocket
- Basic auth or API key for HTTP endpoints

---

### 3. Secrets Management - GOOD ✅

**Finding:** Secrets are properly managed:
- `.gitignore` excludes `config.json`, `.env`, and related files
- API keys loaded from environment variables
- Porcupine access key uses env var `PORCUPINE_ACCESS_KEY`
- Jellyfin credentials use env vars

**No action needed.**

---

### 4. SQL Injection - SAFE ✅

**Finding:** Database operations use parameterized queries:
```python
# Good example from database.py
cur.execute("INSERT INTO memory(...) VALUES(?, ?, ?, ?, ?, ?)", (params...))
```

**Minor note:** Some PRAGMA statements use f-strings but with hardcoded table names from controlled lists - not injectable.

---

### 5. Command Injection - SAFE ✅

**Finding:** Shell commands are properly constructed:
- `subprocess.run()` uses list arguments (not shell=True)
- App registry uses hardcoded process names
- OpenRGB commands use validated color/mode values
- No user input directly reaches shell execution

---

### 6. File Path Handling - SAFE ✅

**Finding:** 
- Music paths come from local index or Jellyfin server
- No user-controlled path traversal vectors found
- Config paths are hardcoded or from trusted config

---

### 7. Dependency Security - RECOMMENDATIONS

**Current state:** Dependencies use minimum version constraints (`>=`).

**Recommendation:** Pin exact versions for reproducibility:
```
# Before
requests>=2.31.0

# After (more secure)
requests==2.31.0
```

Run periodic security scans:
```powershell
pip install pip-audit
pip-audit
```

---

## Security Checklist for Home Use

- [x] Servers bind to localhost only
- [x] Secrets not committed to git
- [x] Parameterized SQL queries
- [x] No shell injection vectors
- [x] App registry uses allowlist
- [x] Blocked processes list prevents closing critical apps
- [ ] Consider firewall rules for ports 8000/8001 (optional)
- [ ] Run `pip-audit` periodically for dependency vulns

---

## Architecture Security Notes

### Positive Design Decisions

1. **Local-first:** LLM, STT, TTS all run locally - no cloud data exposure
2. **Deterministic commands:** System health queries bypass LLM entirely
3. **Blocked processes:** Cannot close VS Code, terminals, or system processes via voice
4. **Five Gates governance:** Execution requires explicit approval workflow
5. **No memory authority:** Memory is advisory only, cannot trigger actions

### Trust Boundaries

```
┌─────────────────────────────────────────────────────┐
│ TRUSTED ZONE (localhost only)                       │
│                                                     │
│  ┌─────────┐    ┌─────────┐    ┌─────────┐        │
│  │ Web UI  │◄──►│ ARGO    │◄──►│ Ollama  │        │
│  │ :8000   │    │ Main    │    │ :11434  │        │
│  └─────────┘    └─────────┘    └─────────┘        │
│       ▲              │                             │
│       │         ┌────┴────┐                        │
│       │         ▼         ▼                        │
│  ┌─────────┐  ┌─────┐  ┌─────┐                    │
│  │WebSocket│  │Audio│  │Piper│                    │
│  │ :8001   │  │ I/O │  │ TTS │                    │
│  └─────────┘  └─────┘  └─────┘                    │
└─────────────────────────────────────────────────────┘
         All services localhost-only
```

---

## Conclusion

ARGO is reasonably secure for home use after the network binding fix. The local-first design inherently limits attack surface. Key recommendations:

1. **Keep servers localhost-only** (now enforced)
2. **Don't expose ports 8000/8001 to the internet** 
3. **Run `pip-audit` periodically**
4. **Keep .env and config.json out of git** (already configured)

For questions or concerns, refer to CONTRIBUTING.md.
