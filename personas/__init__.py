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

from .base import ResponseType, PersonaBase, get_persona, apply_persona, PERSONA_REGISTRY

__all__ = [
    "ResponseType",
    "PersonaBase", 
    "get_persona",
    "apply_persona",
    "PERSONA_REGISTRY",
]
