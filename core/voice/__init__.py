"""Smooth Voice: ARGO's live conversation path over LiveKit + OpenAI Realtime.

``livekit_realtime_agent.py`` at the repo root is only the launcher. The
parts live here, one concern per module:

    worker.py        process lifecycle: build the AgentServer, clear stale
                     agents, drain on request, single-instance lock
    session.py       one room session, start to finish
    agent.py         ArgoRealtimeAgent - instructions, memory, core tools
    tools.py         the capability tools the model can call, by domain
    model.py         the OpenAI realtime model, turn detection, mic filter
    phrase_gates.py  "stop" interrupts and the optional sleep/wake gate
    activity.py      what was heard and said, into the log and event stream
    avatars.py       optional avatar video; never allowed to cost ARGO her voice

The classic (offline) path is ``core/pipeline.py`` and shares none of this.
"""
