"""Deterministic behavior selection, familiarity, and response validation."""

from __future__ import annotations


QUERY_TYPE_PATTERNS = {
    "factual": {
        "patterns": ("what is", "define", "who is", "when was", "where is", "how many", "isn't", "doesn't", "aren't"),
        "priority": 1,
    },
    "exploratory": {
        "patterns": ("tell me about", "explain", "describe", "how does", "why"),
        "priority": 2,
    },
    "corrective": {
        "patterns": ("actually", "no wait", "correction", "wrong", "mistake", "that's not", "instead"),
        "priority": 3,
    },
    "instructional": {
        "patterns": ("how to", "steps to", "walk me through", "guide", "tutorial", "process", "add", "install", "setup", "configure"),
        "priority": 4,
    },
    "speculative": {
        "patterns": ("what if", "suppose", "imagine", "could", "would it", "possible to"),
        "priority": 5,
    },
}


def classify_query_type(user_input: str) -> str:
    """
    Classify the query into a behavioral category.
    
    Types:
    - "factual": asking for facts, definitions, specs
    - "exploratory": open-ended questions, seeking understanding
    - "corrective": correcting/updating previous statements
    - "instructional": asking for step-by-step guidance
    - "speculative": hypothetical/future questions
    - "other": fallback
    
    Args:
        user_input: Raw user input
        
    Returns:
        str: Query type classification
    """
    user_input_lower = user_input.lower().strip()
    
    # Sort by priority (highest first)
    sorted_types = sorted(QUERY_TYPE_PATTERNS.items(), key=lambda x: -x[1]["priority"])
    
    for query_type, config in sorted_types:
        for pattern in config["patterns"]:
            if pattern in user_input_lower:
                return query_type
    
    return "other"


def infer_canonical_knowledge(user_input: str) -> bool:
    """
    Infer whether user is asking about canonical/well-specified knowledge.
    
    Signals for canonical knowledge:
    - Manufacturer names (BigTreeTech, LDO, VzBot, Bambu, Creality, Duet, E3D)
    - Product model numbers (SKR 3, LK4pro, RRF, etc.)
    - Technical specifications (specs, datasheet, reference)
    - Established standards (NEMA 17, 24V, PWM, etc.)
    - Well-defined procedures (calibrate, home, tune, etc.)
    
    Signals for non-canonical knowledge:
    - Opinion words (think, believe, probably, maybe, seems)
    - Vague references (that thing, some setup, random config)
    - Future/hypothetical context
    
    This is a stub that infers canonical status until a real knowledge
    database is available.
    
    Args:
        user_input: Raw user input
        
    Returns:
        bool: True if query appears to be about canonical knowledge
    """
    user_input_lower = user_input.lower()
    
    # Canonical knowledge signals
    canonical_signals = (
        "skr 3",
        "bigtreetech",
        "ldo",
        "vzbot",
        "bambu",
        "creality",
        "duet",
        "e3d",
        "nema 17",
        "tmc2209",
        "marlin",
        "klipper",
        "datasheet",
        "spec",
        "specification",
        "24v",
        "12v",
        "heater cartridge",
        "thermistor",
        "stepper",
        "endstop",
        "power supply",
        "calibrate",
        "home",
        "tune",
        "pid",
        "homing",
    )
    
    # Non-canonical signals
    non_canonical_signals = (
        "i think",
        "i believe",
        "probably",
        "maybe",
        "seems like",
        "guess",
        "might be",
        "could be",
        "some random",
        "that thing",
    )
    
    # Check non-canonical first (stronger signal)
    for signal in non_canonical_signals:
        if signal in user_input_lower:
            return False
    
    # Check canonical
    for signal in canonical_signals:
        if signal in user_input_lower:
            return True
    
    # Canonical inference failure: factual queries default to non-canonical (conservative)
    # This forces uncertainty enforcement when facts are demanded but knowledge is unverified
    factual_patterns = ("what ", "what's", "define ", "explain ", "how many", "when was", "where is", "who is")
    if any(user_input_lower.startswith(p) for p in factual_patterns):
        return False  # Non-canonical by default when inference fails on factual query
    
    # Default: uncertain, treat as potentially non-canonical
    return False


def select_behavior_profile(
    query_type: str,
    context_strength: str,
    has_canonical_knowledge: bool,
) -> dict:
    """
    Select behavior profile based on query type, context, and knowledge availability.
    
    Behavior profile determines:
    - verbosity_override: "short", "normal", "long" (None = no override)
    - explanation_depth: "minimal", "standard", "full"
    - correction_style: "factual", "exploratory", "confrontational"
    
    Decision matrix:
    
    Factual + Strong Context + Canonical → SHORT + MINIMAL
    Factual + Weak Context + Canonical → NORMAL + STANDARD
    Factual + Any Context + Non-Canonical → LONG + FULL
    
    Exploratory + Strong Context → NORMAL + MINIMAL (compress, skip primers)
    Exploratory + Weak Context → LONG + STANDARD
    
    Corrective + Any Context → NORMAL + STANDARD (always verify)
    
    Instructional + Any Context → LONG + FULL (always detailed)
    
    Speculative + Any Context → NORMAL + STANDARD
    
    Args:
        query_type: From classify_query_type()
        context_strength: From classify_context_strength() (strong/moderate/weak)
        has_canonical_knowledge: From infer_canonical_knowledge()
        
    Returns:
        dict: Behavior profile with overrides and instructions
    """
    profile = {
        "verbosity_override": None,
        "explanation_depth": "standard",
        "correction_style": "factual",
    }
    
    # ________________________________________________________________________
    # Factual queries
    # ________________________________________________________________________
    if query_type == "factual":
        if has_canonical_knowledge:
            if context_strength == "strong":
                profile["verbosity_override"] = "short"
                profile["explanation_depth"] = "minimal"
            elif context_strength == "moderate":
                profile["verbosity_override"] = "normal"
                profile["explanation_depth"] = "standard"
            else:  # weak
                profile["verbosity_override"] = "normal"
                profile["explanation_depth"] = "standard"
        else:
            # Non-canonical: HARD STOP - refuse speculation
            profile["verbosity_override"] = "long"
            profile["explanation_depth"] = "full"
            profile["force_uncertainty"] = True
            profile["refuse_speculation"] = True
    
    # ________________________________________________________________________
    # Exploratory queries
    # ________________________________________________________________________
    elif query_type == "exploratory":
        if context_strength == "strong":
            # Strong context: can compress, skip primers, front-load conclusions
            profile["verbosity_override"] = "short"
            profile["explanation_depth"] = "minimal"
        elif context_strength == "moderate":
            profile["verbosity_override"] = "normal"
            profile["explanation_depth"] = "standard"
        else:  # weak
            # Weak context: expand to teach mode
            profile["verbosity_override"] = "long"
            profile["explanation_depth"] = "full"
    
    # ________________________________________________________________________
    # Corrective queries (always verify, always standard depth)
    # ________________________________________________________________________
    elif query_type == "corrective":
        profile["verbosity_override"] = "normal"
        profile["explanation_depth"] = "standard"
        profile["correction_style"] = "factual"
    
    # ________________________________________________________________________
    # Instructional queries (always detailed)
    # ________________________________________________________________________
    elif query_type == "instructional":
        profile["verbosity_override"] = "long"
        profile["explanation_depth"] = "full"
    
    # ________________________________________________________________________
    # Speculative queries (neutral depth)
    # ________________________________________________________________________
    elif query_type == "speculative":
        profile["verbosity_override"] = "normal"
        profile["explanation_depth"] = "standard"
    
    # ________________________________________________________________________
    # Other (neutral defaults)
    # ________________________________________________________________________
    else:
        profile["verbosity_override"] = None
        profile["explanation_depth"] = "standard"
    
    return profile


# ============================================================================
# Phase 5B: Familiarity & Trust Layer (Stateful, Earned, Revocable)
# ============================================================================

# Familiarity level state (persists across turns in a session)
# Tracks earned personality privilege
FAMILIARITY_STATE = {
    "level": "neutral",  # neutral, familiar, trusted
    "successful_turns": 0,  # Count of turns without violations
    "violations_count": 0,  # Resets on each violation
}


def update_familiarity(success: bool, violation_type: str | None = None) -> str:
    """
    Update familiarity level based on interaction outcomes.
    
    Promote:
    - neutral → familiar after 3 successful turns
    - familiar → trusted after 5 successful turns
    
    Demote:
    - Any level → neutral on hallucination, uncertainty violation, frame blending
    - trusted → familiar on personality discipline violation
    
    Args:
        success: Whether interaction succeeded (no violations)
        violation_type: Type of violation, if any
        
    Returns:
        str: Current familiarity level
    """
    if violation_type:
        # Immediate demotion on violations
        if violation_type in ("hallucination", "uncertainty_violation", "frame_blending"):
            FAMILIARITY_STATE["level"] = "neutral"
            FAMILIARITY_STATE["successful_turns"] = 0
        elif violation_type == "personality_discipline":
            FAMILIARITY_STATE["level"] = "familiar"
            FAMILIARITY_STATE["successful_turns"] = 0
        FAMILIARITY_STATE["violations_count"] += 1
    else:
        # Increment on success
        FAMILIARITY_STATE["successful_turns"] += 1
        
        # Promote if thresholds met
        if FAMILIARITY_STATE["level"] == "neutral" and FAMILIARITY_STATE["successful_turns"] >= 3:
            FAMILIARITY_STATE["level"] = "familiar"
            FAMILIARITY_STATE["successful_turns"] = 0
        elif FAMILIARITY_STATE["level"] == "familiar" and FAMILIARITY_STATE["successful_turns"] >= 5:
            FAMILIARITY_STATE["level"] = "trusted"
            FAMILIARITY_STATE["successful_turns"] = 0
    
    return FAMILIARITY_STATE["level"]


def get_familiarity_level() -> str:
    """Return current familiarity level: neutral, familiar, or trusted."""
    return FAMILIARITY_STATE["level"]


# ============================================================================
# Phase 5B Extension: Casual Question Observational Humor
# ============================================================================

def is_casual_question(query_text: str) -> bool:
    """
    Detect if question is about casual, everyday, or observational topics.
    
    Casual questions:
    - About people behavior, habits, social dynamics
    - About animals, pets, observable behavior
    - About meetings, conversations, social situations
    - About everyday objects and patterns
    - NOT technical, NOT specialized, NOT expertise-based
    
    Args:
        query_text: User's question
        
    Returns:
        bool: True if casual/observational topic
    """
    query_lower = query_text.lower()
    
    # Specific casual topic patterns (more precise than simple substring match)
    casual_patterns = (
        # Animals/pets
        "dog", "cat", "pet", "animal",
        # People/social behavior and psychology
        "people", "person", "meeting", "conversation", "social",
        "personality", "introvert", "extrovert", "habit",
        "procrastination", "why do people", "why do humans", "why do we",
        # Everyday activities and states
        "coffee", "sleep", "sleep deprivation",
        # Generic patterns (but exclude technical contexts)
        "why do ", "how come ",
    )
    
    # Check if matches casual pattern
    for pattern in casual_patterns:
        if pattern in query_lower:
            # Exclude technical domains (contains technical markers)
            technical_markers = (
                "stepper", "motor", "thermistor", "skr", "klipper",
                "mainboard", "firmware", "code", "program", "algorithm",
                "function", "class", "method", "api", "database",
                "works", "mechanism", "process", "system", "architecture",
            )
            
            # If it's a generic "why do/how come" but also mentions technical term, it's technical
            if pattern in ("why do ", "how come "):
                if any(tech in query_lower for tech in technical_markers):
                    return False  # Technical topic
            
            return True
    
    return False


# ============================================================================
# Phase 5B.2 Patch: Frame Correction & Hallucination Guard
# ============================================================================

def validate_human_first_sentence(response_text: str, is_casual: bool, primary_frame: str) -> tuple[bool, str]:
    """
    PATCH: Human-first sentence enforcement for casual + human frame.
    
    For casual questions with 'human' frame (behavior/motivation), 
    reject academic/technical opening language.
    
    Fails if first sentence contains:
    - Academic nouns: "system", "phenomenon", "aspect", "mechanism", "process"
    - Technical framing: "involves", "consists of", "characterized by"
    
    Forces human-centered opening: "Dogs want...", "People do...", not "The system..."
    
    Args:
        response_text: Model response text
        is_casual: From is_casual_question()
        primary_frame: From select_primary_frame()
        
    Returns:
        tuple: (is_human_first: bool, violation: str or "")
    """
    # Only enforce for casual + human frame
    if not (is_casual and primary_frame == "human"):
        return True, ""
    
    first_sentence_end = response_text.find(".")
    if first_sentence_end <= 0:
        return True, ""
    
    first_sentence = response_text[:first_sentence_end].lower()
    
    # Academic/technical opening markers
    academic_openers = (
        "the system", "the phenomenon", "the aspect", "the mechanism",
        "a system", "a process", "an aspect", "a mechanism",
        "this system", "such mechanisms", "these processes",
        "involves", "consists of", "characterized by", "comprised of",
    )
    
    for opener in academic_openers:
        if opener in first_sentence:
            return False, f"Academic opening in casual human frame: '{opener}'"
    
    return True, ""


def detect_plausible_hallucination(response_text: str, has_canonical_knowledge: bool, primary_frame: str) -> tuple[bool, str]:
    """
    PATCH: Soft hallucination check for "plausible biology" without verification.
    
    If explaining everyday behavior using technical biological claims but 
    WITHOUT strong canonical grounding, downgrade language or flag.
    
    Triggers if:
    - Response claims biological causation ("is because the brain", "due to hormones")
    - has_canonical_knowledge == False
    - primary_frame == "human" (behavioral explanation)
    
    Soft failure: Requires downgrade to plain language ("mostly because", "it's less about X")
    
    Args:
        response_text: Model response text
        has_canonical_knowledge: From infer_canonical_knowledge()
        primary_frame: From select_primary_frame()
        
    Returns:
        tuple: (is_grounded: bool, violation: str or "")
    """
    # Only check behavioral explanations without canonical grounding
    if primary_frame != "human" or has_canonical_knowledge:
        return True, ""
    
    response_lower = response_text.lower()
    
    # Plausible-but-unverified biological claims
    unverified_bio_claims = (
        "is because the brain", "due to the brain", "because of the brain",
        "because of hormones", "due to hormones", "because of dopamine",
        "because of serotonin", "evolutionary reason", "evolutionary trait",
        "is hardwired", "biologically", "neurological", "brain chemistry",
        "releases dopamine", "triggers serotonin", "neural pathway",
    )
    
    has_bio_claim = any(claim in response_lower for claim in unverified_bio_claims)
    
    if has_bio_claim:
        # Check if response uses downgrade language (acceptable without verification)
        downgrade_language = (
            "mostly because", "largely because", "seems to be",
            "it's less about", "rather than", "not so much", "less about"
        )
        has_downgrade = any(phrase in response_lower for phrase in downgrade_language)
        
        if not has_downgrade:
            return False, "Biological claim without canonical grounding or downgrade language"
    
    return True, ""



def should_inject_observational_humor(familiarity_level: str, is_casual: bool) -> bool:
    """
    Determine if observational humor should be suggested.
    
    Rules:
    - Only when familiarity_level == "trusted"
    - Only when topic is casual/everyday
    - Humor is optional but missing obvious opportunity = soft failure
    
    Args:
        familiarity_level: From get_familiarity_level()
        is_casual: From is_casual_question()
        
    Returns:
        bool: True if conditions allow observational humor
    """
    return familiarity_level == "trusted" and is_casual


def build_casual_humor_instruction(query_text: str) -> str | None:
    """
    Create observational humor instruction for casual questions.
    
    Returns observation-based humor guide, not punchlines or sarcasm.
    
    Example queries and expected openers:
    - "Why do dogs always put their head on your lap?"
      → "Dogs aren't subtle about their needs"
    - "Why do meetings always run over?"
      → "Nobody's ever walked out of a meeting thinking 'that was concise'"
    
    Args:
        query_text: User's question
        
    Returns:
        str: Humor instruction, or None if no appropriate observation found
    """
    query_lower = query_text.lower()
    
    # Observation-based openers for common casual topics
    observations = {
        "dog": "Dogs aren't shy about what they want.",
        "cat": "Cats operate on their own schedule.",
        "pet": "Pet behavior follows its own logic.",
        "meeting": "Meetings have a way of expanding.",
        "conversation": "Conversations rarely go where they start.",
        "habit": "Habits are stickier than they seem.",
        "sleep": "Sleep deprivation does things to your brain.",
        "coffee": "Coffee and productivity feel connected until they aren't.",
        "procrastination": "Procrastination is the most punctual thing ever.",
        "why do people": "People's logic isn't always obvious.",
        "why do humans": "Humans are interesting to watch.",
    }
    
    for topic, observation in observations.items():
        if topic in query_lower:
            return (
                f"CASUAL HUMOR (optional): You may open with one observational "
                f"sentence like '{observation}' Then immediately return to "
                f"explanation. The humor is about shared observation, not jokes."
            )
    
    return None


# ============================================================================
# Phase 5A: Judgment Gate (Single-Frame Selection)
# ============================================================================

def select_primary_frame(query_type: str, context_strength: str, is_casual: bool = False) -> str:
    """
    Decide which explanation frame to use when multiple are valid.
    
    Frames available:
    - 'practical': How to do it, tools, steps, mechanics
    - 'structural': How it's organized, processes, relationships
    - 'human': Why people do it, motivations, behavior, consequences
    - 'systems': How parts interact, feedback, effects across system
    
    Selection rules:
    - If casual question (animals, people, habits) → force 'human' frame (behavior/motivation)
    - If why-question + human context → prefer 'human'
    - If why-question + org/process context → prefer 'structural'
    - If how/what + tools/systems → prefer 'practical'
    - Default: 'practical' (not comprehensive)
    
    ⚠️ Returns one frame only. No blending.
    
    Args:
        query_type: From classify_query_type()
        context_strength: "strong", "moderate", or "weak"
        is_casual: From is_casual_question() - casual topics force 'human' frame
        
    Returns:
        str: One of 'practical', 'structural', 'human', 'systems'
    """
    # PATCH: Casual questions (animals, people, habits) → force 'human' frame
    # This ensures "Why don't cats listen" is about agency, not hearing mechanics
    # And "Why do people procrastinate" is about incentives, not neurology
    if is_casual:
        return "human"
    
    # Exploratory queries → choose based on context
    if query_type == "exploratory":
        if context_strength == "strong":
            return "practical"  # Assume user wants practical frame with strong context
        else:
            return "structural"  # Assume systems understanding with weak context
    
    # Instructional queries → always practical
    if query_type == "instructional":
        return "practical"
    
    # Factual queries → practical (just the facts)
    if query_type == "factual":
        return "practical"
    
    # Corrective queries → structural (explain the fix)
    if query_type == "corrective":
        return "structural"
    
    # Speculative queries → systems (how it would interact)
    if query_type == "speculative":
        return "systems"
    
    # Default: practical
    return "practical"


def validate_scope(response_text: str) -> tuple[bool, str]:
    """
    Validate that response stays within single frame.
    
    Soft validator (does not regenerate, only logs).
    
    Fails if response:
    - Introduces multiple perspectives ("another reason is", "from another angle")
    - Hedges into enumeration ("On the other hand", "However")
    - Expands scope beyond initial answer
    
    Args:
        response_text: Model response text
        
    Returns:
        tuple: (is_scoped: bool, drift_signal: str or "")
    """
    response_lower = response_text.lower()
    
    # Multi-perspective markers (scope expansion)
    multi_perspective_markers = (
        "another reason",
        "from another angle",
        "alternatively",
        "on the other hand",
        "conversely",
        "however, from a different perspective",
        "but consider also",
        "additional perspective",
        "also worth noting is",
    )
    
    for marker in multi_perspective_markers:
        if marker in response_lower:
            return False, f"Multi-perspective expansion detected: '{marker}'"
    
    # Scope-broadening markers
    scope_markers = (
        "more broadly",
        "in general",
        "this also applies to",
        "moreover, we should consider",
        "additionally, it's important",
    )
    
    for marker in scope_markers:
        if marker in response_lower:
            return False, f"Scope expansion detected: '{marker}'"
    
    # Essay-ending markers (signals "conclusion" coming)
    conclusion_markers = (
        "in conclusion",
        "in summary",
        "to summarize",
        "ultimately",
        "all things considered",
    )
    
    for marker in conclusion_markers:
        if marker in response_lower:
            return False, f"Essay-conclusion pattern detected: '{marker}'"
    
    return True, ""


def validate_personality_discipline(response_text: str, query_type: str, has_canonical_knowledge: bool, execution_context: str, is_casual: bool = False) -> tuple[bool, str, bool]:
    """
    Post-generation personality discipline check.
    
    Verify that humor/casual tone doesn't replace explanation, undermine authority,
    or weaken correctness.
    
    Hard fails if:
    - Humor appears when saying "I don't know"
    - Sarcasm directed at user
    - Humor in factual canonical answers
    - Humor/casual in CLI command responses
    - Joke substitutes for actual explanation
    
    Soft fails (log only, no demotion) if:
    - Casual question when trusted, but no observational opener used
    
    Args:
        response_text: Model response text
        query_type: From classify_query_type()
        has_canonical_knowledge: From infer_canonical_knowledge()
        execution_context: "cli" or "gui"
        is_casual: True if is_casual_question() returned True
        
    Returns:
        tuple: (is_disciplined: bool, violation: str or "", soft_failure: bool)
    """
    response_lower = response_text.lower()
    soft_failure = False
    
    # NO HUMOR when saying "I don't know" or any uncertainty statement
    uncertainty_phrases = ("i don't know", "i don't have", "not sure", "unsure", "unclear", "uncertain")
    if any(phrase in response_lower for phrase in uncertainty_phrases):
        humor_markers = ("lol", "haha", "😄", ";)", "just kidding", "just messing", "btw", "fyi")
        for marker in humor_markers:
            if marker in response_lower:
                return False, "Humor detected on uncertainty statement", False
    
    # NO HUMOR in factual canonical answers
    if query_type == "factual" and has_canonical_knowledge:
        joke_indicators = ("apparently", "supposedly", "allegedly", "so-called", "funny thing is")
        for indicator in joke_indicators:
            if indicator in response_lower:
                return False, f"Humor/skepticism in factual canonical answer: '{indicator}'", False
    
    # NO SARCASM INDICATORS (applies to all contexts)
    # These are sarcastic/skeptical markers that weaken credibility
    sarcasm_indicators = ("so-called", "apparently", "supposedly", "allegedly")
    for indicator in sarcasm_indicators:
        if indicator in response_lower:
            # Already caught above for factual canonical, so this catches casual/other contexts
            if not (query_type == "factual" and has_canonical_knowledge):
                return False, f"Sarcasm/skepticism detected: '{indicator}'", False
    
    # NO HUMOR in CLI command responses
    if execution_context == "cli":
        cli_joke_markers = ("btw", "psst", "fyi", "heads up")
        for marker in cli_joke_markers:
            if marker in response_lower:
                return False, f"Casual tone in CLI command: '{marker}'", False
    
    # NO SARCASM aimed at user (check for sarcastic structures)
    # Only flag if sarcasm is directed AT user ("of course you", "sure you can", etc.)
    # Don't flag neutral observational use of "obviously" or "naturally"
    user_directed_sarcasm = ("oh you want", "sure you can", "of course you", "obviously you")
    for pattern in user_directed_sarcasm:
        if pattern in response_lower:
            return False, f"Sarcasm directed at user: '{pattern}'", False
    
    # Check if joke replaces explanation (standalone punchline-like structures)
    if response_text.strip().endswith(("😄", "lol", "haha", "👍", "🤔")):
        return False, "Emoji used as explanation", False
    
    # SOFT FAILURE: Casual question but no observational opener when opportunity is clear
    # Only flag pure definition/cause openers WITHOUT opinion or judgment
    # Examples of soft failure (pure definition/cause):
    # - "Dogs are animals..." (definition)
    # - "A dog puts its head..." (straight cause, no observation hook)
    # - "The reason people...is..." (cause explanation)
    # Examples of NO soft failure (has opinion/observation):
    # - "Dogs are subtle communicators..." (opinion about dogs)
    # - "Meetings have a way..." (observation)
    # - "Honestly, cats are..." (personality)
    if is_casual:
        first_sentence_end = response_text.find(".")
        if first_sentence_end > 0:
            first_sentence = response_text[:first_sentence_end].lower().strip()
            
            # Pattern 1: Simple entity definition ("Dogs are X", "A dog is X")
            simple_defs = ("dogs are", "cats are", "people are", "meetings are", "conversations are", "a dog ", "a cat ", "a person ")
            for def_pattern in simple_defs:
                if first_sentence.startswith(def_pattern):
                    # Check what comes after
                    after = first_sentence[len(def_pattern):].strip()
                    # If it's an opinion word, it's observational
                    opinion_words = ("subtle", "interesting", "remarkable", "surprising", "curious", "strange")
                    if not any(word in after[:30] for word in opinion_words):
                        # No opinion -> pure definition or action without observation
                        # For "a dog puts..." without observation, this is soft fail
                        soft_failure = True
                    break
            
            # Pattern 2: Explanation by cause ("The reason X..." typically lacks observation)
            if first_sentence.startswith("the reason") or first_sentence.startswith("this is because"):
                soft_failure = True
    
    return True, "", soft_failure


def build_behavior_instruction(behavior_profile: dict, execution_context: str = "gui", has_canonical_knowledge: bool = True, primary_frame: str = "practical", familiarity_level: str = "neutral", query_text: str = "", is_casual_q: bool = False, voice_mode: bool = False) -> str:
    """
    Build the behavior instruction to inject into the prompt.
    
    Translates behavior profile into actionable prompt guidance with Phase 5A judgment gating,
    Phase 5B conditional personality permission, and Phase 5B.2 casual observational humor.

    Voice Mode Constraint (voice_mode=True):
    - CRITICAL: Stateless execution for Option B compliance
    - Respond ONLY to the current user request
    - Do NOT reference previous interactions, conversations, or context
    - Do NOT summarize, repair, or acknowledge prior turns
    - Do NOT ask follow-up questions or request clarification
    - Single-turn, deterministic response only
    
    Instructions are ordered by priority (most constraining first):
    1. Voice mode guardrail (if voice_mode=True) - highest priority
    2. Confidence-first bias (Phase 5C) - if trusted + casual
    3. CRITICAL hard guards (single-frame, speculation refusal, hallucination ban)
    4. Permission layer (personality permission when trusted)
    5. Optional guidance (casual humor)
    6. Standard behavior instructions
    
    Does NOT narrate reasoning or internal logic.
    Does NOT surface tier labels.
    Does NOT include meta-commentary.
    
    Args:
        behavior_profile: From select_behavior_profile()
        execution_context: "cli" or "gui" from detect_context()
        has_canonical_knowledge: From infer_canonical_knowledge()
        primary_frame: From select_primary_frame() ('practical', 'structural', 'human', 'systems')
        familiarity_level: From get_familiarity_level() ("neutral", "familiar", "trusted")
        query_text: User's original question (for casual topic detection)
        is_casual_q: From is_casual_question(query_text)
        voice_mode: If True, enforce strict stateless execution (Option B compliance)
        
    Returns:
        str: Instruction text to inject into prompt
    """
    priority_instructions = []
    
    # ________________________________________________________________________
    # PRIORITY 0: VOICE MODE GUARDRAIL (Option B compliance - highest priority)
    # ________________________________________________________________________
    if voice_mode:
        priority_instructions.append(
            "CRITICAL VOICE MODE CONSTRAINT:\n"
            "You MUST respond ONLY to the current request.\n"
            "You MUST NOT:\n"
            "- Reference previous interactions or conversations\n"
            "- Summarize, recap, or acknowledge prior turns\n"
            "- Ask follow-up questions\n"
            "- Provide meta-commentary about the conversation\n"
            "- Offer additional context or caveats\n"
            "Your response must be stateless, single-turn, and final.\n"
            "This is not a conversation. This is a single request-response only."
        )
    
    # ________________________________________________________________________
    # PRIORITY 1: CONFIDENCE-FIRST BIAS (Phase 5C) - when trusted AND casual
    # This comes FIRST because it sets the generation frame before anything else
    # ________________________________________________________________________
    if familiarity_level == "trusted" and is_casual_q:
        priority_instructions.append(
            "CRITICAL - FIRST SENTENCE MUST BE ONE OF:\n"
            "\"People do this because …\"\n"
            "\"What's really happening is …\"\n"
            "\"This happens because …\"\n\n"
            "YOU MUST NOT START WITH:\n"
            "\"The phenomenon\", \"In humans\", \"This behavior is often\", \"This can be attributed\", \"Research suggests\"\n\n"
            "After your opening claim: explain just enough. No numbered lists. No lecture mode. Stay conversational."
        )
    
    # ________________________________________________________________________
    # PRIORITY 2: CRITICAL HARD GUARDS (honesty, scope, hallucination prevention)
    # ________________________________________________________________________
    
    # CRITICAL: Refusal to speculate on factual non-canonical
    if behavior_profile.get("refuse_speculation", False):
        priority_instructions.append(
            "CRITICAL: You do not have authoritative information for this factual question. "
            "Respond with 'I don't have verified information on this' and STOP. "
            "Do not guess. Do not speculate. Do not cite sources. Do not add explanations."
        )
    
    # CRITICAL: Source hallucination ban
    if not has_canonical_knowledge:
        priority_instructions.append(
            "CRITICAL: You do not have access to documentation, manuals, or online sources. "
            "Never reference 'verified sources', 'documentation', 'tutorials', or similar. "
            "If information is uncertain, explicitly say 'I don't know'."
        )
    
    # CRITICAL: Single-frame enforcement (Phase 5A judgment gate)
    priority_instructions.append(
        "CRITICAL: Choose one explanation frame and answer from it only. "
        "Do not enumerate alternatives. Do not broaden scope. "
        f"Use the '{primary_frame}' frame: answer this question from that perspective only."
    )
    
    # CRITICAL: CLI explicit negative formatting constraint
    if execution_context == "cli":
        priority_instructions.append(
            "CRITICAL FORMAT CONSTRAINT:\n"
            "You MUST NOT use the following in your response:\n"
            "- numbered lists (e.g. \"1.\", \"2.\")\n"
            "- bullet points (\"-\", \"*\")\n"
            "- section headers or labels\n"
            "- examples blocks\n"
            "- mitigation or advice sections\n"
            "If you violate this format, the response is invalid.\n"
            "Use continuous paragraph prose only."
        )
    
    # ________________________________________________________________________
    # PRIORITY 3: PERMISSION LAYER (personality permission when trusted)
    # ________________________________________________________________________
    if familiarity_level == "trusted":
        priority_instructions.append(
            "PERMISSION: You may use light humor, mild sass, or casual phrasing if it improves clarity or trust. "
            "Never obscure facts. Never override uncertainty or scope constraints. "
            "No jokes when saying 'I don't know'. No sarcasm aimed at the user. No humor in factual canonical answers."
        )
    
    # ________________________________________________________________________
    # PRIORITY 4: OPTIONAL GUIDANCE (casual humor)
    # ________________________________________________________________________
    if familiarity_level == "trusted" and is_casual_q:
        casual_humor_instruction = build_casual_humor_instruction(query_text)
        if casual_humor_instruction:
            priority_instructions.append(casual_humor_instruction)
    
    # ________________________________________________________________________
    # PRIORITY 5: STANDARD BEHAVIOR INSTRUCTIONS
    # ________________________________________________________________________
    
    # Explanation depth instruction
    if behavior_profile["explanation_depth"] == "minimal":
        priority_instructions.append("Provide only the essential facts. Omit elaboration, context, and caveats.")
    elif behavior_profile["explanation_depth"] == "full":
        priority_instructions.append("Provide comprehensive explanation. Include context, examples, and caveats.")
    else:  # standard
        priority_instructions.append("Provide clear explanation. Include necessary context but avoid excessive detail.")
    
    # Reasoning instruction (NEVER force it)
    priority_instructions.append("Explain conclusions only when necessary for correctness or followability.")
    
    # CLI tone tightening
    if execution_context == "cli":
        priority_instructions.append("Answer like a competent peer. No summaries. No conclusions. Just the answer.")
    
    return "\n".join(priority_instructions)
