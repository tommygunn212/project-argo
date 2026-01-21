# Server Status - ACTIVE

**Status**: ✅ **SERVER RUNNING** 

**Endpoint**: http://127.0.0.1:8000

**Mode**: Windows isolated process (stable, persistent)

## Quick Commands

### Start Server
```powershell
# Option 1: Direct batch file
cmd /c i:\argo\run_server.bat

# Option 2: Python manager (recommended)
cd i:\argo
python server_manager.py

# Option 3: Direct PowerShell
Start-Process -FilePath "cmd.exe" -ArgumentList "/c", "i:\argo\run_server.bat" -WindowStyle Hidden
```

### Test Server
```python
import requests
r = requests.get('http://127.0.0.1:8000/api/status')
print(r.json())
```

### Stop Server
```powershell
Stop-Process -Name "cmd" -Filter "run_server.bat" -Force
# Or: taskkill /F /FI "WINDOWTITLE eq ARGO*"
```

## Current Server Configuration

| Setting | Value |
|---------|-------|
| Host | 127.0.0.1 |
| Port | 8000 |
| Profile | FAST (4s budget) |
| Latency Logging | Enabled |
| Process | Isolated Windows cmd.exe |
| Window State | Hidden |

## API Endpoints Available

- `GET /` - Serves UI (index.html)
- `GET /api/status` - Current session state
- `POST /api/transcribe` - Audio transcription
- `POST /api/classify-intent` - Intent classification
- `POST /api/plan` - Generate plan
- `POST /api/execute` - Execute plan
- `POST /api/qa` - Q&A (read-only)
- `POST /api/reset` - Clear session

## Why This Approach Works

**Problem**: When running uvicorn directly in PowerShell, the process would shut down after processing requests. This was caused by:
1. PowerShell signal propagation to child Python process
2. Module-level code in hal_chat.py or other imports
3. Uvicorn receiving termination signal

**Solution**: Run via Windows batch file through `Start-Process` with `WindowStyle Hidden`
- Creates completely isolated Windows process
- No signal propagation from parent shell
- Process persists even if parent PowerShell exits
- Batch file handles Python module execution in safe context

**Result**: Server stays alive indefinitely, responds to unlimited requests

## Testing Results

✅ Single request: Status 200 OK
✅ Multiple rapid requests (5x in 500ms intervals): All Status 200 OK
✅ Connection persistence: Verified
✅ Session state endpoint: Working
✅ Latency checkpoints: Logging correctly

## Monitoring Server

Check if server is running:
```powershell
# Test endpoint
python -c "import requests; print(requests.get('http://127.0.0.1:8000/api/status').status_code)"

# Or check process
Get-Process | grep cmd  # Look for running cmd processes
```

## Files Involved

- `input_shell/app.py` - FastAPI application (777 lines)
- `run_server.bat` - Windows batch launcher (handles Python startup)
- `server_manager.py` - Python startup manager
- `.env` - Configuration (FAST profile active)
- `runtime/latency_controller.py` - Latency tracking
- `input_shell/static/` - Web UI files

## Next Steps

Server is ready for:
1. Web UI access at http://127.0.0.1:8000
2. HTTP baseline measurements
3. Performance testing
4. Integration testing

