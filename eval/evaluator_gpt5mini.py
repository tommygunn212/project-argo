"""
Evaluator adapter stub for GPT-5-mini.

- If `gpt5mini` package is available, attempts to call it (best-effort)
- If not available, returns `{'evaluation_error': 'gpt5mini_unavailable'}`
- Does not fabricate scores or synthesize data
"""
from __future__ import annotations
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


def evaluate_response(response_text: str) -> Dict[str, Any]:
    """Evaluate a single response using GPT-5-mini if available.

    Returns a dict with either evaluation results or an `evaluation_error` key.
    """
    try:
        import gpt5mini  # type: ignore
    except Exception:
        logger.error('evaluation_error: "gpt5mini_unavailable"')
        return {"evaluation_error": "gpt5mini_unavailable"}

    try:
        # Best-effort call: adapter does not assume API shape.
        if hasattr(gpt5mini, "evaluate"):
            result = gpt5mini.evaluate(response_text)
            return {"evaluation": result}
        elif hasattr(gpt5mini, "Client"):
            client = gpt5mini.Client()
            result = client.evaluate(response_text)
            return {"evaluation": result}
        else:
            logger.error('evaluation_error: "gpt5mini_unrecognized_interface"')
            return {"evaluation_error": "gpt5mini_unrecognized_interface"}

    except Exception as e:
        logger.error(f'evaluation_error: "{e}"')
        return {"evaluation_error": str(e)}
