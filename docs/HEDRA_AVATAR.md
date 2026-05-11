# Hedra / LiveKit Avatar Notes

ARGO's realtime voice path can display a LiveKit remote video avatar in the
dashboard and voice panels. The local canvas avatar remains the fallback.

## Current Status

LiveKit's Hedra plugin documentation now says Hedra sunset the old Realtime
Avatar product on April 15, 2026, and that the LiveKit Hedra plugin no longer
functions. Hedra's own docs still describe Live Avatar setup, so ARGO keeps a
feature-flagged hook for testing accounts where the service still works.

The core OpenAI Realtime voice loop does not depend on Hedra. If Hedra fails,
ARGO continues with normal realtime voice.

## Optional Environment

Set these only when testing Hedra:

```env
ARGO_HEDRA_AVATAR_ENABLED=true
HEDRA_API_KEY=...
HEDRA_AVATAR_ID=...
```

Alternative local image upload path:

```env
ARGO_HEDRA_AVATAR_ENABLED=true
HEDRA_API_KEY=...
HEDRA_AVATAR_IMAGE=assets/avatar/argo-avatar.jpg
```

Optional participant name:

```env
HEDRA_AVATAR_PARTICIPANT_NAME=argo-hedra-avatar
```

The `livekit.plugins.hedra` package must also be installed before enabling this
path. ARGO intentionally does not add that dependency to the default install
because the upstream integration is marked deprecated.

## UI Behavior

When any remote LiveKit video track is subscribed, ARGO attaches it to both
avatar panels and labels the panel `LIVE AVATAR`. When the track leaves, ARGO
returns to the built-in `HEDRA DEFAULT` canvas portrait.
