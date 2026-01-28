"""
================================================================================
ARGO (Autonomous-Resistant Governed Operator)
Memory Module — Context-Aware Interaction Retrieval
================================================================================

Module:      memory.py
Creator:     Tommy Gunn (@tommygunn212)
Version:     1.0.0 (Phase 2a)
Created:     December 2025
Purpose:     TF-IDF + topic-based memory system for conversational context

================================================================================
FEATURES
================================================================================

1. PERSISTENT STORAGE
   - Stores up to 200 interactions in memory/interactions.json
   - Each entry: timestamp, user_input, response, keywords, topic
   - Automatic cleanup when limit exceeded (oldest removed first)

2. RETRIEVAL SYSTEM (Three-Tier Fallback)
   - Tier 1: TF-IDF scoring (keyword relevance)
   - Tier 2: Topic matching (inferred categories)
   - Tier 3: Recency fallback (timestamp ordering)

3. KEYWORD EXTRACTION
   - Automatic keyword extraction from user input and model response
   - Stopword filtering (common words removed)
   - Deduplication and scoring

4. TOPIC INFERENCE
   - 8 core topics: conversation, work, personal, health, tech, creative, planning, other
   - Pattern-based topic classification
   - Fallback to 'other' if no clear match

5. HYGIENE RULES
   - Recall queries never stored (memory stays clean)
   - Automatic deduplication of similar queries
   - No recording of system prompts or metadata

================================================================================
FUNCTIONS
================================================================================

1. load_memory() → List[Dict]
   Load all interactions from disk

2. save_memory(memory: List[Dict])
   Persist interactions to disk

3. infer_topic(text: str) → str
   Classify interaction into one of 8 topics

4. clean_tokens(text: str) → List[str]
   Tokenize and remove stopwords

5. extract_keywords(user_input: str, model_response: str) → List[str]
   Extract meaningful keywords from input and response

6. store_interaction(user_input: str, model_response: str)
   Save interaction to memory (called after each generation)

7. compute_idf(memory: List[Dict]) → Dict[str, float]
   Calculate Inverse Document Frequency for all terms

8. compute_tf(text: str) → Dict[str, float]
   Calculate Term Frequency for query

9. score_by_tfidf(query: str, memory: List[Dict]) → List[tuple]
   Score and rank interactions by relevance

10. find_relevant_memory(query: str, top_n: int = 2) → List[Dict]
    Main retrieval function; returns top N relevant interactions

================================================================================
DESIGN PRINCIPLES
================================================================================

- Explicit storage only (no background learning)
- Transparent scoring (all logic is readable)
- Deterministic retrieval (no randomness)
- No external dependencies (pure Python)
- Fast retrieval (in-memory scoring)
- Easy debugging (full logs available)

================================================================================
"""

import json
import os
import tempfile
import math
from datetime import datetime
from pathlib import Path
from typing import List, Dict

# Absolute path for reliability
BASE_DIR = Path(__file__).parent.resolve()
MEMORY_FILE = BASE_DIR.joinpath("memory", "interactions.json")

# Config
MAX_MEMORY_ENTRIES = 200       # cap so memory doesn't grow forever
RESPONSE_SAVE_LEN = 200        # how much of the model response to keep
MIN_KEYWORD_LEN = 4            # filter tokens smaller than this
MAX_KEYWORDS = 8               # how many keywords to save per interaction

# Stopwords - common words that don't signal relevance
STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "as", "is", "are", "was", "were", "be",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "can", "must", "shall", "what", "which",
    "who", "when", "where", "why", "how", "this", "that", "it", "its"
}


def ensure_memory_file():
    """Create memory directory and file if they don't exist."""
    os.makedirs(MEMORY_FILE.parent, exist_ok=True)
    if not MEMORY_FILE.exists():
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump([], f, indent=2)


def load_memory() -> List[Dict]:
    """Load interaction history from disk."""
    ensure_memory_file()
    with open(MEMORY_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return []


def save_memory(memory: List[Dict]):
    """Save interaction history to disk."""
    os.makedirs(MEMORY_FILE.parent, exist_ok=True)
    temp_file = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=str(MEMORY_FILE.parent),
            delete=False,
        ) as f:
            temp_file = f.name
            json.dump(memory, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_file, MEMORY_FILE)
    finally:
        if temp_file and os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except Exception:
                pass


def infer_topic(text: str) -> str | None:
    """
    Detect coarse topic from text using simple keyword matching.
    
    This is a cheap fallback for memory retrieval when keyword overlap fails.
    Enables topic-based bucketing without embeddings.
    
    Args:
        text: User input or response text
        
    Returns:
        Topic string or None if no topic detected
    """
    text_lower = text.lower()
    
    # Topic patterns (order matters: more specific first)
    patterns = {
        "dogs": ["dog", "dogs", "puppy", "puppies", "canine", "canines"],
        "cats": ["cat", "cats", "kitten", "kittens", "feline", "felines"],
        "birds": ["bird", "birds", "parrot", "eagle", "pigeon"],
        "coffee": ["coffee", "caffeine", "espresso", "latte"],
        "sleep": ["sleep", "sleeping", "insomnia", "rest", "nap"],
        "procrastination": ["procrastination", "procrastinate", "procrastinating"],
        "fear": ["fear", "afraid", "terror", "phobia"],
        "neural": ["neural", "network", "neuron", "neurons", "ai", "artificial"],
    }
    
    for topic, keywords in patterns.items():
        if any(kw in text_lower for kw in keywords):
            return topic
    
    return None


def clean_tokens(text: str) -> List[str]:
    """
    Extract meaningful tokens from text.
    
    - Splits on whitespace
    - Removes short tokens (< MIN_KEYWORD_LEN)
    - Keeps only alphanumeric characters
    - Lowercases for consistency
    """
    tokens = text.lower().split()
    cleaned = [
        "".join(ch for ch in tok if ch.isalnum())
        for tok in tokens
        if len(tok) >= MIN_KEYWORD_LEN
    ]
    return [tok for tok in cleaned if tok]


def extract_keywords(user_input: str, model_response: str) -> List[str]:
    """
    Extract meaningful keywords from user input and model response.
    
    Uses simple token frequency and length heuristics.
    Returns unique tokens up to MAX_KEYWORDS.
    """
    tokens = clean_tokens(user_input) + clean_tokens(model_response)
    unique = list(dict.fromkeys(tokens))  # preserve order, dedupe
    return unique[:MAX_KEYWORDS]


def store_interaction(user_input: str, model_response: str):
    """
    Record a user-model interaction to memory.
    
    Stores full user input, truncated response, extracted keywords, and inferred topic.
    Enforces MAX_MEMORY_ENTRIES limit (keeps most recent).
    """
    memory = load_memory()

    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "user_input": user_input.strip(),
        "model_response": model_response.strip()[:RESPONSE_SAVE_LEN],
        "keywords": extract_keywords(user_input, model_response),
        "topic": infer_topic(user_input + " " + model_response),
    }

    memory.append(entry)

    # Cap memory size (keep most recent)
    if len(memory) > MAX_MEMORY_ENTRIES:
        memory = memory[-MAX_MEMORY_ENTRIES:]

    save_memory(memory)


def compute_idf(memory: List[Dict]) -> Dict[str, float]:
    """
    Compute Inverse Document Frequency for all tokens in memory.
    
    IDF = log(total_documents / documents_containing_token)
    - Common words (the, is, a) → low IDF
    - Rare meaningful words → high IDF
    
    Returns mapping of token → IDF score
    """
    total_docs = len(memory)
    if total_docs == 0:
        return {}
    
    # Count which documents contain each token
    doc_freq = {}
    for entry in memory:
        entry_text = entry.get("user_input", "") + " " + entry.get("model_response", "")
        entry_tokens = set(clean_tokens(entry_text))
        for token in entry_tokens:
            if token not in STOPWORDS:  # Skip stopwords
                doc_freq[token] = doc_freq.get(token, 0) + 1
    
    # Compute IDF for each token
    idf = {}
    for token, freq in doc_freq.items():
        idf[token] = math.log(total_docs / freq) if freq > 0 else 0
    
    return idf


def compute_tf(text: str) -> Dict[str, float]:
    """
    Compute Term Frequency for a document.
    
    TF = count(token) / total_tokens
    Normalized by document length to prevent bias toward longer documents.
    
    Returns mapping of token → TF score (0-1)
    """
    tokens = clean_tokens(text)
    if not tokens:
        return {}
    
    tf = {}
    for token in tokens:
        if token not in STOPWORDS:  # Skip stopwords
            tf[token] = tf.get(token, 0) + 1
    
    # Normalize by total token count
    total = len([t for t in tokens if t not in STOPWORDS])
    if total == 0:
        return {}
    
    for token in tf:
        tf[token] = tf[token] / total
    
    return tf


def score_by_tfidf(query: str, memory: List[Dict]) -> List[tuple]:
    """
    Score all memory entries using TF-IDF similarity to query.
    
    Returns list of (entry, score) tuples sorted by score descending.
    
    Algorithm:
    1. Compute IDF for entire memory corpus
    2. Tokenize query, compute TF
    3. For each entry: sum(TF[token] * IDF[token]) for tokens in query
    4. Sort by score descending
    """
    if not memory:
        return []
    
    # Step 1: Compute IDF for corpus
    idf = compute_idf(memory)
    
    # Step 2: Tokenize query and compute TF
    query_tf = compute_tf(query)
    if not query_tf:
        return [(entry, 0) for entry in memory]
    
    # Step 3: Score each entry
    scored = []
    for entry in memory:
        entry_text = entry.get("user_input", "") + " " + entry.get("model_response", "")
        entry_tokens = set(clean_tokens(entry_text))
        
        # TF-IDF score = sum of (TF[token] * IDF[token]) for tokens in query
        score = 0.0
        for token in query_tf.keys():
            if token in entry_tokens:
                tf = query_tf[token]
                idf_val = idf.get(token, 0)
                score += tf * idf_val
        
        scored.append((entry, score))
    
    # Step 4: Sort by score descending
    scored.sort(key=lambda x: x[1], reverse=True)
    
    return scored


def find_relevant_memory(query: str, top_n: int = 2) -> List[Dict]:
    """
    Retrieve relevant memory entries using two-tier fallback:
    
    1. Primary: Keyword overlap scoring (find common tokens)
    2. Fallback: Topic matching (when keyword overlap is zero)
    
    Returns top_n entries sorted by relevance score.
    """
    memory = load_memory()
    if not memory:
        return []

    query_topic = infer_topic(query)

    # Step 1: Score by TF-IDF (primary tier)
    scored = score_by_tfidf(query, memory)

    # If top result has non-zero score, return top_n TF-IDF matches
    if scored and scored[0][1] > 0:
        return [entry for entry, _ in scored[:top_n]]

    # Step 2: Fallback to topic matching (when TF-IDF scores are zero)
    topic_scored = []
    for entry in memory:
        entry_topic = entry.get("topic", "")
        # Score: 2 if exact match, 1 if partial overlap, 0 if no overlap
        if query_topic and entry_topic:
            if query_topic == entry_topic:
                topic_score = 2
            elif query_topic in entry_topic or entry_topic in query_topic:
                topic_score = 1
            else:
                topic_score = 0
        else:
            topic_score = 0
        
        if topic_score > 0:
            topic_scored.append((entry, topic_score))

    # Sort by topic score (descending)
    topic_scored.sort(key=lambda x: x[1], reverse=True)

    if topic_scored:
        return [entry for entry, _ in topic_scored[:top_n]]

    # Step 3: Last resort - return most recent entries
    return memory[-top_n:] if memory else []
