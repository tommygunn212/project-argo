"""
Base persona interface and response type definitions.

NO IMPORTS FROM:
- pipeline
- coordinator
- intent parser
- confidence logic
- audio
- memory
"""

from enum import Enum
from typing import Dict, Optional, Type
import logging

logger = logging.getLogger("ARGO.Personas")


class ResponseType(Enum):
    """
    Every response MUST declare one of these types.
    No default fallbacks.
    """
    SYSTEM = "system"           # Identity, governance, errors
    COMMAND_ACK = "command_ack" # "Done.", "Playing.", "Stopped."
    CLARIFICATION = "clarification"  # "Could you clarify...?"
    ANSWER = "answer"           # LLM-generated answers to questions


class PersonaBase:
    """
    Base class for all personas.
    
    Personas are text transformers ONLY.
    They receive text and response_type, return transformed text.
    """
    
    name: str = "base"
    
    # Allowance matrix - which response types this persona can handle
    # Override in subclasses
    ALLOWED_TYPES: set = set()
    
    @classmethod
    def is_allowed(cls, response_type: ResponseType) -> bool:
        """Check if this persona is allowed for the given response type."""
        return response_type in cls.ALLOWED_TYPES
    
    @classmethod
    def apply(cls, text: str, response_type: ResponseType) -> str:
        """
        Transform text according to persona rules.
        
        Args:
            text: The response text to transform
            response_type: The type of response (SYSTEM, COMMAND_ACK, etc.)
            
        Returns:
            Transformed text, or original if persona not allowed for this type
        """
        if not cls.is_allowed(response_type):
            logger.debug(f"[PERSONA] {cls.name} not allowed for {response_type.value}, returning unchanged")
            return text
        return cls._transform(text, response_type)
    
    @classmethod
    def _transform(cls, text: str, response_type: ResponseType) -> str:
        """Override in subclasses to implement transformation."""
        return text


# Registry of available personas
PERSONA_REGISTRY: Dict[str, Type[PersonaBase]] = {}


def register_persona(cls: Type[PersonaBase]) -> Type[PersonaBase]:
    """Decorator to register a persona class."""
    PERSONA_REGISTRY[cls.name] = cls
    return cls


def get_persona(name: str) -> Optional[Type[PersonaBase]]:
    """Get a persona class by name."""
    return PERSONA_REGISTRY.get(name)


def apply_persona(text: str, response_type: ResponseType, persona_name: str) -> str:
    """
    Apply a persona transformation to text.
    
    This is the SINGLE entry point for all persona formatting.
    No bypass paths. No exceptions.
    
    Args:
        text: The response text
        response_type: The type of response
        persona_name: Name of the persona to apply
        
    Returns:
        Transformed text
    """
    persona = get_persona(persona_name)
    if persona is None:
        logger.warning(f"[PERSONA] Unknown persona '{persona_name}', using neutral")
        persona = get_persona("neutral")
    
    if persona is None:
        # Fallback if even neutral isn't registered
        return text
    
    return persona.apply(text, response_type)
