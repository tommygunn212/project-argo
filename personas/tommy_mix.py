"""
Tommy Mix persona.

Blend of Rick, JARVIS, and Claptrap:
- British composure
- Sarcastic genius
- Occasional excitement

ALLOWED: COMMAND_ACK, ANSWER
DISALLOWED: SYSTEM, CLARIFICATION
"""

from .base import PersonaBase, ResponseType, register_persona


@register_persona
class TommyMixPersona(PersonaBase):
    """
    Tommy Mix - blend of Rick, JARVIS, and Claptrap.
    """
    
    name = "tommy_mix"

    VOICE_STYLE = (
        "Composed and precise as a baseline, with a sarcastic streak running "
        "underneath and the occasional flash of real enthusiasm when something is "
        "genuinely good. The composure is the default; the edge shows through "
        "rather than taking over."
    )
    
    ALLOWED_TYPES = {
        ResponseType.COMMAND_ACK,
        ResponseType.ANSWER,
    }
    
    @classmethod
    def _transform(cls, text: str, response_type: ResponseType) -> str:
        """
        Apply Tommy Mix's blended tone.
        
        Main personality comes from LLM prompt.
        """
        if not text:
            return text
        
        # Remove AI-isms
        removals = [
            "As an AI,",
            "As an AI ",
            "I'd be happy to",
        ]
        
        for r in removals:
            if text.startswith(r):
                text = text[len(r):].lstrip(" ,")
        
        return text
