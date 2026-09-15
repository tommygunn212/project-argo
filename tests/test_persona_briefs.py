"""Every personality is a different person, and none of them is a robot.

Personality used to be a VOICE_STYLE sentence folded into one generic
assistant prompt. These tests pin the replacement: one brief per persona
carrying voice AND collaboration style, assembled once with the product
contract, producing a genuinely different instruction set per persona - and
never instructing the run-ups or catchphrases Tommy banned.
"""

import pytest

from core import persona_briefs as P


# --- the set -----------------------------------------------------------------

def test_argo_is_the_default_and_first():
    assert P.DEFAULT_PERSONA == "argo"
    assert P.SELECTABLE[0] == "argo"
    assert P.selectable()[0]["name"] == "argo"


def test_every_selectable_persona_has_both_halves_and_a_description():
    for name in P.SELECTABLE:
        b = P.get(name)
        assert b is not None, name
        assert len(b.voice) > 80, f"{name}: voice brief too thin to steer a model"
        assert len(b.collaboration) > 80, f"{name}: no collaboration style"
        assert b.description and b.description[0].isupper(), f"{name}: needs a plain-English description"


def test_argo_reads_as_a_collaborator_not_an_assistant():
    b = P.get("argo")
    text = (b.voice + " " + b.collaboration).lower()
    # Directives, not adjectives: each of these is a behaviour you could check
    # against a transcript.
    for must in ("friend", "contractions", "dry aside", "hole", "assumption", "one level deeper"):
        assert must in text, f"argo brief lost '{must}'"
    for never in ("chatbot", "helpful ai"):
        assert never not in text
    assert "not a service desk" in text


# --- assembly ------------------------------------------------------------------------

def test_each_persona_produces_a_distinct_instruction_set():
    fingerprints = {P.instruction_fingerprint(P.compose_instructions(n)) for n in P.SELECTABLE}
    assert len(fingerprints) == len(P.SELECTABLE)


def test_the_contract_leads_and_the_persona_follows():
    text = P.compose_instructions("jarvis")
    assert text.startswith(P.CONVERSATION_CONTRACT)
    assert P.get("jarvis").block in text
    assert text.index(P.CONVERSATION_CONTRACT) < text.index(P.get("jarvis").block)


def test_nothing_else_is_stacked_on_top():
    """Contract + persona + deep-think policy + tool policy. Four parts, no more."""
    text = P.compose_instructions("argo")
    # Checked by reconstruction rather than by counting blank lines: the
    # contract has paragraphs of its own now.
    expected = "\n\n".join([P.CONVERSATION_CONTRACT, P.get("argo").block,
                             P.DEEP_THINK_POLICY, P.TOOL_POLICY])
    assert text == expected
    assert "get_pc_specs" not in text and "list_folder" not in text, "tool manual leaked into the brief"


def test_unknown_persona_adds_no_manner():
    text = P.compose_instructions("nope")
    assert "Voice and manner:" not in text
    assert text.startswith(P.CONVERSATION_CONTRACT)


def test_fingerprint_is_stable_and_versioned():
    a = P.instruction_fingerprint(P.compose_instructions("argo"))
    b = P.instruction_fingerprint(P.compose_instructions("argo"))
    assert a == b and a.startswith(P.INSTRUCTIONS_VERSION + "-")


# --- what no persona may ask for -----------------------------------------------------

@pytest.mark.parametrize("name", P.SELECTABLE)
def test_no_persona_instructs_a_banned_runup_or_catchphrase(name):
    assert P.find_banned(P.compose_instructions(name)) == []


@pytest.mark.parametrize("name", P.SELECTABLE)
def test_no_persona_brief_carries_a_catchphrase(name):
    b = P.get(name)
    assert P.find_banned(b.voice + " " + b.collaboration) == []


def test_the_hardest_rules_come_first():
    """Realtime models weight the top of the instruction, and the first
    version buried the prohibitions ~2000 characters in - where the model
    ignored them. The first-sentence rule and the silence rule lead now."""
    assert "THE FIRST THING YOU SAY IS THE ANSWER" in P.CONVERSATION_CONTRACT[:700]
    assert "SAY NOTHING AT ALL" in P.CONVERSATION_CONTRACT[:1500]


def test_briefs_are_written_as_directives_not_descriptions():
    """The failure this rewrite fixes: trait adjectives do not steer a
    realtime model. Every brief must tell it what to DO."""
    for name in P.SELECTABLE:
        b = P.get(name)
        text = (b.voice + " " + b.collaboration).lower()
        assert any(v in text for v in ("say", "open with", "answer", "ask", "keep", "never", "do not", "volunteer")), name


def test_the_contract_bans_the_runups_the_first_mic_run_produced():
    c = P.CONVERSATION_CONTRACT.lower()
    for phrase in ("let me lay this out", "okay, let me think", "repeating his question back",
                   "narrating what you are about to do"):
        assert phrase in c
    assert "say nothing at all" in c                        # floor-holding phrases
    assert "twenty seconds" in c and "not a cut-off" in c   # target, not truncation


def test_find_banned_exempts_prohibitions_only():
    assert P.find_banned("Never say 'great question'.") == []
    assert P.find_banned("Open with: great question!") == ["great question"]


# --- deep think keeps the same person ---------------------------------------------------

def test_deep_think_prompt_carries_the_selected_persona():
    for name in P.SELECTABLE:
        prompt = P.deep_think_system_prompt(name)
        assert prompt.startswith(P.DEEP_THINK_CONTRACT)
        assert P.get(name).block in prompt


def test_deep_think_prompts_differ_by_persona_and_are_speakable():
    prompts = {P.deep_think_system_prompt(n) for n in P.SELECTABLE}
    assert len(prompts) == len(P.SELECTABLE)
    c = P.DEEP_THINK_CONTRACT.lower()
    assert "read aloud" in c and "no bullets" in c and "no markdown" in c
    assert "the first sentence is already the answer" in c
