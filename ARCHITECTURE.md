# Argo Architecture

## System Flow

```
User Input
    ↓
[Intent Detection]
    ├─ Recall Query? ("what did we talk about?")
    │   ├─ Pattern match meta-phrases
    │   ├─ Extract count if present ("last 3 things")
    │   └─ Return deterministic list (NO model)
    │
    └─ Regular Query
        ├─ Load user preferences
        ├─ Retrieve relevant past interactions
        ├─ Compose: Preferences + Memory + Query
        ├─ Send to Ollama (llama3.1:8b)
        ├─ Validate output (safety net, not style cop)
        └─ Output + Store to memory
```

## Memory System

### Storage

File: `memory/interactions.json` (max 200 entries)

Each entry contains:
```json
{
  "timestamp": "2026-01-17T19:23:09.505413",
  "user_input": "Why do dogs play?",
  "model_response": "Dogs play for...[200 chars]",
  "keywords": ["dogs", "play", "multitude", ...],
  "topic": "dogs"
}
```

### Retrieval (Three-Tier Fallback)

1. **TF-IDF Scoring** (primary)
   - Computes term frequency × inverse document frequency
   - Rare keywords weighted higher (better signal)
   - Stopwords filtered (30+ common words)

2. **Topic Bucketing** (secondary)
   - 8 core topics: dogs, cats, birds, coffee, sleep, procrastination, fear, neural
   - Topic inferred from keywords at storage time
   - Used when TF-IDF is thin

3. **Recency** (tertiary)
   - Fallback when both above insufficient
   - Returns most recent interactions

### Memory Hygiene

Recall queries (meta-operations) are **never stored to memory**.

Why: Prevents contamination of conversational corpus with bookkeeping.

## Preferences System

### Detection

Pattern matching on user input:
- "be casual" → `tone: casual`
- "brief" → `verbosity: concise`
- "funny" → `humor: yes`
- "use bullets" → `structure: bullets`

### Storage

File: `user_preferences.json`

```json
{
  "tone": "casual",
  "verbosity": "detailed",
  "humor": "yes",
  "structure": "bullets"
}
```

All fields are optional. Null = not set.

### Application

Preferences injected into prompt as:
```
User preferences: Tone preference: casual
```

Injected before memory block, before user query. Recency bias.

### Persistence

Preferences survive session restart and compose naturally (multiple active simultaneously).

## Recall Mode

### Detection

Pattern matching for meta-query trigger phrases:
- "what did we talk about"
- "the last N things"
- "summarize our conversation"
- "earlier you mentioned"
- 15+ other variations

Optional count extraction:
- "last 3 things" → `count=3`
- "last one topic" → `count=1` (word number mapping)
- No count specified → return all

### Formatting

Deterministic list output (no model inference):

**Neutral format** (default):
```
Recent topics:
1. Why do eggs get hard when boiled?
2. What makes cats special?
```

**Casual format** (with tone preference):
```
Here's what we covered:
Recent topics:
1. Why do eggs get hard when boiled?
2. What makes cats special?
```

No summaries. No synthesis. Just lists.

### Hygiene Rule

Recall queries return early in `run_argo()` **before** calling `store_interaction()`.

Code path:
```python
if is_recall_query:
    output = format_recall_response(...)
    print(output)
    # IMPORTANT: Do NOT store to memory
    return  # Early exit
```

## Voice System

### SYSTEM Prompt

Example-based generation with style guidance.

**Examples:**
- Cats: "These little four-legged drama queens strut around like they're royalty"
- Coffee: "Coffee isn't just a drink, it's a warm hug with an attitude"
- Fridge: "That's not poor design — that's hunger playing Tetris on a deadline"

**Rules:**
- Be assertive, slightly dismissive
- Sound like talking to a friend, not teaching
- Use vivid metaphors naturally
- No excessive hedging or softening

### Validator (Safety Net)

File: `wrapper/argo.py` - `validate_voice_compliance()`

**Not a style cop.** Acts like traction control:
- Off by default
- Activates when model drifts
- Can be tightened manually if needed

Current implementation: passes through (you're the arbiter).

## Conversation Browsing

Read-only access to past conversations:

- **list conversations** - Recent sessions by date
- **show today/yesterday/date** - Filter by date
- **show topic <topic>** - Filter by topic
- **summarize <topic>** - Factual summary (questions asked)
- **open <topic>** - Load context for continuation

All browsing is read-only. No memory modification.

## File Structure

```
argo/
├── README.md                 # Quick start
├── ARCHITECTURE.md           # This file
├── CHANGELOG.md              # Release history
├── LICENSE                   # MIT
├── requirements.txt          # Python dependencies
├── setup.ps1                 # Windows setup script
├── .gitignore                # Git ignore rules
│
├── wrapper/
│   ├── argo.py              # Main execution engine
│   ├── memory.py            # TF-IDF + topic fallback
│   ├── prefs.py             # Preference detection + storage
│   └── browsing.py          # Conversation browser
│
├── memory/                   # (gitignored) Session memory
│   ├── interactions.json     # All interactions
│   └── user_preferences.json # Persisted preferences
│
├── logs/                     # (gitignored) Execution logs
│
└── runtime/
    └── ollama/
        └── modelfiles/
            └── argo/
                └── Modelfile # Model configuration
```

All paths relative to repo root. No absolute paths.

## Design Principles

### Explicit Intent Over Automation

- `ai "question"` - single-shot, you invoke
- `ai` - interactive mode, you control flow
- No hidden routing or "did they mean...?" logic

### Recall is Deterministic

- No model generates recall output
- No hallucination risk
- Pure data retrieval with fixed formatting

### Validator = Safety Net, Not Style Cop

- Validation exists to catch drift
- But human taste > algorithmic rules
- Tightened only if behavior degrades

### Human Control > Inference

- You browse conversations
- You decide what to do
- System exposes memory, doesn't reinterpret it
