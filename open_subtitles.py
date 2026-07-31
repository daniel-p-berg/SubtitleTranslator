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
from typing import Any, Callable

import app_paths
import languages
from operation_control import CancellationToken


BASE_URL = "https://api.opensubtitles.com/api/v1"
USER_AGENT = "SubtitleTranslator v0.9"
VIETNAMESE_LANGUAGE = "vi"
_MAX_API_ATTEMPTS = 3
_MAX_RETRY_DELAY_SECONDS = 10.0
_MAX_JSON_BYTES = 4 * 1024 * 1024
_MAX_DOWNLOAD_BYTES = 32 * 1024 * 1024
_MAX_ARCHIVE_ENTRY_BYTES = 16 * 1024 * 1024
_MAX_ARCHIVE_MEMBERS = 200
_RETRYABLE_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}
_EPISODE_PATTERNS = (
    re.compile(r"(?i)(?<![a-z0-9])s(\d{1,2})[ ._-]*e(\d{1,3})(?!\d)"),
    re.compile(r"(?i)(?<![a-z0-9])(\d{1,2})x(\d{1,3})(?!\d)"),
)

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
    cancellation_token: CancellationToken | None = None,
    event_callback: Callable[[str, dict[str, Any]], None] | None = None,
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
    if cancellation_token:
        cancellation_token.raise_if_cancelled()

    query = (query_override or _query_from_filename(video_path)).strip()
    if not query:
        raise OpenSubtitlesError("A title is required for OpenSubtitles search.")

    candidates: list[SubtitleCandidate] = []
    matched_by_hash = False
    request_controls: dict[str, Any] = {}
    if cancellation_token is not None:
        request_controls["cancellation_token"] = cancellation_token
    if event_callback is not None:
        request_controls["event_callback"] = event_callback

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
                **request_controls,
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
            **request_controls,
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

    result = SubtitleSearchResult(
        query=query,
        candidates=tuple(ranked),
        automatic_matches=tuple(automatic),
        matched_by_hash=matched_by_hash,
    )
    if event_callback:
        event_callback(
            "search_completed",
            {
                "query": query,
                "candidate_count": len(ranked),
                "automatic_match_count": len(automatic),
                "matched_by_hash": matched_by_hash,
            },
        )
    return result


def search_subtitles(
    api_key: str,
    video_path: str,
    language_code: str,
    limit: int = 8,
    *,
    cancellation_token: CancellationToken | None = None,
    event_callback: Callable[[str, dict[str, Any]], None] | None = None,
) -> list[SubtitleCandidate]:
    """Return candidates in one language that are safe for automatic use."""
    language = languages.get_language(language_code)
    results = search_results(
        api_key,
        video_path,
        language.code,
        limit=max(limit, 8),
        cancellation_token=cancellation_token,
        event_callback=event_callback,
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
    cancellation_token: CancellationToken | None = None,
    event_callback: Callable[[str, dict[str, Any]], None] | None = None,
) -> str:
    """
    Download a selected OpenSubtitles candidate into the private workspace.

    Returns the local subtitle path.
    """
    api_key = api_key.strip()
    if not api_key:
        raise OpenSubtitlesError("OpenSubtitles API key is required.")
    if cancellation_token:
        cancellation_token.raise_if_cancelled()

    started = time.monotonic()
    request_controls: dict[str, Any] = {}
    if cancellation_token is not None:
        request_controls["cancellation_token"] = cancellation_token
    if event_callback is not None:
        request_controls["event_callback"] = event_callback
    response = _request_json(
        "POST",
        "/download",
        api_key,
        body={"file_id": candidate.file_id, "sub_format": "srt"},
        **request_controls,
    )
    print(f"OpenSubtitles download link created in {time.monotonic() - started:.2f}s.")
    link = response.get("link")
    if not isinstance(link, str) or not link.strip():
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
        link.strip(),
        candidate,
        video_path,
        language,
        output_dir,
        cancellation_token=cancellation_token,
    )
    print(f"OpenSubtitles subtitle file downloaded in {time.monotonic() - started:.2f}s.")
    if event_callback:
        event_callback(
            "download_completed",
            {
                "file_id": candidate.file_id,
                "release_name": candidate.release_name,
                "file_name": candidate.file_name,
            },
        )
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
    cancellation_token: CancellationToken | None = None,
    event_callback: Callable[[str, dict[str, Any]], None] | None = None,
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

    for attempt in range(1, _MAX_API_ATTEMPTS + 1):
        if cancellation_token:
            cancellation_token.raise_if_cancelled()
        request = urllib.request.Request(  # noqa: S310
            url,
            data=data,
            headers=headers,
            method=method,
        )
        try:
            # BASE_URL is a fixed OpenSubtitles HTTPS endpoint.
            with urllib.request.urlopen(  # noqa: S310  # nosec B310
                request,
                timeout=30,
            ) as response:
                payload = _read_limited(
                    response,
                    _MAX_JSON_BYTES,
                    "OpenSubtitles API response",
                ).decode("utf-8")
                decoded = json.loads(payload)
                if not isinstance(decoded, dict):
                    raise OpenSubtitlesError(
                        "OpenSubtitles returned an unexpected JSON response."
                    )
                if cancellation_token:
                    cancellation_token.raise_if_cancelled()
                return decoded
        except urllib.error.HTTPError as exc:
            body_text = exc.read(64 * 1024).decode("utf-8", errors="replace")
            message = _error_message(body_text) or exc.reason
            if exc.code in _RETRYABLE_STATUS_CODES and attempt < _MAX_API_ATTEMPTS:
                retry_after = (
                    exc.headers.get("Retry-After") if exc.headers else None
                )
                delay = _retry_delay(retry_after, attempt)
                print(
                    "OpenSubtitles is temporarily unavailable "
                    f"(HTTP {exc.code}); retrying in {delay:g}s."
                )
                if event_callback:
                    event_callback(
                        "retry",
                        {
                            "attempt": attempt,
                            "status_code": exc.code,
                            "delay_seconds": delay,
                        },
                    )
                if cancellation_token:
                    cancellation_token.wait(delay)
                else:
                    time.sleep(delay)
                continue
            raise OpenSubtitlesError(
                f"OpenSubtitles API error {exc.code}: {message}"
            ) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt < _MAX_API_ATTEMPTS:
                delay = _retry_delay(None, attempt)
                print(
                    "Could not reach OpenSubtitles; "
                    f"retrying in {delay:g}s."
                )
                if event_callback:
                    event_callback(
                        "retry",
                        {
                            "attempt": attempt,
                            "reason": "network error",
                            "delay_seconds": delay,
                        },
                    )
                if cancellation_token:
                    cancellation_token.wait(delay)
                else:
                    time.sleep(delay)
                continue
            raise OpenSubtitlesError(
                f"Could not reach OpenSubtitles: {getattr(exc, 'reason', exc)}"
            ) from exc
        except json.JSONDecodeError as exc:
            raise OpenSubtitlesError("OpenSubtitles returned invalid JSON.") from exc

    raise OpenSubtitlesError("OpenSubtitles request failed after retries.")


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
    source_text = (
        title_query if title_query is not None else _query_from_filename(video_path)
    )
    video_tokens = _meaningful_title_tokens(source_text)
    if not video_tokens:
        return []
    source_episode = _episode_identity(f"{source_text} {Path(video_path).stem}")
    source_year = _release_year(f"{source_text} {Path(video_path).stem}")

    filtered = []
    for candidate in candidates:
        candidate_episode = _candidate_episode_identity(candidate)
        if source_episode and candidate_episode != source_episode:
            continue
        candidate_year = _candidate_release_year(candidate)
        if source_year and candidate_year and source_year != candidate_year:
            continue
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
    source_text = (
        title_query if title_query is not None else _query_from_filename(video_path)
    )
    video_tokens = _meaningful_title_tokens(source_text)
    candidate_tokens = _meaningful_title_tokens(_candidate_text(candidate))
    if not video_tokens or not candidate_tokens:
        return 0.0
    source_episode = _episode_identity(f"{source_text} {Path(video_path).stem}")
    candidate_episode = _candidate_episode_identity(candidate)
    if source_episode and candidate_episode != source_episode:
        return 0.0
    source_year = _release_year(f"{source_text} {Path(video_path).stem}")
    candidate_year = _candidate_release_year(candidate)
    if source_year and candidate_year and source_year != candidate_year:
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
    normalized = unicodedata.normalize("NFKC", text).casefold()
    normalized = re.sub(r"s\d{1,2}[ ._-]*e\d{1,3}", " ", normalized)
    normalized = re.sub(r"\b\d{1,2}x\d{1,3}\b", " ", normalized)
    normalized = re.sub(r"\b\d{1,4}\b", " ", normalized)
    tokens = set(re.findall(r"[^\W_]+", normalized, flags=re.UNICODE))
    folded = (
        unicodedata.normalize("NFKD", normalized)
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    tokens.update(re.findall(r"[a-z][a-z0-9]{2,}", folded))
    return {
        token
        for token in tokens
        if (
            (len(token) >= 3 or any(ord(character) > 127 for character in token))
            and token not in _TITLE_STOPWORDS
            and token not in _RELEASE_STOPWORDS
        )
    }


def _episode_identity(text: str) -> tuple[int, int] | None:
    """Return a season/episode pair from common release-name conventions."""
    normalized = unicodedata.normalize("NFKC", text)
    for pattern in _EPISODE_PATTERNS:
        match = pattern.search(normalized)
        if match:
            return int(match.group(1)), int(match.group(2))
    return None


def _candidate_episode_identity(
    candidate: SubtitleCandidate,
) -> tuple[int, int] | None:
    """Prefer structured OpenSubtitles episode metadata over release text."""
    attrs = candidate.source.get("attributes", {})
    feature = attrs.get("feature_details") or {}
    season = feature.get("season_number", feature.get("season"))
    episode = feature.get("episode_number", feature.get("episode"))
    try:
        if season not in (None, "") and episode not in (None, ""):
            return int(season), int(episode)
    except (TypeError, ValueError):
        pass
    return _episode_identity(_candidate_text(candidate))


def _release_year(text: str) -> int | None:
    """Return the first plausible screen release year from title text."""
    for value in re.findall(r"(?<!\d)(?:19|20)\d{2}(?!\d)", text):
        year = int(value)
        if 1888 <= year <= 2100:
            return year
    return None


def _candidate_release_year(candidate: SubtitleCandidate) -> int | None:
    """Prefer canonical OpenSubtitles year metadata over noisy release names."""
    try:
        year = int(candidate.feature_year)
    except (TypeError, ValueError):
        year = 0
    if 1888 <= year <= 2100:
        return year
    return _release_year(_candidate_text(candidate))


def _download_link(
    link: str,
    candidate: SubtitleCandidate,
    video_path: str,
    language: languages.LanguageProfile,
    output_directory: Path,
    *,
    cancellation_token: CancellationToken | None = None,
) -> str:
    """Download and unpack the subtitle file returned by OpenSubtitles."""
    parsed = urllib.parse.urlsplit(link)
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise OpenSubtitlesError(
            "OpenSubtitles returned an unsafe subtitle download URL."
        )
    request = urllib.request.Request(  # noqa: S310
        link,
        headers={"User-Agent": USER_AGENT},
    )
    if cancellation_token:
        cancellation_token.raise_if_cancelled()
    try:
        # The returned link is restricted to credential-free HTTPS above.
        with urllib.request.urlopen(  # noqa: S310  # nosec B310
            request,
            timeout=60,
        ) as response:
            data = _read_limited(
                response,
                _MAX_DOWNLOAD_BYTES,
                "Downloaded subtitle",
            )
            content_type = response.headers.get("Content-Type", "")
    except (urllib.error.URLError, TimeoutError) as exc:
        reason = getattr(exc, "reason", exc)
        raise OpenSubtitlesError(
            f"Could not download subtitle file: {reason}"
        ) from exc

    if cancellation_token:
        cancellation_token.raise_if_cancelled()
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
            with gzip.GzipFile(fileobj=BytesIO(data)) as compressed:
                data = compressed.read(_MAX_ARCHIVE_ENTRY_BYTES + 1)
            if len(data) > _MAX_ARCHIVE_ENTRY_BYTES:
                raise OpenSubtitlesError(
                    "Downloaded gzip subtitle is too large to process safely."
                )
        except OSError as exc:
            raise OpenSubtitlesError(
                "Downloaded gzip subtitle could not be unpacked."
            ) from exc

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
        members = archive.infolist()
        if len(members) > _MAX_ARCHIVE_MEMBERS:
            raise OpenSubtitlesError(
                "Downloaded subtitle archive contains too many files."
            )
        supported = [
            member
            for member in members
            if (
                not member.is_dir()
                and Path(member.filename).suffix.lower()
                in app_paths.SUBTITLE_EXTENSIONS
            )
        ]
        if not supported:
            raise OpenSubtitlesError("Downloaded archive did not contain an SRT/ASS/SSA file.")
        member = supported[0]
        if member.flag_bits & 0x1:
            raise OpenSubtitlesError(
                "Downloaded subtitle archive is encrypted."
            )
        if member.file_size > _MAX_ARCHIVE_ENTRY_BYTES:
            raise OpenSubtitlesError(
                "Downloaded subtitle archive entry is too large to process safely."
            )
        suffix = Path(member.filename).suffix.lower()
        path = output_directory / (
            f"{Path(video_path).stem} [OpenSubtitles {language.code} "
            f"{file_id}]{suffix}"
        )
        with archive.open(member) as source:
            subtitle_data = source.read(_MAX_ARCHIVE_ENTRY_BYTES + 1)
        if len(subtitle_data) > _MAX_ARCHIVE_ENTRY_BYTES:
            raise OpenSubtitlesError(
                "Downloaded subtitle archive entry is too large to process safely."
            )
        _write_text_subtitle(path, subtitle_data)
        return str(path)


def _read_limited(response: Any, limit: int, label: str) -> bytes:
    """Read a bounded HTTP response before allocating untrusted content."""
    headers = getattr(response, "headers", {})
    content_length = headers.get("Content-Length")
    try:
        declared_length = int(content_length) if content_length else 0
    except (TypeError, ValueError):
        declared_length = 0
    if declared_length > limit:
        raise OpenSubtitlesError(f"{label} is too large to process safely.")
    data = response.read(limit + 1)
    if len(data) > limit:
        raise OpenSubtitlesError(f"{label} is too large to process safely.")
    return data


def _retry_delay(retry_after: str | None, attempt: int) -> float:
    """Return a short bounded Retry-After or exponential delay."""
    if retry_after:
        try:
            return max(
                0.0,
                min(float(retry_after), _MAX_RETRY_DELAY_SECONDS),
            )
        except ValueError:
            pass
    return min(float(2 ** (attempt - 1)), _MAX_RETRY_DELAY_SECONDS)


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
