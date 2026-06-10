"""SQLite database layer for persistent song library storage."""

import os
import sqlite3
import threading

from biaoke.lib.get_platform import get_data_directory

_SCHEMA = """
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS songs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT UNIQUE NOT NULL,
    youtube_id TEXT,
    format TEXT NOT NULL,
    artist TEXT,
    title TEXT,
    variant TEXT,
    year INTEGER,
    genre TEXT,
    metadata_status TEXT DEFAULT 'pending',
    enrichment_attempts INTEGER DEFAULT 0,
    last_enrichment_attempt TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_youtube_id ON songs(youtube_id);
CREATE INDEX IF NOT EXISTS idx_artist ON songs(artist);
CREATE INDEX IF NOT EXISTS idx_title ON songs(title);
CREATE INDEX IF NOT EXISTS idx_metadata_status ON songs(metadata_status);

CREATE TABLE IF NOT EXISTS coach_tracks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_type TEXT NOT NULL,
    source_url TEXT,
    source_id TEXT,
    display_title TEXT NOT NULL,
    artist TEXT,
    title TEXT,
    duration_seconds REAL,
    file_path TEXT,
    status TEXT NOT NULL DEFAULT 'queued',
    quality_status TEXT NOT NULL DEFAULT 'unknown',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source_type, source_id)
);

CREATE INDEX IF NOT EXISTS idx_coach_tracks_source ON coach_tracks(source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_coach_tracks_status ON coach_tracks(status);
CREATE INDEX IF NOT EXISTS idx_coach_tracks_title ON coach_tracks(title);

CREATE TABLE IF NOT EXISTS coach_assets (
    track_id INTEGER PRIMARY KEY,
    original_audio_path TEXT,
    instrumental_audio_path TEXT,
    vocal_reference_path TEXT,
    guide_path TEXT,
    lyrics_path TEXT,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(track_id) REFERENCES coach_tracks(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS coach_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    track_id INTEGER NOT NULL,
    stage TEXT NOT NULL,
    status TEXT NOT NULL,
    progress REAL DEFAULT 0,
    error TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    started_at TEXT,
    finished_at TEXT,
    FOREIGN KEY(track_id) REFERENCES coach_tracks(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_coach_jobs_track ON coach_jobs(track_id);
CREATE INDEX IF NOT EXISTS idx_coach_jobs_status ON coach_jobs(status);

CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


class KaraokeDatabase:
    """Persistent song library backed by SQLite.

    Pure data layer with no filesystem operations. All paths are stored as
    native OS strings (str(path), never as_posix()).
    """

    def __init__(self, db_path: str | None = None) -> None:
        if db_path is None:
            db_path = os.path.join(get_data_directory(), "biaoke.db")
        self._db_path = db_path
        # All operations (including reads) share a single connection, so the
        # lock is required for thread safety -- Python's sqlite3.Connection is
        # not thread-safe even with check_same_thread=False. WAL mode benefits
        # crash recovery and write performance; Python-level read concurrency
        # would require separate connections per reader.
        self._lock = threading.Lock()
        self._conn = self._connect()
        self._create_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _create_schema(self) -> None:
        self._conn.executescript(_SCHEMA)
        with self._conn:
            self._conn.execute("PRAGMA user_version = 2")

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def get_all_song_paths(self) -> list[str]:
        """Return all song file paths (unsorted; SongList handles sort order)."""
        with self._lock:
            rows = self._conn.execute("SELECT file_path FROM songs").fetchall()
            return [row[0] for row in rows]

    def get_song_count(self) -> int:
        """Return the total number of songs in the library."""
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM songs").fetchone()[0]

    def list_coach_tracks(self, limit: int = 100, status: str | None = None) -> list[dict]:
        """Return coach preparation tracks, newest first."""
        limit = max(1, min(int(limit), 500))
        with self._lock:
            if status:
                rows = self._conn.execute(
                    """
                    SELECT *
                    FROM coach_tracks
                    WHERE status = ?
                    ORDER BY updated_at DESC, id DESC
                    LIMIT ?
                    """,
                    (status, limit),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    """
                    SELECT *
                    FROM coach_tracks
                    ORDER BY updated_at DESC, id DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            return [_row_to_dict(row) for row in rows]

    def get_coach_track(self, track_id: int) -> dict | None:
        """Return a coach track by id."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM coach_tracks WHERE id = ?",
                (track_id,),
            ).fetchone()
            return _row_to_dict(row) if row else None

    def find_coach_track_by_source(self, source_type: str, source_id: str) -> dict | None:
        """Return a coach track by stable source identity."""
        with self._lock:
            row = self._conn.execute(
                """
                SELECT *
                FROM coach_tracks
                WHERE source_type = ? AND source_id = ?
                """,
                (source_type, source_id),
            ).fetchone()
            return _row_to_dict(row) if row else None

    def upsert_coach_track(
        self,
        *,
        source_type: str,
        source_url: str | None,
        source_id: str,
        display_title: str,
        artist: str | None = None,
        title: str | None = None,
        duration_seconds: float | None = None,
        file_path: str | None = None,
        status: str = "queued",
    ) -> dict:
        """Insert or update a coach preparation track."""
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO coach_tracks (
                    source_type,
                    source_url,
                    source_id,
                    display_title,
                    artist,
                    title,
                    duration_seconds,
                    file_path,
                    status,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(source_type, source_id) DO UPDATE SET
                    source_url = excluded.source_url,
                    display_title = excluded.display_title,
                    artist = COALESCE(excluded.artist, coach_tracks.artist),
                    title = COALESCE(excluded.title, coach_tracks.title),
                    duration_seconds = COALESCE(
                        excluded.duration_seconds,
                        coach_tracks.duration_seconds
                    ),
                    file_path = COALESCE(excluded.file_path, coach_tracks.file_path),
                    status = excluded.status,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    source_type,
                    source_url,
                    source_id,
                    display_title,
                    artist,
                    title,
                    duration_seconds,
                    file_path,
                    status,
                ),
            )
            row = self._conn.execute(
                """
                SELECT *
                FROM coach_tracks
                WHERE source_type = ? AND source_id = ?
                """,
                (source_type, source_id),
            ).fetchone()
            return _row_to_dict(row)

    def update_coach_track(
        self,
        track_id: int,
        *,
        status: str | None = None,
        quality_status: str | None = None,
        file_path: str | None = None,
    ) -> dict | None:
        """Update mutable coach track fields and return the updated track."""
        assignments = []
        values: list = []
        if status is not None:
            assignments.append("status = ?")
            values.append(status)
        if quality_status is not None:
            assignments.append("quality_status = ?")
            values.append(quality_status)
        if file_path is not None:
            assignments.append("file_path = ?")
            values.append(file_path)
        if not assignments:
            return self.get_coach_track(track_id)

        assignments.append("updated_at = CURRENT_TIMESTAMP")
        values.append(track_id)
        with self._lock, self._conn:
            self._conn.execute(
                f"UPDATE coach_tracks SET {', '.join(assignments)} WHERE id = ?",
                values,
            )
        return self.get_coach_track(track_id)

    def set_coach_assets(
        self,
        track_id: int,
        *,
        original_audio_path: str | None = None,
        instrumental_audio_path: str | None = None,
        vocal_reference_path: str | None = None,
        guide_path: str | None = None,
        lyrics_path: str | None = None,
    ) -> dict:
        """Upsert asset paths for a coach track."""
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO coach_assets (
                    track_id,
                    original_audio_path,
                    instrumental_audio_path,
                    vocal_reference_path,
                    guide_path,
                    lyrics_path,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(track_id) DO UPDATE SET
                    original_audio_path = COALESCE(
                        excluded.original_audio_path,
                        coach_assets.original_audio_path
                    ),
                    instrumental_audio_path = COALESCE(
                        excluded.instrumental_audio_path,
                        coach_assets.instrumental_audio_path
                    ),
                    vocal_reference_path = COALESCE(
                        excluded.vocal_reference_path,
                        coach_assets.vocal_reference_path
                    ),
                    guide_path = COALESCE(excluded.guide_path, coach_assets.guide_path),
                    lyrics_path = COALESCE(excluded.lyrics_path, coach_assets.lyrics_path),
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    track_id,
                    original_audio_path,
                    instrumental_audio_path,
                    vocal_reference_path,
                    guide_path,
                    lyrics_path,
                ),
            )
            row = self._conn.execute(
                "SELECT * FROM coach_assets WHERE track_id = ?",
                (track_id,),
            ).fetchone()
            return _row_to_dict(row)

    def get_coach_assets(self, track_id: int) -> dict | None:
        """Return asset paths for a coach track."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM coach_assets WHERE track_id = ?",
                (track_id,),
            ).fetchone()
            return _row_to_dict(row) if row else None

    def delete_coach_track(self, track_id: int) -> bool:
        """Delete a coach track and its preparation metadata."""
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT id FROM coach_tracks WHERE id = ?",
                (track_id,),
            ).fetchone()
            if not row:
                return False
            self._conn.execute("DELETE FROM coach_jobs WHERE track_id = ?", (track_id,))
            self._conn.execute("DELETE FROM coach_assets WHERE track_id = ?", (track_id,))
            self._conn.execute("DELETE FROM coach_tracks WHERE id = ?", (track_id,))
            return True

    def find_coach_track_by_media_path(self, file_path: str) -> dict | None:
        """Return a coach track whose original/stem/queue path matches file_path."""
        with self._lock:
            row = self._conn.execute(
                """
                SELECT coach_tracks.*
                FROM coach_tracks
                LEFT JOIN coach_assets ON coach_assets.track_id = coach_tracks.id
                WHERE coach_tracks.file_path = ?
                   OR coach_assets.original_audio_path = ?
                   OR coach_assets.instrumental_audio_path = ?
                   OR coach_assets.vocal_reference_path = ?
                ORDER BY coach_tracks.updated_at DESC, coach_tracks.id DESC
                LIMIT 1
                """,
                (file_path, file_path, file_path, file_path),
            ).fetchone()
            return _row_to_dict(row) if row else None

    def create_coach_job(
        self,
        track_id: int,
        *,
        stage: str,
        status: str = "queued",
        progress: float = 0,
        error: str | None = None,
    ) -> dict:
        """Create a coach preparation job."""
        with self._lock, self._conn:
            cursor = self._conn.execute(
                """
                INSERT INTO coach_jobs (track_id, stage, status, progress, error)
                VALUES (?, ?, ?, ?, ?)
                """,
                (track_id, stage, status, progress, error),
            )
            job_id = cursor.lastrowid
            row = self._conn.execute("SELECT * FROM coach_jobs WHERE id = ?", (job_id,)).fetchone()
            return _row_to_dict(row)

    def update_coach_job(
        self,
        job_id: int,
        *,
        stage: str | None = None,
        status: str | None = None,
        progress: float | None = None,
        error: str | None = None,
    ) -> dict | None:
        """Update a coach preparation job and return it."""
        assignments = []
        values: list = []
        if stage is not None:
            assignments.append("stage = ?")
            values.append(stage)
        if status is not None:
            assignments.append("status = ?")
            values.append(status)
            if status == "running":
                assignments.append("started_at = COALESCE(started_at, CURRENT_TIMESTAMP)")
            if status in {"complete", "failed"}:
                assignments.append("finished_at = CURRENT_TIMESTAMP")
        if progress is not None:
            assignments.append("progress = ?")
            values.append(max(0, min(100, float(progress))))
        if error is not None:
            assignments.append("error = ?")
            values.append(error)
        if not assignments:
            return self.get_coach_job(job_id)

        assignments.append("updated_at = CURRENT_TIMESTAMP")
        values.append(job_id)
        with self._lock, self._conn:
            self._conn.execute(
                f"UPDATE coach_jobs SET {', '.join(assignments)} WHERE id = ?",
                values,
            )
        return self.get_coach_job(job_id)

    def get_coach_job(self, job_id: int) -> dict | None:
        """Return a coach preparation job by id."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM coach_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            return _row_to_dict(row) if row else None

    def list_coach_jobs(self, track_id: int | None = None, limit: int = 100) -> list[dict]:
        """Return coach preparation jobs, newest first."""
        limit = max(1, min(int(limit), 500))
        with self._lock:
            if track_id is None:
                rows = self._conn.execute(
                    """
                    SELECT *
                    FROM coach_jobs
                    ORDER BY updated_at DESC, id DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    """
                    SELECT *
                    FROM coach_jobs
                    WHERE track_id = ?
                    ORDER BY updated_at DESC, id DESC
                    LIMIT ?
                    """,
                    (track_id, limit),
                ).fetchall()
            return [_row_to_dict(row) for row in rows]

    def get_next_coach_job(
        self,
        *,
        stage: str,
        status: str = "queued",
    ) -> dict | None:
        """Return the oldest queued coach job matching stage/status."""
        with self._lock:
            row = self._conn.execute(
                """
                SELECT *
                FROM coach_jobs
                WHERE stage = ? AND status = ?
                ORDER BY id ASC
                LIMIT 1
                """,
                (stage, status),
            ).fetchone()
            return _row_to_dict(row) if row else None

    def requeue_interrupted_coach_analysis_jobs(self) -> int:
        """Requeue analysis jobs that were interrupted by a process restart."""
        analysis_stages = (
            "analyze_pending",
            "build_guide",
            "separate_stems",
            "extract_melody",
            "align_lyrics",
            "write_coach_guide",
        )
        placeholders = ", ".join("?" for _ in analysis_stages)
        with self._lock, self._conn:
            cursor = self._conn.execute(
                f"""
                UPDATE coach_jobs
                SET stage = 'analyze_pending',
                    status = 'queued',
                    progress = 0,
                    error = NULL,
                    started_at = NULL,
                    finished_at = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE status = 'running'
                  AND stage IN ({placeholders})
                """,
                analysis_stages,
            )
            return int(cursor.rowcount)

    # ------------------------------------------------------------------
    # Batch write operations (used by LibraryScanner)
    # ------------------------------------------------------------------

    def insert_songs(self, songs: list[dict]) -> None:
        """Batch-insert song records. Silently ignores duplicate file_paths."""
        with self._lock, self._conn:
            self._conn.executemany(
                """
                INSERT OR IGNORE INTO songs (file_path, youtube_id, format)
                VALUES (:file_path, :youtube_id, :format)
                """,
                songs,
            )

    def update_paths(self, moves: list[tuple[str, str]]) -> None:
        """Batch-update file paths for moved songs.

        Args:
            moves: List of (old_path, new_path) tuples.
        """
        with self._lock, self._conn:
            self._conn.executemany(
                "UPDATE songs SET file_path = ?, updated_at = CURRENT_TIMESTAMP WHERE file_path = ?",
                [(new, old) for old, new in moves],
            )

    def delete_by_paths(self, file_paths: list[str]) -> None:
        """Batch-delete songs by file path."""
        with self._lock, self._conn:
            self._conn.executemany(
                "DELETE FROM songs WHERE file_path = ?",
                [(p,) for p in file_paths],
            )

    def apply_scan_diff(
        self,
        moves: list[tuple[str, str]],
        inserts: list[dict],
        deletes: list[str],
    ) -> None:
        """Apply a complete scan diff atomically in a single transaction."""
        with self._lock, self._conn:
            if moves:
                self._conn.executemany(
                    "UPDATE songs SET file_path = ?, updated_at = CURRENT_TIMESTAMP WHERE file_path = ?",
                    [(new, old) for old, new in moves],
                )
            if inserts:
                self._conn.executemany(
                    """
                    INSERT OR IGNORE INTO songs (file_path, youtube_id, format)
                    VALUES (:file_path, :youtube_id, :format)
                    """,
                    inserts,
                )
            if deletes:
                self._conn.executemany(
                    "DELETE FROM songs WHERE file_path = ?",
                    [(p,) for p in deletes],
                )

    # ------------------------------------------------------------------
    # Single-record write operations (delegate to batch methods)
    # ------------------------------------------------------------------

    def delete_by_path(self, file_path: str) -> None:
        """Delete a single song by file path (UI-triggered delete)."""
        self.delete_by_paths([file_path])

    def update_path(self, old_path: str, new_path: str) -> None:
        """Update a single song's file path (UI-triggered rename)."""
        self.update_paths([(old_path, new_path)])

    # ------------------------------------------------------------------
    # Metadata (app-level key-value store)
    # ------------------------------------------------------------------

    def get_metadata(self, key: str) -> str | None:
        """Return the value for a metadata key, or None if not set."""
        with self._lock:
            row = self._conn.execute("SELECT value FROM metadata WHERE key = ?", (key,)).fetchone()
            return row[0] if row else None

    def set_metadata(self, key: str, value: str) -> None:
        """Set a metadata key-value pair (upsert)."""
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
                (key, value),
            )

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def check_integrity(self) -> tuple[bool, str]:
        """Run PRAGMA integrity_check. Returns (ok, message)."""
        with self._lock:
            result = self._conn.execute("PRAGMA integrity_check").fetchone()[0]
            return result == "ok", result

    def close(self) -> None:
        """Close the database connection."""
        with self._lock:
            self._conn.close()


def _row_to_dict(row: sqlite3.Row) -> dict:
    return dict(row)
