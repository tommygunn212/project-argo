"""
Claptrap persona.

Rules:
- Extremely enthusiastic
- Can answer questions with excitement
- Command acks are short (1-3 words)
- No long explanations in COMMAND_ACK

ALLOWED: COMMAND_ACK, ANSWER
DISALLOWED: SYSTEM, CLARIFICATION
"""

from .base import PersonaBase, ResponseType, register_persona


@register_persona
class ClaptrapPersona(PersonaBase):
    """
    Claptrap from Borderlands.
    
    Allowed for COMMAND_ACK (short) and ANSWER (enthusiastic).
    System and clarification stay neutral.
    """
    
    name = "claptrap"
    
    # Claptrap allowed for acks and answers
    ALLOWED_TYPES = {
        ResponseType.COMMAND_ACK,
        ResponseType.ANSWER,
    }
    
    # Short ack responses for commands
    SHORT_ACKS = [
        "Done!",
        "You got it!",
        "On it!",
        "Okay!",
    ]
    
    @classmethod
    def _transform(cls, text: str, response_type: ResponseType) -> str:
        """
        Apply Claptrap's enthusiasm.
        
        For COMMAND_ACK: Keep it short (1-3 words)
        For ANSWER: Let the LLM handle full enthusiasm
        """
        if not text:
            return text
        
        if response_type == ResponseType.COMMAND_ACK:
            # For command acks, keep it very short
            # The text should already be short, just ensure it
            words = text.split()
            if len(words) > 5:
                # Truncate long acks
                return "Done!"
            # Add excitement if not present
            if not text.endswith("!"):
                text = text.rstrip(".") + "!"
            return text
        
        # For ANSWER, the LLM prompt handles the personality
        # Light post-processing only
        return text
