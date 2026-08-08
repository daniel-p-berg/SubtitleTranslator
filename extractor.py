"""
extractor.py - Extract English subtitle tracks from MKV/MP4 video files.

Uses ffprobe to inspect subtitle streams and ffmpeg to extract/convert
them to SRT format for downstream translation.
"""

import json
import os
import re
import subprocess
import tempfile
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import median

import app_paths
import dependencies
import languages
import subtitle_sync

FFPROBE_PATH = dependencies.resolve_tool("ffprobe") or "ffprobe"
FFMPEG_PATH = dependencies.resolve_tool("ffmpeg") or "ffmpeg"

# Image-based subtitle codecs that cannot be translated
IMAGE_BASED_CODECS = {
    "hdmv_pgs_bitmap",
    "hdmv_pgs_subtitle",
    "pgssub",
    "dvd_subtitle",
    "dvdsub",
    "xsub",
    "dvb_subtitle",
    "dvb_teletext",
}

PGS_CODECS = {
    "hdmv_pgs_bitmap",
    "hdmv_pgs_subtitle",
    "pgssub",
}

# Text-based subtitle codecs that can be converted to SRT
TEXT_BASED_CODECS = {
    "srt",
    "subrip",
    "ass",
    "ssa",
    "webvtt",
    "mov_text",
    "text",
    "microdvd",
    "jacosub",
    "sami",
    "realtext",
    "subviewer",
    "subviewer1",
}

_ENGLISH_TOKENS = {"en", "eng", "english"}
_VIETNAMESE_TOKENS = {"vi", "vie", "viet", "vietnamese", "vn"}
_NON_ENGLISH_TOKENS = {
    "ara",
    "arabic",
    "chi",
    "chinese",
    "de",
    "deu",
    "dut",
    "es",
    "esp",
    "fre",
    "french",
    "ger",
    "german",
    "hin",
    "hindi",
    "ind",
    "indonesian",
    "ita",
    "italian",
    "ja",
    "japanese",
    "jpn",
    "kor",
    "korean",
    "por",
    "portuguese",
    "pt",
    "rus",
    "russian",
    "spa",
    "spanish",
    "tha",
    "thai",
    "vi",
    "vie",
    "vietnamese",
    "zho",
}
_TITLE_NOISE_TOKENS = {
    "1080p",
    "2160p",
    "480p",
    "720p",
    "aac",
    "ac3",
    "bluray",
    "ddp",
    "dl",
    "dual",
    "eac3",
    "h264",
    "h265",
    "hevc",
    "and",
    "for",
    "from",
    "proper",
    "repack",
    "sub",
    "subs",
    "subtitle",
    "subtitles",
    "the",
    "web",
    "webdl",
    "webrip",
    "with",
    "x264",
    "x265",
}
_MAX_SUBTITLE_SCORE_BYTES = 2 * 1024 * 1024

def _check_tool(_path: str, name: str) -> str:
    """Resolve a tool at call time so guided installs work without a restart."""
    try:
        return dependencies.require_tool(name)
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            f"{name} is required for subtitle inspection. "
            "Install FFmpeg with Homebrew: brew install ffmpeg"
        ) from exc


def _probe_subtitle_streams(input_path: str) -> list[dict]:
    """
    Run ffprobe on the input file and return all subtitle stream metadata.

    Args:
        input_path: Absolute or relative path to the video file.

    Returns:
        A list of dicts, one per subtitle stream, as returned by ffprobe.

    Raises:
        FileNotFoundError: If ffprobe is not installed.
        RuntimeError: If ffprobe fails to read the file.
    """
    ffprobe_path = _check_tool(FFPROBE_PATH, "ffprobe")

    cmd = [
        ffprobe_path,
        "-v", "error",
        "-print_format", "json",
        "-show_streams",
        "-select_streams", "s",
        input_path,
    ]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"ffprobe failed on '{input_path}':\n{result.stderr.strip()}"
        )

    data = json.loads(result.stdout)
    return data.get("streams", [])


def _stream_summary(streams: list[dict]) -> str:
    """
    Build a human-readable summary of subtitle streams for error messages.

    Args:
        streams: List of ffprobe stream dicts.

    Returns:
        A formatted multi-line string describing each stream.
    """
    if not streams:
        return "  (no subtitle tracks found in this file)"

    lines = []
    for s in streams:
        idx = s.get("index", "?")
        codec = s.get("codec_name", "unknown")
        tags = s.get("tags", {})
        lang = tags.get("language", tags.get("LANGUAGE", "und"))
        title = tags.get("title", tags.get("TITLE", ""))
        disp = s.get("disposition", {})
        flags = []
        if disp.get("default"):
            flags.append("default")
        if disp.get("forced"):
            flags.append("forced")
        flag_str = f" [{', '.join(flags)}]" if flags else ""
        title_str = f" - {title}" if title else ""
        lines.append(f"  Stream #{idx}: lang={lang}, codec={codec}{title_str}{flag_str}")

    return "\n".join(lines)


def _pick_english_stream(streams: list[dict]) -> dict:
    """
    Select the best English subtitle stream from a list of streams.

    Selection priority:
      1. Full/non-forced English stream whose title contains 'full'
      2. Full/non-forced English stream flagged as 'default'
      3. First full/non-forced English stream found
      4. Forced/signs-only English streams as a last resort

    Args:
        streams: All subtitle streams from ffprobe.

    Returns:
        The chosen stream dict.

    Raises:
        ValueError: If no English subtitle track is found, with a detailed
                    description of the tracks that ARE present.
    """
    english_langs = {"eng", "en", "english"}

    english_streams = []
    for s in streams:
        tags = s.get("tags", {})
        lang = tags.get("language", tags.get("LANGUAGE", "")).lower().strip()
        if lang in english_langs:
            english_streams.append(s)

    if not english_streams:
        summary = _stream_summary(streams)
        raise ValueError(
            f"No English subtitle track found in the file.\n"
            f"Subtitle tracks present:\n{summary}\n\n"
            f"Tip: Look for a track with language tag 'eng', 'en', or 'english'."
        )

    text_streams = [
        s
        for s in english_streams
        if s.get("codec_name", "").lower().strip() not in IMAGE_BASED_CODECS
    ]
    if not text_streams:
        summary = _stream_summary(streams)
        raise ValueError(
            "No text-based English subtitle track found in the file.\n"
            f"Subtitle tracks present:\n{summary}\n\n"
            "Image-based subtitle tracks such as PGS store pictures, not text, "
            "so they cannot be translated or used for timing sync."
        )

    full_streams = [s for s in text_streams if not _is_forced_or_signs_stream(s)]
    fallback_streams = full_streams or text_streams

    # Prefer stream whose title contains 'full'
    for s in fallback_streams:
        tags = s.get("tags", {})
        title = tags.get("title", tags.get("TITLE", "")).lower()
        if "full" in title:
            return s

    # Prefer default-flagged stream, but only after excluding forced/signs-only
    # tracks when a full English track is available.
    for s in fallback_streams:
        disp = s.get("disposition", {})
        if disp.get("default"):
            return s

    # Fall back to first viable English stream.
    return fallback_streams[0]


@dataclass(frozen=True)
class ExternalSubtitle:
    """One text subtitle discovered inside the approved media container."""

    path: Path
    language: languages.LanguageProfile | None
    score: float


def probe_subtitle_streams(input_path: str) -> list[dict]:
    """Return embedded subtitle metadata for the selected media file."""
    return _probe_subtitle_streams(input_path)


def stream_language(stream: dict) -> languages.LanguageProfile | None:
    """Resolve a supported language from an ffprobe subtitle stream."""
    tags = stream.get("tags") or {}
    value = str(tags.get("language", tags.get("LANGUAGE", "")))
    title = str(tags.get("title", tags.get("TITLE", "")))
    return languages.identify_language(value, title)


def is_text_stream(stream: dict) -> bool:
    """Return whether a stream can be extracted as text."""
    codec = str(stream.get("codec_name", "")).lower().strip()
    return codec in TEXT_BASED_CODECS or codec not in IMAGE_BASED_CODECS


def is_pgs_stream(stream: dict) -> bool:
    """Return whether a stream contains Blu-ray PGS subtitle images."""
    codec = str(stream.get("codec_name", "")).lower().strip()
    return codec in PGS_CODECS


def is_language_stream(
    stream: dict,
    language_code: str,
    *,
    text_only: bool = False,
) -> bool:
    """Return whether stream metadata identifies a requested language."""
    profile = stream_language(stream)
    if profile is None or profile.code != languages.get_language(language_code).code:
        return False
    return not text_only or is_text_stream(stream)


def pick_language_stream(
    streams: list[dict],
    language_code: str,
    *,
    text_only: bool = True,
) -> dict | None:
    """Choose the best embedded subtitle for one supported language."""
    candidates = [
        stream
        for stream in streams
        if is_language_stream(stream, language_code, text_only=text_only)
    ]
    if not candidates:
        return None
    return max(candidates, key=_stream_preference_score)


def pick_reference_stream(
    streams: list[dict],
    *,
    preferred_language: str = "auto",
    excluded_language: str | None = None,
    text_only: bool = True,
) -> dict | None:
    """Choose the best independent subtitle reference in any language."""
    candidates = reference_stream_candidates(
        streams,
        preferred_language=preferred_language,
        excluded_language=excluded_language,
        text_only=text_only,
    )
    return candidates[0] if candidates else None


def reference_stream_candidates(
    streams: list[dict],
    *,
    preferred_language: str = "auto",
    excluded_language: str | None = None,
    text_only: bool = True,
) -> list[dict]:
    """Return viable embedded references in deterministic preference order."""
    candidates = [
        stream
        for stream in streams
        if (not text_only or is_text_stream(stream))
        and not _is_forced_or_signs_stream(stream)
    ]
    if excluded_language:
        excluded = languages.get_language(excluded_language).code
        candidates = [
            stream
            for stream in candidates
            if not stream_language(stream)
            or stream_language(stream).code != excluded
        ]
    if not candidates:
        return []

    preferred_code = None
    if preferred_language and preferred_language != "auto":
        preferred_code = languages.get_language(preferred_language).code
    return sorted(
        candidates,
        reverse=True,
        key=lambda stream: (
            1
            if preferred_code
            and stream_language(stream)
            and stream_language(stream).code == preferred_code
            else 0,
            *_stream_preference_score(stream),
        ),
    )


def is_probable_progressive_caption_srt(path: str | Path) -> bool:
    """Detect cue-per-word or cue-per-frame exports unsafe to translate raw."""
    source = Path(path)
    try:
        cues = subtitle_sync.parse_srt_timings(source)
    except (OSError, ValueError):
        return False
    # ASS conversions can contain hundreds of zero-duration drawing or
    # replacement events alongside ordinary dialogue.  Those events never
    # remain visible long enough to behave like progressive captions and must
    # not make a full dialogue track look like a cue-per-word export.
    visible_durations = [
        cue.end_ms - cue.start_ms
        for cue in cues
        if cue.end_ms > cue.start_ms
    ]
    if len(visible_durations) < 500:
        return False
    short_cues = sum(
        duration_ms < 250
        for duration_ms in visible_durations
    )
    return short_cues / len(visible_durations) >= 0.55


@dataclass(frozen=True)
class ProgressiveCaptionCollapseReport:
    """Summary of repeated animation frames collapsed into stable captions."""

    total_cues: int
    collapsed_source_cues: int
    replacement_cues: int
    discarded_empty_cues: int
    output_cues: int


def collapse_repeated_progressive_caption_cues(
    srt_path: str | Path,
    *,
    output_directory: str | Path | None = None,
) -> tuple[str, ProgressiveCaptionCollapseReport]:
    """Collapse identical rapid-fire animation frames into stable SRT cues."""
    source = Path(srt_path).resolve()
    raw = source.read_text(encoding="utf-8-sig")
    cues = _parse_structured_srt(raw)
    timing_line_count = sum(
        1 for line in raw.splitlines() if _SRT_TIMING_RE.match(line)
    )
    if (
        not cues
        or timing_line_count <= 0
        or len(cues) / timing_line_count < 0.95
    ):
        return str(source), ProgressiveCaptionCollapseReport(
            total_cues=timing_line_count,
            collapsed_source_cues=0,
            replacement_cues=0,
            discarded_empty_cues=0,
            output_cues=timing_line_count,
        )

    rapid_by_text: defaultdict[tuple[str, ...], list[tuple[int, int]]] = (
        defaultdict(list)
    )
    for cue_index, cue in enumerate(cues):
        if cue.end_ms - cue.start_ms >= 250:
            continue
        text_key = tuple(line.strip() for line in cue.text_lines)
        if not any(text_key):
            continue
        rapid_by_text[text_key].append((cue.start_ms, cue_index))

    collapsible_groups: list[list[int]] = []
    for occurrences in rapid_by_text.values():
        clusters: list[list[tuple[int, int]]] = []
        for item in sorted(occurrences):
            if not clusters or item[0] - clusters[-1][-1][0] > 1_000:
                clusters.append([item])
            else:
                clusters[-1].append(item)
        collapsible_groups.extend(
            [cue_index for _start_ms, cue_index in cluster]
            for cluster in clusters
            if len(cluster) >= 10
        )

    collapsed_indices = {
        cue_index
        for group in collapsible_groups
        for cue_index in group
    }
    if not collapsed_indices:
        return str(source), ProgressiveCaptionCollapseReport(
            total_cues=timing_line_count,
            collapsed_source_cues=0,
            replacement_cues=0,
            discarded_empty_cues=0,
            output_cues=timing_line_count,
        )

    replacements: list[_ParsedSrtCue] = []
    for group in collapsible_groups:
        grouped_cues = [cues[index] for index in group]
        first = min(grouped_cues, key=lambda cue: cue.start_ms)
        start_ms = min(cue.start_ms for cue in grouped_cues)
        end_ms = max(cue.end_ms for cue in grouped_cues)
        replacements.append(
            _ParsedSrtCue(
                index=first.index,
                timing_line=(
                    f"{_srt_timestamp_from_ms(start_ms)} --> "
                    f"{_srt_timestamp_from_ms(end_ms)}"
                ),
                text_lines=first.text_lines,
                start_ms=start_ms,
                end_ms=end_ms,
            )
        )

    output_cues = [
        cue
        for index, cue in enumerate(cues)
        if index not in collapsed_indices
    ]
    output_cues.extend(replacements)
    output_cues.sort(key=lambda cue: (cue.start_ms, cue.end_ms, cue.index))
    discarded_empty = timing_line_count - len(cues)
    report = ProgressiveCaptionCollapseReport(
        total_cues=timing_line_count,
        collapsed_source_cues=len(collapsed_indices),
        replacement_cues=len(replacements),
        discarded_empty_cues=discarded_empty,
        output_cues=len(output_cues),
    )

    output_dir = (
        Path(output_directory).expanduser()
        if output_directory
        else Path(tempfile.mkdtemp(prefix="subtitle_progressive_collapse_"))
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{source.stem}.collapsed.srt"
    output_path.write_text(_render_srt(output_cues), encoding="utf-8")
    return str(output_path), report


def pick_playback_pgs_stream(
    streams: list[dict],
    *,
    preferred_language: str = "auto",
    excluded_language: str | None = None,
) -> dict | None:
    """Choose one full PGS stream worth retaining for dual-subtitle playback."""
    excluded_code = (
        languages.get_language(excluded_language).code
        if excluded_language
        else None
    )
    candidates = []
    for stream in streams:
        if not is_pgs_stream(stream) or _is_forced_or_signs_stream(stream):
            continue
        profile = stream_language(stream)
        if excluded_code and profile and profile.code == excluded_code:
            continue
        candidates.append(stream)

    if not candidates:
        return None

    if preferred_language and preferred_language != "auto":
        preferred_code = languages.get_language(preferred_language).code
        preferred = [
            stream
            for stream in candidates
            if stream_language(stream)
            and stream_language(stream).code == preferred_code
        ]
        if preferred:
            candidates = preferred
        else:
            unknown = [
                stream for stream in candidates if stream_language(stream) is None
            ]
            if not unknown:
                return None
            candidates = unknown

    return max(candidates, key=_stream_preference_score)


def extract_subtitle_stream(
    input_path: str,
    stream: dict,
    *,
    output_directory: str | Path | None = None,
) -> str:
    """Extract one embedded text subtitle as a clean, position-free SRT."""
    ffmpeg_path = _check_tool(FFMPEG_PATH, "ffmpeg")
    stream_index = stream.get("index")
    codec_name = str(stream.get("codec_name", "")).lower().strip()
    if stream_index is None:
        raise RuntimeError("Selected subtitle stream has no stream index.")
    if codec_name in IMAGE_BASED_CODECS:
        raise RuntimeError(
            f"Subtitle track #{stream_index} uses image codec '{codec_name}' "
            "and cannot provide translation text."
        )

    source = Path(input_path).expanduser().resolve()
    if output_directory:
        output_dir = Path(output_directory).expanduser()
        output_dir.mkdir(parents=True, exist_ok=True)
    else:
        output_dir = Path(tempfile.mkdtemp(prefix="subtitle_extractor_"))
    profile = stream_language(stream)
    language_code = profile.code if profile else "und"
    output_path = output_dir / f"{source.stem}.{language_code}.srt"
    command = [
        ffmpeg_path,
        "-y",
        "-i",
        str(source),
        "-map",
        f"0:{stream_index}",
        "-c:s",
        "srt",
        str(output_path),
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg failed to extract subtitle track #{stream_index}:\n"
            f"{result.stderr.strip()}"
        )
    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise RuntimeError(
            f"Subtitle track #{stream_index} produced an empty SRT file."
        )
    return convert_to_srt(
        str(output_path),
        output_directory=output_dir,
    )


def extract_pgs_subtitle_stream(
    input_path: str,
    stream: dict,
    *,
    output_directory: str | Path | None = None,
) -> str:
    """Losslessly copy one embedded PGS stream to a standalone SUP file."""
    ffmpeg_path = _check_tool(FFMPEG_PATH, "ffmpeg")
    stream_index = stream.get("index")
    if stream_index is None:
        raise RuntimeError("Selected PGS subtitle stream has no stream index.")
    if not is_pgs_stream(stream):
        codec_name = str(stream.get("codec_name", "unknown"))
        raise RuntimeError(
            f"Subtitle track #{stream_index} uses '{codec_name}', not PGS."
        )

    source = Path(input_path).expanduser().resolve()
    output_dir = (
        Path(output_directory).expanduser()
        if output_directory
        else Path(tempfile.mkdtemp(prefix="subtitle_extractor_"))
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    profile = stream_language(stream) or languages.UNKNOWN_LANGUAGE
    output_path = (
        output_dir
        / f"{source.stem}.{profile.code}.track-{stream_index}.sup"
    )
    command = [
        ffmpeg_path,
        "-y",
        "-i",
        str(source),
        "-map",
        f"0:{stream_index}",
        "-c:s",
        "copy",
        str(output_path),
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg failed to preserve PGS track #{stream_index}:\n"
            f"{result.stderr.strip()}"
        )
    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise RuntimeError(
            f"PGS track #{stream_index} produced an empty SUP file."
        )
    return str(output_path)


def find_external_subtitles(
    input_path: str,
    *,
    media_roots: tuple[str, ...] | list[str] = (),
    language_code: str | None = None,
) -> list[ExternalSubtitle]:
    """Find ranked sidecar text subtitles without scanning unapproved folders."""
    video_path = Path(input_path).expanduser().resolve()
    search_root = app_paths.media_container_for_path(video_path, media_roots)
    if not search_root.is_dir():
        return []

    requested = languages.get_language(language_code) if language_code else None
    discovered_files = list(app_paths.iter_files_recursive(search_root))
    container_video_count = sum(
        path.suffix.lower() in app_paths.VIDEO_EXTENSIONS
        for path in discovered_files
    )
    video_episode = _episode_identity(video_path.stem)
    video_year = _release_year(video_path.stem)
    candidates: list[ExternalSubtitle] = []
    for path in discovered_files:
        if path.suffix.lower() not in app_paths.SUBTITLE_EXTENSIONS:
            continue
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if resolved == video_path:
            continue

        relative_text = " ".join(path.relative_to(search_root).parts)
        profile = _identify_sidecar_language(path, video_path, search_root)
        if requested and (profile is None or profile.code != requested.code):
            continue
        tokens = _filename_tokens(relative_text)
        if _has_forced_or_signs_tokens(tokens):
            continue

        video_tokens = _title_tokens(video_path.stem)
        subtitle_tokens = _title_tokens(path.stem)
        subtitle_episode = _episode_identity(path.stem)
        if _episode_identities_conflict(video_episode, subtitle_episode):
            continue
        subtitle_year = _release_year(path.stem)
        if video_year and subtitle_year and video_year != subtitle_year:
            continue
        overlap = len(video_tokens & subtitle_tokens)
        overlap_ratio = overlap / max(
            1,
            min(len(video_tokens), len(subtitle_tokens)),
        )
        if overlap_ratio < 0.45 and not (
            container_video_count == 1
            and _is_generic_subtitle_name(path, profile)
        ):
            continue
        score = overlap_ratio * 100
        if profile:
            score += 25
        if requested and profile and profile.code == requested.code:
            score += 100
        if path.suffix.lower() == ".srt":
            score += 8
        if "full" in tokens:
            score += 15
        if {"sdh", "cc"} & tokens:
            score -= 15
        score += _subtitle_content_score(path)

        candidates.append(ExternalSubtitle(path, profile, score))

    return sorted(
        candidates,
        key=lambda item: (item.score, _safe_size(item.path)),
        reverse=True,
    )


def find_external_subtitle(
    input_path: str,
    language_code: str,
    *,
    media_roots: tuple[str, ...] | list[str] = (),
) -> ExternalSubtitle | None:
    """Return the best sidecar subtitle in a requested language."""
    matches = find_external_subtitles(
        input_path,
        media_roots=media_roots,
        language_code=language_code,
    )
    return matches[0] if matches else None


def _stream_preference_score(stream: dict) -> tuple[int, int, int]:
    tags = stream.get("tags") or {}
    title = str(tags.get("title", tags.get("TITLE", ""))).lower()
    return (
        0 if _is_forced_or_signs_stream(stream) else 1,
        1 if "full" in title else 0,
        1 if stream.get("disposition", {}).get("default") else 0,
    )


def _safe_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _is_forced_or_signs_stream(stream: dict) -> bool:
    """Return true when a subtitle stream appears to be forced/signs-only."""
    disp = stream.get("disposition", {})
    if disp.get("forced"):
        return True

    tags = stream.get("tags", {})
    title = tags.get("title", tags.get("TITLE", "")).lower()
    forced_markers = (
        "forced",
        "sign",
        "signs",
        "songs",
        "song",
        "karaoke",
    )
    return any(marker in title for marker in forced_markers)


def is_vietnamese_stream(stream: dict, *, text_only: bool = False) -> bool:
    """Return true when stream metadata identifies a Vietnamese subtitle."""
    tags = stream.get("tags", {})
    lang = tags.get("language", tags.get("LANGUAGE", "")).lower().strip()
    title = tags.get("title", tags.get("TITLE", "")).lower()
    title_tokens = set(re.findall(r"[a-z]+", title))
    is_vietnamese = lang in _VIETNAMESE_TOKENS or bool(
        title_tokens & _VIETNAMESE_TOKENS
    )
    if not is_vietnamese:
        return False
    if not text_only:
        return True
    codec = stream.get("codec_name", "").lower().strip()
    return codec in TEXT_BASED_CODECS


def pick_vietnamese_stream(streams: list[dict]) -> dict | None:
    """Choose the best embedded text-based Vietnamese subtitle stream."""
    candidates = [
        stream for stream in streams
        if is_vietnamese_stream(stream, text_only=True)
    ]
    if not candidates:
        return None

    full_streams = [
        stream for stream in candidates
        if not _is_forced_or_signs_stream(stream)
    ]
    preferred = full_streams or candidates
    return max(
        preferred,
        key=lambda stream: (
            bool(stream.get("disposition", {}).get("default")),
            "full" in stream.get("tags", {}).get("title", "").lower(),
        ),
    )


def find_external_english_subtitle(input_path: str) -> tuple[str, str] | None:
    """
    Find and normalize an external English subtitle near *input_path*.

    Searches the approved media container holding the video, including
    nested ``Subs``/``Subtitles`` folders. Returns ``(clean_srt_path,
    source_path)`` when a likely English subtitle is found.
    """
    source_path = _pick_external_english_subtitle(input_path)
    if source_path is None:
        return None
    return convert_to_srt(str(source_path)), str(source_path)


def extract_image_subtitle_timings(
    input_path: str,
    selected_stream: dict | None = None,
    *,
    preferred_language: str = "auto",
    excluded_language: str | None = None,
) -> tuple[list[subtitle_sync.CueTiming], str] | None:
    """
    Extract cue timings from the best embedded image-based subtitle stream.

    PGS/DVD-style subtitle tracks cannot be converted to text, but their packet
    timestamps can still be used as a timing skeleton for validating external
    subtitles from the same cut.
    """
    streams = _probe_subtitle_streams(input_path)
    stream = _pick_image_subtitle_stream(
        streams,
        selected_stream,
        preferred_language=preferred_language,
        excluded_language=excluded_language,
    )
    if stream is None:
        return None

    cues = _subtitle_packet_timings(input_path, int(stream.get("index", -1)))
    if not cues:
        return None

    idx = stream.get("index", "?")
    codec = stream.get("codec_name", "image").upper()
    return cues, f"embedded image track {idx} {codec}"


def find_external_image_subtitle_timings(
    input_path: str,
    *,
    media_roots: tuple[str, ...] | list[str] = (),
) -> tuple[list[subtitle_sync.CueTiming], str] | None:
    """
    Find timing skeletons in external image subtitle files near *input_path*.

    Some releases ship VobSub/DVD subtitles as ``.sub``/``.idx`` files in a
    subtitle folder. They are not translatable text, but their cue timestamps
    can still validate whether a target SRT belongs to the same cut.
    """
    video_path = Path(input_path).resolve()
    search_root = app_paths.media_container_for_path(video_path, media_roots)
    if not search_root.is_dir():
        return None

    discovered_files = list(app_paths.iter_files_recursive(search_root))
    container_video_count = sum(
        path.suffix.lower() in app_paths.VIDEO_EXTENSIONS
        for path in discovered_files
    )
    candidates: list[tuple[float, int, Path, list[subtitle_sync.CueTiming], str]] = []
    for path in discovered_files:
        if path.suffix.lower() not in app_paths.IMAGE_SUBTITLE_EXTENSIONS:
            continue
        try:
            result = _image_subtitle_file_timings(path)
        except Exception:
            continue
        if result is None:
            continue
        cues, label = result
        if len(cues) < 5:
            continue
        score = _external_image_subtitle_score(path, video_path, search_root)
        if score < 45 and container_video_count != 1:
            continue
        candidates.append((
            score,
            len(cues),
            path,
            cues,
            label,
        ))

    if not candidates:
        return None

    _score, _count, path, cues, label = max(
        candidates,
        key=lambda item: (item[0], item[1]),
    )
    return cues, f"external image {path.name} {label}"


def _image_subtitle_file_timings(
    subtitle_path: Path,
) -> tuple[list[subtitle_sync.CueTiming], str] | None:
    """Return the densest image-subtitle stream timings from a subtitle file."""
    streams = _probe_subtitle_streams(str(subtitle_path))
    candidates: list[tuple[int, int, str, list[subtitle_sync.CueTiming]]] = []
    for stream in streams:
        codec_name = stream.get("codec_name", "").lower().strip()
        if codec_name not in IMAGE_BASED_CODECS:
            continue
        stream_index = int(stream.get("index", -1))
        cues = _subtitle_packet_timings(str(subtitle_path), stream_index)
        if not cues:
            continue
        forced_rank = 0 if _is_forced_or_signs_stream(stream) else 1
        candidates.append((len(cues), forced_rank, codec_name.upper(), cues))

    if not candidates:
        return None

    _count, _forced_rank, codec_label, cues = max(candidates, key=lambda item: (item[0], item[1]))
    return cues, f"track {codec_label}"


def _external_image_subtitle_score(
    subtitle_path: Path,
    video_path: Path,
    search_root: Path,
) -> float:
    """Loosely score an external image subtitle file by title/path overlap."""
    relative_text = " ".join(subtitle_path.relative_to(search_root).parts)
    tokens = _filename_tokens(relative_text)
    video_tokens = _title_tokens(video_path.stem)
    subtitle_tokens = _title_tokens(subtitle_path.stem)
    overlap = len(video_tokens & subtitle_tokens)
    overlap_ratio = overlap / max(1, min(len(video_tokens), len(subtitle_tokens)))
    score = overlap_ratio * 100
    if {"subs", "subtitles", "subtitle"} & tokens:
        score += 5
    if _has_forced_or_signs_tokens(tokens):
        score -= 50
    return score


def _pick_image_subtitle_stream(
    streams: list[dict],
    selected_stream: dict | None = None,
    *,
    preferred_language: str = "auto",
    excluded_language: str | None = None,
) -> dict | None:
    """Pick an image-based subtitle stream for timing-only use."""
    if selected_stream is not None:
        codec_name = selected_stream.get("codec_name", "").lower().strip()
        if codec_name in IMAGE_BASED_CODECS:
            return selected_stream

    excluded_code = (
        languages.get_language(excluded_language).code
        if excluded_language
        else None
    )
    preferred_code = (
        languages.get_language(preferred_language).code
        if preferred_language and preferred_language != "auto"
        else None
    )
    candidates = []
    for stream in streams:
        codec_name = stream.get("codec_name", "").lower().strip()
        if codec_name not in IMAGE_BASED_CODECS:
            continue
        profile = stream_language(stream)
        if excluded_code and profile and profile.code == excluded_code:
            continue
        candidates.append(stream)

    if not candidates:
        return None

    return max(
        candidates,
        key=lambda stream: (
            1
            if preferred_code
            and stream_language(stream)
            and stream_language(stream).code == preferred_code
            else 0,
            *_stream_preference_score(stream),
        ),
    )


def _subtitle_packet_timings(input_path: str, stream_index: int) -> list[subtitle_sync.CueTiming]:
    """Read subtitle packet timestamps for the absolute ffprobe stream index."""
    ffprobe_path = _check_tool(FFPROBE_PATH, "ffprobe")
    cmd = [
        ffprobe_path,
        "-v", "error",
        "-select_streams", "s",
        "-show_packets",
        "-show_entries", "packet=stream_index,pts_time,duration_time",
        "-of", "json",
        input_path,
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"ffprobe failed reading subtitle packet timings:\n{result.stderr.strip()}"
        )

    data = json.loads(result.stdout or "{}")
    packet_starts: list[tuple[int, int | None]] = []
    for packet in data.get("packets", []):
        if int(packet.get("stream_index", -1)) != stream_index:
            continue
        start_ms = _packet_time_to_ms(packet.get("pts_time"))
        if start_ms is None:
            continue
        duration_ms = _packet_time_to_ms(packet.get("duration_time"))
        packet_starts.append((start_ms, duration_ms))

    if not packet_starts:
        return []

    packet_starts.sort(key=lambda item: item[0])
    cues: list[subtitle_sync.CueTiming] = []
    for index, (start_ms, duration_ms) in enumerate(packet_starts):
        next_start = (
            packet_starts[index + 1][0]
            if index + 1 < len(packet_starts)
            else None
        )
        if duration_ms is None or duration_ms <= 0:
            duration_ms = (
                max(500, next_start - start_ms)
                if next_start and next_start > start_ms
                else 2500
            )
        duration_ms = min(max(duration_ms, 500), 12_000)
        cues.append(subtitle_sync.CueTiming(start_ms, start_ms + duration_ms))

    return _coalesce_packet_cues(cues)


def _packet_time_to_ms(value: object) -> int | None:
    """Convert an ffprobe time value in seconds to milliseconds."""
    if value in (None, "N/A"):
        return None
    try:
        return int(round(float(value) * 1000))
    except (TypeError, ValueError):
        return None


def _coalesce_packet_cues(
    cues: list[subtitle_sync.CueTiming],
) -> list[subtitle_sync.CueTiming]:
    """Merge duplicate subtitle packets that belong to the same cue."""
    merged: list[subtitle_sync.CueTiming] = []
    for cue in sorted(cues, key=lambda item: (item.start_ms, item.end_ms)):
        if not merged or cue.start_ms - merged[-1].start_ms > 250:
            merged.append(cue)
            continue
        previous = merged[-1]
        merged[-1] = subtitle_sync.CueTiming(
            previous.start_ms,
            max(previous.end_ms, cue.end_ms),
        )
    return merged


def _pick_external_english_subtitle(input_path: str) -> Path | None:
    """Return the best external English subtitle candidate for *input_path*."""
    video_path = Path(input_path).resolve()
    search_root = app_paths.media_container_for_path(video_path)
    if not search_root.is_dir():
        return None

    discovered_files = list(app_paths.iter_files_recursive(search_root))
    container_video_count = sum(
        path.suffix.lower() in app_paths.VIDEO_EXTENSIONS
        for path in discovered_files
    )
    candidates: list[tuple[float, int, Path]] = []
    for path in discovered_files:
        if path.resolve() == video_path:
            continue
        if path.suffix.lower() not in app_paths.SUBTITLE_EXTENSIONS:
            continue
        score = _external_english_subtitle_score(path, video_path, search_root)
        if score is None:
            continue
        video_tokens = _title_tokens(video_path.stem)
        subtitle_tokens = _title_tokens(path.stem)
        overlap_ratio = len(video_tokens & subtitle_tokens) / max(
            1,
            min(len(video_tokens), len(subtitle_tokens)),
        )
        if overlap_ratio < 0.45 and not (
            container_video_count == 1
            and _is_generic_subtitle_name(path, languages.get_language("en"))
        ):
            continue
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        candidates.append((score, size, path))

    if not candidates:
        return None
    return max(candidates, key=lambda item: (item[0], item[1]))[2]


def _external_english_subtitle_score(
    subtitle_path: Path,
    video_path: Path,
    search_root: Path,
) -> float | None:
    """Score a possible external English subtitle, or reject it with ``None``."""
    relative_text = " ".join(subtitle_path.relative_to(search_root).parts)
    tokens = _filename_tokens(relative_text)
    if _has_forced_or_signs_tokens(tokens):
        return None

    english_markers = tokens & _ENGLISH_TOKENS
    non_english_markers = tokens & _NON_ENGLISH_TOKENS
    if non_english_markers and not english_markers:
        return None

    video_tokens = _title_tokens(video_path.stem)
    subtitle_tokens = _title_tokens(subtitle_path.stem)
    overlap = len(video_tokens & subtitle_tokens)
    overlap_ratio = overlap / max(1, min(len(video_tokens), len(subtitle_tokens)))

    if not english_markers and (overlap < 2 or overlap_ratio < 0.45):
        return None

    score = 0.0
    if english_markers:
        score += 100
    score += overlap_ratio * 40
    if subtitle_path.suffix.lower() == ".srt":
        score += 10
    if "full" in tokens:
        score += 20
    if {"sdh", "cc"} & tokens:
        score -= 30
    if {"subs", "subtitles", "subtitle"} & tokens:
        score += 5
    score += _subtitle_content_score(subtitle_path)
    return score


def _subtitle_content_score(subtitle_path: Path) -> float:
    """Prefer dialogue-like subtitles over SDH/CC-style subtitle files."""
    try:
        with subtitle_path.open("rb") as source:
            raw = source.read(_MAX_SUBTITLE_SCORE_BYTES).decode(
                "utf-8-sig",
                errors="replace",
            )
    except OSError:
        return 0.0

    text_lines: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or _INDEX_RE.match(stripped) or _TS_RE.search(stripped):
            continue
        cleaned = _TAG_RE.sub("", stripped).strip()
        if cleaned:
            text_lines.append(cleaned)

    if not text_lines:
        return 0.0

    sdh_lines = sum(1 for line in text_lines if _looks_like_sdh_line(line))
    sdh_ratio = sdh_lines / len(text_lines)

    if sdh_ratio >= 0.18:
        return -50.0
    if sdh_ratio >= 0.08:
        return -25.0
    if sdh_ratio >= 0.03:
        return -10.0
    return 0.0


def _looks_like_sdh_line(line: str) -> bool:
    """Return true for common non-dialogue cues found in SDH/CC subtitles."""
    cleaned = line.strip()
    if not cleaned:
        return False
    if "♪" in cleaned:
        return True
    if cleaned.startswith("[") or cleaned.endswith("]"):
        return True
    if re.fullmatch(r"\([^)]{2,80}\)", cleaned):
        return True
    if re.fullmatch(r"[A-Z0-9][A-Z0-9 .,'!?/-]{1,60}:\s*", cleaned):
        return True
    if re.fullmatch(r"[A-Z0-9][A-Z0-9 .,'!?/-]{1,40}\s+\[[^\]]+\]:\s*", cleaned):
        return True

    letters = [char for char in cleaned if char.isalpha()]
    if not letters or any(char.islower() for char in letters):
        return False
    sound_words = {
        "alarm",
        "beep",
        "beeping",
        "buzz",
        "buzzing",
        "chatter",
        "chattering",
        "click",
        "clicking",
        "clink",
        "cough",
        "coughing",
        "ding",
        "dings",
        "exhales",
        "gasping",
        "groan",
        "groans",
        "grunt",
        "grunting",
        "hissing",
        "music",
        "panting",
        "phone",
        "playing",
        "roar",
        "roaring",
        "sighs",
        "speaking",
        "thumping",
        "wheezing",
    }
    tokens = set(re.findall(r"[a-z]+", cleaned.lower()))
    return bool(tokens & sound_words)


def _has_forced_or_signs_tokens(tokens: set[str]) -> bool:
    forced_markers = {"forced", "sign", "signs", "song", "songs", "karaoke"}
    return bool(tokens & forced_markers)


def _filename_tokens(text: str) -> set[str]:
    """Tokenize filename/path text for loose language and title matching."""
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return set(re.findall(r"[^\W_]+", normalized, flags=re.UNICODE))


def _identify_sidecar_language(
    path: Path,
    video_path: Path,
    search_root: Path,
) -> languages.LanguageProfile | None:
    """Read explicit language markers without treating title words as metadata."""
    try:
        relative = path.relative_to(search_root)
    except ValueError:
        return None

    for parent in reversed(relative.parts[:-1]):
        profile = languages.identify_language(parent)
        if profile and _normalized_marker(parent) in profile.search_tokens:
            return profile

    profile = languages.identify_language(path.stem)
    if profile and _normalized_marker(path.stem) in profile.search_tokens:
        return profile

    subtitle_parts = _marker_parts(path.stem)
    video_parts = _marker_parts(video_path.stem)
    common_prefix = 0
    for subtitle_part, video_part in zip(subtitle_parts, video_parts):
        if subtitle_part != video_part:
            break
        common_prefix += 1

    candidates = (
        subtitle_parts[common_prefix:]
        if common_prefix
        else subtitle_parts
    )
    video_groups = set(_marker_groups(video_parts))
    for marker in _marker_groups(candidates):
        if not common_prefix and marker in video_groups:
            continue
        profile = languages.identify_language(marker)
        if profile and marker in profile.search_tokens:
            return profile
    return None


def _marker_parts(text: str) -> tuple[str, ...]:
    return tuple(
        _normalized_marker(part)
        for part in re.split(r"[\s._\[\](){}]+", text)
        if _normalized_marker(part)
    )


def _marker_groups(parts: tuple[str, ...]) -> tuple[str, ...]:
    groups: list[str] = []
    for end in range(len(parts), 0, -1):
        for width in range(1, min(3, end) + 1):
            groups.append("".join(parts[end - width:end]))
    return tuple(groups)


def _normalized_marker(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.casefold())


def _title_tokens(text: str) -> set[str]:
    """Return meaningful title tokens, excluding codec/release noise."""
    tokens = _filename_tokens(text)
    return {
        token
        for token in tokens
        if (
            (len(token) >= 3 or any(ord(character) > 127 for character in token))
            and token not in _TITLE_NOISE_TOKENS
        )
    }


def _is_generic_subtitle_name(
    path: Path,
    profile: languages.LanguageProfile | None,
) -> bool:
    """Recognize names such as ``English.srt`` inside one-video releases."""
    tokens = _filename_tokens(path.stem)
    allowed = {
        "default",
        "dialogue",
        "full",
        "main",
        "sub",
        "subs",
        "subtitle",
        "subtitles",
    }
    if profile:
        for value in (
            profile.code,
            profile.name,
            profile.opensubtitles_code,
            profile.mux_code,
            *profile.aliases,
        ):
            allowed.update(_filename_tokens(value))
    return bool(tokens) and all(token.isdecimal() or token in allowed for token in tokens)


def _episode_identity(text: str) -> tuple[int | None, int] | None:
    """Return a season/episode pair from common sidecar naming conventions."""
    normalized = unicodedata.normalize("NFKC", text)
    for pattern in (
        r"(?i)(?<![a-z0-9])s(\d{1,2})[ ._-]*e(\d{1,3})(?!\d)",
        r"(?i)(?<![a-z0-9])(\d{1,2})x(\d{1,3})(?!\d)",
    ):
        match = re.search(pattern, normalized)
        if match:
            return int(match.group(1)), int(match.group(2))
    # Many anime releases omit the season and use ``Title - 05 [WEB]``.
    # Preserve the unknown season instead of assuming season one; callers can
    # still reject a sidecar for a different episode number.
    match = re.search(
        r"(?i)(?<![a-z0-9])-\s*(\d{1,3})(?=$|[ ._\[\](){}-])",
        normalized,
    )
    if match:
        return None, int(match.group(1))
    return None


def _episode_identities_conflict(
    first: tuple[int | None, int] | None,
    second: tuple[int | None, int] | None,
) -> bool:
    """Return whether two known episode identities cannot describe one item."""
    if first is None or second is None:
        return False
    first_season, first_episode = first
    second_season, second_episode = second
    if first_episode != second_episode:
        return True
    return (
        first_season is not None
        and second_season is not None
        and first_season != second_season
    )


def _release_year(text: str) -> int | None:
    """Return the first plausible screen release year in a filename."""
    match = re.search(r"(?<!\d)(?:19|20)\d{2}(?!\d)", text)
    return int(match.group()) if match else None


_INDEX_RE = re.compile(r"^\d+\s*$")
_TS_RE    = re.compile(r"-->")
_TIMING_LINE_RE = re.compile(
    r"^(\s*\d+:\d{2}:\d{2}[,.]\d{1,3}\s*-->\s*"
    r"\d+:\d{2}:\d{2}[,.]\d{1,3})(?:\s+.*)?$"
)
# Matches {any ASS override block} or any HTML-like <tag>
_TAG_RE   = re.compile(r"\{[^}]*\}|<[^>]+>")
_SRT_TIMING_RE = re.compile(
    r"^\s*(?P<start>\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})\s*-->\s*"
    r"(?P<end>\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})"
)
_LINK_RE = re.compile(
    r"(?ix)"
    r"(?:https?://|www\.)\S+"
    r"|(?:\b[\w.+-]+@[\w.-]+\.[a-z]{2,24}\b)"
    r"|(?:\b(?:[a-z0-9](?:[a-z0-9-]{0,62})\.)+[a-z]{2,24}\b)"
)
_ATTRIBUTION_RE = re.compile(
    r"(?ix)\b(?:"
    r"subtitles?\s+(?:by|from|provided)"
    r"|(?:translated|translation|synced|timed|encoded|ripped)\s+by"
    r"|(?:watch|movies?)\s+online"
    r"|visit\s+(?:our|the)\s+(?:site|website)"
    r"|join\s+(?:our|us\s+on)"
    r"|download\s+(?:more\s+)?subtitles?"
    r")\b"
)
_BRAND_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9._-]{4,}", re.I)
_PROMO_TOKEN_STOPWORDS = {
    "download",
    "downloaded",
    "english",
    "movie",
    "movies",
    "online",
    "provided",
    "subtitle",
    "subtitles",
    "translated",
    "translation",
    "vietnamese",
    "website",
}


@dataclass(frozen=True)
class PromotionalCleanupReport:
    """Auditable summary of conservative external-subtitle cleanup."""

    total_cues: int
    removed_cues: int
    reason_counts: tuple[tuple[str, int], ...]

    def summary(self) -> str:
        """Return a compact user-facing description of removed cues."""
        reasons = ", ".join(
            f"{count} {reason}" for reason, count in self.reason_counts
        )
        if reasons:
            return (
                f"Removed {self.removed_cues} probable promotional/invalid "
                f"cue(s): {reasons}."
            )
        return f"Removed {self.removed_cues} probable promotional/invalid cue(s)."


@dataclass(frozen=True)
class _ParsedSrtCue:
    """One structured SRT cue retained during promotional analysis."""

    index: str
    timing_line: str
    text_lines: tuple[str, ...]
    start_ms: int
    end_ms: int


def _clean_srt_tags(srt_text: str) -> str:
    """
    Strip inline formatting tags from the dialogue lines of an SRT file.

    Leaves index lines (bare integers) and empty separator lines untouched.
    Timestamp start/end values are preserved, but any trailing placement
    settings are removed. Dialogue text lines have inline formatting stripped:

    * SRT/WebVTT timestamp settings like ``X1:… Y1:…`` or ``position:…``
    * ASS override blocks like ``{\\an8}`` or ``{\\pos(320,50)}``
    * HTML-style tags like ``<b>``, ``</b>``, ``<i>``, ``<font color=…>``

    Args:
        srt_text: Full text content of an SRT file.

    Returns:
        Cleaned SRT text with the same block structure and line endings.
    """
    out = []
    for line in srt_text.splitlines(keepends=True):
        content = line.rstrip("\r\n")
        ending  = line[len(content):]
        if not content or _INDEX_RE.match(content):
            out.append(line)                           # preserve as-is
        elif _TS_RE.search(content):
            match = _TIMING_LINE_RE.match(content)
            out.append((match.group(1) if match else content) + ending)
        else:
            out.append(_TAG_RE.sub("", content) + ending)
    return "".join(out)


def remove_probable_promotional_cues(
    srt_path: str,
    *,
    video_duration_ms: int | None = None,
    output_directory: str | Path | None = None,
) -> tuple[str, PromotionalCleanupReport]:
    """
    Remove only high-confidence promotional or structurally invalid SRT cues.

    Detection combines independent signals rather than relying on a list of
    site names: links/domains, subtitle-credit language, repeated rare tokens,
    periodic placement, appended out-of-order cues, and timestamps beyond the
    video. The input file is never modified; a cleaned, renumbered temp copy is
    returned with an auditable report.
    """
    source = Path(srt_path).resolve()
    raw = source.read_text(encoding="utf-8-sig")
    cues = _parse_structured_srt(raw)
    if not cues:
        return str(source), PromotionalCleanupReport(0, 0, ())
    timing_line_count = sum(
        1 for line in raw.splitlines() if _SRT_TIMING_RE.match(line)
    )
    if len(cues) != timing_line_count:
        return str(source), PromotionalCleanupReport(len(cues), 0, ())

    normalized_phrases = [_normalized_cue_text(cue) for cue in cues]
    phrase_counts = Counter(
        phrase for phrase in normalized_phrases if 8 <= len(phrase) <= 160
    )

    token_to_cues: dict[str, list[int]] = defaultdict(list)
    for cue_index, cue in enumerate(cues):
        for token in _distinctive_tokens(cue):
            token_to_cues[token].append(cue_index)
    repeated_tokens = {
        token
        for token, positions in token_to_cues.items()
        if 2 <= len(positions) <= max(12, len(cues) // 40)
    }
    periodic_tokens = {
        token
        for token in repeated_tokens
        if _token_occurs_periodically(token_to_cues[token], cues)
    }

    appended_flags: list[bool] = []
    latest_start = -1
    appended_tail = False
    for cue in cues:
        if latest_start >= 0 and cue.start_ms < latest_start - 30_000:
            appended_tail = True
        appended_flags.append(appended_tail)
        latest_start = max(latest_start, cue.start_ms)

    removed: set[int] = set()
    reason_counts: Counter[str] = Counter()
    for cue_index, cue in enumerate(cues):
        plain_text = _TAG_RE.sub("", "\n".join(cue.text_lines)).strip()
        word_count = len(re.findall(r"\w+", plain_text, flags=re.UNICODE))
        cue_tokens = _distinctive_tokens(cue)
        score = 0
        reasons: list[str] = []

        if _LINK_RE.search(plain_text):
            score += 4
            reasons.append("link/domain")
        if _ATTRIBUTION_RE.search(plain_text):
            score += 3
            reasons.append("subtitle promotion")
        repeated_phrase = phrase_counts.get(normalized_phrases[cue_index], 0) >= 2
        if repeated_phrase:
            score += 2
            reasons.append("repeated phrase")
        if cue_tokens & repeated_tokens and not repeated_phrase:
            score += 2
            reasons.append("repeated brand-like token")
        if cue_tokens & periodic_tokens:
            score += 2
            reasons.append("periodic placement")
        if appended_flags[cue_index]:
            score += 2
            reasons.append("appended out-of-order")
        if (
            video_duration_ms is not None
            and cue.start_ms > video_duration_ms + 30_000
        ):
            score += 4
            reasons.append("outside video duration")
        if score > 0 and word_count <= 20:
            score += 1

        if score < 4:
            continue
        removed.add(cue_index)
        for reason in set(reasons):
            reason_counts[reason] += 1

    output_dir = (
        Path(output_directory).expanduser()
        if output_directory
        else Path(tempfile.mkdtemp(prefix="subtitle_promo_clean_"))
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{source.stem}.cleaned.srt"
    retained = [cue for index, cue in enumerate(cues) if index not in removed]
    output_path.write_text(_render_srt(retained), encoding="utf-8")
    report = PromotionalCleanupReport(
        total_cues=len(cues),
        removed_cues=len(removed),
        reason_counts=tuple(sorted(reason_counts.items())),
    )
    return str(output_path), report


def _parse_structured_srt(srt_text: str) -> list[_ParsedSrtCue]:
    """Parse well-formed SRT blocks while preserving dialogue text."""
    normalized = srt_text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []

    cues: list[_ParsedSrtCue] = []
    for block in re.split(r"\n{2,}", normalized):
        lines = block.splitlines()
        if len(lines) < 3:
            continue
        timing_match = _SRT_TIMING_RE.match(lines[1])
        if timing_match is None:
            continue
        try:
            start_ms = _srt_timestamp_ms(timing_match.group("start"))
            end_ms = _srt_timestamp_ms(timing_match.group("end"))
        except ValueError:
            continue
        cues.append(
            _ParsedSrtCue(
                index=lines[0].strip(),
                timing_line=lines[1].strip(),
                text_lines=tuple(lines[2:]),
                start_ms=start_ms,
                end_ms=end_ms,
            )
        )
    return cues


def _srt_timestamp_ms(value: str) -> int:
    """Convert one SRT timestamp to milliseconds."""
    hours_text, minutes_text, seconds_text = value.replace(".", ",").split(":")
    seconds_text, milliseconds_text = seconds_text.split(",", 1)
    milliseconds_text = milliseconds_text.ljust(3, "0")[:3]
    return (
        int(hours_text) * 3_600_000
        + int(minutes_text) * 60_000
        + int(seconds_text) * 1_000
        + int(milliseconds_text)
    )


def _srt_timestamp_from_ms(value: int) -> str:
    """Format non-negative milliseconds as one canonical SRT timestamp."""
    value = max(0, int(value))
    hours, remainder = divmod(value, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, milliseconds = divmod(remainder, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"


def _normalized_cue_text(cue: _ParsedSrtCue) -> str:
    """Normalize cue text for conservative repeated-phrase detection."""
    plain = _TAG_RE.sub("", " ".join(cue.text_lines)).lower()
    return " ".join(re.findall(r"\w+", plain, flags=re.UNICODE))


def _distinctive_tokens(cue: _ParsedSrtCue) -> set[str]:
    """Return possible brand/source tokens without assuming particular names."""
    plain = _TAG_RE.sub("", " ".join(cue.text_lines))
    tokens: set[str] = set()
    for raw_token in _BRAND_TOKEN_RE.findall(plain):
        source_token = raw_token.strip("._-")
        normalized = source_token.lower()
        if normalized in _PROMO_TOKEN_STOPWORDS:
            continue
        has_source_shape = (
            any(character in source_token for character in "._-")
            or any(character.isdigit() for character in source_token)
            or source_token.isupper()
            or any(character.isupper() for character in source_token[1:])
        )
        if has_source_shape:
            tokens.add(normalized)
    return tokens


def _token_occurs_periodically(
    cue_indices: list[int],
    cues: list[_ParsedSrtCue],
) -> bool:
    """Return true when a repeated token appears on a regular long cadence."""
    starts = sorted({cues[index].start_ms for index in cue_indices})
    if len(starts) < 3:
        return False
    gaps = [right - left for left, right in zip(starts, starts[1:])]
    typical_gap = float(median(gaps))
    if typical_gap < 5 * 60_000:
        return False
    tolerance = max(15_000.0, typical_gap * 0.08)
    regular = sum(abs(gap - typical_gap) <= tolerance for gap in gaps)
    return regular / len(gaps) >= 0.60


def _render_srt(cues: list[_ParsedSrtCue]) -> str:
    """Render retained cues with sequential indices and original timestamps."""
    blocks = []
    for index, cue in enumerate(cues, start=1):
        blocks.append(
            "\n".join((str(index), cue.timing_line, *cue.text_lines))
        )
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def convert_to_srt(
    input_path: str,
    *,
    output_directory: str | Path | None = None,
) -> str:
    """
    Ensure a subtitle file is in clean SRT format.

    Detects SRT vs ASS/SSA by reading the first bytes of the file.
    ASS/SSA files begin with ``[Script Info]``; SRT files begin with a
    block index (digit).  A cleaned temp SRT copy is always returned so
    inline style and position tags cannot leak into the muxed subtitle track.

    Note: Conversion/cleaning strips embedded positioning data
    (``\\pos``, ``\\move``, ``{\\an8}``, etc.) that cause subtitles to jump
    around in players like mpv.

    Args:
        input_path: Path to a .srt, .ass, or .ssa file.

    Returns:
        Absolute path to a valid cleaned .srt file in a temp directory.

    Raises:
        FileNotFoundError: If ffmpeg is not installed.
        RuntimeError: If ffmpeg conversion fails.
    """
    input_path = str(Path(input_path).resolve())

    # Detect format by first bytes.  ASS/SSA starts with "[Script Info]".
    try:
        with open(input_path, "rb") as fh:
            header = fh.read(64).decode("utf-8-sig", errors="replace")
    except OSError:
        header = ""

    input_suffix = Path(input_path).suffix.lower()
    if not header.lstrip().startswith("[Script Info]") and input_suffix == ".srt":
        # Already SRT (or an unknown format). Normalize a copy so any
        # embedded ASS/HTML tags in dialogue lines are stripped before muxing.
        stem = Path(input_path).stem
        output_dir = (
            Path(output_directory).expanduser()
            if output_directory
            else Path(tempfile.mkdtemp(prefix="subtitle_clean_"))
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        out_path = str(output_dir / f"{stem}.srt")
        raw = _read_subtitle_text(Path(input_path))
        Path(out_path).write_text(_clean_srt_tags(raw), encoding="utf-8")
        return out_path

    # Convert ASS/SSA → SRT via ffmpeg
    ffmpeg_path = _check_tool(FFMPEG_PATH, "ffmpeg")
    stem = Path(input_path).stem
    output_dir = (
        Path(output_directory).expanduser()
        if output_directory
        else Path(tempfile.mkdtemp(prefix="subtitle_convert_"))
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = str(output_dir / f"{stem}.srt")

    cmd = [
        ffmpeg_path,
        "-y",
        "-i", input_path,
        "-c:s", "srt",
        out_path,
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg failed to convert '{Path(input_path).name}' to SRT:\n"
            f"{result.stderr.strip()}"
        )

    # Post-process: strip any residual HTML-style and ASS override tags
    # from dialogue lines so the translator sees clean plain text.
    try:
        raw = Path(out_path).read_text(encoding="utf-8-sig")
        Path(out_path).write_text(_clean_srt_tags(raw), encoding="utf-8")
    except OSError:
        pass  # cleaning is best-effort; return the file even if this fails

    return out_path


def _read_subtitle_text(path: Path) -> str:
    """Read common subtitle encodings and normalize the result to Unicode."""
    data = path.read_bytes()
    for encoding in (
        "utf-8-sig",
        "utf-8",
        "utf-16",
        "cp1258",
        "windows-1252",
        "windows-1251",
        "shift_jis",
        "euc-kr",
        "gb18030",
        "big5",
        "latin-1",
    ):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def extract_english_subtitles(input_path: str) -> str:
    """
    Extract the English subtitle track from a video file and return a clean SRT path.

    Identifies the best English text-based subtitle stream using ffprobe,
    then extracts it (converting ASS/SSA to SRT via ffmpeg if needed).
    Inline formatting tags are always stripped from the resulting SRT
    (catches ``<font>`` tags in source files that were already SRT-format).
    No ASS file is generated; mpv should control subtitle styling/placement.

    Args:
        input_path: Path to the MKV or MP4 video file.

    Returns:
        Path to a clean, tag-free SRT file in a temp directory.

    Raises:
        FileNotFoundError: If ffprobe or ffmpeg is not installed.
        ValueError: If no English subtitle track is found.
        RuntimeError: If the identified track uses image-based subtitles
                      (PGS, DVDSUB, etc.) which cannot be translated,
                      or if ffmpeg extraction fails.
    """
    ffmpeg_path = _check_tool(FFMPEG_PATH, "ffmpeg")

    input_path = str(Path(input_path).resolve())
    streams = _probe_subtitle_streams(input_path)
    stream = _pick_english_stream(streams)

    stream_index = stream.get("index")
    codec_name = stream.get("codec_name", "").lower()

    # Check for image-based subtitles
    if codec_name in IMAGE_BASED_CODECS:
        raise RuntimeError(
            f"Subtitle track #{stream_index} uses an image-based codec "
            f"('{codec_name}'), which cannot be translated automatically.\n"
            f"Image-based formats (PGS, DVDSUB) store frames as pictures, "
            f"not text.\n"
            f"You need a text-based subtitle track such as SRT, ASS, or SSA.\n"
            f"Consider sourcing an external .srt file for this anime."
        )

    # Warn if codec is unrecognised but attempt extraction anyway
    if codec_name not in TEXT_BASED_CODECS:
        print(
            f"Warning: unrecognised subtitle codec '{codec_name}' for "
            f"stream #{stream_index}. Attempting extraction as SRT anyway."
        )

    # Build output path in a temp directory
    stem = Path(input_path).stem
    tmp_dir = tempfile.mkdtemp(prefix="subtitle_extractor_")
    out_path = os.path.join(tmp_dir, f"{stem}_eng.srt")

    # Map using the absolute stream index; ffmpeg's -map 0:INDEX selects by
    # global index. We use the stream's own index field directly.
    cmd = [
        ffmpeg_path,
        "-y",                          # overwrite without asking
        "-i", input_path,
        "-map", f"0:{stream_index}",   # select only this subtitle stream
        "-c:s", "srt",                 # convert to SRT (handles ASS/SSA too)
        out_path,
    ]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg failed to extract subtitle track #{stream_index}:\n"
            f"{result.stderr.strip()}"
        )

    if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
        raise RuntimeError(
            f"ffmpeg ran successfully but produced an empty or missing SRT file.\n"
            f"Source stream: #{stream_index}, codec: {codec_name}"
        )

    # Ensure plain SRT (converts ASS/SSA → SRT via ffmpeg if needed; also
    # strips residual ASS positioning tags on the converted file).
    srt_path = convert_to_srt(out_path)

    # Always strip inline tags from dialogue lines so mpv controls placement
    # and styling rather than embedded subtitle overrides.
    raw = Path(srt_path).read_text(encoding="utf-8-sig")
    Path(srt_path).write_text(_clean_srt_tags(raw), encoding="utf-8")

    return srt_path
