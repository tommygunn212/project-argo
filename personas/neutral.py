"""
Neutral persona - the default.

Allowed for ALL response types.
No transformation - returns text as-is.
"""

from .base import PersonaBase, ResponseType, register_persona


@register_persona
class NeutralPersona(PersonaBase):
    """
    Neutral persona - no transformation.
    
    This is the safe default that works for all response types.
    """
    
    name = "neutral"
    
    # Neutral is allowed everywhere
    ALLOWED_TYPES = {
        ResponseType.SYSTEM,
        ResponseType.COMMAND_ACK,
        ResponseType.CLARIFICATION,
        ResponseType.ANSWER,
    }
    
    @classmethod
    def _transform(cls, text: str, response_type: ResponseType) -> str:
        """No transformation for neutral."""
        return text
