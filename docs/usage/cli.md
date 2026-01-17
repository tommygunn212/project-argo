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

## Audio Transcription

Transcribe an audio file and process with ARGO:

```powershell
ai --transcribe audio.wav
```

Flow:
1. ARGO transcribes the audio using Whisper
2. Displays: "Here's what I heard: '<transcript>'. Proceed? (yes/no)"
3. You confirm or reject the transcript
4. If confirmed: ARGO processes the transcript as a query
5. If rejected: Re-record and try again

**With session persistence:**

```powershell
ai --transcribe audio1.wav --session meeting
ai --transcribe audio2.wav --session meeting
```

Both transcriptions will be stored in the same session and can reference each other.

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
