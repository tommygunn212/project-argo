"""Jellyfin to SQLite ingest (owns schema creation)."""

import time
import logging
from pathlib import Path
from typing import Dict, List

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)
except Exception:
    pass

from core.database import MusicDatabase, init_schema, music_db_exists
from core.config import MUSIC_DB_PATH
from core.jellyfin_provider import get_jellyfin_provider

logger = logging.getLogger(__name__)
LOCK_FILE = Path("data/.ingest.lock")



def ingest_jellyfin_library() -> Dict[str, int]:
    if LOCK_FILE.exists():
        logger.warning("[JELLYFIN] Ingest already running (lock file present)")
        return {"ingested": 0, "skipped": 0, "errors": 0, "locked": 1}

    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOCK_FILE.write_text(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), encoding="utf-8")

    try:
        logger.info("[DB] Creating schema")
        logger.info("[DB] Path: %s", MUSIC_DB_PATH)
        init_schema(MUSIC_DB_PATH)

        provider = get_jellyfin_provider()
        start = time.perf_counter()
        logger.info("[JELLYFIN] Fetching artists/albums/tracks")
        tracks = provider.load_music_library()
        duration_ms = int((time.perf_counter() - start) * 1000)
        logger.info("[JELLYFIN] Fetched %s tracks in %sms", len(tracks), duration_ms)

        db = MusicDatabase()
        is_first = db.count_tracks() == 0
        ingest_result = db.ingest_jellyfin_tracks(tracks, incremental=not is_first)

        anomalies = getattr(provider, "anomalies", [])
        if anomalies:
            for anomaly in anomalies:
                try:
                    db.record_ingest_anomaly(
                        jellyfin_id=anomaly.get("jellyfin_id"),
                        issue=anomaly.get("issue"),
                        raw_name=anomaly.get("raw_name"),
                        path=anomaly.get("path"),
                    )
                except Exception:
                    pass

        logger.info(
            "[DB] Inserted/updated counts: ingested=%s skipped=%s errors=%s",
            ingest_result.get("ingested"),
            ingest_result.get("skipped"),
            ingest_result.get("errors"),
        )
        logger.info("[DB] Ingest complete")
        return ingest_result
    finally:
        if LOCK_FILE.exists():
            try:
                LOCK_FILE.unlink()
            except Exception:
                pass


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    result = ingest_jellyfin_library()
    print(result)
