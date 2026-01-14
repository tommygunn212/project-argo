"""
HAL Chat - Direct interface to Ollama's HAL model via REST API.

This module provides a simple HTTP-based chat interface to the HAL model
running in Ollama. Unlike the wrapper approach used for JARVIS, HAL Chat
uses Ollama's official chat completion API endpoint.

Key Features:
- Direct REST API calls to Ollama
- Support for system prompts and optional context
- JSON response handling
- Simple CLI interface for one-off interactions

Model: hal
Endpoint: http://localhost:11434/api/chat
Format: Application/JSON

Example:
    python hal_chat.py "What is your name?"
    python hal_chat.py "Say hello" --context "This is a test"
"""

import requests
import sys

# ============================================================================
# Configuration
# ============================================================================

OLLAMA_URL = "http://localhost:11434/api/chat"
"""Ollama REST API endpoint for chat completions."""

MODEL = "hal"
"""Name of the Ollama model to query."""


# ============================================================================
# Chat Function
# ============================================================================

def chat(user_message: str, context: str | None = None) -> str:
    """
    Send a message to the HAL model and return the response.
    
    Architecture:
    1. Build message array with system prompt and optional context
    2. Create JSON payload with model name and messages
    3. POST to Ollama's chat endpoint
    4. Parse JSON response and extract content
    
    Message Structure:
    - System: "You are called HAL." (identity constraint)
    - Optional System: Custom context (if provided)
    - User: User's actual message
    
    Args:
        user_message: The user's input text
        context: Optional system context (e.g., "You are in debug mode")
        
    Returns:
        str: The model's response text
        
    Raises:
        requests.exceptions.HTTPError: If Ollama returns an error status
        requests.exceptions.Timeout: If the request takes longer than 60 seconds
        KeyError: If Ollama response has unexpected structure
        
    Example:
        response = chat("Hello", context="You are helpful")
        print(response)
    """
    # ________________________________________________________________________
    # Build Message Array
    # ________________________________________________________________________
    
    messages = []

    # System: identity constraint
    # This ensures HAL knows its name and persona
    messages.append({
        "role": "system",
        "content": "You are called HAL."
    })

    # Optional: additional system context
    # Useful for setting mode, constraints, or background information
    if context:
        messages.append({
            "role": "system",
            "content": f"Context: {context}"
        })

    # User message
    messages.append({
        "role": "user",
        "content": user_message
    })

    # ________________________________________________________________________
    # Build Request Payload
    # ________________________________________________________________________
    
    payload = {
        "model": MODEL,
        "messages": messages,
        "stream": False  # Wait for complete response before returning
    }

    # ________________________________________________________________________
    # Execute API Call
    # ________________________________________________________________________
    
    response = requests.post(OLLAMA_URL, json=payload, timeout=60)
    response.raise_for_status()  # Raise exception on HTTP error

    # ________________________________________________________________________
    # Parse Response
    # ________________________________________________________________________
    
    # Expected structure: {"message": {"content": "..."}}
    return response.json()["message"]["content"]


# ============================================================================
# CLI Interface
# ============================================================================

if __name__ == "__main__":
    # ________________________________________________________________________
    # Argument Parsing
    # ________________________________________________________________________
    
    if len(sys.argv) < 2:
        print("Usage: python hal_chat.py \"your message here\"")
        sys.exit(1)

    user_input = sys.argv[1]

    # ________________________________________________________________________
    # Optional Context
    # ________________________________________________________________________
    
    # Uncomment and modify to add context to the system prompt
    # This is useful for testing different modes or scenarios
    context = None
    # context = "The user just completed building and running a custom Ollama model."
    # context = "You are in debug mode. Explain your reasoning."

    # ________________________________________________________________________
    # Execute and Output
    # ________________________________________________________________________
    
    reply = chat(user_input, context)
    print(reply)

