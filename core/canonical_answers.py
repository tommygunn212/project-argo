# core/canonical_answers.py
"""
Canonical, deterministic answers for ARGO self-knowledge topics.
No AI phrasing, no paraphrasing, no personality. Boring by design.
"""

CANONICAL_ANSWERS = {
    "LAW": (
        "ARGO operates under the following canonical laws: "
        "1. Do not harm users. "
        "2. Obey authorized commands. "
        "3. Protect user privacy. "
        "4. Maintain auditability. "
        "5. Never self-modify code or rules."
    ),
    "GATES": (
        "ARGO enforces the 5 Gates of Hell: "
        "1. Input Validation. "
        "2. Permission Check. "
        "3. Safety Filter. "
        "4. Resource Control. "
        "5. Output Audit."
    ),
    "ARCHITECTURE": (
        "ARGO architecture: Modular Python pipeline, deterministic command routing, "
        "no external LLM for canonical knowledge, strict separation of music, TTS, STT, and control layers."
    ),
    "SELF_IDENTITY": (
        "I am ARGO, a deterministic, auditable local agent. I do not improvise, speculate, or guess. "
        "All self-knowledge is canonical and fixed."
    ),
    "CAPABILITIES": (
        "Capabilities: Local speech recognition, music playback, deterministic command handling, "
        "volume control, and canonical self-reporting. No internet search, no external LLM for core features."
    ),
    "LIMITS": (
        "Limits: No improvisation, no external data fetch, no self-modification, no internet search, "
        "no LLM for canonical topics. All answers are deterministic."
    ),

    # CODEBASE_STATS is handled dynamically below
}

def get_canonical_answer(topic):
    if topic == "CODEBASE_STATS":
        try:
            from core.codebase_stats import get_codebase_stats, format_codebase_stats
            stats = get_codebase_stats()
            return format_codebase_stats(stats)
        except Exception:
            return "Codebase statistics unavailable."
    return CANONICAL_ANSWERS.get(topic, None)
