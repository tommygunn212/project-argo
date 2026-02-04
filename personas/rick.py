"""
Rick Sanchez persona.

Rules:
- Max ONE metaphor per response
- No sarcasm in explanations
- No jokes in SYSTEM or CLARIFICATION
- Must preserve factual clarity
- Length cap enforced

Rick is an overlay, not an author.

ALLOWED: ANSWER only
DISALLOWED: SYSTEM, COMMAND_ACK, CLARIFICATION
"""

from .base import PersonaBase, ResponseType, register_persona


@register_persona
class RickPersona(PersonaBase):
    """
    Rick Sanchez from Rick and Morty.
    
    Only applies to ANSWER responses.
    System, command, and clarification responses stay neutral.
    """
    
    name = "rick"
    
    # Rick only allowed for answers
    ALLOWED_TYPES = {
        ResponseType.ANSWER,
    }
    
    # Rick-isms to potentially inject (used sparingly)
    INTERJECTIONS = [
        "Look,",
        "Okay,",
        "Morty,",
    ]
    
    @classmethod
    def _transform(cls, text: str, response_type: ResponseType) -> str:
        """
        Apply Rick's tone to answer text.
        
        Rules:
        - Add one interjection at start if not already present
        - Keep factual content intact
        - No heavy transformation (Rick is overlay, not author)
        """
        if not text:
            return text
        
        # Don't double-apply if already has Rick-ism
        text_lower = text.lower()
        if any(text_lower.startswith(i.lower()) for i in cls.INTERJECTIONS):
            return text
        
        # Add light Rick flavor - just a starter
        # The LLM prompt should handle the main personality
        return text
