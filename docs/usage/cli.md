# ARGO Usage Guide

## Interactive Mode

Start ARGO in interactive mode for multi-turn conversations:

```powershell
ai
```

Then ask questions naturally:

```
argo > Why does ice melt when heated?
argo > What about other materials?
argo > exit
```

Type `exit` or `quit` to leave interactive mode.

## Single-Shot Mode

Ask a single question and get a response:

```powershell
ai "Why does ice melt?"
```

The program exits automatically after responding.

## Conversation Browsing

Review past interactions by date or topic:

```powershell
ai
argo > list conversations
argo > show topic science
argo > summarize science
argo > exit
```

**Available commands:**
- `list conversations` — Show recent interactions
- `show by date today` — View today's conversations
- `show by topic <topic>` — View conversations by category
- `summarize by topic <topic>` — Get summary of topic
- `context <topic>` — Get detailed context for topic

## Exiting

Type `exit` or `quit` in interactive mode. Single-shot mode exits automatically after responding.
