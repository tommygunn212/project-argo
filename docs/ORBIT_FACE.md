# Orbit face

Orbit is an original procedural cyan circuit face inside a star field and orbital rings. All art is drawn locally with Canvas 2D; no external assets, downloads, credentials, GPU/WebGL, microphone permission, or avatar service are required. Existing voice audio remains owned by ARGO.

## Preview first

Open `I:\argo\frontend-v2\orbit-demo.html` in a browser, or run the existing standalone lab server:

```powershell
.\.venv\Scripts\python.exe tools/motion_lab_server.py
```

Visit `http://127.0.0.1:8777/orbit-demo.html`. Try idle, listening, thinking, speaking, sleeping, and reduced motion. Speaking uses simulated amplitude, not live microphone input. No real-portrait landmark calibration is involved: this is a new procedural face, not a replacement portrait rig.

## Enable in ARGO

Files are installed in this checkout. The dashboard has an Orbit choice in both avatar selectors. The HTTP asset whitelist was updated, so an already-running backend needs a restart before it can serve the new assets. At a convenient break in the current voice session run:

```powershell
.\RESTART_ARGO.bat
```

Then open `http://localhost:8000/v2-assets/orbit-demo.html` to review the face. Click **Use Orbit in ARGO**, open/reload `http://localhost:8000/v2`, or select **Orbit** directly in the dashboard. The preference uses the existing `argo_avatar` localStorage key and is per browser/origin. Selecting on port 8777 or a file URL does not select it on port 8000. Choose Orb, Cortana, or Auto to revert. Orbit is not forced as the default.

The dashboard uses the existing received-audio meter for Smooth Voice and the existing desktop speech meter for Classic. Hidden tabs skip rendering; resolution is capped at 1.5 device pixels per CSS pixel. Reduced motion stops orbit rotation, star twinkling, and blinking while preserving voice amplitude.

## Wake and sleep

Renderer API: `new OrbitFace.Face(canvas).draw(milliseconds, amplitude0to1, state, reducedMotion)`.
`SLEEPING`, `SLEEP`, `OFFLINE`, and `DISCONNECTED` dim the face, close its eyes, and suppress mouth movement even if audio amplitude is nonzero. Other states fade it awake. The demo exposes sleep/wake through its state buttons. In the dashboard Orbit follows the existing `avatarVisualState()` result. That existing function reports LISTENING/SPEAKING while Smooth Voice is connected: it does not expose the worker's private wake-word sleep latch. Therefore spoken sleep/wake is NOT independently visualized by Orbit yet; the worker's voice gate itself is unchanged. Do not mistake the demo sleep switch for microphone privacy or a voice-gate control.

## Completion reminder and music

```powershell
.\.venv\Scripts\python.exe tools/orbit_ready.py
```

This idempotently reuses a pending Orbit completion reminder, or saves a new due-now reminder through `tools.reminders` to the existing SQLite store. ARGO's existing reminder consumer delivers it when running; this is not a new scheduler. It creates `runtime/orbit/orbit-ready.wav`, a short original melody, and plays it once using Windows winsound. Run with `--no-play` to save without sound. Playback errors propagate as failures; no default system beep is substituted. The WAV can be replayed separately. The persistent spoken reminder does not replay music later: the music is the immediate completion alarm.

The demo also has **Play completion music**, **Remind me in one minute**, and **Stop alarm / cancel reminder**. Its browser timer is only valid while the page remains open and may be delayed in background tabs. These controls use synthesized Web Audio after a user gesture.

## Verification, 2026-11-22

- 11 Node tests passed across Orbit and the existing neural orb, including finite render geometry, resize, sleep despite loud input, wake recovery, missing-context rejection, and parsing the persisted dashboard/demo inline scripts.
- Existing frontend HTTP tests: 2 passed. An isolated real HTTP handler served both new files with exact byte matches and correct MIME types; an unlisted asset returned 404.
- `core.frontend_http` and `tools.orbit_ready` imported successfully.
- Completion script executed: reminder ID 2 saved; synchronous Windows music playback returned successfully. Physical speaker audibility is not verified.
- Browser preview host was unavailable. Visual quality, frame rate, and live voice synchronization have NOT been visually verified. No live stack restart was performed during the active voice task.
- Git commits were attempted after each logical change but blocked by read-only `.git` permissions. Changes remain uncommitted; the existing untracked `orbit_face_handoff.txt` was preserved.
