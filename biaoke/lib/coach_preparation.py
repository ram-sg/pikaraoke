"""Coach catalog preparation orchestration."""

from __future__ import annotations

import logging
import json
import os
from pathlib import Path
from threading import Event, Thread
from typing import Any

import requests

from biaoke.lib.events import EventSystem
from biaoke.lib.karaoke_database import KaraokeDatabase
from biaoke.lib.lyrics_alignment import with_vocal_activity_alignment
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
PITCH_BANDS_CENTS = [25, 40, 60, 80, 100, 130, 160, 200, 250, 320]
TIMING_BANDS_MS = [40, 70, 100, 140, 180, 230, 290, 360, 450, 600]
LYRICS_DURATION_TOLERANCE_SECONDS = 12.0
LYRICS_DURATION_TOLERANCE_RATIO = 0.08


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
            track["assets"] = self._db.get_coach_assets(track["id"])
        return tracks

    def get_track_with_assets(self, track_id: int) -> dict[str, Any] | None:
        """Return one coach track with jobs/assets attached."""
        track = self._db.get_coach_track(track_id)
        if not track:
            return None
        jobs = self._db.list_coach_jobs(track_id=track_id, limit=10)
        track["jobs"] = jobs
        track["latest_job"] = jobs[0] if jobs else None
        track["assets"] = self._db.get_coach_assets(track_id)
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
            lyrics_guide = write_song_guide(media_path)
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
            transcript = _transcribe_coach_vocals(melody_source_path)
            self._db.update_coach_job(job_id, stage="write_coach_guide", progress=85)
            coach_guide_path = _write_coach_guide(
                media_path,
                lyrics_guide,
                melody_guide,
                stems=stems,
                melody_source_path=melody_source_path,
                transcript=transcript,
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

        quality_status = _coach_quality_status(lyrics_guide, melody_guide, stems)
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
) -> Path:
    path = _coach_guide_path(media_path)
    lyrics = with_vocal_activity_alignment(lyrics_guide.get("lyrics") or {}, melody_guide)
    word_alignment = build_word_alignment_from_transcript(
        lyrics_guide.get("lyrics") or {},
        transcript.get("words") if isinstance(transcript, dict) else [],
        method="faster_whisper_word_alignment",
    )
    if word_alignment:
        lyrics["alignment"] = word_alignment
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
            "status": _coach_quality_status(lyrics_guide, melody_guide, stems),
            "lyrics_ready": (lyrics_guide.get("lyrics") or {}).get("status") == "ready",
            "melody_ready": bool(melody_guide.get("notes")),
            "vocal_stem_ready": bool(stems and stems.get("vocals_path")),
            "messages": _coach_quality_messages(lyrics_guide, melody_guide, stems),
        },
    }
    tmp_path = path.with_name(path.name + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(tmp_path, path)
    return path


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
    if lyrics.get("status") == "ready" and not lyrics.get("has_karaoke_timing"):
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


def _transcribe_coach_vocals(media_path: Path) -> dict[str, Any] | None:
    service_url = os.environ.get(SCORING_SERVICE_ENV, "").strip()
    if not service_url:
        return None
    try:
        return _transcribe_coach_vocals_with_service(service_url, media_path)
    except requests.RequestException as exc:
        logging.warning("Coach transcription service failed for %s: %s", media_path, exc)
        return None


def _transcribe_coach_vocals_with_service(service_url: str, media_path: Path) -> dict[str, Any]:
    base_url = service_url.rsplit("/", 1)[0]
    response = requests.post(
        f"{base_url}/transcribe",
        json={
            "input_path": str(media_path),
            "model": os.environ.get(TRANSCRIBE_MODEL_ENV, "medium"),
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
        "language": payload.get("language"),
        "language_probability": payload.get("language_probability"),
        "words": payload.get("words") or [],
    }


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
