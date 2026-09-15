"""Wire persona_briefs in as the single source of truth."""
import io, json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
log = []

def patch(rel, old, new, label, marker):
    p = ROOT / rel
    s = io.open(p, encoding="utf-8").read()
    if marker in s:
        log.append(f"SKIP {label}"); return
    assert old in s, f"ANCHOR MISSING in {rel}: {label}"
    assert s.count(old) == 1, f"AMBIGUOUS in {rel}: {label} (x{s.count(old)})"
    io.open(p, "w", encoding="utf-8", newline="").write(s.replace(old, new, 1))
    log.append(f"OK   {label}")

LK = "core/livekit_config.py"
s = io.open(ROOT / LK, encoding="utf-8").read()

# --- 1. the contract replaces the inline instructions + briefs ------------------
start = s.index("DEFAULT_REALTIME_INSTRUCTIONS = (")
end = s.index("\n\n\ndef read_voice_personality")
if "from core.persona_briefs import" not in s[start:end]:
    s = s[:start] + '''from core.persona_briefs import (  # noqa: E402
    CONVERSATION_CONTRACT,
    DEEP_THINK_POLICY,
    TOOL_POLICY,
    compose_instructions,
    instruction_fingerprint,
)

# The product contract is the base instruction. Everything ARGO is told is
# assembled once, in core.persona_briefs.compose_instructions; these names are
# kept so existing callers and tests keep working.
DEFAULT_REALTIME_INSTRUCTIONS = CONVERSATION_CONTRACT
TOOL_BRIEF = TOOL_POLICY
DEEP_THINK_BRIEF = DEEP_THINK_POLICY''' + s[end:]
    log.append("OK   livekit_config: contract from persona_briefs")
else:
    log.append("SKIP livekit_config: contract from persona_briefs")

# --- 2. compose delegates ---------------------------------------------------------------
cstart = s.index("def compose_realtime_instructions(")
cend = s.index("@dataclass(frozen=True)")
s = s[:cstart] + '''def compose_realtime_instructions(
    base_instructions: str,
    personality: str,
    *,
    deep_think: bool = True,
) -> str:
    """Assemble everything the realtime model is told - once, here.

    Order: the conversation contract (what every ARGO does), the selected
    persona's voice AND collaboration style, the deep-think policy, the short
    tool policy. Nothing else is layered on top: not the classic personas'
    text post-processors, not a tool manual, not a second system prompt.

    `base_instructions` is the contract unless a caller overrides it (tests
    do); an unknown persona contributes no manner at all.
    """
    return compose_instructions(personality, deep_think=deep_think, contract=base_instructions)


''' + s[cend:]
log.append("OK   livekit_config: compose delegates to persona_briefs")

# --- 3. default persona + fingerprint on the config ---------------------------------------
s = s.replace('''    personality: str = "argo"
    noise_cancellation: bool = True''', '''    personality: str = "argo"
    instruction_fingerprint: str = ""
    noise_cancellation: bool = True''', 1)
s = s.replace('''        instructions=compose_realtime_instructions(
            base_instructions,
            personality,
            deep_think=_bool(
                _env_or_config(cfg, "ARGO_DEEP_THINK_ENABLED", "livekit.deep_think.enabled", True)
            ),
        ),''', '''        instructions=_instructions,
        instruction_fingerprint=instruction_fingerprint(_instructions),''', 1)
s = s.replace('''    return LiveKitRealtimeConfig(
        enabled=_bool(_env_or_config(cfg, "ARGO_LIVEKIT_ENABLED", "livekit.enabled", True)),''',
'''    _instructions = compose_realtime_instructions(
        base_instructions,
        personality,
        deep_think=_bool(
            _env_or_config(cfg, "ARGO_DEEP_THINK_ENABLED", "livekit.deep_think.enabled", True)
        ),
    )

    return LiveKitRealtimeConfig(
        enabled=_bool(_env_or_config(cfg, "ARGO_LIVEKIT_ENABLED", "livekit.enabled", True)),''', 1)
log.append("OK   livekit_config: fingerprint on the config")

# --- 4. status: active now vs saved for next, plus the persona list ---------------------
s = s.replace('''        "voice_mode": read_voice_mode(),''', '''        "voice_mode": read_voice_mode(),
        # What the live session is ACTUALLY running, from the record the
        # worker writes at session start - not what is saved in config.
        "active_now": _active_now(),
        # What the NEXT connection will use. Shown separately, so a changed
        # dropdown never looks like it transformed a session already in flight.
        "saved_for_next": {
            "model": cfg.model,
            "voice": cfg.voice,
            "personality": cfg.personality,
            "instruction_fingerprint": cfg.instruction_fingerprint,
        },
        "personas": _persona_list(),''', 1)
s = s.replace('''def livekit_status(config: Any | None = None) -> dict[str, Any]:''', '''def _active_now() -> dict[str, Any] | None:
    try:
        from core.voice_active import read_active

        return read_active()
    except Exception:
        return None


def _persona_list() -> list[dict[str, str]]:
    try:
        from core.persona_briefs import selectable

        return selectable()
    except Exception:
        return []


def livekit_status(config: Any | None = None) -> dict[str, Any]:''', 1)
log.append("OK   livekit_config: active_now / saved_for_next / personas in status")

io.open(ROOT / LK, "w", encoding="utf-8", newline="").write(s)

# --- 5. deep think keeps the persona ------------------------------------------------------
patch("core/deep_think.py",
'''async def think(
    question: str,
    *,
    history: Iterable[dict] | None = None,
    model: str = "gpt-5.5",
    timeout: float = 90.0,
) -> DeepThinkResult:''',
'''async def think(
    question: str,
    *,
    history: Iterable[dict] | None = None,
    model: str = "gpt-5.5",
    timeout: float = 90.0,
    persona: str | None = None,
) -> DeepThinkResult:''',
"deep_think: persona parameter", marker="persona: str | None = None,\n) -> DeepThinkResult:")

patch("core/deep_think.py",
'''        messages = [{"role": "system", "content": SYSTEM_PROMPT}]''',
'''        # Same person, thinking longer. The persona's voice and collaboration
        # style ride along so the answer read back aloud is still HER answer.
        from core.persona_briefs import deep_think_system_prompt

        messages = [{"role": "system", "content": deep_think_system_prompt(persona)}]''',
"deep_think: persona system prompt", marker="deep_think_system_prompt(persona)")

patch("core/deep_think.py",
'''        logger.info(
            "[DeepThink] model=%s context_turns=%d question=%r",
            model, len(messages) - 2, question[:160],
        )''',
'''        logger.info(
            "[DeepThink] model=%s persona=%s context_turns=%d question=%r",
            model, persona or "argo", len(messages) - 2, question[:160],
        )''',
"deep_think: log persona", marker="persona=%s context_turns")

# --- 6. agent: pass persona, write the active record, log Active now ----------------------
AG = "livekit_realtime_agent.py"
patch(AG,
'''        result = await deep_think.think(
            question,
            history=history,
            model=cfg.deep_think_model,
            timeout=cfg.deep_think_timeout,
        )''',
'''        result = await deep_think.think(
            question,
            history=history,
            model=cfg.deep_think_model,
            timeout=cfg.deep_think_timeout,
            persona=cfg.personality,
        )''',
"agent: think_deeply passes persona", marker="persona=cfg.personality,")

patch(AG,
'''    _log_session_activity(session)
    _wire_urgent_interrupts(session, cfg)''',
'''    _log_session_activity(session)
    _wire_urgent_interrupts(session, cfg)

    # The one line that answers "what is she running right now", and the
    # record the dashboard's 'Active now' is filled from.
    from core.voice_active import write_active

    room_name = str(getattr(getattr(ctx, "room", None), "name", "") or "")
    logger.info(
        "[LiveKit] Active now: %s / %s / personality %s (instructions %s)",
        cfg.model, cfg.voice, cfg.personality, cfg.instruction_fingerprint,
    )
    write_active(
        model=cfg.model, voice=cfg.voice, personality=cfg.personality,
        instruction_fingerprint=cfg.instruction_fingerprint, room=room_name,
        job_id=str(getattr(getattr(ctx, "job", None), "id", "") or ""),
    )
    _ve.emit("session_config", model=cfg.model, voice=cfg.voice, personality=cfg.personality,
             instruction_fingerprint=cfg.instruction_fingerprint, room=room_name)''',
"agent: Active now log + record", marker="[LiveKit] Active now:")

patch(AG,
'''    async def _on_shutdown(reason: str = "") -> None:
        _ve.emit("session_end", room=str(getattr(getattr(job, "room", None), "name", "") or ""),
                 job_id=str(getattr(job, "id", "") or ""), reason=str(reason or ""))''',
'''    async def _on_shutdown(reason: str = "") -> None:
        _ve.emit("session_end", room=str(getattr(getattr(job, "room", None), "name", "") or ""),
                 job_id=str(getattr(job, "id", "") or ""), reason=str(reason or ""))
        try:
            from core.voice_active import mark_ended

            mark_ended(str(reason or ""))
        except Exception:
            pass''',
"agent: mark active record ended", marker="mark_ended(str(reason")

# --- 7. persisted selection -> argo -------------------------------------------------------------
from datetime import datetime, timezone
pf = ROOT / "runtime" / "voice_personality.json"
pf.write_text(json.dumps({"personality": "argo", "updated_at": datetime.now(timezone.utc).isoformat()}, indent=2), encoding="utf-8")
log.append("OK   runtime/voice_personality.json -> argo")

print("\n".join(log))
import ast
for rel in (LK, "core/deep_think.py", AG):
    ast.parse(io.open(ROOT / rel, encoding="utf-8").read())
print("all parse")
