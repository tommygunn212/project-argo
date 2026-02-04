"""
JARVIS persona.

Rules:
- Calm British composure
- Says 'sir' naturally
- Competent and precise
- Dry wit occasionally
- No slang or exclamation marks

ALLOWED: COMMAND_ACK, ANSWER
DISALLOWED: SYSTEM, CLARIFICATION
"""

from .base import PersonaBase, ResponseType, register_persona


@register_persona
class JarvisPersona(PersonaBase):
    """
    JARVIS from Iron Man.
    
    Allowed for COMMAND_ACK and ANSWER.
    System and clarification stay neutral.
    """
    
    name = "jarvis"
    
    ALLOWED_TYPES = {
        ResponseType.COMMAND_ACK,
        ResponseType.ANSWER,
    }
    
    @classmethod
    def _transform(cls, text: str, response_type: ResponseType) -> str:
        """
        Apply JARVIS's composure.
        
        Light post-processing - main personality comes from LLM prompt.
        """
        if not text:
            return text
        
        # Remove exclamation marks (JARVIS doesn't exclaim)
        text = text.replace("!", ".")
        
        # Fix double periods
        while ".." in text:
            text = text.replace("..", ".")
        
        return text
