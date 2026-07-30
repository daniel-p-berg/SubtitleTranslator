"""OpenSubtitles.com REST API helpers."""

from __future__ import annotations

import gzip
import json
import re
import struct
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

import app_paths
import languages


BASE_URL = "https://api.opensubtitles.com/api/v1"
USER_AGENT = "SubtitleTranslator v0.9"
VIETNAMESE_LANGUAGE = "vi"

_TITLE_STOPWORDS = {
    "a",
    "an",
    "and",
    "at",
    "de",
    "del",
    "der",
    "di",
    "dl",
    "el",
    "en",
    "eng",
    "ep",
    "episode",
    "episodio",
    "for",
    "from",
    "hardsub",
    "in",
    "ita",
    "jpn",
    "la",
    "le",
    "multi",
    "of",
    "on",
    "or",
    "sub",
    "subs",
    "subtitle",
    "subtitles",
    "the",
    "to",
    "vi",
    "vie",
    "vietnamese",
    "with",
}

_RELEASE_STOPWORDS = {
    "1080p",
    "2160p",
    "480p",
    "720p",
    "aac",
    "ac3",
    "amzn",
    "bdrip",
    "bluray",
    "brip",
    "ddp",
    "dl",
    "eac3",
    "h264",
    "h265",
    "hdrip",
    "hevc",
    "proper",
    "remux",
    "repack",
    "web",
    "webdl",
    "webrip",
    "x264",
    "x265",
    "yify",
}


class OpenSubtitlesError(RuntimeError):
    """Raised when the OpenSubtitles API cannot complete a requested action."""


@dataclass(frozen=True)
class SubtitleCandidate:
    """A normalized subtitle search result."""

    file_id: int
    release_name: str
    file_name: str
    language: str
    download_count: int
    rating: float
    trusted: bool
    source: dict[str, Any]

    @property
    def score(self) -> tuple[int, float, int]:
        """Sort key favoring trusted, well-rated, often-downloaded subtitles."""
        return (1 if self.trusted else 0, self.rating, self.download_count)

    def label(self) -> str:
        """Human-readable summary for logs."""
        name = self.release_name or self.file_name or f"file_id={self.file_id}"
        return (
            f"{name} "
            f"(rating={self.rating:g}, downloads={self.download_count}, "
            f"trusted={'yes' if self.trusted else 'no'})"
        )

    @property
    def feature_title(self) -> str:
        """Canonical title supplied by OpenSubtitles, when available."""
        attrs = self.source.get("attributes", {})
        feature = attrs.get("feature_details") or {}
        return str(feature.get("title") or feature.get("movie_name") or "")

    @property
    def feature_year(self) -> str:
        """Canonical release year supplied by OpenSubtitles, when available."""
        attrs = self.source.get("attributes", {})
        feature = attrs.get("feature_details") or {}
        year = feature.get("year")
        return str(year) if year not in (None, "") else ""


@dataclass(frozen=True)
class SubtitleSearchResult:
    """Automatic matches plus broader candidates suitable for manual review."""

    query: str
    candidates: tuple[SubtitleCandidate, ...]
    automatic_matches: tuple[SubtitleCandidate, ...]
    matched_by_hash: bool


def movie_hash(video_path: str) -> str:
    """
    Compute the OpenSubtitles movie hash for a local video file.

    The hash is the file size plus unsigned 64-bit words from the first and
    last 64 KiB of the file, modulo 2^64.
    """
    path = Path(video_path)
    file_size = path.stat().st_size
    chunk_size = 64 * 1024
    if file_size < chunk_size * 2:
        raise OpenSubtitlesError("File is too small to compute an OpenSubtitles hash.")

    total = file_size
    with path.open("rb") as fh:
        total = _add_hash_chunk(total, fh.read(chunk_size))
        fh.seek(max(0, file_size - chunk_size))
        total = _add_hash_chunk(total, fh.read(chunk_size))

    return f"{total & 0xFFFFFFFFFFFFFFFF:016x}"


def test_api_key(api_key: str) -> None:
    """Validate an API key without searching for or downloading a subtitle."""
    if not api_key.strip():
        raise OpenSubtitlesError("OpenSubtitles API key is required.")
    _request_json("GET", "/infos/languages", api_key.strip())


def _add_hash_chunk(total: int, data: bytes) -> int:
    """Add one 64 KiB chunk to an OpenSubtitles hash accumulator."""
    usable = len(data) - (len(data) % 8)
    for (value,) in struct.iter_unpack("<Q", data[:usable]):
        total = (total + value) & 0xFFFFFFFFFFFFFFFF
    return total


def search_results(
    api_key: str,
    video_path: str,
    language_code: str,
    *,
    query_override: str | None = None,
    limit: int = 50,
) -> SubtitleSearchResult:
    """
    Search OpenSubtitles and retain rejected candidates for manual review.

    A normal search tries the movie hash first and then the filename. An
    explicit query skips the hash lookup. Filename results are ranked broadly,
    while ``automatic_matches`` contains only candidates that pass the strict
    title filter.
    """
    api_key = api_key.strip()
    if not api_key:
        raise OpenSubtitlesError("OpenSubtitles API key is required.")
    language = languages.get_language(language_code)

    query = (query_override or _query_from_filename(video_path)).strip()
    if not query:
        raise OpenSubtitlesError("A title is required for OpenSubtitles search.")

    candidates: list[SubtitleCandidate] = []
    matched_by_hash = False

    if query_override is None:
        started = time.monotonic()
        try:
            hash_value = movie_hash(video_path)
            print(
                "OpenSubtitles movie hash computed in "
                f"{time.monotonic() - started:.2f}s."
            )
        except (OSError, OpenSubtitlesError):
            hash_value = ""

        if hash_value:
            started = time.monotonic()
            data = _request_json(
                "GET",
                "/subtitles",
                api_key,
                query={
                    "languages": language.opensubtitles_code,
                    "moviehash": hash_value,
                },
            )
            candidates = _parse_candidates(data)
            matched_by_hash = bool(candidates)
            print(
                "OpenSubtitles hash search "
                f"returned {len(candidates)} result(s) in "
                f"{time.monotonic() - started:.2f}s."
            )

    if not matched_by_hash:
        started = time.monotonic()
        data = _request_json(
            "GET",
            "/subtitles",
            api_key,
            query={
                "languages": language.opensubtitles_code,
                "query": query.lower(),
            },
        )
        candidates = _parse_candidates(data)
        print(
            "OpenSubtitles filename search "
            f"returned {len(candidates)} result(s) in {time.monotonic() - started:.2f}s."
        )

    ranked = sorted(
        candidates,
        key=lambda item: (
            _filename_match_score(item, video_path, title_query=query),
            *item.score,
        ),
        reverse=True,
    )[:limit]
    automatic = (
        ranked
        if matched_by_hash
        else _filter_filename_candidates(
            ranked,
            video_path,
            title_query=query,
        )
    )
    if not matched_by_hash:
        print(
            "OpenSubtitles title-match filter kept "
            f"{len(automatic)} of {len(ranked)} filename result(s)."
        )

    return SubtitleSearchResult(
        query=query,
        candidates=tuple(ranked),
        automatic_matches=tuple(automatic),
        matched_by_hash=matched_by_hash,
    )


def search_subtitles(
    api_key: str,
    video_path: str,
    language_code: str,
    limit: int = 8,
) -> list[SubtitleCandidate]:
    """Return candidates in one language that are safe for automatic use."""
    language = languages.get_language(language_code)
    results = search_results(
        api_key,
        video_path,
        language.code,
        limit=max(limit, 8),
    )
    if not results.candidates:
        return []
    if not results.automatic_matches:
        best = results.candidates[0]
        print(f"Best rejected result: {best.label()}")
        raise OpenSubtitlesError(
            f"OpenSubtitles returned {language.name} filename results, but none "
            "matched this video's title closely enough. Best rejected "
            f"result: {best.label()}"
        )
    return list(results.automatic_matches[:limit])


def download_subtitle(
    api_key: str,
    candidate: SubtitleCandidate,
    video_path: str,
    *,
    language_code: str | None = None,
    workspace_directory: str | Path | None = None,
    output_directory: str | Path | None = None,
) -> str:
    """
    Download a selected OpenSubtitles candidate into the private workspace.

    Returns the local subtitle path.
    """
    api_key = api_key.strip()
    if not api_key:
        raise OpenSubtitlesError("OpenSubtitles API key is required.")

    started = time.monotonic()
    response = _request_json(
        "POST",
        "/download",
        api_key,
        body={"file_id": candidate.file_id, "sub_format": "srt"},
    )
    print(f"OpenSubtitles download link created in {time.monotonic() - started:.2f}s.")
    link = response.get("link")
    if not link:
        message = response.get("message") or "OpenSubtitles did not return a download link."
        raise OpenSubtitlesError(message)

    if language_code:
        language = languages.get_language(language_code)
    else:
        language = languages.identify_language(candidate.language) or languages.get_language("en")
    output_dir = (
        Path(output_directory).expanduser()
        if output_directory
        else app_paths.workspace_subtitles_dir(workspace_directory)
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    output_path = _download_link(
        link,
        candidate,
        video_path,
        language,
        output_dir,
    )
    print(f"OpenSubtitles subtitle file downloaded in {time.monotonic() - started:.2f}s.")
    return output_path


def find_and_download(
    api_key: str,
    video_path: str,
    language_code: str,
    *,
    workspace_directory: str | Path | None = None,
) -> tuple[str, SubtitleCandidate, int]:
    """
    Search, download the best target-language result, and return details.

    Returns:
        ``(subtitle_path, chosen_candidate, result_count)``.
    """
    language = languages.get_language(language_code)
    candidates = search_subtitles(api_key, video_path, language.code)
    if not candidates:
        raise OpenSubtitlesError(
            f"No {language.name} subtitles found on OpenSubtitles."
        )

    chosen = candidates[0]
    subtitle_path = download_subtitle(
        api_key,
        chosen,
        video_path,
        language_code=language.code,
        workspace_directory=workspace_directory,
    )
    return subtitle_path, chosen, len(candidates)


def search_vietnamese_results(
    api_key: str,
    video_path: str,
    *,
    query_override: str | None = None,
    limit: int = 50,
) -> SubtitleSearchResult:
    """Backward-compatible Vietnamese search wrapper."""
    return search_results(
        api_key,
        video_path,
        "vi",
        query_override=query_override,
        limit=limit,
    )


def search_vietnamese(
    api_key: str,
    video_path: str,
    limit: int = 8,
) -> list[SubtitleCandidate]:
    """Backward-compatible Vietnamese candidate wrapper."""
    return search_subtitles(api_key, video_path, "vi", limit)


def find_and_download_vietnamese(
    api_key: str,
    video_path: str,
) -> tuple[str, SubtitleCandidate, int]:
    """Backward-compatible Vietnamese download wrapper."""
    return find_and_download(api_key, video_path, "vi")


def _request_json(
    method: str,
    path: str,
    api_key: str,
    *,
    query: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Send a JSON request to the OpenSubtitles REST API."""
    url = f"{BASE_URL}{path}"
    if query:
        url = f"{url}?{urllib.parse.urlencode(query)}"

    data = None
    headers = {
        "Accept": "application/json",
        "Api-Key": api_key,
        "User-Agent": USER_AGENT,
    }
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read().decode("utf-8")
            return json.loads(payload)
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        message = _error_message(body_text) or exc.reason
        raise OpenSubtitlesError(f"OpenSubtitles API error {exc.code}: {message}") from exc
    except urllib.error.URLError as exc:
        raise OpenSubtitlesError(f"Could not reach OpenSubtitles: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise OpenSubtitlesError("OpenSubtitles returned invalid JSON.") from exc


def _parse_candidates(payload: dict[str, Any]) -> list[SubtitleCandidate]:
    """Normalize OpenSubtitles search results."""
    candidates: list[SubtitleCandidate] = []
    for item in payload.get("data", []):
        attrs = item.get("attributes", {})
        files = attrs.get("files") or []
        if not files:
            continue
        file_info = files[0]
        file_id = file_info.get("file_id")
        if file_id is None:
            continue
        try:
            file_id = int(file_id)
        except (TypeError, ValueError):
            continue

        candidates.append(
            SubtitleCandidate(
                file_id=file_id,
                release_name=str(attrs.get("release") or attrs.get("feature_details", {}).get("title") or ""),
                file_name=str(file_info.get("file_name") or ""),
                language=str(attrs.get("language") or ""),
                download_count=_int_value(attrs.get("download_count")),
                rating=_float_value(attrs.get("ratings")),
                trusted=bool(attrs.get("from_trusted")),
                source=item,
            )
        )
    return candidates


def _filter_filename_candidates(
    candidates: list[SubtitleCandidate],
    video_path: str,
    *,
    title_query: str | None = None,
) -> list[SubtitleCandidate]:
    """
    Keep only filename-search results that look textually related to the video.

    OpenSubtitles can return broad season/episode matches for noisy release
    names. A trusted but unrelated ``S01E01`` result is worse than no result,
    so filename search requires strong overlap on meaningful title words.
    """
    video_tokens = _meaningful_title_tokens(
        title_query if title_query is not None else _query_from_filename(video_path)
    )
    if not video_tokens:
        return candidates

    filtered = []
    for candidate in candidates:
        candidate_tokens = _meaningful_title_tokens(_candidate_text(candidate))
        overlap = video_tokens & candidate_tokens
        if not overlap:
            continue
        if len(video_tokens) <= 2:
            # Short titles are vulnerable to false positives such as
            # "MF Ghost" for "Ghost in the Shell". Require every
            # meaningful word when the local title has only one or two.
            if overlap == video_tokens:
                filtered.append(candidate)
        elif len(overlap) >= 2:
            filtered.append(candidate)
    return filtered


def _filename_match_score(
    candidate: SubtitleCandidate,
    video_path: str,
    *,
    title_query: str | None = None,
) -> float:
    """Return a rough 0..1 text-match score between a result and local video."""
    video_tokens = _meaningful_title_tokens(
        title_query if title_query is not None else _query_from_filename(video_path)
    )
    candidate_tokens = _meaningful_title_tokens(_candidate_text(candidate))
    if not video_tokens or not candidate_tokens:
        return 0.0
    overlap = len(video_tokens & candidate_tokens)
    return overlap / max(1, min(len(video_tokens), len(candidate_tokens)))


def _candidate_text(candidate: SubtitleCandidate) -> str:
    """Combine the OpenSubtitles fields that may contain title/release text."""
    attrs = candidate.source.get("attributes", {})
    feature = attrs.get("feature_details") or {}
    parts = [
        candidate.release_name,
        candidate.file_name,
        str(feature.get("title") or ""),
        str(feature.get("movie_name") or ""),
    ]
    return " ".join(part for part in parts if part)


def _meaningful_title_tokens(text: str) -> set[str]:
    """Tokenize a release/title string into words useful for match filtering."""
    normalized = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    normalized = normalized.lower()
    normalized = re.sub(r"s\d{1,2}e\d{1,3}", " ", normalized)
    normalized = re.sub(r"\b\d{1,4}\b", " ", normalized)
    tokens = set(re.findall(r"[a-z][a-z0-9]{2,}", normalized))
    return {
        token
        for token in tokens
        if token not in _TITLE_STOPWORDS and token not in _RELEASE_STOPWORDS
    }


def _download_link(
    link: str,
    candidate: SubtitleCandidate,
    video_path: str,
    language: languages.LanguageProfile,
    output_directory: Path,
) -> str:
    """Download and unpack the subtitle file returned by OpenSubtitles."""
    request = urllib.request.Request(link, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            data = response.read()
            content_type = response.headers.get("Content-Type", "")
    except urllib.error.URLError as exc:
        raise OpenSubtitlesError(f"Could not download subtitle file: {exc.reason}") from exc

    file_name = candidate.file_name or f"{Path(video_path).stem}.srt"
    if zipfile.is_zipfile(BytesIO(data)):
        return _write_zip_subtitle(
            data,
            video_path,
            language,
            output_directory,
            candidate.file_id,
        )

    if data.startswith(b"\x1f\x8b") or "gzip" in content_type.lower():
        try:
            data = gzip.decompress(data)
        except OSError:
            pass

    suffix = Path(file_name).suffix.lower()
    if suffix not in app_paths.SUBTITLE_EXTENSIONS:
        suffix = ".srt"

    path = output_directory / (
        f"{Path(video_path).stem} [OpenSubtitles {language.code} "
        f"{candidate.file_id}]{suffix}"
    )
    _write_text_subtitle(path, data)
    return str(path)


def _write_zip_subtitle(
    data: bytes,
    video_path: str,
    language: languages.LanguageProfile,
    output_directory: Path,
    file_id: int,
) -> str:
    """Extract the first supported subtitle file from a zip archive."""
    with zipfile.ZipFile(BytesIO(data)) as archive:
        names = [
            name for name in archive.namelist()
            if Path(name).suffix.lower() in app_paths.SUBTITLE_EXTENSIONS
        ]
        if not names:
            raise OpenSubtitlesError("Downloaded archive did not contain an SRT/ASS/SSA file.")
        name = names[0]
        suffix = Path(name).suffix.lower()
        path = output_directory / (
            f"{Path(video_path).stem} [OpenSubtitles {language.code} "
            f"{file_id}]{suffix}"
        )
        _write_text_subtitle(path, archive.read(name))
        return str(path)


def _write_text_subtitle(path: Path, data: bytes) -> None:
    """Write subtitle bytes as UTF-8 text for downstream ffmpeg/Tkinter work."""
    for encoding in ("utf-8-sig", "utf-8", "cp1258", "windows-1252", "latin-1"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = data.decode("utf-8", errors="replace")
    path.write_text(text, encoding="utf-8")


def _query_from_filename(video_path: str) -> str:
    """Build a conservative search query from a release filename."""
    stem = Path(video_path).stem
    stem = re.sub(r"[\[\(].*?[\]\)]", " ", stem)
    stem = re.sub(r"[._-]+", " ", stem)
    stem = re.sub(r"\b(1080p|720p|2160p|480p|x264|x265|h264|h265|hevc|aac|web[- ]?dl|webrip|bluray)\b", " ", stem, flags=re.I)
    return re.sub(r"\s+", " ", stem).strip()


def _error_message(body_text: str) -> str:
    """Extract an API error message from a JSON body when possible."""
    try:
        payload = json.loads(body_text)
    except json.JSONDecodeError:
        return body_text.strip()
    message = payload.get("message") or payload.get("error") or ""
    if isinstance(message, list):
        return "; ".join(str(item) for item in message)
    return str(message)


def _int_value(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _float_value(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
