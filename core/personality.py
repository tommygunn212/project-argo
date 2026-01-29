"""
Personality Injection - Example-Driven System

Loads personality examples based on explicit mode.

Rules (from personality_injection_design_reference-clap.txt):
- Personality is ONLY example-driven
- Modes: Mild (default), Claptrap (explicit only), Tommy Gunn (explicit only)
- No rules, sliders, heuristics, or tone logic
- Examples stored as Q→A pairs in examples/{mode}/*.txt
- If no example found or loading fails → default to Mild
"""

import os
import logging
from typing import Optional, Dict, List
from pathlib import Path

logger = logging.getLogger(__name__)


# ============================================================================
# 1) PERSONALITY LOADER (PUBLIC API)
# ============================================================================
class PersonalityLoader:
    """Load personality examples from disk.

    Design:
    - Example-driven only (no heuristics, no sliders)
    - Explicit mode selection (mild/claptrap/tommy_gunn)
    - Cached to avoid repeated disk reads
    """
    
    SUPPORTED_MODES = ["mild", "claptrap", "tommy_gunn"]
    DEFAULT_MODE = "mild"
    
    def __init__(self, examples_dir: str = "examples"):
        """Initialize with examples directory."""
        # 1.1) Resolve examples directory
        # Convert relative path to absolute if needed
        if not os.path.isabs(examples_dir):
            # Get the directory of this file (core/)
            core_dir = os.path.dirname(os.path.abspath(__file__))
            parent_dir = os.path.dirname(core_dir)
            examples_dir = os.path.join(parent_dir, examples_dir)
        
        # 1.2) Internal state
        self.examples_dir = examples_dir
        self.cache: Dict[str, List[Dict[str, str]]] = {}
        
    def load_examples(self, mode: str = DEFAULT_MODE) -> List[Dict[str, str]]:
        """
        Load Q→A examples for given mode.
        
        Args:
            mode: "mild" or "claptrap"
            
        Returns:
            List of {"question": str, "answer": str} dicts
        """
        # 2.1) Validate mode
        if mode not in self.SUPPORTED_MODES:
            logger.warning(f"[Personality] Unknown mode '{mode}', defaulting to {self.DEFAULT_MODE}")
            mode = self.DEFAULT_MODE
        
        # 2.2) Return cached if available
        if mode in self.cache:
            return self.cache[mode]
        
        # 2.3) Load from disk
        examples = []
        mode_dir = os.path.join(self.examples_dir, mode)
        
        if not os.path.exists(mode_dir):
            logger.warning(f"[Personality] Mode directory not found: {mode_dir}")
            return []
        
        # 2.4) Parse files (Q/A pairs)
        try:
            for filename in sorted(os.listdir(mode_dir)):
                if not filename.endswith(".txt"):
                    continue
                
                filepath = os.path.join(mode_dir, filename)
                pairs = self._parse_file(filepath)
                examples.extend(pairs)
                logger.debug(f"[Personality] Loaded {len(pairs)} examples from {filename}")
            
            self.cache[mode] = examples
            logger.info(f"[Personality] Loaded {len(examples)} total examples for mode '{mode}'")
            return examples
        
        except Exception as e:
            logger.error(f"[Personality] Failed to load examples for mode '{mode}': {e}")
            return []
    
    def _parse_file(self, filepath: str) -> List[Dict[str, str]]:
        """
        Parse Q→A file.
        
        Format:
            Q: Question text here
            A: Answer text here
            
            Q: Next question
            A: Next answer
        
        Args:
            filepath: Path to .txt file
            
        Returns:
            List of {"question": str, "answer": str} dicts
        """
        # 3.1) Parse loop state
        pairs = []
        current_q = None
        current_a = None
        
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                lines = f.readlines()
            
            i = 0
            # 3.2) Single-pass parse (preserves order)
            while i < len(lines):
                line = lines[i].strip()
                i += 1
                
                if not line:
                    continue
                
                if line.startswith("Q:"):
                    # If we have a previous pair, save it
                    if current_q is not None and current_a is not None:
                        pairs.append({"question": current_q, "answer": current_a})
                    
                    current_q = line[2:].strip()
                    current_a = None
                
                elif line.startswith("A:"):
                    current_a = line[2:].strip()
                    
                    # Multi-line answers: consume following indented lines
                    while i < len(lines):
                        next_line = lines[i]
                        if not next_line.strip():
                            i += 1
                            continue
                        if next_line.startswith(("Q:", "A:")):
                            break
                        if next_line[0] not in (" ", "\t"):
                            break
                        
                        current_a += "\n" + next_line.strip()
                        i += 1
            
            # 3.3) Save last pair
            if current_q is not None and current_a is not None:
                pairs.append({"question": current_q, "answer": current_a})
        
        except Exception as e:
            logger.error(f"[Personality] Failed to parse {filepath}: {e}")
        
        return pairs
    
    def get_example(self, mode: str, question: str) -> Optional[str]:
        """
        Find example answer for question (keyword-based match).
        
        Matches if:
        - Exact phrase match (case-insensitive)
        - Or all main keywords from user question appear in example question
        
        Args:
            mode: "mild" or "claptrap"
            question: User question
            
        Returns:
            Example answer if found, None otherwise
        """
        # 4.1) Load examples for mode
        examples = self.load_examples(mode)
        
        question_lower = question.lower()
        
        # 4.2) Extract keywords (filter out common stop words)
        stop_words = {"do", "why", "what", "how", "is", "the", "a", "an", "that", "this", "i", "my", "you", "your"}
        user_keywords = [w for w in question_lower.split() if w and w not in stop_words and len(w) > 2]
        
        for ex in examples:
            ex_q = ex["question"].lower()
            
            # 4.3) Exact substring match first
            if question_lower in ex_q or ex_q in question_lower:
                logger.debug(f"[Personality] Exact match found for '{question}'")
                return ex["answer"]
            
            # 4.4) Keyword match (all user keywords appear in example question)
            if user_keywords and all(kw in ex_q for kw in user_keywords):
                logger.debug(f"[Personality] Keyword match found for '{question}'")
                return ex["answer"]
        
        return None


# ============================================================================
# 5) GLOBAL LOADER SINGLETON
# ============================================================================
# Global instance
_personality_loader: Optional[PersonalityLoader] = None


def get_personality_loader(examples_dir: str = "examples") -> PersonalityLoader:
    """Get or create global personality loader."""
    # 5.1) Initialize on first access
    global _personality_loader
    if _personality_loader is None:
        _personality_loader = PersonalityLoader(examples_dir)
    return _personality_loader
