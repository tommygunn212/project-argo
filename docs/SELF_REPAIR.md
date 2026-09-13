# ARGO repair workflow

## Use it

Say **“ARGO, your voice isn't working. Diagnose and fix it.”** in classic voice,
Smooth Voice, or type it in Chat. Both voice paths call the same repair service.

ARGO checks the selected conversational provider, STT/TTS initialization,
selected audio devices, disk space, and memory. Basic checks do not measure
audible output, transcription accuracy, or cloud response quality.

When a supported repair is available, ARGO describes the finding and proposes
one action. Say **“approve repair”** or **“cancel repair”**, or use the buttons in
System. Approval refers to one unique proposal, expires after five minutes, and
is consumed once. Generic “yes” is not used because it can refer to another
conversation or memory prompt.

After execution, ARGO runs the checks again and reports the observed outcome.
“Checks passed” asks you to try the original symptom again; it is not a claim
that every aspect of the system is working. “Repair status” repeats the result.

## Runtime repairs

- Start/restart the local default Ollama service when its health probe fails.
- Restart the selected STT manager or selected OpenAI TTS client.
- Restart the active AudioManager, clear its buffers, or request LISTENING.
- Retry a saved failed conversational response. This calls conversational
  generation directly; it never repeats a device command, email, or file action.

Unsupported actions, failed return values, exceptions, expired proposals, and
duplicate approvals report errors. The service does not infer success from a
process launch or silently retry side-effecting commands.

## Code repair with Astra

If checks cannot explain the symptom, say **“prepare code repair”**. ARGO records
the complaint and diagnostic finding. You can also describe a problem directly
in **System → Code Repair**.

1. Review the request and approve **Run Astra Repair**.
2. ARGO requires a clean committed checkout matching the proposal's base commit.
3. It creates an independent local Git clone under
   `runtime/code_requests/<job-id>/workspace`, detaches it at that commit, and
   removes its remote. Ignored local data and environment files are not copied.
4. Local Codex runs `gpt-6-astra` with high reasoning and `workspace-write`, with
   automatic escalation disabled and user Codex configuration ignored. Local
   Codex authentication is still required. No model substitution is performed.
5. ARGO tracks exit status and a 30-minute agent deadline, captures tracked and
   new-file changes, and runs fixed focused pytest and Node UI checks in the
   clone with the ARGO Python interpreter. Each command has a three-minute limit.
6. System shows progress, changed files, diff, test output, and the agent report.
   The report is agent-written; the separate test output is captured by ARGO.
7. **Apply reviewed patch** appears only after a zero agent exit, passing tests,
   an agent report, and a nonempty stable patch. It requires the reviewed hash,
   unchanged base commit, and a clean running checkout. ARGO checks the patch
   before applying it. It does not commit, push, or restart the running app.

Job metadata, request, agent log, report, tests, and patch are kept in the job
directory. The dashboard refreshes every five seconds while visible. After an
ARGO restart, unfinished jobs are marked interrupted and are not automatically
resumed or applied; their files remain available for inspection. Review-ready
jobs remain available. No repair directories are automatically deleted.

The clone isolates edits from the running checkout; it is not a virtual machine.
The Codex process uses its workspace sandbox. The focused test subprocess is a
normal local test run in that clone. Do not treat passing these tests as a full
security or hardware certification.

## Verification

The automated integration tests use actual temporary Git repositories and child
Python processes as deterministic stand-ins for an agent. They exercise the
production clone, monitoring, diff, verification, persistence, and apply code.
They cover agent failure, test failure, timeout, tampered patches, dirty working
trees, duplicate/expired approvals, and restart recovery. A separate test calls
the registered LiveKit repair tool over real localhost HTTP, including rejection
of unauthenticated calls. UI tests execute the real rendering/button functions.

Recorded verification: 170 targeted Python tests and 6 JavaScript checks passed
on 2026-09-12. This is a focused regression result, not a full-repository count.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_self_repair_and_code_repair.py -q
node --test tests/test_cortana_avatar.cjs tests/test_repair_ui.cjs
```

This verification does not spend model credits or open a microphone. A live
Astra completion and a physical microphone/speaker repair still require an
actual reported problem and the corresponding runtime approval.

Codex launch behavior follows the [official non-interactive documentation](https://developers.openai.com/codex/noninteractive/).
