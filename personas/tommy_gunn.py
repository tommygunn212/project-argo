"""
Tommy Gunn persona (ARGO's default voice).

Rules:
- Dry, smart, amused
- Sharp, well-read adult tone
- Calm confidence
- One dry jab max
- No greetings
- No corporate filler

ALLOWED: COMMAND_ACK, ANSWER
DISALLOWED: SYSTEM, CLARIFICATION
"""

from .base import PersonaBase, ResponseType, register_persona


@register_persona
class TommyGunnPersona(PersonaBase):
    """
    Tommy Gunn - ARGO's signature voice.
    
    Dry, observational, confident.
    """
    
    name = "tommy_gunn"
    
    ALLOWED_TYPES = {
        ResponseType.COMMAND_ACK,
        ResponseType.ANSWER,
    }
    
    @classmethod
    def _transform(cls, text: str, response_type: ResponseType) -> str:
        """
        Apply Tommy Gunn's tone.
        
        Main personality comes from LLM prompt.
        Post-processing removes unwanted artifacts.
        """
        if not text:
            return text
        
        # Remove common AI-isms that slip through
        removals = [
            "As an AI,",
            "As an AI ",
            "I'd be happy to",
            "I'm happy to",
            "Great question!",
            "That's a great question",
        ]
        
        for r in removals:
            if text.startswith(r):
                text = text[len(r):].lstrip(" ,")
        
        return text
