"""
Music Resolver

Resolves human music requests into local metadata matches using a strict cascade.
Local authority: the index decides the file, never the LLM.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import os
import re
from difflib import SequenceMatcher
from typing import Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class Resolution:
    tracks: List[Dict]
    clarification: Optional[str] = None
    reason: str = ""


class MusicResolver:
    def __init__(self, tracks: List[Dict]):
        self.tracks = tracks
        self.aliases = self._load_aliases()

    def resolve(self, query: str, llm_interpret: Optional[Callable[[str], Optional[Dict]]] = None) -> Resolution:
        clean = self._normalize(query)
        if not clean:
            return Resolution([], None, "empty")

        # Step 1: Alias cache
        alias = self.aliases.get(clean)
        if alias:
            resolved = self._resolve_alias(alias)
            if resolved.tracks or resolved.clarification:
                return resolved

        # Step 2: Era/year filter (regex-solvable, no LLM)
        era_filter = self._extract_era_filter(clean)
        if era_filter:
            tracks = self._filter_by_era(era_filter)
            if tracks:
                return Resolution(tracks, None, "era")

        # Step 3: Exact metadata match
        exact = self._exact_match(clean)
        if exact.tracks or exact.clarification:
            return exact

        # Step 4: Fuzzy token match
        fuzzy = self._fuzzy_match(clean)
        if fuzzy.tracks or fuzzy.clarification:
            return fuzzy

        # Step 5: LLM intent extraction (interpret only)
        if llm_interpret:
            parsed = llm_interpret(query)
            if parsed:
                interpreted = self._resolve_interpretation(parsed)
                if interpreted.tracks or interpreted.clarification:
                    return interpreted

        return Resolution([], None, "none")

    # ------------------------------------------------------------
    # Alias handling
    # ------------------------------------------------------------

    def _load_aliases(self) -> Dict[str, Dict]:
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        path = os.path.join(base_dir, "music_aliases.json")
        if not os.path.exists(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return {}

        aliases = {}
        for key, value in data.items():
            if not isinstance(value, dict):
                continue
            aliases[self._normalize(key)] = value
        return aliases

    def _resolve_alias(self, alias: Dict) -> Resolution:
        scope = alias.get("scope")
        target = alias.get("target")
        boost_album = alias.get("boost_album")
        title = alias.get("title")
        artist = alias.get("artist")

        if boost_album:
            tracks = self._filter_by_album(boost_album)
            if tracks:
                return Resolution(tracks, None, "alias_boost_album")

        if scope == "album" and title:
            return Resolution(self._filter_by_album(title), None, "alias_album")
        if scope == "song" and target:
            tracks = self._filter_by_song(target)
            if artist:
                tracks = self._filter_by_artist_and_tracks(artist, tracks)
            return Resolution(tracks, None, "alias_song")
        if scope == "artist" and target:
            return Resolution(self._filter_by_artist(target), None, "alias_artist")

        return Resolution([], None, "alias_no_match")

    # ------------------------------------------------------------
    # Exact/fuzzy matching
    # ------------------------------------------------------------

    def _exact_match(self, clean: str) -> Resolution:
        album_tracks = self._filter_by_album(clean)
        if album_tracks:
            return Resolution(album_tracks, None, "exact_album")

        artist_tracks = self._filter_by_artist(clean)
        if artist_tracks:
            return Resolution(artist_tracks, None, "exact_artist")

        song_tracks = self._filter_by_song(clean)
        if song_tracks:
            return Resolution(song_tracks, None, "exact_song")

        return Resolution([], None, "exact_none")

    def _fuzzy_match(self, clean: str) -> Resolution:
        candidates = self._collect_candidates()
        if not candidates:
            return Resolution([], None, "fuzzy_none")

        scored = []
        for label, value in candidates:
            ratio = self._ratio(clean, value)
            scored.append((ratio, label, value))

        scored.sort(reverse=True, key=lambda item: item[0])
        best_ratio, best_label, best_value = scored[0]
        if best_ratio < 0.85:
            return Resolution([], None, "fuzzy_below_threshold")

        if len(scored) > 1:
            second_ratio, second_label, second_value = scored[1]
            if second_ratio >= 0.85 and abs(best_ratio - second_ratio) <= 0.02:
                clarification = self._format_clarification(best_label, best_value, second_label, second_value)
                return Resolution([], clarification, "fuzzy_clarify")

        return self._resolve_best_candidate(best_label, best_value, "fuzzy")

    # ------------------------------------------------------------
    # Era/vibe handling
    # ------------------------------------------------------------

    def _extract_era_filter(self, clean: str) -> Optional[Dict]:
        genre_map = {
            "rock": "rock",
            "punk": "punk",
            "metal": "metal",
            "pop": "pop",
            "jazz": "jazz",
            "blues": "blues",
            "rap": "rap",
            "hip hop": "hip hop",
            "hiphop": "hip hop",
            "electronic": "electronic",
            "dance": "dance",
            "indie": "indie",
            "alternative": "alternative",
        }

        era_map = {
            "70s bowie": {"artist": "David Bowie", "year_start": 1970, "year_end": 1979},
            "early metallica": {"artist": "Metallica", "year_start": 1981, "year_end": 1986},
            "cbgb stuff": {"genre": "punk", "year_start": 1974, "year_end": 1980},
            "cbgb": {"genre": "punk", "year_start": 1974, "year_end": 1980},
            "new york club": {"genre": "punk", "year_start": 1974, "year_end": 1980},
        }

        for phrase, mapping in era_map.items():
            if phrase in clean:
                return dict(mapping)

        decade_match = re.search(r"\b(\d{2})s\b", clean)
        year_match = re.search(r"\b(19|20)\d{2}\b", clean)

        if year_match:
            year = int(year_match.group())
            return {"year_start": year, "year_end": year, "genre": self._extract_genre(clean, genre_map)}

        if decade_match:
            decade = int(decade_match.group(1))
            year_start = 1900 + decade if decade >= 50 else 2000 + decade
            return {"year_start": year_start, "year_end": year_start + 9, "genre": self._extract_genre(clean, genre_map)}

        return None

    def _extract_genre(self, clean: str, genre_map: Dict[str, str]) -> Optional[str]:
        for key, value in genre_map.items():
            if key in clean:
                return value
        return None

    def _filter_by_era(self, era: Dict) -> List[Dict]:
        year_start = era.get("year_start")
        year_end = era.get("year_end")
        genre = era.get("genre")
        artist = era.get("artist")

        tracks = self.tracks
        if artist:
            tracks = self._filter_by_artist_and_tracks(artist, tracks)
        if genre:
            tracks = self._filter_by_genre_and_tracks(genre, tracks)
        if year_start is not None and year_end is not None:
            tracks = [t for t in tracks if t.get("year") and year_start <= t.get("year") <= year_end]

        return tracks

    # ------------------------------------------------------------
    # LLM interpretation
    # ------------------------------------------------------------

    def _resolve_interpretation(self, parsed: Dict) -> Resolution:
        artist = parsed.get("artist")
        song = parsed.get("song")
        album = parsed.get("album")
        era = parsed.get("era")

        if era and isinstance(era, str):
            clean_era = self._normalize(era)
            if artist:
                clean_era = f"{clean_era} {self._normalize(artist)}".strip()
            era_filter = self._extract_era_filter(clean_era)
            if era_filter:
                if artist:
                    era_filter["artist"] = artist
                tracks = self._filter_by_era(era_filter)
                if tracks:
                    return Resolution(tracks, None, "llm_era")

        if album:
            tracks = self._filter_by_album(album)
            if tracks:
                return Resolution(tracks, None, "llm_album")

        if artist:
            tracks = self._filter_by_artist(artist)
            if tracks:
                return Resolution(tracks, None, "llm_artist")

        if song:
            tracks = self._filter_by_song(song)
            if tracks:
                return Resolution(tracks, None, "llm_song")

        # Fuzzy fallback on parsed fields
        for term in (album, song, artist):
            if term:
                fuzzy = self._fuzzy_match(self._normalize(term))
                if fuzzy.tracks or fuzzy.clarification:
                    fuzzy.reason = "llm_fuzzy"
                    return fuzzy

        return Resolution([], None, "llm_no_match")

    # ------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------

    def _normalize(self, text: str) -> str:
        text = text.lower().strip()
        text = text.replace("’", "'")
        text = re.sub(r"[^a-z0-9\s]", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def _ratio(self, a: str, b: str) -> float:
        return SequenceMatcher(None, a, b).ratio()

    def _collect_candidates(self) -> List[Tuple[str, str]]:
        candidates = []
        seen = set()
        for t in self.tracks:
            for label in ("artist", "album", "song"):
                value = t.get(label)
                if not value:
                    continue
                clean = self._normalize(str(value))
                key = (label, clean)
                if clean and key not in seen:
                    seen.add(key)
                    candidates.append((label, clean))
        return candidates

    def _format_clarification(self, label_a: str, value_a: str, label_b: str, value_b: str) -> str:
        def pretty(label: str, value: str) -> str:
            return f"{label} {value}"
        return f"I found {pretty(label_a, value_a)} and {pretty(label_b, value_b)}. Which one are you looking for?"

    def _resolve_best_candidate(self, label: str, value: str, reason: str) -> Resolution:
        if label == "album":
            return Resolution(self._filter_by_album(value), None, reason)
        if label == "artist":
            return Resolution(self._filter_by_artist(value), None, reason)
        if label == "song":
            return Resolution(self._filter_by_song(value), None, reason)
        return Resolution([], None, reason)

    def _filter_by_artist_and_tracks(self, artist: str, tracks: List[Dict]) -> List[Dict]:
        artist_clean = self._normalize(artist)
        return [t for t in tracks if t.get("artist") and self._normalize(t.get("artist")) == artist_clean]

    def _filter_by_genre_and_tracks(self, genre: str, tracks: List[Dict]) -> List[Dict]:
        genre_clean = self._normalize(genre)
        return [t for t in tracks if t.get("genre") and self._normalize(t.get("genre")) == genre_clean]

    def _filter_by_artist(self, artist: str) -> List[Dict]:
        return self._filter_by_artist_and_tracks(artist, self.tracks)

    def _filter_by_album(self, album: str) -> List[Dict]:
        album_clean = self._normalize(album)
        return [t for t in self.tracks if t.get("album") and self._normalize(t.get("album")) == album_clean]

    def _filter_by_song(self, song: str) -> List[Dict]:
        song_clean = self._normalize(song)
        return [t for t in self.tracks if t.get("song") and self._normalize(t.get("song")) == song_clean]
