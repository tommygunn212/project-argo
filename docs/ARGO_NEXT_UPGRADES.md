# ARGO Next Upgrades

## 1. Phone Vision

Status: first pass implemented.

ARGO now exposes a phone-friendly image analysis path:

- Mobile URL: use `/api/mobile-access` to get the LAN URL.
- UI: `/v2` -> Tools -> Phone Vision.
- API: `POST /api/vision/analyze-upload`
- Payload: JSON with `image_data` as a browser image data URL and `prompt` as the question.
- Backend: `tools.vision.analyze_uploaded_image()` decodes the image and sends it through the existing OpenAI vision path.

Use this from a phone on the same Wi-Fi by opening the LAN `/v2` URL, choosing the Phone Vision image input, taking or selecting a photo, and pressing Analyze Image.

Next step: add optional live camera frame capture for repeated looks, with a visible manual Analyze button so ARGO does not stream private camera frames continuously.

## 2. Vibe Coding Bridge

Goal: let Tommy say a coding request to ARGO and have it become a concrete coding-agent task.

Recommended safe architecture:

1. ARGO records the request as a Markdown task file under `runtime/code_requests/`.
2. ARGO opens the target repo and task file in VS Code using `code -r`.
3. If Codex CLI/app control is available, ARGO can dispatch the task to Codex with explicit repo path, requested change, and verification commands.
4. ARGO stores the result path, diff summary, and test output back in `runtime/code_requests/`.
5. ARGO never silently edits arbitrary repos without a visible task record.

Current local status:

- VS Code CLI is installed: `code.cmd`.
- Claude CLI is not currently on PATH.
- Codex is installed through the Windows app package, but direct PowerShell launch returned access denied in this session.

Implemented first step:

- `scripts/create_code_request.py` creates the request record and can open it in VS Code with `--open-vscode`.

Remaining steps:

- Local Codex CLI is now confirmed. The `/v2` System panel creates a task record and, after explicit approval, dispatches `gpt-6-astra` with high reasoning in the ARGO workspace. The generated prompt forbids commit, push, unrelated deletion, and external-system changes.
- Add process-status polling and a visual diff/review panel before treating a completed coding-agent run as an applied repair.
- Add Claude only after a local CLI or API path is installed and authenticated.

## 3. Speaker Recognition

Goal: ARGO knows whether the speaker is Tommy or someone else.

Current status:

- ARGO already exposes `speaker_identity` readiness in `/api/livekit-status`.
- Speechmatics is the configured provider scaffold.
- Speaker-ID is off by default and not yet enrolled.

Recommended stages:

1. Enrollment mode: record 3-5 short samples per person and store labeled voice profiles.
2. Identification mode: every realtime voice turn gets a probable speaker label plus confidence.
3. Personal-command gate: sensitive actions require Tommy voice match or manual confirmation.
4. UI status: show current speaker and confidence in Dashboard and Voice panels.

Important guardrail: voice recognition should be treated as a convenience signal, not a sole security factor. For destructive or private actions, keep confirmation.

## 4. AI Provider Router

Status: first pass implemented.

Goal: let Tommy choose one or more AI backends for ARGO responses without scattering LLM calls through the codebase.

Target providers:

- Ollama local models, starting with `qwen:latest`
- OpenAI API models
- Gemini API models

Recommended architecture:

1. Add provider classes behind one interface: `generate()`, `stream()`, and `health_check()`.
2. Add an `LLMRouter` that owns provider selection, fallback order, and multi-model compare mode.
3. Keep API keys in `.env` or a credential store, not in `config.json`.
4. Store safe provider settings in config: enabled providers, selected models, primary provider, fallback list, and mode.
5. Add a UI settings panel for provider/model selection and mode selection.
6. Keep deterministic ARGO commands outside the router; only conversational/planning/writing LLM work should use it.

Best first implementation:

- Phase 1: single active provider chooser. Done in `core.llm_router`.
- Phase 2: fallback chain across configured enabled providers. Done for OpenAI, Ollama, and Gemini.
- Phase 3: multi-AI compare mode for explicit high-value requests only.
- Phase 4: task-based routing, for example local for simple chat, cloud for coding/planning/vision-heavy work.

Current implementation:

- Config-driven providers live under `llm.providers`.
- `llm.primary`, `llm.fallbacks`, and `llm.mode` control deterministic selection.
- `ArgoPipeline.generate_response()` and streamed LLM -> TTS output both route through `LLMRouter`.
- Provider start, success, and error events are emitted to the timeline.
- API keys stay in environment variables, not in `config.json`.

Remaining UI work:

- Add a settings panel for toggling providers, selecting models, and changing fallback order.
- Add explicit multi-model compare mode for manual high-value prompts.

Guardrails:

- Do not call multiple paid APIs by default.
- Emit timeline events for selected provider, fallback attempts, errors, and latency.
- Keep streaming TTS compatibility intact so the provider router does not break the current LLM -> TTS flow.
