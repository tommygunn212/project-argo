# Advanced Jellyfin Music Search for ARGO

## Overview

ARGO can now handle complex music requests using Jellyfin's advanced query filters. Instead of pulling 10,000 tracks and guessing which one you want, ARGO sends **specific filters to the Jellyfin server** and gets back only the matching results.

## How It Works

### 1. Voice Command → Intent Parsing
```
User: "Play metal from 1984"
Parser detects: music intent with keyword="metal from 1984"
```

### 2. Keyword → Structured Parameters
```
Parser extracts:
- Genre: Metal
- Year: 1984
- Artist: (not specified)
```

### 3. Jellyfin Server-Side Search
```python
advanced_search(
    genre="Metal",      # Filter by genre
    year=1984,          # Filter by year  
    artist=None         # No artist filter
)
```

### 4. Results Returned
```
Found 2 matching Metal tracks from 1984:
1. Ratt - Wanted Man
2. Ratt - The Morning After
```

## Voice Commands Supported

### By Genre
- "Play metal"
- "Play some punk rock"
- "Play classic rock"
- "Play house music"

### By Year
- "Play music from 1984"
- "Play songs from the 80s"
- "Play 1980"

### By Artist
- "Play Alice Cooper"
- "Play Led Zeppelin"
- "Play Metallica"

### Combined
- "Play metal from 1984" (Genre + Year)
- "Play Alice Cooper from 1972" (Artist + Year)
- "Play punk rock from 1977" (Genre + Year)
- "Play classic rock" (Compound Genre)

## Test Results

All voice command patterns tested successfully:

| Command | Type | Results |
|---------|------|---------|
| "play metal from 1984" | Genre + Year | 2 tracks found |
| "play alice cooper" | Artist | 23 tracks found |
| "play punk rock" | Compound Genre | 18 tracks found |
| "play rock from 1980" | Genre + Year | 10 tracks found |
| "play some heavy metal" | Genre (with filler) | 186 tracks found |

## Implementation Details

### `advanced_search()` Method
Located in `core/jellyfin_provider.py`

```python
def advanced_search(self, query_text=None, year=None, genre=None, artist=None):
    """
    Query Jellyfin API with specific filters.
    
    Args:
        query_text: General search term (fallback)
        year: Production year filter (e.g., 1984)
        genre: Genre filter (e.g., "Metal", "Rock")
        artist: Artist name filter
    
    Returns:
        List of matching tracks
    """
```

### `_parse_music_keyword()` Method
Located in `core/music_player.py`

Extracts structured parameters from natural language:
- Recognizes 20+ genre keywords
- Handles year patterns ("1984", "from 80s", "from 1980")
- Removes filler words ("play", "some", "music", etc.)
- Maps genre aliases to canonical names

### Integration Point
In `play_by_keyword()`:
```python
parsed = self._parse_music_keyword(keyword)

# Call advanced search with extracted filters
tracks = self.jellyfin_provider.advanced_search(
    query_text=None,  # IMPORTANT: Don't use query_text with filters
    year=parsed.get("year"),
    genre=parsed.get("genre"),
    artist=parsed.get("artist")
)
```

## Why This Matters

**Before:** ARGO loaded 10,000 tracks, sorted through them, and often fell back to random selection
**After:** ARGO asks Jellyfin "give me Metal tracks from 1984" and gets 2 results instantly

### Performance
- Zero indexing delay
- Server does the filtering (fast, scalable)
- Smaller result sets (easier to pick from)
- No cache rebuilds needed

## Genre Mapping

Jellyfin genre names (case-sensitive):
- Metal, Rock, Punk, Pop, Soul, R&B
- Jazz, Blues, Country, Folk, Americana
- Electronic, House, Techno
- Hip-Hop, Rap, Indie, Alternative
- New Wave, Glam Rock, Punk Rock, Alternative Rock

## Files Modified

1. **core/jellyfin_provider.py**
   - Added `advanced_search()` method with year/genre/artist filters
   - Full Jellyfin API integration

2. **core/music_player.py**
   - Added `_parse_music_keyword()` method
   - Updated `play_by_keyword()` to use advanced search
   - Supports both local and Jellyfin modes

3. **core/music_player.py** (Bug fix)
   - Fixed `_play_jellyfin_track()`: added missing `track` parameter to `set_artist_mode()`

## Testing

Run verification scripts:

```bash
# Test keyword parsing
python scripts/test_advanced_search.py

# Test Jellyfin API integration  
python scripts/test_jellyfin_advanced_search.py

# Test complete voice -> music flow
python scripts/test_voice_to_music_flow.py
```

All tests pass ✓

## Next Steps

1. **Run the GUI launcher** to test voice commands live
2. **Say commands** like "Play metal from 1984"
3. **Music will stream** from Jellyfin with instant filtering
4. **Skip/Next works** to play similar tracks

## Known Limitations

- Genre names must match Jellyfin's library metadata
- Year filtering requires tracks to have ProductionYear set
- Artist filtering uses partial matching (case-insensitive)
- Some genre aliases (e.g., "heavy metal" → "Metal") are lossy

## Configuration

No configuration needed - uses existing .env:
```
MUSIC_SOURCE=jellyfin
JELLYFIN_URL=http://localhost:8096
JELLYFIN_API_KEY=...
JELLYFIN_USER_ID=...
```
