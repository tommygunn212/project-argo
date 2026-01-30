class MockJellyfinProvider:
    def __init__(self):
        self._tracks = [
            {"artist": "Guns and Roses", "song": "Sweet Child O Mine", "year": 1987, "genre": "Rock"},
            {"artist": "Guns and Roses", "song": "Welcome to the Jungle", "year": 1987, "genre": "Rock"},
            {"artist": "The Police", "song": "Don't Stand So Close to Me", "year": 1980, "genre": "Rock"},
            {"artist": "The Clash", "song": "London Calling", "year": 1979, "genre": "Rock"},
            {"artist": "Joy Division", "song": "Disorder", "year": 1979, "genre": "New Wave"},
            {"artist": "Blondie", "song": "Heart of Glass", "year": 1978, "genre": "Rock"},
            {"artist": "The Cure", "song": "A Forest", "year": 1980, "genre": "Alternative"},
        ]

    def _match(self, track, value):
        if value is None:
            return True
        value_lower = str(value).lower()
        return value_lower in str(track).lower()

    def advanced_search(self, **kwargs):
        artist = kwargs.get("artist")
        song = kwargs.get("song")
        genre = kwargs.get("genre")
        year = kwargs.get("year")

        results = []
        for track in self._tracks:
            if artist and artist.lower() not in track["artist"].lower():
                continue
            if song and song.lower() not in track["song"].lower():
                continue
            if genre and genre.lower() not in track["genre"].lower():
                continue
            if year and int(year) != int(track["year"]):
                continue
            results.append(track)
        return results

    def search_by_keyword(self, keyword, *_args, **_kwargs):
        if not keyword:
            return []
        keyword_lower = str(keyword).lower()
        return [
            track for track in self._tracks
            if keyword_lower in track["artist"].lower()
            or keyword_lower in track["song"].lower()
            or keyword_lower in track["genre"].lower()
        ]
