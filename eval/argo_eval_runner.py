"""
Non-interactive evaluation runner.

- Reads `eval_prompts_v1.txt` (one prompt per non-comment line)
- Instantiates `LLMResponseGenerator` directly
- Calls `generate(intent)` once per prompt (no retries)
- Writes one JSONL to `eval/results/` with fields: prompt, intent_type, response, error
- No coordinator, no audio, no wake word

Run as: python eval/argo_eval_runner.py
"""
from __future__ import annotations
import os
import json
import logging
from datetime import datetime
from typing import Optional

# Local LLM response generator (isolated LLM component)
from core.response_generator import LLMResponseGenerator

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Simple Intent placeholder matching what LLMResponseGenerator expects
class SimpleIntent:
    def __init__(self, raw_text: str, intent_type_value: str = "unknown", confidence: float = 0.9):
        self.raw_text = raw_text
        # The ResponseGenerator expects `intent.intent_type.value`
        self.intent_type = type("_T", (), {"value": intent_type_value})()
        self.confidence = confidence


def detect_intent_type(text: str) -> str:
    t = text.strip()
    if not t:
        return "unknown"
    lowered = t.lower()
    # Basic heuristics
    if lowered.endswith("?") or lowered.startswith(("why", "what", "how", "when", "who", "where")):
        return "question"
    if lowered in ("open chrome.", "open chrome", "open photoshop", "stop", "play music", "next"):
        return "command"
    if t.isupper() and len(t.split()) < 10:
        return "question"
    return "unknown"


def load_prompts(prompts_path: str) -> list[str]:
    prompts = []
    with open(prompts_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            stripped = line.strip()
            # Skip comments and empty lines
            if not stripped:
                continue
            if stripped.startswith("#"):
                continue
            prompts.append(line)
    return prompts


def run_once():
    root = os.path.dirname(os.path.dirname(__file__))
    prompts_path = os.path.join(root, "eval", "eval_prompts_v1.txt")
    results_dir = os.path.join(root, "eval", "results")

    if not os.path.exists(prompts_path):
        logger.error(f"Prompts not found: {prompts_path}")
        return 1

    os.makedirs(results_dir, exist_ok=True)

    prompts = load_prompts(prompts_path)
    logger.info(f"Loaded {len(prompts)} prompts from {prompts_path}")

    generator = None
    try:
        generator = LLMResponseGenerator()
    except Exception as e:
        logger.error(f"Failed to initialize LLMResponseGenerator: {e}")
        # We continue and will record errors per-prompt

    timestamp = datetime.utcnow().isoformat(timespec="seconds").replace(":", "-")
    out_path = os.path.join(results_dir, f"eval_run_{timestamp}.jsonl")

    with open(out_path, "w", encoding="utf-8") as out_f:
        for prompt in prompts:
            intent_type = detect_intent_type(prompt)
            intent = SimpleIntent(prompt, intent_type_value=intent_type)
            record = {"prompt": prompt, "intent_type": intent_type, "response": None, "error": None}

            if generator is None:
                record["error"] = "LLMResponseGenerator_initialization_failed"
                logger.warning("Skipping generation due to generator init failure")
            else:
                try:
                    resp = generator.generate(intent, memory=None)
                    record["response"] = resp
                except Exception as e:
                    record["error"] = str(e)

            out_f.write(json.dumps(record, ensure_ascii=False) + "\n")

    logger.info(f"Wrote results to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_once())
