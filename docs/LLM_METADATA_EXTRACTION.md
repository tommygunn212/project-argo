# LLM Intent Parsing for ARGO Music Search

## Overview

The LLM is used **only** as a metadata parser when local resolution fails. It never selects files. Local index is authoritative.

## Resolution Order (Strict)

1. Alias cache (`music_aliases.json`)
2. Era/year filter (regex)
3. Exact metadata match (artist/album/song)
4. Fuzzy token match (>=85%)
5. LLM intent parse (metadata only)

If no match is found after parsing, ARGO reports a miss and does not play a random track.

## LLM Prompt Shape (Constrained)

```
You are a music metadata parser. Convert the user's yell into a JSON search object.
User: 'play that heroes song by bowie'
Output: {"artist": "David Bowie", "song": "Heroes", "album": null, "era": null}
User: 'play old metallica'
Output: {"artist": "Metallica", "song": null, "album": null, "era": "early"}
```

## Example Outcomes

| Request | Interpretation | Resolver Outcome |
|---------|----------------|------------------|
| "play that heroes song by bowie" | artist=David Bowie, song=Heroes | Song match (local) |
| "play old metallica" | artist=Metallica, era=early | Era filter (local) |
| "play the album with Starman on it" | album intent | Album match (local) or clarification |

## Files Involved

- **core/music_resolver.py** — LLM parsing is the last step
- **core/music_player.py** — Calls resolver and applies fail-safe

## Known Constraints

- LLM output must map to local metadata; no guessing
- If parsing returns ambiguous candidates, ARGO asks once then stops
