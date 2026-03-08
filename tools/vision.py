"""
ARGO Computer Vision — "Give ARGO eyes."

Screenshot capture + GPT-4o vision API for screen analysis,
error reading, OCR-style queries, and general visual description.
"""

import base64
import io
import logging
import os
from typing import Optional

logger = logging.getLogger("argo.tools.vision")


# ---------------------------------------------------------------------------
# Screenshot capture
# ---------------------------------------------------------------------------

def capture_screenshot() -> Optional[bytes]:
    """Capture the primary monitor and return PNG bytes."""
    try:
        import mss
        with mss.mss() as sct:
            monitor = sct.monitors[1]  # primary monitor
            img = sct.grab(monitor)
            png_bytes = mss.tools.to_png(img.rgb, img.size)
            return png_bytes
    except ImportError:
        logger.error("[VISION] mss not installed — run: pip install mss")
        return None
    except Exception as e:
        logger.error(f"[VISION] Screenshot capture failed: {e}")
        return None


def capture_screenshot_region(left: int, top: int, width: int, height: int) -> Optional[bytes]:
    """Capture a specific screen region and return PNG bytes."""
    try:
        import mss
        with mss.mss() as sct:
            region = {"left": left, "top": top, "width": width, "height": height}
            img = sct.grab(region)
            png_bytes = mss.tools.to_png(img.rgb, img.size)
            return png_bytes
    except ImportError:
        logger.error("[VISION] mss not installed — run: pip install mss")
        return None
    except Exception as e:
        logger.error(f"[VISION] Region capture failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Image encoding helpers
# ---------------------------------------------------------------------------

def _encode_image_base64(png_bytes: bytes) -> str:
    """Encode raw PNG bytes to a base64 data-URI string for OpenAI vision."""
    b64 = base64.b64encode(png_bytes).decode("utf-8")
    return f"data:image/png;base64,{b64}"


# ---------------------------------------------------------------------------
# Vision analysis via OpenAI GPT-4o
# ---------------------------------------------------------------------------

def analyze_image(
    png_bytes: bytes,
    user_prompt: str = "Describe what you see on screen.",
    model: str = "gpt-4o",
    max_tokens: int = 512,
) -> str:
    """Send a screenshot (PNG bytes) to GPT-4o vision and return the description."""
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return "OpenAI API key not configured. Cannot analyze images."

    if not png_bytes:
        return "No image data to analyze."

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)

        image_url = _encode_image_base64(png_bytes)
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are ARGO's vision module. Analyze the screenshot and "
                        "answer the user's question concisely. Focus on what's relevant. "
                        "If there are error messages, read them verbatim. "
                        "Keep responses under 3 sentences unless more detail is needed."
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_prompt},
                        {"type": "image_url", "image_url": {"url": image_url, "detail": "high"}},
                    ],
                },
            ],
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"[VISION] GPT-4o analysis failed: {e}")
        return f"Vision analysis failed: {e}"


# ---------------------------------------------------------------------------
# High-level convenience functions
# ---------------------------------------------------------------------------

def describe_screen(user_prompt: str = "Describe what you see on my screen.") -> str:
    """Capture screenshot and describe it."""
    png = capture_screenshot()
    if not png:
        return "I couldn't capture your screen. Make sure the mss package is installed."
    return analyze_image(png, user_prompt=user_prompt)


def read_screen_error() -> str:
    """Capture screenshot and specifically look for error messages."""
    png = capture_screenshot()
    if not png:
        return "I couldn't capture your screen."
    return analyze_image(
        png,
        user_prompt=(
            "Look at this screenshot carefully. Identify any error messages, "
            "warnings, or dialog boxes. Read any error text verbatim and briefly "
            "explain what it means and suggest a fix."
        ),
    )


def analyze_screen_with_question(question: str) -> str:
    """Capture screenshot and answer a specific question about it."""
    png = capture_screenshot()
    if not png:
        return "I couldn't capture your screen."
    return analyze_image(png, user_prompt=question)


# ---------------------------------------------------------------------------
# Voice command parser
# ---------------------------------------------------------------------------

def parse_vision_command(text: str) -> dict:
    """Parse a vision-related voice command into action + optional question.

    Returns:
        {"action": "describe"|"read_error"|"question", "question": str}
    """
    import re
    lower = text.lower()

    # Error-reading patterns
    if re.search(r"\b(read|what)\b.*\b(error|warning|exception|traceback|bug|crash)\b", lower) or \
       re.search(r"\b(error|warning|exception)\b.*\b(say|mean|is)\b", lower):
        return {"action": "read_error", "question": ""}

    # General description
    if re.search(r"\b(describe|what(?:'s| is))\b.*\b(screen|see|looking|display|monitor|desktop)\b", lower) or \
       re.search(r"\b(look(?:ing)?|see)\b.*\bscreen\b", lower):
        # Check if there's a more specific question
        q_match = re.search(r"\b(?:and|then)\s+(.+)", lower)
        if q_match:
            return {"action": "question", "question": q_match.group(1).strip()}
        return {"action": "describe", "question": ""}

    # Screenshot request (just capture + describe)
    if re.search(r"\b(take|grab|capture)\b.*\b(screenshot|screen\s?shot|snap|picture)\b", lower):
        return {"action": "describe", "question": ""}

    # Fallback: treat as a question about what's on screen
    # Strip the command prefix to extract the actual question
    question = re.sub(r"^.*?\b(tell me|can you|what|how|why|where|who|is|are|do|does)\b", r"\1", lower).strip()
    if not question or question == lower:
        question = text
    return {"action": "question", "question": question}
