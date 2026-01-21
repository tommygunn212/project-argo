# Personality System - Quick Reference

## What Is It?

ARGO now has an example-driven personality injection system with two modes:

1. **Mild** (default) - Calm, factual, analytical responses
2. **Claptrap** (explicit) - Sharp, attitude-filled, opinionated responses

## How It Works

When a user asks a question:
1. Intent parser classifies it (greeting, question, command, etc.)
2. If it's a QUESTION → check personality examples first
3. If example found → return it directly (no LLM call)
4. If no example → call LLM as normal
5. If it's a COMMAND → skip personality, stay professional always

## File Structure

```
examples/
├── mild/
│   ├── cats.txt          (5 calm cat Q&A pairs)
│   └── bad_coffee.txt    (5 educational coffee Q&A pairs)
└── claptrap/
    ├── cats.txt          (5 sharp cat Q&A pairs)
    └── bad_coffee.txt    (5 sarcastic coffee Q&A pairs)
```

## Adding New Examples

1. Create a new `.txt` file in `examples/{mode}/` folder
2. Format Q&A pairs like this:

```
Q: Why do cats hate the vet?
A: Because you're betraying their trust by taking them to The Place Where Bad Things Happen. In their mind, you're basically a traitor.

Q: How can I tell if my cat is sick?
A: They'll ignore you more than usual. Or they'll actually want your attention, which means they're definitely dying. There's no in-between.
```

3. Multi-line answers are supported - just indent continuation lines

## Adding Claptrap Mode Activation

To let users switch to Claptrap mode:

```python
# In coordinator.py or similar
if "claptrap mode" in user_text.lower():
    response_generator.personality_mode = "claptrap"
    return "Claptrap mode activated. Buckle up."
elif "mild mode" in user_text.lower():
    response_generator.personality_mode = "mild"
    return "Back to professional mode."
```

## Testing

Run the evaluation test:
```bash
python test_personality_eval.py
```

Expected output: "ALL TESTS PASSED"

## Code Integration Points

**PersonalityLoader** (`core/personality.py`):
- `get_personality_loader()` - Get global instance
- `loader.get_example(mode, question)` - Find matching example
- `loader.load_examples(mode)` - Load all examples for a mode

**Response Generator** (`core/response_generator.py`):
- `self.personality_loader` - Instance variable (already integrated)
- `self.personality_mode` - Current mode ("mild" or "claptrap")
- Personality check happens before LLM call in `generate()` method

## Design Rules (Non-Negotiable)

1. ✅ Personality is ONLY example-driven (no rules, sliders, heuristics)
2. ✅ Two modes: Mild (default) + Claptrap (explicit)
3. ✅ Examples stored as Q→A pairs in `examples/{mode}/*.txt`
4. ✅ If no example found → default to Mild
5. ✅ Commands ALWAYS stay humor-free (excluded from personality)
6. ✅ No blending, no escalation, no tone inference

## Example Q&A Pattern

### Mild (Factual, Educational)
```
Q: Why does bad coffee taste bad?
A: Coffee flavor depends on extraction—water temperature, grind size, and brewing time all matter. Over-extraction (too hot, too long) pulls out bitter compounds.
```

### Claptrap (Sharp, Opinionated)
```
Q: Why does bad coffee taste bad?
A: Because someone didn't respect the craft. Over-extraction, stale beans, or tap water that tastes like a swimming pool. It's not complicated—they just didn't care.
```

## Troubleshooting

**Q: Examples not loading?**
- Check `examples/{mode}/` directories exist
- Verify .txt files are UTF-8 encoded
- Look for error logs in personality.py logger output

**Q: Claptrap answers too soft/too harsh?**
- Edit the .txt files in `examples/claptrap/`
- Rerun test to verify changes
- Same question always returns same answer (cached)

**Q: Commands showing personality when they shouldn't?**
- Confirmed: Commands are skipped from personality check
- They call LLM as normal and stay professional

## Performance

- Examples are cached in memory after first load
- No disk I/O after first access (sub-millisecond responses)
- Keyword matching is O(n) where n = number of examples (~10-20)
- Global singleton prevents repeated initialization

## Future Enhancements

- Add more example categories (music, tech, personal topics)
- Create user-provided personality packs
- Add personality for commands (if design ever changes)
- Context-aware mode switching (automatic based on topic)

---

**System Status**: PRODUCTION READY  
**Last Updated**: Personality implementation complete  
**Design Reference**: personality_injection_design_reference-clap.txt
