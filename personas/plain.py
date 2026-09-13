"""
Plain persona - minimal, factual, no personality.

ALLOWED: ALL response types
"""

from .base import PersonaBase, ResponseType, register_persona


@register_persona
class PlainPersona(PersonaBase):
    """
    Plain - just facts, no personality.
    """
    
    name = "plain"

    VOICE_STYLE = (
        "Flat and factual. No colour, no warmth, no hedging, no personality of "
        "any kind. Answer the question and stop talking."
    )
    
    ALLOWED_TYPES = {
        ResponseType.SYSTEM,
        ResponseType.COMMAND_ACK,
        ResponseType.CLARIFICATION,
        ResponseType.ANSWER,
    }
    
    @classmethod
    def _transform(cls, text: str, response_type: ResponseType) -> str:
        """No transformation for plain."""
        return text
