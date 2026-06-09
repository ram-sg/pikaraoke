"""FFmpeg utilities for media processing and transcoding."""

from __future__ import annotations

import logging
import platform
import subprocess
from typing import TYPE_CHECKING, Any

import ffmpeg

from biaoke.lib.get_platform import is_running_in_docker

if TYPE_CHECKING:
    from biaoke.lib.file_resolver import FileResolver


def get_media_duration(file_path: str) -> int | None:
    """Get the duration of a media file in seconds.

    Args:
        file_path: Path to the media file.

    Returns:
        Duration in seconds (rounded), or None if unable to determine.
    """
    try:
        duration = ffmpeg.probe(file_path)["format"]["duration"]
        return round(float(duration))
    except:
        return None


def has_video_stream(file_path: str) -> bool:
    """Return True when a media file has at least one video stream."""
    try:
        probe = ffmpeg.probe(file_path)
    except Exception:
        return False
    return any(stream.get("codec_type") == "video" for stream in probe.get("streams", []))


def build_ffmpeg_cmd(
    fr: FileResolver,
    semitones: int = 0,
    normalize_audio: bool = True,
    force_mp4_encoding: bool = False,
    buffer_fully_before_playback: bool = False,
    avsync: float = 0,
    cdg_pixel_scaling: bool = False,
) -> Any:
    """Build an ffmpeg command for transcoding media.

    Handles video/audio codec selection, pitch shifting, audio normalization,
    and CDG file rendering.

    Args:
        fr: FileResolver instance with source file information.
        semitones: Number of semitones to shift pitch (0 = no shift).
        normalize_audio: Whether to apply loudness normalization.
        force_mp4_encoding: If True, force mp4 encoding.
        avsync: Audio/video sync adjustment in seconds.
        cdg_pixel_scaling: Enable pixel scaling for CDG rendering.

    Returns:
        ffmpeg stream object ready to execute with run_async().
    """
    avsync = float(avsync)
    is_cdg = fr.cdg_file_path is not None
    is_transposed = semitones != 0

    if fr.file_path is None:
        raise ValueError("File path is required to build ffmpeg command")

    # Use h/w acceleration on Pi
    using_hardware_encoder = supports_hardware_h264_encoding()
    default_vcodec = "h264_v4l2m2m" if using_hardware_encoder else "libx264"

    has_video = is_cdg or has_video_stream(fr.file_path)

    # CDG always needs encoding; MP4 can copy video stream (already H.264 compatible).
    # WEBM uses VP8/VP9 which must be transcoded to H.264 for fMP4 containers.
    if not has_video:
        vcodec = None
    elif is_cdg:
        vcodec = "libx264"
    else:
        vcodec = "copy" if fr.file_extension == ".mp4" else default_vcodec

    # Optimize bitrate: CDG is simple graphics (500k), video files need more
    # Pi 3B+ struggles with 5M in real-time, 2M provides better stability
    if not has_video:
        vbitrate = None
    elif is_cdg:
        vbitrate = "500k"
    elif using_hardware_encoder:
        vbitrate = "2M"
    else:
        vbitrate = "5M"

    # Copy audio if no processing needed, otherwise re-encode with AAC.
    # CDG and audio-only stems always re-encode audio for browser/container compatibility.
    acodec = "aac" if not has_video or is_cdg or is_transposed or normalize_audio or avsync != 0 else "copy"

    # For container formats with VFR or timestamp issues, use genpts
    if fr.file_extension in [".webm", ".avi", ".mov", ".mkv"]:
        input = ffmpeg.input(fr.file_path, **{"fflags": "+genpts"})
    else:
        input = ffmpeg.input(fr.file_path)
    audio = input.audio

    # Audio sync adjustment: delay or trim
    if avsync > 0:
        audio = audio.filter("adelay", f"{avsync * 1000}|{avsync * 1000}")
    elif avsync < 0:
        audio = audio.filter("atrim", start=-avsync)

    # Pitch shifting: 2^(semitones/12)
    if is_transposed:
        audio = audio.filter("rubberband", pitch=2 ** (semitones / 12))

    # Loudness normalization
    if normalize_audio:
        audio = audio.filter("loudnorm", i=-16, tp=-1.5, lra=11)

    # Video source: CDG input, original video stream, or none for audio-only stems.
    if is_cdg:
        logging.info("Playing CDG/MP3 file: " + fr.file_path)
        cdg_input = ffmpeg.input(fr.cdg_file_path, copyts=None)
        video = cdg_input.video.filter("fps", fps=25)
        if cdg_pixel_scaling:
            video = video.filter("scale", -1, 720, flags="neighbor")
    elif has_video:
        video = input.video
    else:
        video = None

    # Build output based on format
    if force_mp4_encoding:
        movflags = (
            "+faststart" if buffer_fully_before_playback else "frag_keyframe+default_base_moof"
        )
        output_streams = (audio, video) if video is not None else (audio,)
        output_kwargs = {
            "acodec": acodec,
            "listen": 1,
            "f": "mp4",
            "movflags": movflags,
        }
        if video is not None:
            output_kwargs.update(
                {
                    "vcodec": vcodec,
                    "preset": "ultrafast",
                    "video_bitrate": vbitrate,
                    **({"pix_fmt": "yuv420p"} if is_cdg else {}),
                }
            )
        output = ffmpeg.output(
            *output_streams,
            fr.output_file,
            **output_kwargs,
        )
    else:
        # HLS format with fMP4 segments
        # Both MP4 and HLS streaming modes use this - difference is in serving:
        # - mp4: Stream concatenates init + segments for progressive playback
        # - hls: Browser requests segments via .m3u8 playlist
        output_streams = (audio, video) if video is not None else (audio,)
        output_kwargs = {
            "acodec": "aac",
            "audio_bitrate": "192k",
            "ac": 2,  # Force stereo
            "ar": 48000,  # Standard sample rate
            "f": "hls",
            "hls_time": 3,
            "hls_list_size": 0,
            "hls_playlist_type": "event",
            "hls_segment_type": "fmp4",
            "hls_fmp4_init_filename": fr.init_filename,
            "hls_segment_filename": fr.segment_pattern,
        }
        if video is not None:
            output_kwargs.update(
                {
                    "vcodec": vcodec,
                    "preset": "ultrafast",
                    "video_bitrate": vbitrate,
                    **({"pix_fmt": "yuv420p"} if is_cdg else {}),
                    "vsync": "cfr",
                    "avoid_negative_ts": "make_zero",
                }
            )
        output = ffmpeg.output(
            *output_streams,
            fr.output_file,
            **output_kwargs,
        )

    args = output.get_args()
    logging.debug(f"COMMAND: ffmpeg " + " ".join(args))
    return output


def get_ffmpeg_version() -> str:
    """Get the installed FFmpeg version string.

    Returns:
        Version string, or an error message if FFmpeg is not installed
        or version cannot be parsed.
    """
    try:
        # Execute the command 'ffmpeg -version'
        result = subprocess.run(
            ["ffmpeg", "-version"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )
        # Parse the first line to get the version
        first_line = result.stdout.split("\n")[0]
        version_info = first_line.split(" ")[2]  # Assumes the version info is the third element
        return version_info
    except FileNotFoundError:
        return "FFmpeg is not installed"
    except IndexError:
        return "Unable to parse FFmpeg version"


def is_transpose_enabled() -> bool:
    """Check if FFmpeg has the rubberband filter for pitch shifting.

    Returns:
        True if rubberband filter is available, False otherwise.
    """
    try:
        filters = subprocess.run(["ffmpeg", "-filters"], capture_output=True)
    except FileNotFoundError:
        return False
    except IndexError:
        return False
    return "rubberband" in filters.stdout.decode()


def supports_hardware_h264_encoding() -> bool:
    """Check if hardware H.264 encoding (h264_v4l2m2m) is available.

    Only returns True on ARM architecture (Raspberry Pi) where h264_v4l2m2m
    is actually supported. On x86/Intel systems, returns False to use software encoding.

    Returns:
        True if hardware encoding is available, False otherwise.
    """
    # Check CPU architecture first - h264_v4l2m2m only works on ARM
    arch = platform.machine().lower()
    is_arm = any(arm_variant in arch for arm_variant in ["arm", "aarch"])

    if not is_arm:
        # Not ARM (probably Intel x86/x64), don't use h264_v4l2m2m
        logging.debug(f"CPU architecture {arch} is not ARM, using software encoder")
        return False

    if is_running_in_docker():
        # Docker containers do not have access to the GPU
        logging.debug("Running in Docker where GPU access is not available, using software encoder")
        return False

    # On ARM, check if h264_v4l2m2m is available
    try:
        codecs = subprocess.run(["ffmpeg", "-codecs"], capture_output=True)
    except FileNotFoundError:
        return False
    except IndexError:
        return False

    has_encoder = "h264_v4l2m2m" in codecs.stdout.decode()
    if has_encoder:
        logging.info("ARM platform detected, using h264_v4l2m2m hardware encoder")
    else:
        logging.debug("ARM platform but h264_v4l2m2m not available")

    return has_encoder


def is_ffmpeg_installed() -> bool:
    """Check if FFmpeg is installed and accessible.

    Returns:
        True if FFmpeg is installed, False otherwise.
    """
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True)
    except FileNotFoundError:
        return False
    return True
