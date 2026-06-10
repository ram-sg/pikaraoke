"""Coach catalog preparation orchestration."""

from __future__ import annotations

import logging
import json
import os
import re
import shutil
from pathlib import Path
from threading import Event, Thread
from typing import Any

import requests

from biaoke.lib.events import EventSystem
from biaoke.lib.karaoke_database import KaraokeDatabase
from biaoke.lib.lyrics_alignment import ALIGNMENT_SCHEMA, ALIGNMENT_VERSION, with_vocal_activity_alignment
from biaoke.lib.scoring import ScoreAnalysisError, extract_melody_guide_from_media
from biaoke.lib.song_guide import write_song_guide
from biaoke.lib.song_guide import guide_path_for_media
from biaoke.lib.text_audio_alignment import build_word_alignment_from_transcript
from biaoke.lib.youtube_dl import get_youtube_id_from_url


COACH_GUIDE_SCHEMA = "biaoke.coach_guide"
COACH_GUIDE_VERSION = 1
COACH_GUIDE_SUFFIX = ".biaoke-coach.json"
DEFAULT_PREPARE_USER = "Biaoke Coach"
FAILED_STATUS = "failed"
NEEDS_REVIEW_STATUS = "needs_review"
PROCESSING_STATUS = "processing"
QUEUED_STATUS = "queued"
READY_STATUS = "ready"
DEFAULT_ANALYZER_POLL_SECONDS = 3.0
SCORING_SERVICE_ENV = "BIAOKE_SCORING_SERVICE_URL"
SEPARATE_STEMS_ENV = "BIAOKE_COACH_SEPARATE_STEMS"
DEMUCS_MODEL_ENV = "BIAOKE_COACH_DEMUCS_MODEL"
STEMS_TIMEOUT_ENV = "BIAOKE_COACH_STEMS_TIMEOUT"
TRANSCRIBE_TIMEOUT_ENV = "BIAOKE_COACH_TRANSCRIBE_TIMEOUT"
TRANSCRIBE_MODEL_ENV = "BIAOKE_COACH_TRANSCRIBE_MODEL"
ALIGN_TIMEOUT_ENV = "BIAOKE_COACH_ALIGN_TIMEOUT"
AI_REVIEW_PROVIDER_ENV = "AI_REVIEW_PROVIDER"
DEEPSEEK_API_KEY_ENV = "DEEPSEEK_API_KEY"
DEEPSEEK_BASE_URL_ENV = "DEEPSEEK_BASE_URL"
DEEPSEEK_MODEL_ENV = "DEEPSEEK_MODEL"
DEEPSEEK_REASONING_EFFORT_ENV = "DEEPSEEK_REASONING_EFFORT"
DEEPSEEK_THINKING_ENV = "DEEPSEEK_THINKING"
DEEPSEEK_TIMEOUT_ENV = "DEEPSEEK_TIMEOUT"
MIMO_API_KEY_ENV = "MIMO_API_KEY"
MIMO_COMPAT_API_KEY_ENV = "XIAOMI_MIMO_API_KEY"
MIMO_BASE_URL_ENV = "MIMO_BASE_URL"
MIMO_MODEL_ENV = "MIMO_MODEL"
MIMO_TIMEOUT_ENV = "MIMO_TIMEOUT"
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-pro"
DEFAULT_DEEPSEEK_REASONING_EFFORT = "high"
DEFAULT_MIMO_BASE_URL = "https://api.xiaomimimo.com/v1"
DEFAULT_MIMO_MODEL = "mimo-v2.5-pro"
PITCH_BANDS_CENTS = [25, 40, 60, 80, 100, 130, 160, 200, 250, 320]
TIMING_BANDS_MS = [40, 70, 100, 140, 180, 230, 290, 360, 450, 600]
LYRICS_DURATION_TOLERANCE_SECONDS = 12.0
LYRICS_DURATION_TOLERANCE_RATIO = 0.08
VOCAL_FILTER_LEAD_SECONDS = 0.12
VOCAL_FILTER_TAIL_SECONDS = 0.65
VOCAL_FILTER_MAX_SUSTAIN_EXTENSION_SECONDS = 5.0
VOCAL_FILTER_MERGE_GAP_SECONDS = 1.4
VOCAL_FILTER_MIN_WORD_CONFIDENCE = 0.25
VOCAL_FILTER_MIN_NOTE_SECONDS = 0.14
VOCAL_FILTER_LINE_BASE_SECONDS = 1.0
VOCAL_FILTER_LINE_SECONDS_PER_WORD = 0.8
VOCAL_FILTER_LINE_MIN_SECONDS = 2.6
VOCAL_FILTER_MIN_TRANSCRIPT_LINE_COVERAGE = 0.45
VOCAL_FILTER_PREFACE_MAX_GAP_SECONDS = 4.0
VOCAL_FILTER_PREFACE_MAX_NOTE_GAP_SECONDS = 0.65
VOCAL_FILTER_PREFACE_MIN_SECONDS = 0.45
VOCAL_FILTER_PREFACE_MIN_CONFIDENCE = 0.7
VOCAL_FILTER_VERSION = 4
AI_REVIEW_MIN_CONFIDENCE = 0.35
AI_REVIEW_EXISTING_LYRICS_MIN_TEXT_MATCH = 0.85
AI_REVIEW_MAX_LINES = 320
AI_REVIEW_MAX_PAINT_UNITS = 5000
AI_REVIEW_MAX_TRANSCRIPT_WORDS = 1200
AI_REVIEW_MAX_NOTES = 700
FORCED_ALIGNMENT_MIN_CONFIDENCE = 0.18
FORCED_ALIGNMENT_MIN_COVERAGE = 0.35
FORCED_ALIGNMENT_LINE_MIN_TRANSCRIPT_COVERAGE = 0.32
TRANSCRIPT_RETRY_MIN_ALIGNMENT_COVERAGE = 0.68
TRANSCRIPTION_PROMPT_MAX_CHARS = 2200


class CoachPreparationManager:
    """Registers tracks and follows acquisition jobs for coach mode."""

    def __init__(
        self,
        *,
        db: KaraokeDatabase,
        events: EventSystem,
        download_manager,
        download_path: str,
        analyzer_poll_seconds: float = DEFAULT_ANALYZER_POLL_SECONDS,
    ) -> None:
        self._db = db
        self._events = events
        self._download_manager = download_manager
        self._download_path = Path(download_path)
        self._analyzer_poll_seconds = max(0.5, float(analyzer_poll_seconds))
        self._worker_stop = Event()
        self._worker_thread: Thread | None = None

    def start(self) -> None:
        """Start the background coach analyzer worker."""
        if self._worker_thread and self._worker_thread.is_alive():
            return
        self._recover_interrupted_analysis_jobs()
        self._worker_thread = Thread(target=self._analyzer_loop, daemon=True)
        self._worker_thread.start()
        logging.debug("Coach preparation analyzer worker started")

    def stop(self) -> None:
        """Signal the background analyzer worker to stop."""
        self._worker_stop.set()

    def prepare_youtube(
        self,
        *,
        url: str,
        title: str | None = None,
        user: str | None = None,
    ) -> dict[str, Any]:
        """Create a coach preparation job for a YouTube/YouTube Music URL."""
        source_id = get_youtube_id_from_url(url) or url
        display_title = (title or url).strip()
        track = self._db.upsert_coach_track(
            source_type="youtube",
            source_url=url,
            source_id=source_id,
            display_title=display_title,
            title=display_title,
            status=QUEUED_STATUS,
        )
        job = self._db.create_coach_job(
            track["id"],
            stage="acquire",
            status=QUEUED_STATUS,
            progress=0,
        )

        self._download_manager.queue_download(
            url,
            enqueue=False,
            user=user or DEFAULT_PREPARE_USER,
            title=display_title,
            context={"coach_track_id": track["id"], "coach_job_id": job["id"]},
            download_subtitles=False,
        )
        self._events.emit("notification", f"Preparacao adicionada: {display_title}", "success")
        return {"track": track, "job": job}

    def register_local_file(self, file_path: str) -> dict[str, Any]:
        """Register an already-local media file as a coach preparation track."""
        path = Path(file_path)
        display_title = path.stem if path.name else file_path
        track = self._db.upsert_coach_track(
            source_type="local",
            source_url=str(path),
            source_id=str(path.resolve()) if path.exists() else str(path),
            display_title=display_title,
            title=display_title,
            file_path=str(path),
            status=PROCESSING_STATUS,
        )
        job = self._db.create_coach_job(
            track["id"],
            stage="analyze_pending",
            status=QUEUED_STATUS,
            progress=0,
        )
        self._db.set_coach_assets(
            track["id"],
            original_audio_path=str(path),
            lyrics_path=str(guide_path_for_media(path)),
        )
        return {"track": track, "job": job}

    def handle_download_started(self, context: dict[str, Any] | None) -> None:
        """Mark a coach acquisition job as running."""
        if not context:
            return
        job_id = context.get("coach_job_id")
        track_id = context.get("coach_track_id")
        if not job_id or not track_id:
            return
        self._db.update_coach_track(int(track_id), status=PROCESSING_STATUS)
        self._db.update_coach_job(
            int(job_id),
            stage="acquire",
            status="running",
            progress=5,
        )

    def handle_download_completed(
        self,
        song_path: str | None,
        context: dict[str, Any] | None,
        *_args,
    ) -> None:
        """Mark download acquisition complete and enqueue the future analyzer stage."""
        if not context:
            return
        job_id = context.get("coach_job_id")
        track_id = context.get("coach_track_id")
        if not job_id or not track_id:
            return

        if not song_path:
            self.handle_download_failed(context, "Download finalizado sem arquivo localizado")
            return

        track_id = int(track_id)
        self._db.update_coach_job(int(job_id), status="complete", progress=100)
        self._db.update_coach_track(
            track_id,
            status=PROCESSING_STATUS,
            file_path=song_path,
        )
        self._db.set_coach_assets(
            track_id,
            original_audio_path=song_path,
            lyrics_path=str(guide_path_for_media(song_path)),
        )
        self._db.create_coach_job(
            track_id,
            stage="analyze_pending",
            status=QUEUED_STATUS,
            progress=0,
        )
        logging.info("Coach acquisition complete for track %s: %s", track_id, song_path)

    def run_pending_analysis_once(self) -> bool:
        """Process one queued analyzer job if available.

        Returns True when a job was processed. This method is public so tests and
        future admin routes can trigger deterministic single-step processing.
        """
        job = self._db.get_next_coach_job(stage="analyze_pending", status=QUEUED_STATUS)
        if not job:
            return False
        self._run_analysis_job(job)
        return True

    def _recover_interrupted_analysis_jobs(self) -> None:
        """Requeue analyzer jobs left running by a process/container restart."""
        recovered = self._db.requeue_interrupted_coach_analysis_jobs()
        if recovered:
            logging.warning("Recovered %s interrupted coach analysis job(s)", recovered)

    def handle_download_failed(
        self,
        context: dict[str, Any] | None,
        error: str | None = None,
        *_args,
    ) -> None:
        """Mark a coach preparation download as failed."""
        if not context:
            return
        job_id = context.get("coach_job_id")
        track_id = context.get("coach_track_id")
        if job_id:
            self._db.update_coach_job(
                int(job_id),
                status="failed",
                progress=0,
                error=error or "Falha no download",
            )
        if track_id:
            self._db.update_coach_track(int(track_id), status=FAILED_STATUS)

    def list_tracks(self, limit: int = 100) -> list[dict[str, Any]]:
        """Return prepared/preparing tracks with their latest job and assets."""
        tracks = self._db.list_coach_tracks(limit=limit)
        for track in tracks:
            jobs = self._db.list_coach_jobs(track_id=track["id"], limit=10)
            track["jobs"] = jobs
            track["latest_job"] = jobs[0] if jobs else None
            track["assets"] = _coach_assets_with_runtime_flags(self._db.get_coach_assets(track["id"]))
        return tracks

    def get_track_with_assets(self, track_id: int) -> dict[str, Any] | None:
        """Return one coach track with jobs/assets attached."""
        track = self._db.get_coach_track(track_id)
        if not track:
            return None
        jobs = self._db.list_coach_jobs(track_id=track_id, limit=10)
        track["jobs"] = jobs
        track["latest_job"] = jobs[0] if jobs else None
        track["assets"] = _coach_assets_with_runtime_flags(self._db.get_coach_assets(track_id))
        return track

    def get_track_for_media_path(self, file_path: str | Path) -> dict[str, Any] | None:
        """Return a coach track associated with a currently playing media path."""
        track = self._db.find_coach_track_by_media_path(str(file_path))
        if not track:
            return None
        return self.get_track_with_assets(int(track["id"]))

    def get_playable_track_asset(self, track_id: int) -> dict[str, Any] | None:
        """Return the best playable file for a prepared coach track."""
        track = self.get_track_with_assets(track_id)
        if not track:
            return None
        assets = track.get("assets") or {}
        candidate_paths = [
            assets.get("instrumental_audio_path"),
            assets.get("original_audio_path"),
            track.get("file_path"),
        ]
        for candidate in candidate_paths:
            if candidate and Path(str(candidate)).is_file():
                return {
                    "track": track,
                    "path": str(candidate),
                    "title": track.get("display_title") or Path(str(candidate)).stem,
                    "using_instrumental": candidate == assets.get("instrumental_audio_path"),
                }
        return None

    def reanalyze_track(self, track_id: int) -> dict[str, Any] | None:
        """Queue a prepared track for fresh coach analysis."""
        track = self._db.get_coach_track(track_id)
        if not track:
            return None
        assets = self._db.get_coach_assets(track_id)
        media_path = _track_media_path(track, assets)
        if not media_path or not media_path.is_file():
            raise ValueError("Arquivo da musica nao encontrado para reprocessar.")

        self._db.update_coach_track(
            track_id,
            status=PROCESSING_STATUS,
            quality_status="unknown",
            file_path=str(media_path),
        )
        job = self._db.create_coach_job(
            track_id,
            stage="analyze_pending",
            status=QUEUED_STATUS,
            progress=0,
        )
        return {"track": self.get_track_with_assets(track_id), "job": job}

    def review_track_with_ai(self, track_id: int) -> dict[str, Any] | None:
        """Use the configured AI provider to review and correct a generated coach guide."""
        track = self.get_track_with_assets(track_id)
        if not track:
            return None
        assets = track.get("assets") or {}
        guide_path = Path(str(assets.get("guide_path") or ""))
        if not guide_path.is_file():
            raise ValueError("Guia do Coach nao encontrado para revisar.")

        job = self._db.create_coach_job(
            track_id,
            stage="ai_review",
            status="running",
            progress=5,
        )
        try:
            with guide_path.open("r", encoding="utf-8") as handle:
                guide = json.load(handle)
            review = _review_coach_guide_with_ai(track, guide)
            revised_guide = _apply_ai_review_to_coach_guide(guide, review)
            _write_json_with_backup(guide_path, revised_guide)
        except (OSError, ValueError, requests.RequestException, json.JSONDecodeError) as exc:
            self._db.update_coach_job(
                job["id"],
                status="failed",
                progress=0,
                error=str(exc),
            )
            raise ValueError(f"Revisao por IA falhou: {exc}") from exc

        quality_status = (revised_guide.get("quality") or {}).get("status") or "unknown"
        track_status = READY_STATUS if quality_status == "ready" else NEEDS_REVIEW_STATUS
        self._db.update_coach_track(
            track_id,
            status=track_status,
            quality_status=quality_status,
        )
        finished_job = self._db.update_coach_job(job["id"], status="complete", progress=100)
        self._events.emit(
            "notification",
            f"Revisao por IA concluida: {track.get('display_title') or track_id}",
            "success" if track_status == READY_STATUS else "warning",
        )
        return {
            "track": self.get_track_with_assets(track_id),
            "job": finished_job,
            "review": (revised_guide.get("quality") or {}).get("ai_review") or {},
        }

    def revert_ai_review(self, track_id: int) -> dict[str, Any] | None:
        """Restore the coach guide snapshot saved before the latest AI review."""
        track = self.get_track_with_assets(track_id)
        if not track:
            return None
        assets = track.get("assets") or {}
        guide_path = Path(str(assets.get("guide_path") or ""))
        backup_path = _ai_review_backup_path(guide_path)
        if not guide_path.is_file() or not backup_path.is_file():
            raise ValueError("Backup anterior a revisao por IA nao encontrado.")

        job = self._db.create_coach_job(
            track_id,
            stage="ai_revert",
            status="running",
            progress=10,
        )
        try:
            with backup_path.open("r", encoding="utf-8") as handle:
                restored_guide = json.load(handle)
            after_path = guide_path.with_name(guide_path.name + ".after-ai-review")
            if guide_path.is_file():
                shutil.copy2(guide_path, after_path)
            shutil.copy2(backup_path, guide_path)
            backup_path.unlink()
        except (OSError, json.JSONDecodeError) as exc:
            self._db.update_coach_job(
                job["id"],
                status="failed",
                progress=0,
                error=str(exc),
            )
            raise ValueError(f"Reversao da IA falhou: {exc}") from exc

        quality_status = (restored_guide.get("quality") or {}).get("status") or "unknown"
        track_status = READY_STATUS if quality_status == "ready" else NEEDS_REVIEW_STATUS
        self._db.update_coach_track(
            track_id,
            status=track_status,
            quality_status=quality_status,
        )
        finished_job = self._db.update_coach_job(job["id"], status="complete", progress=100)
        self._events.emit(
            "notification",
            f"Revisao por IA revertida: {track.get('display_title') or track_id}",
            "warning",
        )
        return {
            "track": self.get_track_with_assets(track_id),
            "job": finished_job,
        }

    def delete_track(self, track_id: int, *, delete_files: bool = True) -> dict[str, Any] | None:
        """Delete a coach track and, when safe, its generated media files."""
        track = self.get_track_with_assets(track_id)
        if not track:
            return None

        deleted_paths = []
        kept_paths = []
        candidate_paths = _coach_file_paths(track)
        if delete_files:
            for candidate in candidate_paths:
                result = _delete_coach_file(candidate, self._download_path)
                if result == "deleted":
                    deleted_paths.append(str(candidate))
                elif result == "kept":
                    kept_paths.append(str(candidate))

        if deleted_paths:
            self._db.delete_by_paths(deleted_paths)
        self._db.delete_coach_track(track_id)
        return {
            "track": track,
            "deleted_paths": deleted_paths,
            "kept_paths": kept_paths,
        }

    def load_coach_guide_for_media_path(self, file_path: str | Path) -> dict[str, Any] | None:
        """Load a .biaoke-coach.json package associated with a media path."""
        track = self.get_track_for_media_path(file_path)
        if not track:
            return None
        assets = track.get("assets") or {}
        guide_path = assets.get("guide_path")
        if not guide_path or not Path(str(guide_path)).is_file():
            return None
        with Path(str(guide_path)).open("r", encoding="utf-8") as handle:
            guide = json.load(handle)
        guide["track"] = {
            "id": track.get("id"),
            "display_title": track.get("display_title"),
            "status": track.get("status"),
            "quality_status": track.get("quality_status"),
        }
        guide["assets"] = assets
        return guide

    def _analyzer_loop(self) -> None:
        while not self._worker_stop.is_set():
            processed = self.run_pending_analysis_once()
            wait_seconds = 0.2 if processed else self._analyzer_poll_seconds
            self._worker_stop.wait(wait_seconds)

    def _run_analysis_job(self, job: dict[str, Any]) -> None:
        job_id = int(job["id"])
        track_id = int(job["track_id"])
        track = self._db.get_coach_track(track_id)
        if not track:
            self._db.update_coach_job(
                job_id,
                status="failed",
                progress=0,
                error="Track nao encontrado",
            )
            return

        media_path = _track_media_path(track, self._db.get_coach_assets(track_id))
        if not media_path or not media_path.is_file():
            self._db.update_coach_job(
                job_id,
                status="failed",
                progress=0,
                error="Arquivo da musica nao encontrado",
            )
            self._db.update_coach_track(track_id, status=FAILED_STATUS)
            return

        self._db.update_coach_track(track_id, status=PROCESSING_STATUS)
        self._db.update_coach_job(
            job_id,
            stage="build_guide",
            status="running",
            progress=10,
        )

        try:
            existing_lyrics = _load_existing_coach_lyrics(media_path)
            lyrics_guide = write_song_guide(media_path)
            if _lyrics_ready(existing_lyrics) and not _lyrics_ready(lyrics_guide.get("lyrics")):
                lyrics_guide = {**lyrics_guide, "lyrics": existing_lyrics}
            self._db.update_coach_job(job_id, stage="separate_stems", progress=30)
            stems = _separate_coach_stems(media_path)
            if stems:
                self._db.set_coach_assets(
                    track_id,
                    instrumental_audio_path=stems.get("instrumental_path"),
                    vocal_reference_path=stems.get("vocals_path"),
                )
            melody_source_path = Path(stems["vocals_path"]) if stems else media_path
            self._db.update_coach_job(job_id, stage="extract_melody", progress=55)
            melody_guide = _extract_coach_melody(melody_source_path)
            self._db.update_coach_job(job_id, stage="align_lyrics", progress=72)
            transcript, transcript_alignment = _transcribe_and_align_coach_vocals(
                melody_source_path,
                lyrics_guide.get("lyrics") or {},
            )
            melody_guide = _filter_melody_to_vocal_windows(
                melody_guide,
                lyrics_guide.get("lyrics") or {},
                transcript,
                preserve_vocal_stem_preface=bool(stems and stems.get("vocals_path")),
            )
            forced_alignment = _align_coach_lyrics(
                melody_source_path,
                lyrics_guide.get("lyrics") or {},
                melody_guide,
                transcript,
                transcript_alignment=transcript_alignment,
            )
            self._db.update_coach_job(job_id, stage="write_coach_guide", progress=85)
            coach_guide_path = _write_coach_guide(
                media_path,
                lyrics_guide,
                melody_guide,
                stems=stems,
                melody_source_path=melody_source_path,
                transcript=transcript,
                transcript_alignment=transcript_alignment,
                forced_alignment=forced_alignment,
            )
        except (OSError, ScoreAnalysisError, ValueError) as exc:
            logging.warning("Coach analysis failed for %s: %s", media_path, exc)
            self._db.update_coach_job(
                job_id,
                status="failed",
                progress=0,
                error=str(exc),
            )
            self._db.update_coach_track(track_id, status=FAILED_STATUS)
            return

        quality_status = _coach_quality_status(
            _lyrics_guide_for_quality(
                lyrics_guide,
                forced_alignment=forced_alignment,
                transcript_alignment=transcript_alignment,
            ),
            melody_guide,
            stems,
        )
        track_status = READY_STATUS if quality_status == "ready" else NEEDS_REVIEW_STATUS
        self._db.set_coach_assets(
            track_id,
            original_audio_path=str(media_path),
            instrumental_audio_path=stems.get("instrumental_path") if stems else None,
            vocal_reference_path=stems.get("vocals_path") if stems else None,
            guide_path=str(coach_guide_path),
            lyrics_path=str(guide_path_for_media(media_path)),
        )
        self._db.update_coach_track(
            track_id,
            status=track_status,
            quality_status=quality_status,
            file_path=str(media_path),
        )
        self._db.update_coach_job(job_id, status="complete", progress=100)
        self._events.emit(
            "notification",
            f"Coach preparado: {track.get('display_title') or media_path.name}",
            "success" if track_status == READY_STATUS else "warning",
        )


def _track_media_path(track: dict[str, Any], assets: dict[str, Any] | None) -> Path | None:
    if assets and assets.get("original_audio_path"):
        return Path(str(assets["original_audio_path"]))
    if track.get("file_path"):
        return Path(str(track["file_path"]))
    return None


def _coach_file_paths(track: dict[str, Any]) -> list[Path]:
    assets = track.get("assets") or {}
    paths = [
        track.get("file_path"),
        assets.get("original_audio_path"),
        assets.get("instrumental_audio_path"),
        assets.get("vocal_reference_path"),
        assets.get("guide_path"),
        f"{assets.get('guide_path')}.before-ai-review" if assets.get("guide_path") else None,
        f"{assets.get('guide_path')}.after-ai-review" if assets.get("guide_path") else None,
        assets.get("lyrics_path"),
    ]
    unique_paths = []
    seen = set()
    for raw_path in paths:
        if not raw_path:
            continue
        path = Path(str(raw_path))
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique_paths.append(path)
    return unique_paths


def _coach_assets_with_runtime_flags(assets: dict[str, Any] | None) -> dict[str, Any] | None:
    if not assets:
        return assets
    enriched = dict(assets)
    guide_path_value = str(enriched.get("guide_path") or "").strip()
    if not guide_path_value:
        enriched["ai_review_backup_path"] = None
        enriched["has_ai_review_backup"] = False
        return enriched
    backup_path = _ai_review_backup_path(Path(guide_path_value))
    has_backup = backup_path.is_file()
    enriched["ai_review_backup_path"] = str(backup_path) if has_backup else None
    enriched["has_ai_review_backup"] = has_backup
    return enriched


def _ai_review_backup_path(guide_path: Path) -> Path:
    return guide_path.with_name(guide_path.name + ".before-ai-review")


def _delete_coach_file(path: Path, download_root: Path) -> str:
    if not _path_is_inside(path, download_root):
        return "kept"
    try:
        if path.is_file() or path.is_symlink():
            path.unlink()
            return "deleted"
    except OSError as exc:
        logging.warning("Failed to delete coach file %s: %s", path, exc)
        return "kept"
    return "missing"


def _path_is_inside(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except ValueError:
        return False


def _coach_guide_path(media_path: str | Path) -> Path:
    return Path(media_path).with_suffix(COACH_GUIDE_SUFFIX)


def _write_coach_guide(
    media_path: str | Path,
    lyrics_guide: dict[str, Any],
    melody_guide: dict[str, Any],
    *,
    stems: dict[str, Any] | None = None,
    melody_source_path: str | Path | None = None,
    transcript: dict[str, Any] | None = None,
    transcript_alignment: dict[str, Any] | None = None,
    forced_alignment: dict[str, Any] | None = None,
) -> Path:
    path = _coach_guide_path(media_path)
    _backup_existing_coach_guide(path)
    melody_guide = _filter_melody_to_vocal_windows(
        melody_guide,
        lyrics_guide.get("lyrics") or {},
        transcript,
        preserve_vocal_stem_preface=bool(stems and stems.get("vocals_path")),
    )
    lyrics = with_vocal_activity_alignment(lyrics_guide.get("lyrics") or {}, melody_guide)
    if _is_usable_forced_alignment(forced_alignment):
        forced_payload = _forced_alignment_payload(forced_alignment)
        if transcript_alignment:
            forced_payload = _merge_alignment_with_fallback(forced_payload, transcript_alignment)
        lyrics["alignment"] = forced_payload
    elif transcript_alignment:
        lyrics["alignment"] = transcript_alignment
    else:
        word_alignment = build_word_alignment_from_transcript(
            lyrics_guide.get("lyrics") or {},
            transcript.get("words") if isinstance(transcript, dict) else [],
            method="faster_whisper_word_alignment",
        )
        if word_alignment:
            lyrics["alignment"] = word_alignment
    quality_lyrics_guide = {"lyrics": lyrics}
    payload = {
        "schema": COACH_GUIDE_SCHEMA,
        "version": COACH_GUIDE_VERSION,
        "media": {
            "path": str(media_path),
            "basename": Path(media_path).name,
            "melody_source_path": str(melody_source_path or media_path),
        },
        "stems": stems or {"status": "missing", "message": "Vocal separado ainda nao foi gerado."},
        "transcript": transcript or {"status": "missing", "message": "Transcricao vocal ainda nao foi gerada."},
        "lyrics": lyrics,
        "melody": melody_guide,
        "tasks": _build_pitch_tasks(lyrics_guide, melody_guide),
        "quality": {
            "status": _coach_quality_status(quality_lyrics_guide, melody_guide, stems),
            "lyrics_ready": (lyrics_guide.get("lyrics") or {}).get("status") == "ready",
            "melody_ready": bool(melody_guide.get("notes")),
            "vocal_stem_ready": bool(stems and stems.get("vocals_path")),
            "messages": _coach_quality_messages(quality_lyrics_guide, melody_guide, stems),
        },
    }
    tmp_path = path.with_name(path.name + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(tmp_path, path)
    return path


def _backup_existing_coach_guide(path: Path) -> None:
    backup_path = path.with_name(path.name + ".before-analysis")
    if not path.is_file() or backup_path.exists():
        return
    try:
        shutil.copy2(path, backup_path)
    except OSError as exc:
        logging.warning("Failed to back up coach guide %s: %s", path, exc)


def _load_existing_coach_lyrics(media_path: str | Path) -> dict[str, Any] | None:
    path = _coach_guide_path(media_path)
    if not path.is_file():
        return None
    try:
        with path.open("r", encoding="utf-8") as handle:
            guide = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    lyrics = guide.get("lyrics") if isinstance(guide, dict) else None
    return lyrics if _lyrics_ready(lyrics) else None


def _lyrics_ready(lyrics: Any) -> bool:
    return (
        isinstance(lyrics, dict)
        and lyrics.get("status") == "ready"
        and isinstance(lyrics.get("lines"), list)
        and len(lyrics.get("lines") or []) > 0
    )


def _is_usable_forced_alignment(alignment: dict[str, Any] | None) -> bool:
    if not isinstance(alignment, dict) or alignment.get("status") != "ready":
        return False
    units = alignment.get("paint_units") if isinstance(alignment.get("paint_units"), list) else []
    if not units:
        return False
    confidence = alignment.get("confidence") if isinstance(alignment.get("confidence"), dict) else {}
    overall = _safe_float(confidence.get("overall"))
    coverage = _safe_float(confidence.get("coverage"))
    if overall is not None and overall < FORCED_ALIGNMENT_MIN_CONFIDENCE:
        return False
    if coverage is not None and coverage < FORCED_ALIGNMENT_MIN_COVERAGE:
        return False
    return True


def _forced_alignment_payload(alignment: dict[str, Any]) -> dict[str, Any]:
    raw_units = alignment.get("paint_units") if isinstance(alignment.get("paint_units"), list) else []
    units = []
    previous_end = 0.0
    previous_line: int | None = None
    for raw_unit in raw_units:
        if not isinstance(raw_unit, dict):
            continue
        start = _safe_float(raw_unit.get("start"))
        end = _safe_float(raw_unit.get("end"))
        text = str(raw_unit.get("text") or "").strip()
        if start is None or end is None or end <= start or not text:
            continue
        line_index = _safe_int(raw_unit.get("line_index"), default=0)
        if previous_line is not None and line_index != previous_line:
            previous_end = 0.0
        if start < previous_end:
            start = previous_end
            end = max(end, start + 0.06)
        unit = {
            "start": round(start, 3),
            "end": round(end, 3),
            "text": text,
            "line_index": line_index,
            "unit_index": _safe_int(raw_unit.get("unit_index"), default=len(units)),
            "unit_type": "word",
            "precision": str(raw_unit.get("precision") or "mms_fa_forced_alignment"),
            "confidence": round(max(0.0, min(1.0, _safe_float(raw_unit.get("confidence")) or 0.0)), 3),
        }
        units.append(unit)
        previous_end = float(unit["end"])
        previous_line = line_index

    return {
        "schema": ALIGNMENT_SCHEMA,
        "version": ALIGNMENT_VERSION,
        "status": "ready" if units else "missing",
        "method": str(alignment.get("method") or "mms_fa_forced_alignment"),
        "language": alignment.get("language") or "auto",
        "granularity": "word",
        "engine": alignment.get("engine"),
        "model": alignment.get("model"),
        "device": alignment.get("device"),
        "paint_units": units,
        "confidence": alignment.get("confidence") or {"overall": 0.0},
    }


def _merge_alignment_with_fallback(
    primary_alignment: dict[str, Any],
    fallback_alignment: dict[str, Any],
) -> dict[str, Any]:
    primary_units = primary_alignment.get("paint_units") if isinstance(primary_alignment.get("paint_units"), list) else []
    fallback_units = fallback_alignment.get("paint_units") if isinstance(fallback_alignment.get("paint_units"), list) else []
    primary_lines = {
        _safe_int(unit.get("line_index"), default=-1)
        for unit in primary_units
        if isinstance(unit, dict)
    }
    merged_units = [dict(unit) for unit in primary_units if isinstance(unit, dict)]
    fallback_count = 0
    for unit in fallback_units:
        if not isinstance(unit, dict):
            continue
        line_index = _safe_int(unit.get("line_index"), default=-1)
        if line_index in primary_lines:
            continue
        merged_units.append(dict(unit))
        fallback_count += 1

    if fallback_count <= 0:
        return primary_alignment

    merged_units.sort(
        key=lambda unit: (
            _safe_int(unit.get("line_index"), default=0),
            _safe_int(unit.get("unit_index"), default=0),
            _safe_float(unit.get("start")) or 0.0,
        )
    )
    merged_alignment = dict(primary_alignment)
    merged_alignment["method"] = f"{primary_alignment.get('method') or 'forced_alignment'}+fallback"
    merged_alignment["paint_units"] = merged_units
    confidence = dict(primary_alignment.get("confidence") or {})
    confidence["fallback_units"] = fallback_count
    confidence["fallback_method"] = fallback_alignment.get("method")
    merged_alignment["confidence"] = confidence
    return merged_alignment


def _lyrics_guide_for_quality(
    lyrics_guide: dict[str, Any],
    *,
    forced_alignment: dict[str, Any] | None = None,
    transcript_alignment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    lyrics = dict(lyrics_guide.get("lyrics") or {})
    if _is_usable_forced_alignment(forced_alignment):
        lyrics["alignment"] = _forced_alignment_payload(forced_alignment or {})
    elif transcript_alignment:
        lyrics["alignment"] = transcript_alignment
    return {"lyrics": lyrics}


def _review_coach_guide_with_ai(track: dict[str, Any], guide: dict[str, Any]) -> dict[str, Any]:
    provider = _select_ai_review_provider(require_key=True)
    if provider == "mimo":
        return _review_coach_guide_with_mimo(track, guide)
    if provider == "deepseek":
        return _review_coach_guide_with_deepseek(track, guide)
    raise ValueError(f"{AI_REVIEW_PROVIDER_ENV} invalido: {provider}")


def _review_coach_guide_with_mimo(track: dict[str, Any], guide: dict[str, Any]) -> dict[str, Any]:
    api_key = _mimo_api_key()
    if not api_key:
        raise ValueError(f"{MIMO_API_KEY_ENV} nao configurada.")

    model = os.environ.get(MIMO_MODEL_ENV, DEFAULT_MIMO_MODEL).strip() or DEFAULT_MIMO_MODEL
    base_url = os.environ.get(MIMO_BASE_URL_ENV, DEFAULT_MIMO_BASE_URL).strip() or DEFAULT_MIMO_BASE_URL
    request_body = {
        "model": model,
        "messages": _coach_ai_review_messages(track, guide),
        "response_format": {"type": "json_object"},
        "max_tokens": 24000,
        "stream": False,
        "temperature": 0.1,
    }

    response = requests.post(
        f"{base_url.rstrip('/')}/chat/completions",
        headers={
            "api-key": api_key,
            "Content-Type": "application/json",
        },
        json=request_body,
        timeout=_mimo_timeout_seconds(),
    )
    response.raise_for_status()
    return _parse_ai_review_response(response.json(), provider="mimo", model=model)


def _review_coach_guide_with_deepseek(track: dict[str, Any], guide: dict[str, Any]) -> dict[str, Any]:
    api_key = os.environ.get(DEEPSEEK_API_KEY_ENV, "").strip()
    if not api_key:
        raise ValueError(f"{DEEPSEEK_API_KEY_ENV} nao configurada.")

    model = os.environ.get(DEEPSEEK_MODEL_ENV, DEFAULT_DEEPSEEK_MODEL).strip() or DEFAULT_DEEPSEEK_MODEL
    base_url = os.environ.get(DEEPSEEK_BASE_URL_ENV, DEFAULT_DEEPSEEK_BASE_URL).strip() or DEFAULT_DEEPSEEK_BASE_URL
    request_body = {
        "model": model,
        "messages": _coach_ai_review_messages(track, guide),
        "response_format": {"type": "json_object"},
        "max_tokens": 24000,
        "stream": False,
    }
    thinking_mode = _deepseek_thinking_mode()
    if thinking_mode:
        request_body["thinking"] = {"type": thinking_mode}
        if thinking_mode == "enabled":
            request_body["reasoning_effort"] = _deepseek_reasoning_effort()
        else:
            request_body["temperature"] = 0.1

    response = requests.post(
        f"{base_url.rstrip('/')}/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=request_body,
        timeout=_deepseek_timeout_seconds(),
    )
    response.raise_for_status()
    return _parse_ai_review_response(response.json(), provider="deepseek", model=model)


def _coach_ai_review_messages(track: dict[str, Any], guide: dict[str, Any]) -> list[dict[str, str]]:
    review_input = _coach_ai_review_input(track, guide)
    return [
        {
            "role": "system",
            "content": (
                "You review karaoke vocal-coach guide data. Return only valid JSON. "
                "Use only the provided lyrics, transcript words, melody timing and metadata. "
                "Do not add song lyrics from memory or external knowledge. "
                "Prefer precise transcript-backed paint_units when synchronization is being corrected."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(review_input, ensure_ascii=False),
        },
    ]


def _parse_ai_review_response(payload: dict[str, Any], *, provider: str, model: str) -> dict[str, Any]:
    content = _ai_chat_response_content(payload)
    if not content:
        raise ValueError(f"{_ai_review_provider_label(provider)} nao retornou conteudo de revisao.")
    review = _parse_ai_review_json(content)
    review["_provider"] = provider
    review["_model"] = payload.get("model") or model
    if payload.get("usage"):
        review["_usage"] = payload.get("usage")
    return review


def _ai_chat_response_content(payload: dict[str, Any]) -> str:
    if not isinstance(payload, dict):
        return ""
    message = ((payload.get("choices") or [{}])[0].get("message") or {})
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part)
    return ""


def _coach_ai_review_input(track: dict[str, Any], guide: dict[str, Any]) -> dict[str, Any]:
    lyrics = guide.get("lyrics") if isinstance(guide.get("lyrics"), dict) else {}
    melody = guide.get("melody") if isinstance(guide.get("melody"), dict) else {}
    transcript = guide.get("transcript") if isinstance(guide.get("transcript"), dict) else {}
    return {
        "task": (
            "Return JSON with keys action, confidence, summary, issues, lines and optional alignment. "
            "If existing lyrics are present, preserve the provided lyric text exactly and correct only timings. "
            "If lyrics are missing, group transcript words into readable line-timed captions. "
            "Every line must have start, end and text. Times are seconds. Lines must be monotonic. "
            "When possible, also return alignment.paint_units with word-level or segment-level timings "
            "so the guitar-hero track and lyric painting use the same clock."
        ),
        "output_schema": {
            "action": "apply or no_change",
            "confidence": "number from 0 to 1",
            "summary": "short explanation",
            "issues": ["short issue codes or notes"],
            "lines": [{"start": 0.0, "end": 1.0, "text": "visible lyric/caption line"}],
            "alignment": {
                "granularity": "word or segment",
                "paint_units": [
                    {
                        "start": 0.0,
                        "end": 0.4,
                        "text": "lyric word or timed lyric fragment",
                        "line_index": 0,
                        "unit_index": 0,
                        "unit_type": "word",
                    }
                ],
            },
        },
        "rules": [
            "Never invent missing lyrics from memory.",
            "When lyrics.lines is not empty, every returned line text must be copied from the provided lyrics, not from transcript wording.",
            "Use transcript word timings and melody/vocal_activity_spans only as timing anchors.",
            "If you return alignment.paint_units, unit text must be copied from its returned line and must not introduce new lyric text.",
            "Prefer one paint_unit per lyric word when transcript words match the lyric; use segment units only for source karaoke fragments.",
            "Paint units must be monotonic, inside the song duration, and assigned to the correct zero-based line_index.",
            "If lyric timings exceed song duration, preserve lyric order and realign timings into the vocal span instead of rewriting text.",
            "Drop an existing lyric line only when it is clearly metadata, duplicate noise, or impossible to place.",
            "If lyrics are missing, transcript-derived captions are allowed and must be marked by the summary/issues.",
            "Keep line text short enough for karaoke display.",
            "Do not change pitch notes or MIDI values.",
        ],
        "track": {
            "id": track.get("id"),
            "display_title": track.get("display_title"),
            "source_type": track.get("source_type"),
            "source_id": track.get("source_id"),
        },
        "quality": guide.get("quality") or {},
        "duration_seconds": _guide_duration_seconds(melody) or None,
        "lyrics": {
            "status": lyrics.get("status"),
            "source": lyrics.get("source"),
            "source_format": lyrics.get("source_format"),
            "has_karaoke_timing": bool(lyrics.get("has_karaoke_timing")),
            "line_count": len(lyrics.get("lines") or []),
            "lines": _compact_lyric_lines(lyrics.get("lines") or []),
            "current_alignment": _compact_alignment(lyrics.get("alignment") or {}),
        },
        "transcript": {
            "status": transcript.get("status"),
            "engine": transcript.get("engine"),
            "language": transcript.get("language"),
            "words": _compact_transcript_words(transcript.get("words") or []),
        },
        "melody": {
            "duration_seconds": melody.get("duration_seconds"),
            "note_count": len(melody.get("notes") or []),
            "notes": _compact_melody_notes(melody.get("notes") or []),
            "vocal_activity_spans": _compact_vocal_activity_spans(melody),
            "vocal_filter": melody.get("vocal_filter") or {},
        },
    }


def _compact_lyric_lines(lines: list[Any]) -> list[dict[str, Any]]:
    compact = []
    for line in lines[:AI_REVIEW_MAX_LINES]:
        if not isinstance(line, dict):
            continue
        start = _safe_float(line.get("start"))
        end = _safe_float(line.get("end"))
        text = _clean_ai_text(line.get("text"))
        if start is None or end is None or not text:
            continue
        compact.append({"start": round(start, 3), "end": round(end, 3), "text": text})
    return compact


def _compact_alignment(alignment: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(alignment, dict):
        return {}
    units = alignment.get("paint_units") if isinstance(alignment.get("paint_units"), list) else []
    return {
        "status": alignment.get("status"),
        "method": alignment.get("method"),
        "granularity": alignment.get("granularity"),
        "confidence": alignment.get("confidence") or {},
        "paint_units": _compact_alignment_units(units),
    }


def _compact_alignment_units(units: list[Any]) -> list[dict[str, Any]]:
    compact = []
    for unit in units[:AI_REVIEW_MAX_PAINT_UNITS]:
        if not isinstance(unit, dict):
            continue
        start = _safe_float(unit.get("start"))
        end = _safe_float(unit.get("end"))
        text = _clean_ai_text(unit.get("text"))
        if start is None or end is None or not text:
            continue
        compact.append(
            {
                "start": round(start, 3),
                "end": round(end, 3),
                "text": text,
                "line_index": _safe_int(unit.get("line_index"), default=0),
                "unit_index": _safe_int(unit.get("unit_index"), default=len(compact)),
                "unit_type": str(unit.get("unit_type") or "unit")[:32],
                "precision": str(unit.get("precision") or "")[:80],
            }
        )
    return compact


def _compact_transcript_words(words: list[Any]) -> list[dict[str, Any]]:
    compact = []
    for word in words[:AI_REVIEW_MAX_TRANSCRIPT_WORDS]:
        if not isinstance(word, dict):
            continue
        start = _safe_float(word.get("start"))
        end = _safe_float(word.get("end"))
        text = _clean_ai_text(word.get("word") or word.get("text"))
        if start is None or end is None or not text:
            continue
        item = {"start": round(start, 3), "end": round(end, 3), "text": text}
        confidence = _safe_float(word.get("probability") or word.get("confidence"))
        if confidence is not None:
            item["confidence"] = round(confidence, 4)
        compact.append(item)
    return compact


def _compact_vocal_activity_spans(melody: dict[str, Any]) -> list[dict[str, Any]]:
    notes = []
    for note in melody.get("notes") or []:
        if not isinstance(note, dict):
            continue
        start = _safe_float(note.get("start"))
        end = _safe_float(note.get("end"))
        midi = _safe_float(note.get("midi"))
        if start is None or end is None or midi is None or end <= start:
            continue
        notes.append((start, end, midi))
    notes.sort(key=lambda item: item[0])
    if not notes:
        return []

    spans = []
    span_start, span_end = notes[0][0], notes[0][1]
    midi_values = [notes[0][2]]
    for start, end, midi in notes[1:]:
        if start - span_end <= 0.85:
            span_end = max(span_end, end)
            midi_values.append(midi)
            continue
        spans.append(_compact_vocal_span(span_start, span_end, midi_values))
        span_start, span_end = start, end
        midi_values = [midi]
    spans.append(_compact_vocal_span(span_start, span_end, midi_values))
    return spans[:500]


def _compact_vocal_span(start: float, end: float, midi_values: list[float]) -> dict[str, Any]:
    return {
        "start": round(start, 3),
        "end": round(end, 3),
        "duration": round(max(0.0, end - start), 3),
        "min_midi": round(min(midi_values), 2),
        "max_midi": round(max(midi_values), 2),
    }


def _compact_melody_notes(notes: list[Any]) -> list[dict[str, Any]]:
    compact = []
    for note in notes[:AI_REVIEW_MAX_NOTES]:
        if not isinstance(note, dict):
            continue
        start = _safe_float(note.get("start"))
        end = _safe_float(note.get("end"))
        midi = _safe_float(note.get("midi"))
        if start is None or end is None or midi is None:
            continue
        item = {"start": round(start, 3), "end": round(end, 3), "midi": round(midi, 3)}
        confidence = _safe_float(note.get("confidence"))
        if confidence is not None:
            item["confidence"] = round(confidence, 4)
        compact.append(item)
    return compact


def _mimo_api_key() -> str:
    return os.environ.get(MIMO_API_KEY_ENV, "").strip() or os.environ.get(MIMO_COMPAT_API_KEY_ENV, "").strip()


def _requested_ai_review_provider() -> str:
    raw_value = os.environ.get(AI_REVIEW_PROVIDER_ENV, "auto").strip().casefold()
    if raw_value in {"", "auto"}:
        return "auto"
    if raw_value in {"mimo", "xiaomi", "xiaomi_mimo", "xiaomi-mimo"}:
        return "mimo"
    if raw_value == "deepseek":
        return "deepseek"
    raise ValueError(f"{AI_REVIEW_PROVIDER_ENV} invalido. Use auto, mimo ou deepseek.")


def _select_ai_review_provider(*, require_key: bool) -> str:
    provider = _requested_ai_review_provider()
    if provider != "auto":
        return provider
    if _mimo_api_key():
        return "mimo"
    if os.environ.get(DEEPSEEK_API_KEY_ENV, "").strip():
        return "deepseek"
    if require_key:
        raise ValueError(f"{MIMO_API_KEY_ENV} ou {DEEPSEEK_API_KEY_ENV} nao configurada.")
    return "mimo"


def _ai_review_provider_label(provider: Any) -> str:
    normalized = str(provider or "").strip().casefold()
    if normalized == "mimo":
        return "MiMo"
    if normalized == "deepseek":
        return "DeepSeek"
    return "IA"


def _ai_review_provider_slug(provider: Any) -> str:
    normalized = str(provider or "").strip().casefold()
    if normalized in {"mimo", "deepseek"}:
        return normalized
    return "ai"


def _ai_review_tag(provider: Any) -> str:
    slug = _ai_review_provider_slug(provider)
    return f"{slug}_review" if slug == "ai" else f"{slug}_ai_review"


def _default_ai_review_model(provider: Any) -> str:
    slug = _ai_review_provider_slug(provider)
    if slug == "mimo":
        return os.environ.get(MIMO_MODEL_ENV, DEFAULT_MIMO_MODEL)
    if slug == "deepseek":
        return os.environ.get(DEEPSEEK_MODEL_ENV, DEFAULT_DEEPSEEK_MODEL)
    return ""


def _parse_ai_review_json(content: str) -> dict[str, Any]:
    text = str(content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise
        parsed = json.loads(text[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("IA retornou JSON invalido.")
    return parsed


def _apply_ai_review_to_coach_guide(guide: dict[str, Any], review: dict[str, Any]) -> dict[str, Any]:
    melody = guide.get("melody") if isinstance(guide.get("melody"), dict) else {}
    transcript = guide.get("transcript") if isinstance(guide.get("transcript"), dict) else {}
    stems = guide.get("stems") if isinstance(guide.get("stems"), dict) else None
    provider = _ai_review_provider_slug(review.get("_provider") or _select_ai_review_provider(require_key=False))
    confidence = _safe_float(review.get("confidence"))
    if confidence is None:
        confidence = 0.0
    if confidence < AI_REVIEW_MIN_CONFIDENCE:
        raise ValueError("IA retornou confianca baixa para aplicar a revisao.")
    if str(review.get("action") or "apply").strip().casefold() == "no_change":
        raise ValueError("IA nao encontrou uma revisao aplicavel.")

    review_lyrics = review.get("lyrics") if isinstance(review.get("lyrics"), dict) else {}
    revised_lines = _validated_ai_review_lines(
        review.get("lines") or review_lyrics.get("lines"),
        duration_seconds=_guide_duration_seconds(melody),
    )
    if not revised_lines:
        raise ValueError("IA nao retornou linhas validas para a legenda.")

    original_lyrics = guide.get("lyrics") if isinstance(guide.get("lyrics"), dict) else {}
    _validate_ai_preserves_existing_lyrics(original_lyrics, revised_lines)
    revised_lyrics = dict(original_lyrics)
    revised_lyrics.update(
        {
            "status": "ready",
            "source": _ai_review_source_name(original_lyrics.get("source"), provider),
            "source_format": "ai_review_lines",
            "confidence": round(max(_safe_float(original_lyrics.get("confidence")) or 0.0, confidence), 3),
            "has_karaoke_timing": False,
            "line_count": len(revised_lines),
            "lines": revised_lines,
        }
    )
    revised_lyrics.pop("alignment", None)
    revised_lyrics["ai_review"] = _ai_review_metadata(review, len(revised_lines))

    revised_lyrics = with_vocal_activity_alignment(revised_lyrics, melody)
    ai_alignment = _validated_ai_review_alignment(
        review.get("alignment") or review_lyrics.get("alignment") or review.get("paint_units"),
        revised_lines,
        duration_seconds=_guide_duration_seconds(melody),
        confidence=confidence,
        provider=provider,
    )
    if ai_alignment:
        revised_lyrics["alignment"] = ai_alignment
    else:
        word_alignment = build_word_alignment_from_transcript(
            revised_lyrics,
            transcript.get("words") if isinstance(transcript, dict) else [],
            method=f"{provider}_review_transcript_alignment",
        )
        if word_alignment:
            revised_lyrics["alignment"] = word_alignment

    revised_guide = dict(guide)
    revised_guide["lyrics"] = revised_lyrics
    revised_guide["tasks"] = _build_pitch_tasks({"lyrics": revised_lyrics}, melody)
    quality_status = _coach_quality_status({"lyrics": revised_lyrics}, melody, stems)
    revised_guide["quality"] = {
        "status": quality_status,
        "lyrics_ready": revised_lyrics.get("status") == "ready",
        "melody_ready": bool(melody.get("notes")),
        "vocal_stem_ready": bool(stems and stems.get("vocals_path")),
        "messages": _coach_quality_messages({"lyrics": revised_lyrics}, melody, stems),
        "ai_review": _ai_review_metadata(review, len(revised_lines)),
    }
    return revised_guide


def _validated_ai_review_lines(raw_lines: Any, *, duration_seconds: float = 0.0) -> list[dict[str, Any]]:
    if not isinstance(raw_lines, list):
        return []
    max_end = duration_seconds + 1.5 if duration_seconds > 0 else None
    lines = []
    previous_end = 0.0
    for raw_line in raw_lines[:AI_REVIEW_MAX_LINES]:
        if not isinstance(raw_line, dict):
            continue
        start = _safe_float(raw_line.get("start"))
        end = _safe_float(raw_line.get("end"))
        text = _clean_ai_text(raw_line.get("text"))
        if start is None or end is None or not text:
            continue
        if max_end is not None and start > max_end:
            continue
        start = max(0.0, start)
        if max_end is not None:
            end = min(end, max_end)
        if start < previous_end:
            start = previous_end
        if end <= start + 0.08:
            continue
        line = {
            "start": round(start, 3),
            "end": round(end, 3),
            "text": text,
            "has_karaoke_timing": False,
            "segments": _segments_for_ai_line(text, start, end),
        }
        lines.append(line)
        previous_end = float(line["end"])
    return lines


def _validated_ai_review_alignment(
    raw_alignment: Any,
    revised_lines: list[dict[str, Any]],
    *,
    duration_seconds: float = 0.0,
    confidence: float = 0.0,
    provider: str = "ai",
) -> dict[str, Any] | None:
    if isinstance(raw_alignment, dict):
        raw_units = raw_alignment.get("paint_units")
        raw_granularity = str(raw_alignment.get("granularity") or "").strip().casefold()
    elif isinstance(raw_alignment, list):
        raw_units = raw_alignment
        raw_granularity = ""
    else:
        return None
    if not isinstance(raw_units, list) or not raw_units:
        return None

    max_end = duration_seconds + 1.5 if duration_seconds > 0 else None
    line_texts = [_normalize_ai_review_text(line.get("text")) for line in revised_lines]
    units = []
    previous_end = 0.0
    for raw_unit in raw_units[:AI_REVIEW_MAX_PAINT_UNITS]:
        if not isinstance(raw_unit, dict):
            continue
        start = _safe_float(raw_unit.get("start"))
        end = _safe_float(raw_unit.get("end"))
        text = _clean_ai_text(raw_unit.get("text"))
        if start is None or end is None or not text:
            continue
        if max_end is not None and start > max_end:
            continue
        start = max(0.0, start)
        if max_end is not None:
            end = min(end, max_end)
        if start < previous_end:
            start = previous_end
        if end <= start + 0.04:
            continue

        line_index = _safe_int(raw_unit.get("line_index"), default=-1)
        if line_index < 0 or line_index >= len(revised_lines):
            line_index = _line_index_for_ai_unit(revised_lines, start, end)
        if line_index < 0 or line_index >= len(revised_lines):
            continue

        unit_text = _normalize_ai_review_text(text)
        line_text = line_texts[line_index] if line_index < len(line_texts) else ""
        if not unit_text or not line_text or unit_text not in line_text:
            continue

        unit_type = str(raw_unit.get("unit_type") or raw_granularity or "word").strip().casefold()
        if unit_type not in {"word", "segment", "syllable"}:
            unit_type = "word"
        unit = {
            "start": round(start, 3),
            "end": round(end, 3),
            "text": text,
            "line_index": line_index,
            "unit_index": _safe_int(raw_unit.get("unit_index"), default=len(units)),
            "unit_type": unit_type,
            "precision": _ai_review_tag(provider),
            "confidence": round(max(0.0, min(1.0, confidence)), 3),
        }
        units.append(unit)
        previous_end = float(unit["end"])

    if not units:
        return None
    covered_lines = {unit["line_index"] for unit in units}
    if len(revised_lines) > 1 and len(covered_lines) / len(revised_lines) < 0.35:
        return None

    granularities = {unit["unit_type"] for unit in units}
    granularity = "syllable" if "syllable" in granularities else "segment" if "segment" in granularities else "word"
    return {
        "schema": ALIGNMENT_SCHEMA,
        "version": ALIGNMENT_VERSION,
        "status": "ready",
        "method": f"{_ai_review_provider_slug(provider)}_review_paint_units",
        "language": "auto",
        "granularity": granularity,
        "paint_units": units,
        "confidence": {
            "overall": round(max(0.0, min(1.0, confidence)), 3),
            "uses_ai_review_timing": True,
            "paint_units": len(units),
            "covered_lines": len(covered_lines),
        },
    }


def _line_index_for_ai_unit(revised_lines: list[dict[str, Any]], start: float, end: float) -> int:
    midpoint = (start + end) / 2.0
    best_index = -1
    best_overlap = 0.0
    for index, line in enumerate(revised_lines):
        line_start = _safe_float(line.get("start"))
        line_end = _safe_float(line.get("end"))
        if line_start is None or line_end is None:
            continue
        overlap = max(0.0, min(end, line_end + 0.35) - max(start, line_start - 0.35))
        if overlap > best_overlap:
            best_overlap = overlap
            best_index = index
        if line_start - 0.35 <= midpoint <= line_end + 0.35:
            return index
    return best_index


def _validate_ai_preserves_existing_lyrics(
    original_lyrics: dict[str, Any],
    revised_lines: list[dict[str, Any]],
) -> None:
    original_lines = original_lyrics.get("lines") if isinstance(original_lyrics.get("lines"), list) else []
    original_texts = [_normalize_ai_review_text(line.get("text")) for line in original_lines if isinstance(line, dict)]
    original_texts = [text for text in original_texts if text]
    if len(original_texts) < 4:
        return

    original_full_text = " ".join(original_texts)
    revised_texts = [_normalize_ai_review_text(line.get("text")) for line in revised_lines]
    revised_texts = [text for text in revised_texts if text]
    if not revised_texts:
        raise ValueError("IA removeu todas as linhas da letra existente.")

    matched = sum(1 for text in revised_texts if text in original_full_text)
    match_ratio = matched / len(revised_texts)
    if match_ratio < AI_REVIEW_EXISTING_LYRICS_MIN_TEXT_MATCH:
        raise ValueError(
            "IA alterou texto demais da letra existente; revisao bloqueada para evitar letra inventada."
        )


def _normalize_ai_review_text(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip().casefold()
    return re.sub(r"[^\w'’ ]+", "", text, flags=re.UNICODE)


def _segments_for_ai_line(text: str, start: float, end: float) -> list[dict[str, Any]]:
    pieces = re.findall(r"\S+\s*", text) or [text]
    total_weight = sum(max(1, len(piece.strip())) for piece in pieces)
    duration = max(0.05, end - start)
    cursor = start
    segments = []
    for index, piece in enumerate(pieces):
        is_last = index == len(pieces) - 1
        weight = max(1, len(piece.strip()))
        segment_duration = end - cursor if is_last else duration * (weight / total_weight)
        segment_end = min(end, cursor + max(0.03, segment_duration))
        segments.append({"text": piece, "start": round(cursor, 3), "end": round(segment_end, 3)})
        cursor = segment_end
    return segments


def _clean_ai_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:240]


def _ai_review_source_name(original_source: Any, provider: Any = None) -> str:
    source = str(original_source or "").strip()
    tag = _ai_review_tag(provider or _select_ai_review_provider(require_key=False))
    if not source:
        return tag
    if tag in source.split("+"):
        return source
    return f"{source}+{tag}"


def _ai_review_metadata(review: dict[str, Any], line_count: int) -> dict[str, Any]:
    confidence = _safe_float(review.get("confidence")) or 0.0
    raw_issues = review.get("issues") if isinstance(review.get("issues"), list) else []
    provider = _ai_review_provider_slug(review.get("_provider") or _select_ai_review_provider(require_key=False))
    metadata = {
        "provider": provider,
        "model": review.get("_model") or _default_ai_review_model(provider),
        "confidence": round(max(0.0, min(1.0, confidence)), 3),
        "summary": _clean_ai_text(review.get("summary")),
        "issues": [str(issue)[:120] for issue in raw_issues if str(issue).strip()][:12],
        "line_count": line_count,
    }
    if review.get("_usage"):
        metadata["usage"] = review.get("_usage")
    return metadata


def _write_json_with_backup(path: Path, payload: dict[str, Any]) -> None:
    backup_path = _ai_review_backup_path(path)
    if path.is_file() and not backup_path.exists():
        shutil.copy2(path, backup_path)
    tmp_path = path.with_name(path.name + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(tmp_path, path)


def _filter_melody_to_vocal_windows(
    melody_guide: dict[str, Any],
    lyrics: dict[str, Any] | None,
    transcript: dict[str, Any] | None,
    *,
    preserve_vocal_stem_preface: bool = False,
) -> dict[str, Any]:
    """Remove pitch guide material that is not supported by vocal timestamps."""
    melody = dict(melody_guide or {})
    existing_filter = melody.get("vocal_filter")
    if (
        isinstance(existing_filter, dict)
        and existing_filter.get("applied")
        and existing_filter.get("version") == VOCAL_FILTER_VERSION
    ):
        return melody

    notes = melody.get("notes") if isinstance(melody.get("notes"), list) else []
    contour = melody.get("contour") if isinstance(melody.get("contour"), list) else []
    windows, source = _vocal_timing_windows(lyrics, transcript)
    if not windows:
        melody["vocal_filter"] = {
            "applied": False,
            "reason": "no_vocal_timing_windows",
            "raw_notes": len(notes),
            "raw_contour_points": len(contour),
        }
        return melody

    preface_metadata = {}
    if preserve_vocal_stem_preface and "line_lyrics" in source:
        windows, preface_metadata = _extend_first_window_to_preface_vocal_cluster(windows, notes)

    filtered_notes = _filter_notes_to_windows(notes, windows)
    filtered_contour = _filter_contour_to_windows(contour, windows, filtered_notes)
    melody["notes"] = filtered_notes
    melody["contour"] = filtered_contour
    melody["vocal_filter"] = {
        "applied": True,
        "version": VOCAL_FILTER_VERSION,
        "source": source,
        "windows": len(windows),
        "raw_notes": len(notes),
        "kept_notes": len(filtered_notes),
        "removed_notes": max(0, len(notes) - len(filtered_notes)),
        "raw_contour_points": len(contour),
        "kept_contour_points": len(filtered_contour),
        "removed_contour_points": max(0, len(contour) - len(filtered_contour)),
        **preface_metadata,
    }
    return melody


def _extend_first_window_to_preface_vocal_cluster(
    windows: list[tuple[float, float]],
    notes: list[Any],
) -> tuple[list[tuple[float, float]], dict[str, Any]]:
    if not windows:
        return windows, {}
    first_start, first_end = windows[0]
    if first_start <= 0:
        return windows, {}

    selected_cluster: dict[str, Any] | None = None
    for cluster in _note_activity_clusters(notes):
        cluster_end = float(cluster["end"])
        if cluster_end >= first_start:
            break
        gap = first_start - cluster_end
        if gap <= VOCAL_FILTER_PREFACE_MAX_GAP_SECONDS:
            selected_cluster = cluster

    if not selected_cluster:
        return windows, {}

    extended_start = max(0.0, float(selected_cluster["start"]) - VOCAL_FILTER_LEAD_SECONDS)
    if extended_start >= first_start - 0.05:
        return windows, {}

    extended_windows = list(windows)
    extended_windows[0] = (round(extended_start, 3), first_end)
    return extended_windows, {
        "preface_first_window_extended": True,
        "preface_first_window_source": "vocal_stem_notes",
        "preface_first_window_original_start": round(first_start, 3),
        "preface_first_window_start": round(extended_start, 3),
        "preface_first_window_cluster_end": round(float(selected_cluster["end"]), 3),
        "preface_first_window_gap": round(first_start - float(selected_cluster["end"]), 3),
        "preface_first_window_notes": int(selected_cluster["count"]),
    }


def _note_activity_clusters(notes: list[Any]) -> list[dict[str, Any]]:
    intervals = []
    for note in notes:
        if not isinstance(note, dict):
            continue
        start = _safe_float(note.get("start"))
        end = _safe_float(note.get("end"))
        confidence = _safe_float(note.get("confidence"))
        if start is None or end is None or end <= start:
            continue
        if confidence is None or confidence < VOCAL_FILTER_PREFACE_MIN_CONFIDENCE:
            continue
        intervals.append((start, end, confidence))

    intervals.sort()
    clusters: list[dict[str, Any]] = []
    current_start: float | None = None
    current_end: float | None = None
    confidence_total = 0.0
    count = 0

    def flush() -> None:
        nonlocal current_start, current_end, confidence_total, count
        if current_start is None or current_end is None or count <= 0:
            return
        duration = current_end - current_start
        mean_confidence = confidence_total / count
        if duration >= VOCAL_FILTER_PREFACE_MIN_SECONDS:
            clusters.append(
                {
                    "start": round(current_start, 3),
                    "end": round(current_end, 3),
                    "duration": round(duration, 3),
                    "confidence": round(mean_confidence, 3),
                    "count": count,
                }
            )
        current_start = None
        current_end = None
        confidence_total = 0.0
        count = 0

    for start, end, confidence in intervals:
        if current_start is None or current_end is None:
            current_start = start
            current_end = end
            confidence_total = confidence
            count = 1
            continue
        if start - current_end <= VOCAL_FILTER_PREFACE_MAX_NOTE_GAP_SECONDS:
            current_end = max(current_end, end)
            confidence_total += confidence
            count += 1
            continue
        flush()
        current_start = start
        current_end = end
        confidence_total = confidence
        count = 1
    flush()
    return clusters


def _vocal_timing_windows(
    lyrics: dict[str, Any] | None,
    transcript: dict[str, Any] | None,
) -> tuple[list[tuple[float, float]], str]:
    transcript_windows = _transcript_word_windows(transcript)
    has_transcript = bool(transcript_windows)
    lyric_windows = _karaoke_lyric_windows(lyrics, merge=not has_transcript)
    line_windows = _line_lyric_windows(lyrics, merge=not has_transcript)

    if transcript_windows and lyric_windows:
        lyric_windows = _windows_missing_transcript_coverage(lyric_windows, transcript_windows)
        if not lyric_windows:
            return transcript_windows, "transcript_words"
        return _merge_time_windows(
            transcript_windows + lyric_windows,
            VOCAL_FILTER_MERGE_GAP_SECONDS,
        ), "transcript_words+karaoke_lyrics"
    if transcript_windows and line_windows:
        line_windows = _windows_missing_transcript_coverage(line_windows, transcript_windows)
        if not line_windows:
            return transcript_windows, "transcript_words"
        return _merge_time_windows(
            transcript_windows + line_windows,
            VOCAL_FILTER_MERGE_GAP_SECONDS,
        ), "transcript_words+line_lyrics"
    if transcript_windows:
        return transcript_windows, "transcript_words"

    if lyric_windows:
        return lyric_windows, "karaoke_lyrics"

    if line_windows:
        return line_windows, "line_lyrics"

    return [], "none"


def _windows_missing_transcript_coverage(
    candidate_windows: list[tuple[float, float]],
    transcript_windows: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    missing = []
    for start, end in candidate_windows:
        duration = max(0.001, end - start)
        coverage = _window_overlap_seconds(start, end, transcript_windows) / duration
        if coverage < VOCAL_FILTER_MIN_TRANSCRIPT_LINE_COVERAGE:
            missing.append((start, end))
    return missing


def _window_overlap_seconds(
    start: float,
    end: float,
    windows: list[tuple[float, float]],
) -> float:
    total = 0.0
    for window_start, window_end in windows:
        total += max(0.0, min(end, window_end) - max(start, window_start))
    return total


def _transcript_word_windows(transcript: dict[str, Any] | None) -> list[tuple[float, float]]:
    if not isinstance(transcript, dict):
        return []
    words = transcript.get("words") if isinstance(transcript.get("words"), list) else []
    intervals = []
    for word in words:
        if not isinstance(word, dict):
            continue
        start = _safe_float(word.get("start"))
        end = _safe_float(word.get("end"))
        confidence = _safe_float(word.get("probability") or word.get("confidence"))
        text = str(word.get("word") or word.get("text") or "").strip()
        if not text or start is None or end is None or end <= start:
            continue
        if confidence is not None and confidence < VOCAL_FILTER_MIN_WORD_CONFIDENCE:
            continue
        intervals.append(
            (
                max(0.0, start - VOCAL_FILTER_LEAD_SECONDS),
                end + VOCAL_FILTER_TAIL_SECONDS,
            )
        )
    return _merge_time_windows(intervals, VOCAL_FILTER_MERGE_GAP_SECONDS)


def _karaoke_lyric_windows(lyrics: dict[str, Any] | None, *, merge: bool = True) -> list[tuple[float, float]]:
    if not isinstance(lyrics, dict) or not lyrics.get("has_karaoke_timing"):
        return []
    intervals = []
    lines = lyrics.get("lines") if isinstance(lyrics.get("lines"), list) else []
    for line in lines:
        if not isinstance(line, dict):
            continue
        segments = line.get("segments") if isinstance(line.get("segments"), list) else []
        for segment in segments:
            if not isinstance(segment, dict):
                continue
            start = _safe_float(segment.get("start"))
            end = _safe_float(segment.get("end"))
            text = str(segment.get("text") or "").strip()
            if text and start is not None and end is not None and end > start:
                intervals.append((max(0.0, start - VOCAL_FILTER_LEAD_SECONDS), end + VOCAL_FILTER_TAIL_SECONDS))
    if not merge:
        return intervals
    return _merge_time_windows(intervals, VOCAL_FILTER_MERGE_GAP_SECONDS)


def _line_lyric_windows(lyrics: dict[str, Any] | None, *, merge: bool = True) -> list[tuple[float, float]]:
    if not isinstance(lyrics, dict) or lyrics.get("status") != "ready":
        return []
    lines = lyrics.get("lines") if isinstance(lyrics.get("lines"), list) else []
    intervals = []
    for line in lines:
        if not isinstance(line, dict):
            continue
        start = _safe_float(line.get("start"))
        end = _safe_float(line.get("end"))
        text = re.sub(r"\s+", " ", str(line.get("text") or "")).strip()
        if not text or start is None or end is None or end <= start:
            continue
        estimated_end = _estimated_line_vocal_end(start, end, text)
        intervals.append((max(0.0, start - VOCAL_FILTER_LEAD_SECONDS), estimated_end + VOCAL_FILTER_TAIL_SECONDS))
    if len(intervals) < 2:
        return []
    if not merge:
        return intervals
    return _merge_time_windows(intervals, VOCAL_FILTER_MERGE_GAP_SECONDS)


def _estimated_line_vocal_end(start: float, end: float, text: str) -> float:
    words = re.findall(r"[^\W_]+(?:['’][^\W_]+)*", text, flags=re.UNICODE)
    word_count = max(1, len(words))
    reasonable_duration = max(
        VOCAL_FILTER_LINE_MIN_SECONDS,
        VOCAL_FILTER_LINE_BASE_SECONDS + word_count * VOCAL_FILTER_LINE_SECONDS_PER_WORD,
    )
    return min(end, start + reasonable_duration)


def _filter_notes_to_windows(notes: list[Any], windows: list[tuple[float, float]]) -> list[dict[str, Any]]:
    filtered = []
    for note in notes:
        if not isinstance(note, dict):
            continue
        start = _safe_float(note.get("start"))
        end = _safe_float(note.get("end"))
        if start is None or end is None or end <= start:
            continue
        for window_start, window_end in _overlapping_windows(start, end, windows):
            clipped_start = max(start, window_start)
            sustain_cap = window_end
            if window_start <= start <= window_end:
                sustain_cap = window_end + VOCAL_FILTER_MAX_SUSTAIN_EXTENSION_SECONDS
            clipped_end = min(end, sustain_cap)
            if clipped_end - clipped_start < VOCAL_FILTER_MIN_NOTE_SECONDS:
                continue
            clipped = dict(note)
            clipped["start"] = round(clipped_start, 3)
            clipped["end"] = round(clipped_end, 3)
            filtered.append(clipped)
    return filtered


def _filter_contour_to_windows(
    contour: list[Any],
    windows: list[tuple[float, float]],
    notes: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    filtered = []
    note_windows = _note_windows(notes or [])
    for point in contour:
        if not isinstance(point, dict):
            continue
        time = _first_float(point.get("time"), point.get("t"), point.get("start"))
        if time is None or not (_time_in_windows(time, windows) or _time_in_windows(time, note_windows)):
            continue
        filtered.append(dict(point))
    return filtered


def _note_windows(notes: list[dict[str, Any]]) -> list[tuple[float, float]]:
    windows = []
    for note in notes:
        start = _safe_float(note.get("start"))
        end = _safe_float(note.get("end"))
        if start is not None and end is not None and end > start:
            windows.append((start, end))
    return windows


def _first_float(*values: Any) -> float | None:
    for value in values:
        parsed = _safe_float(value)
        if parsed is not None:
            return parsed
    return None


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any, *, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _overlapping_windows(
    start: float,
    end: float,
    windows: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    return [(window_start, window_end) for window_start, window_end in windows if window_end > start and window_start < end]


def _time_in_windows(time: float, windows: list[tuple[float, float]]) -> bool:
    return any(start <= time <= end for start, end in windows)


def _merge_time_windows(
    windows: list[tuple[float, float]],
    max_gap_seconds: float,
) -> list[tuple[float, float]]:
    valid_windows = [(start, end) for start, end in windows if end > start]
    if not valid_windows:
        return []
    valid_windows.sort()
    merged: list[tuple[float, float]] = []
    current_start, current_end = valid_windows[0]
    for start, end in valid_windows[1:]:
        if start - current_end <= max_gap_seconds:
            current_end = max(current_end, end)
            continue
        merged.append((round(current_start, 3), round(current_end, 3)))
        current_start, current_end = start, end
    merged.append((round(current_start, 3), round(current_end, 3)))
    return merged


def _build_pitch_tasks(lyrics_guide: dict[str, Any], melody_guide: dict[str, Any]) -> list[dict]:
    lyrics = lyrics_guide.get("lyrics") or {}
    lines = lyrics.get("lines") if isinstance(lyrics.get("lines"), list) else []
    tasks = []
    for note in melody_guide.get("notes") or []:
        start = float(note.get("start", 0))
        end = float(note.get("end", start))
        if end <= start:
            continue
        task = {
            "type": "pitch",
            "start": round(start, 3),
            "end": round(end, 3),
            "text": _lyric_text_at(lines, start, end),
            "target_midi": note.get("midi"),
            "target_note": note.get("note"),
            "target_frequency": note.get("frequency"),
            "pitch_bands_cents": PITCH_BANDS_CENTS,
            "timing_bands_ms": TIMING_BANDS_MS,
            "weight": round(max(0.25, min(1.0, float(note.get("confidence", 0.6)))), 3),
            "confidence": note.get("confidence", 0),
        }
        tasks.append(task)
    return tasks


def _lyric_text_at(lines: list[dict], start: float, end: float) -> str:
    midpoint = start + ((end - start) / 2)
    for line in lines:
        try:
            if float(line.get("start", -1)) <= midpoint <= float(line.get("end", -1)):
                return str(line.get("text") or "")
        except (TypeError, ValueError):
            continue
    return ""


def _coach_quality_status(
    lyrics_guide: dict[str, Any],
    melody_guide: dict[str, Any],
    stems: dict[str, Any] | None = None,
) -> str:
    messages = _coach_quality_messages(lyrics_guide, melody_guide, stems)
    blocking_messages = [message for message in messages if message != "line_timing_only"]
    return "ready" if not blocking_messages else "needs_review"


def _coach_quality_messages(
    lyrics_guide: dict[str, Any],
    melody_guide: dict[str, Any],
    stems: dict[str, Any] | None = None,
) -> list[str]:
    messages = []
    lyrics = lyrics_guide.get("lyrics") or {}
    if lyrics.get("status") != "ready":
        messages.append("needs_lyrics")
    if not melody_guide.get("notes"):
        messages.append("needs_melody")
    if not stems or not stems.get("vocals_path"):
        messages.append("mix_melody_only")
    if (
        lyrics.get("status") == "ready"
        and not lyrics.get("has_karaoke_timing")
        and not _lyrics_has_precise_alignment(lyrics)
    ):
        messages.append("line_timing_only")
    if _lyrics_duration_mismatch(lyrics, melody_guide):
        messages.append("lyrics_duration_mismatch")
    if _melody_ends_before_lyrics(lyrics, melody_guide):
        messages.append("melody_ends_before_lyrics")
    return messages


def _lyrics_duration_mismatch(lyrics: dict[str, Any], melody_guide: dict[str, Any]) -> bool:
    duration = _guide_duration_seconds(melody_guide)
    if not duration:
        return False
    lyrics_end = _last_line_end(lyrics)
    if not lyrics_end:
        return False
    tolerance = max(LYRICS_DURATION_TOLERANCE_SECONDS, duration * LYRICS_DURATION_TOLERANCE_RATIO)
    return lyrics_end > duration + tolerance


def _lyrics_has_precise_alignment(lyrics: dict[str, Any]) -> bool:
    alignment = lyrics.get("alignment") if isinstance(lyrics.get("alignment"), dict) else {}
    units = alignment.get("paint_units") if isinstance(alignment.get("paint_units"), list) else []
    granularity = str(alignment.get("granularity") or "").strip().casefold()
    return (
        alignment.get("status") == "ready"
        and granularity in {"word", "segment", "syllable"}
        and bool(units)
    )


def _melody_ends_before_lyrics(lyrics: dict[str, Any], melody_guide: dict[str, Any]) -> bool:
    duration = _guide_duration_seconds(melody_guide)
    if not duration:
        return False
    lyrics_end = _last_line_end(lyrics)
    notes_end = _last_note_end(melody_guide)
    if not lyrics_end or not notes_end:
        return False
    return lyrics_end <= duration + max(6.0, duration * 0.04) and notes_end + 20.0 < lyrics_end


def _guide_duration_seconds(melody_guide: dict[str, Any]) -> float:
    try:
        return float(melody_guide.get("duration_seconds") or 0)
    except (TypeError, ValueError):
        return 0.0


def _last_line_end(lyrics: dict[str, Any]) -> float:
    lines = lyrics.get("lines") if isinstance(lyrics.get("lines"), list) else []
    return _last_end(lines)


def _last_note_end(melody_guide: dict[str, Any]) -> float:
    notes = melody_guide.get("notes") if isinstance(melody_guide.get("notes"), list) else []
    return _last_end(notes)


def _last_end(items: list[dict[str, Any]]) -> float:
    values = []
    for item in items:
        try:
            values.append(float(item.get("end") or 0))
        except (AttributeError, TypeError, ValueError):
            continue
    return max(values, default=0.0)


def _coach_melody_seconds() -> int | None:
    raw_value = os.environ.get("BIAOKE_COACH_MELODY_SECONDS")
    if not raw_value:
        return None
    try:
        return max(30, min(900, int(raw_value)))
    except ValueError:
        return None


def _extract_coach_melody(media_path: Path) -> dict[str, Any]:
    service_url = os.environ.get(SCORING_SERVICE_ENV, "").strip()
    if service_url:
        try:
            return _extract_coach_melody_with_service(service_url, media_path)
        except requests.RequestException as exc:
            logging.warning("Coach melody service failed for %s, falling back locally: %s", media_path, exc)

    return extract_melody_guide_from_media(
        media_path,
        prefer_torchcrepe=_truthy(os.environ.get("BIAOKE_COACH_TORCHCREPE")),
        max_seconds=_coach_melody_seconds(),
    )


def _separate_coach_stems(media_path: Path) -> dict[str, Any] | None:
    if _falsey(os.environ.get(SEPARATE_STEMS_ENV)):
        return None

    service_url = os.environ.get(SCORING_SERVICE_ENV, "").strip()
    if not service_url:
        return None

    try:
        return _separate_coach_stems_with_service(service_url, media_path)
    except requests.RequestException as exc:
        logging.warning("Coach stem separation service failed for %s: %s", media_path, exc)
        return None


def _separate_coach_stems_with_service(service_url: str, media_path: Path) -> dict[str, Any]:
    vocals_path, instrumental_path = _stem_output_paths(media_path)
    if _existing_stems_are_ready(vocals_path, instrumental_path):
        return {
            "status": "ready",
            "engine": "demucs_cached",
            "model": os.environ.get(DEMUCS_MODEL_ENV, "htdemucs"),
            "device": "cached",
            "vocals_path": str(vocals_path),
            "instrumental_path": str(instrumental_path),
        }

    base_url = service_url.rsplit("/", 1)[0]
    response = requests.post(
        f"{base_url}/separate",
        json={
            "input_path": str(media_path),
            "vocals_path": str(vocals_path),
            "instrumental_path": str(instrumental_path),
            "model": os.environ.get(DEMUCS_MODEL_ENV, "htdemucs"),
        },
        timeout=_stems_timeout_seconds(),
    )
    response.raise_for_status()
    payload = response.json()
    return {
        "status": payload.get("status", "ready"),
        "engine": payload.get("engine", "demucs"),
        "model": payload.get("model"),
        "device": payload.get("device"),
        "vocals_path": payload.get("vocals_path") or str(vocals_path),
        "instrumental_path": payload.get("instrumental_path") or str(instrumental_path),
    }


def _existing_stems_are_ready(vocals_path: Path, instrumental_path: Path) -> bool:
    try:
        return (
            vocals_path.is_file()
            and instrumental_path.is_file()
            and vocals_path.stat().st_size > 1024
            and instrumental_path.stat().st_size > 1024
        )
    except OSError:
        return False


def _stem_output_paths(media_path: Path) -> tuple[Path, Path]:
    stems_dir = media_path.parent / ".biaoke-stems"
    return (
        stems_dir / f"{media_path.stem}.vocals.wav",
        stems_dir / f"{media_path.stem}.instrumental.wav",
    )


def _stems_timeout_seconds() -> int:
    raw_value = os.environ.get(STEMS_TIMEOUT_ENV)
    try:
        return max(300, min(3600, int(raw_value or 1800)))
    except ValueError:
        return 1800


def _transcribe_timeout_seconds() -> int:
    raw_value = os.environ.get(TRANSCRIBE_TIMEOUT_ENV)
    try:
        return max(300, min(3600, int(raw_value or 1200)))
    except ValueError:
        return 1200


def _align_timeout_seconds() -> int:
    raw_value = os.environ.get(ALIGN_TIMEOUT_ENV)
    try:
        return max(300, min(3600, int(raw_value or 1200)))
    except ValueError:
        return 1200


def _deepseek_timeout_seconds() -> int:
    raw_value = os.environ.get(DEEPSEEK_TIMEOUT_ENV)
    try:
        return max(15, min(300, int(raw_value or 90)))
    except ValueError:
        return 90


def _mimo_timeout_seconds() -> int:
    raw_value = os.environ.get(MIMO_TIMEOUT_ENV)
    try:
        return max(15, min(300, int(raw_value or 90)))
    except ValueError:
        return 90


def _deepseek_thinking_mode() -> str:
    raw_value = os.environ.get(DEEPSEEK_THINKING_ENV, "enabled").strip().casefold()
    if raw_value in {"0", "false", "off", "no", "disabled"}:
        return "disabled"
    return "enabled"


def _deepseek_reasoning_effort() -> str:
    raw_value = os.environ.get(DEEPSEEK_REASONING_EFFORT_ENV, DEFAULT_DEEPSEEK_REASONING_EFFORT)
    effort = str(raw_value or DEFAULT_DEEPSEEK_REASONING_EFFORT).strip().casefold()
    return effort if effort in {"high", "max"} else DEFAULT_DEEPSEEK_REASONING_EFFORT


def _transcribe_and_align_coach_vocals(
    media_path: Path,
    lyrics: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    transcript = _transcribe_coach_vocals(media_path)
    transcript_alignment = build_word_alignment_from_transcript(
        lyrics,
        transcript.get("words") if isinstance(transcript, dict) else [],
        method="faster_whisper_word_alignment",
    )
    if isinstance(transcript, dict):
        transcript = {**transcript, "alignment_coverage": _alignment_coverage(transcript_alignment)}
    if not _should_retry_transcription_with_lyrics_prompt(lyrics, transcript_alignment):
        return transcript, transcript_alignment

    prompt = _transcription_prompt_from_lyrics(lyrics)
    if not prompt:
        return transcript, transcript_alignment

    retry_transcript = _transcribe_coach_vocals(
        media_path,
        vad_filter=False,
        initial_prompt=prompt,
        beam_size=8,
        mode="lyrics_prompt_no_vad",
    )
    retry_alignment = build_word_alignment_from_transcript(
        lyrics,
        retry_transcript.get("words") if isinstance(retry_transcript, dict) else [],
        method="faster_whisper_lyrics_prompt_no_vad_alignment",
    )
    if isinstance(retry_transcript, dict):
        retry_transcript = {**retry_transcript, "alignment_coverage": _alignment_coverage(retry_alignment)}
    if _alignment_coverage(retry_alignment) <= _alignment_coverage(transcript_alignment):
        return transcript, transcript_alignment

    selected = dict(retry_transcript or {})
    selected["fallback_of"] = _transcript_metadata(transcript)
    selected["selection_reason"] = "lyrics_prompt_no_vad_improved_alignment"
    selected["alignment_coverage"] = _alignment_coverage(retry_alignment)
    return selected, retry_alignment


def _should_retry_transcription_with_lyrics_prompt(
    lyrics: dict[str, Any],
    transcript_alignment: dict[str, Any] | None,
) -> bool:
    if not _lyrics_ready(lyrics):
        return False
    if not _transcription_prompt_from_lyrics(lyrics):
        return False
    return _alignment_coverage(transcript_alignment) < TRANSCRIPT_RETRY_MIN_ALIGNMENT_COVERAGE


def _transcription_prompt_from_lyrics(lyrics: dict[str, Any]) -> str:
    if not _lyrics_ready(lyrics):
        return ""
    lines = lyrics.get("lines") if isinstance(lyrics.get("lines"), list) else []
    fragments = []
    for line in lines:
        if not isinstance(line, dict):
            continue
        text = re.sub(r"\s+", " ", str(line.get("text") or "")).strip()
        if text:
            fragments.append(text)
        prompt = " ".join(fragments)
        if len(prompt) >= TRANSCRIPTION_PROMPT_MAX_CHARS:
            return prompt[:TRANSCRIPTION_PROMPT_MAX_CHARS]
    return " ".join(fragments)[:TRANSCRIPTION_PROMPT_MAX_CHARS]


def _alignment_coverage(alignment: dict[str, Any] | None) -> float:
    if not isinstance(alignment, dict):
        return 0.0
    confidence = alignment.get("confidence") if isinstance(alignment.get("confidence"), dict) else {}
    try:
        return float(confidence.get("overall") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _transcript_metadata(transcript: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(transcript, dict):
        return {"status": "missing"}
    return {
        "status": transcript.get("status"),
        "engine": transcript.get("engine"),
        "model": transcript.get("model"),
        "language": transcript.get("language"),
        "vad_filter": transcript.get("vad_filter"),
        "prompted": transcript.get("prompted"),
        "word_count": len(transcript.get("words") or []),
        "alignment_coverage": transcript.get("alignment_coverage"),
    }


def _transcribe_coach_vocals(
    media_path: Path,
    *,
    vad_filter: bool = True,
    initial_prompt: str | None = None,
    beam_size: int = 5,
    mode: str = "default",
) -> dict[str, Any] | None:
    service_url = os.environ.get(SCORING_SERVICE_ENV, "").strip()
    if not service_url:
        return None
    try:
        return _transcribe_coach_vocals_with_service(
            service_url,
            media_path,
            vad_filter=vad_filter,
            initial_prompt=initial_prompt,
            beam_size=beam_size,
            mode=mode,
        )
    except requests.RequestException as exc:
        logging.warning("Coach transcription service failed for %s: %s", media_path, exc)
        return None


def _transcribe_coach_vocals_with_service(
    service_url: str,
    media_path: Path,
    *,
    vad_filter: bool,
    initial_prompt: str | None,
    beam_size: int,
    mode: str,
) -> dict[str, Any]:
    base_url = service_url.rsplit("/", 1)[0]
    response = requests.post(
        f"{base_url}/transcribe",
        json={
            "input_path": str(media_path),
            "model": os.environ.get(TRANSCRIBE_MODEL_ENV, "medium"),
            "vad_filter": bool(vad_filter),
            "initial_prompt": initial_prompt or None,
            "beam_size": int(beam_size),
        },
        timeout=_transcribe_timeout_seconds(),
    )
    response.raise_for_status()
    payload = response.json()
    return {
        "status": payload.get("status", "ready"),
        "engine": payload.get("engine", "faster-whisper"),
        "model": payload.get("model"),
        "device": payload.get("device"),
        "mode": mode,
        "vad_filter": payload.get("vad_filter", vad_filter),
        "prompted": payload.get("prompted", bool(initial_prompt)),
        "language": payload.get("language"),
        "language_probability": payload.get("language_probability"),
        "words": payload.get("words") or [],
    }


def _align_coach_lyrics(
    media_path: Path,
    lyrics: dict[str, Any],
    melody_guide: dict[str, Any],
    transcript: dict[str, Any] | None,
    *,
    transcript_alignment: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    service_url = os.environ.get(SCORING_SERVICE_ENV, "").strip()
    if not service_url:
        return None

    lines = _lyrics_lines_for_forced_alignment(lyrics, melody_guide, transcript_alignment)
    if not lines:
        return None

    try:
        return _align_coach_lyrics_with_service(
            service_url,
            media_path,
            lines,
            language=_transcript_language(transcript),
        )
    except requests.RequestException as exc:
        logging.warning("Coach forced lyric alignment failed for %s: %s", media_path, exc)
        return None


def _align_coach_lyrics_with_service(
    service_url: str,
    media_path: Path,
    lines: list[dict[str, Any]],
    *,
    language: str | None,
) -> dict[str, Any] | None:
    base_url = service_url.rsplit("/", 1)[0]
    response = requests.post(
        f"{base_url}/align-lyrics",
        json={
            "input_path": str(media_path),
            "language": language or "auto",
            "model": "mms_fa",
            "lines": lines,
        },
        timeout=_align_timeout_seconds(),
    )
    response.raise_for_status()
    payload = response.json()
    if _is_usable_forced_alignment(payload):
        return payload
    logging.info(
        "Coach forced lyric alignment not usable for %s: %s",
        media_path,
        (payload or {}).get("reason") if isinstance(payload, dict) else "invalid_payload",
    )
    return None


def _lyrics_lines_for_forced_alignment(
    lyrics: dict[str, Any],
    melody_guide: dict[str, Any],
    transcript_alignment: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not isinstance(lyrics, dict) or lyrics.get("status") != "ready":
        return []
    source_lines = lyrics.get("lines") if isinstance(lyrics.get("lines"), list) else []
    if not source_lines:
        return []

    refined_lyrics = with_vocal_activity_alignment(lyrics, melody_guide)
    refined_windows = _line_windows_from_alignment(refined_lyrics.get("alignment") or {})
    transcript_windows = _line_windows_from_word_alignment(transcript_alignment, source_lines)
    lines = []
    previous_start = 0.0
    for line_index, line in enumerate(source_lines):
        if not isinstance(line, dict):
            continue
        text = re.sub(r"\s+", " ", str(line.get("text") or "")).strip()
        if not text:
            continue
        timing_source = "transcript_words"
        window = transcript_windows.get(line_index)
        if not window:
            window = refined_windows.get(line_index)
            timing_source = "line_activity" if window else "line_timing"
        start, end = window or _raw_line_window(line)
        if start is None or end is None or end <= start:
            continue
        start = max(0.0, start)
        if start + 0.08 < previous_start:
            start = previous_start
        end = max(end, start + 0.2)
        lines.append(
            {
                "line_index": line_index,
                "start": round(start, 3),
                "end": round(end, 3),
                "text": text,
                "timing_source": timing_source,
            }
        )
        previous_start = start
    return lines


def _line_windows_from_alignment(alignment: dict[str, Any]) -> dict[int, tuple[float, float]]:
    units = alignment.get("paint_units") if isinstance(alignment.get("paint_units"), list) else []
    windows: dict[int, tuple[float, float]] = {}
    for unit in units:
        if not isinstance(unit, dict) or unit.get("unit_type") != "line":
            continue
        start = _safe_float(unit.get("start"))
        end = _safe_float(unit.get("end"))
        line_index = _safe_int(unit.get("line_index"), default=-1)
        if line_index < 0 or start is None or end is None or end <= start:
            continue
        windows[line_index] = (start, end)
    return windows


def _line_windows_from_word_alignment(
    alignment: dict[str, Any] | None,
    source_lines: list[Any],
) -> dict[int, tuple[float, float]]:
    if not isinstance(alignment, dict):
        return {}
    units = alignment.get("paint_units") if isinstance(alignment.get("paint_units"), list) else []
    by_line: dict[int, list[dict[str, Any]]] = {}
    for unit in units:
        if not isinstance(unit, dict):
            continue
        if str(unit.get("unit_type") or "").strip().casefold() != "word":
            continue
        if "interpolated" in str(unit.get("precision") or ""):
            continue
        start = _safe_float(unit.get("start"))
        end = _safe_float(unit.get("end"))
        line_index = _safe_int(unit.get("line_index"), default=-1)
        if line_index < 0 or start is None or end is None or end <= start:
            continue
        by_line.setdefault(line_index, []).append(unit)

    windows = {}
    for line_index, line_units in by_line.items():
        if line_index >= len(source_lines):
            continue
        line = source_lines[line_index] if isinstance(source_lines[line_index], dict) else {}
        word_count = max(1, _lyric_word_count(str(line.get("text") or "")))
        coverage = len(line_units) / word_count
        if coverage < FORCED_ALIGNMENT_LINE_MIN_TRANSCRIPT_COVERAGE:
            continue
        start = min(float(unit["start"]) for unit in line_units)
        end = max(float(unit["end"]) for unit in line_units)
        if end > start:
            windows[line_index] = (start, end)
    return windows


def _raw_line_window(line: dict[str, Any]) -> tuple[float | None, float | None]:
    return _safe_float(line.get("start")), _safe_float(line.get("end"))


def _lyric_word_count(text: str) -> int:
    return len(re.findall(r"[^\W_]+(?:['’][^\W_]+)*", str(text or ""), flags=re.UNICODE))


def _transcript_language(transcript: dict[str, Any] | None) -> str | None:
    if not isinstance(transcript, dict):
        return None
    value = str(transcript.get("language") or "").strip()
    if not value:
        return None
    return value


def _extract_coach_melody_with_service(service_url: str, media_path: Path) -> dict[str, Any]:
    base_url = service_url.rsplit("/", 1)[0]
    params = {}
    max_seconds = _coach_melody_seconds()
    if max_seconds is not None:
        params["max_seconds"] = str(max_seconds)
    with media_path.open("rb") as handle:
        response = requests.post(
            f"{base_url}/melody",
            params=params,
            files={"audio": (media_path.name, handle, "application/octet-stream")},
            timeout=600,
        )
    response.raise_for_status()
    return response.json()


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().casefold() in {"1", "true", "yes", "on"}


def _falsey(value: str | None) -> bool:
    return str(value or "").strip().casefold() in {"0", "false", "no", "off"}
