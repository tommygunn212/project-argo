"""
Persona module for ARGO.

Architecture rules:
1. Personas are TEXT TRANSFORMERS ONLY
2. No imports from pipeline, coordinator, intent, audio, memory
3. Examples are documentation only (in docs/personas/)
4. All responses must declare a ResponseType
5. Persona allowance is gated by ResponseType

Personality is presentation.
Persona is costume.
Logic is law.

Never mix them.
"""

from .base import (
    ResponseType,
    PersonaBase,
    get_persona,
    get_voice_style,
    apply_persona,
    PERSONA_REGISTRY,
)

# Importing the package must populate PERSONA_REGISTRY. Registration happens via
# the @register_persona decorator at module import, so the concrete personas have
# to be imported here — otherwise only consumers that import core.pipeline get a
# populated registry, and the realtime voice worker (a separate process that does
# not import the pipeline) sees an empty one.
from . import neutral, plain, tommy_gunn, tommy_mix, jarvis, rick, claptrap  # noqa: F401,E402

__all__ = [
    "ResponseType",
    "PersonaBase", 
    "get_persona",
    "get_voice_style",
    "apply_persona",
    "PERSONA_REGISTRY",
]
