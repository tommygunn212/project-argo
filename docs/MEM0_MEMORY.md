# Mem0 Long-Term Memory

Status: optional companion layer.

ARGO still keeps local memory in SQLite by default, with PostgreSQL available through the existing memory backend. Mem0 adds cloud semantic recall for selected durable facts and preferences. It is not used as the only source of truth.

## Setup

Set the API key in the ignored local environment file:

```powershell
MEM0_API_KEY="..."
```

Optional switches:

```powershell
ARGO_MEM0_ENABLED="true"
ARGO_MEM0_USER_ID="tommy"
ARGO_MEM0_SEARCH_LIMIT="5"
ARGO_MEM0_CONTEXT_CHARS="1200"
ARGO_MEM0_AUTO_STORE_TURNS="false"
```

With `MEM0_API_KEY` present, Mem0 is enabled unless `ARGO_MEM0_ENABLED` is set to `false`.

## What Gets Stored

By default ARGO sends only selected durable facts to Mem0:

- explicit memory writes after confirmation
- brain memory facts such as "remember Tommy prefers fast back-and-forth"
- implicit identity facts that ARGO already stores locally

Completed transcript turns stay in the local memory backend unless `ARGO_MEM0_AUTO_STORE_TURNS=true` is explicitly enabled.

## Recall Flow

When ARGO builds context for an LLM turn, it now gathers:

```text
ArgoBrain facts and current state
-> Mem0 semantic long-term memory
-> local durable conversation-turn recall
```

This keeps quick local state available while letting Mem0 surface useful older preferences and facts by meaning instead of exact text.

## Privacy Boundary

The Mem0 adapter refuses obvious secrets such as tokens, API keys, passwords, and private keys before sending a fact. Local SQLite/PostgreSQL remain the durable audit trail and fallback path.
