# Hedra / LiveKit Avatar Notes

ARGO's realtime voice path can display a LiveKit remote video avatar in the
dashboard and voice panels. The local canvas avatar remains the fallback.

## Current Status

LiveKit's current Hedra plugin documentation says Hedra sunset the old Realtime
Avatar product on April 15, 2026, and the newest `livekit-plugins-hedra` package
is now a disabled stub. The May 6 `ruxakK/cortana_companion` example works from
the older LiveKit 1.4 plugin line, so ARGO pins only `livekit-plugins-hedra` to
`1.4.6` while keeping the rest of the realtime stack on LiveKit Agents 1.5.

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

Optional participant identity:

```env
HEDRA_AVATAR_PARTICIPANT_IDENTITY=argo-hedra-avatar
```

`HEDRA_AVATAR_ID` is preferred if you already have an uploaded asset in Hedra.
`HEDRA_AVATAR_IMAGE` follows the May 6 companion pattern and uploads a local
portrait image at session start. Do not enable this path without a real
`HEDRA_API_KEY`; ARGO will log a warning and continue without avatar video.

## UI Behavior

When any remote LiveKit video track is subscribed, ARGO attaches it to both
avatar panels and labels the panel `LIVE AVATAR`. When the track leaves, ARGO
returns to the built-in `HEDRA DEFAULT` canvas portrait.
