"""Language-neutral subtitle preparation, synchronization, and merge workflow."""

from __future__ import annotations

import json
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal

from send2trash import send2trash

import app_paths
import audio_activity
import diagnostics as app_diagnostics
import extractor
import languages
import muxer
import open_subtitles
from operation_control import (
    CancellationToken,
    OperationCancelled,
)
import subtitle_sync
import translation_cost
import translator


Strategy = Literal["automatic", "find", "translate"]
ProgressCallback = Callable[[str, str, int], None]


@dataclass(frozen=True)
class TrackSummary:
    """Display-safe subtitle track information."""

    index: int
    codec: str
    language_code: str
    language_name: str
    title: str
    text_based: bool
    forced: bool


@dataclass(frozen=True)
class MediaInspection:
    """Subtitle inventory for one selected media file."""

    video_path: str
    tracks: tuple[TrackSummary, ...]
    sidecars: tuple[extractor.ExternalSubtitle, ...]
    suggested_source_language: str
    target_available: bool
    duration_seconds: float


@dataclass
class PipelineOptions:
    """User choices and ephemeral credentials for one operation."""

    video_path: str
    target_language: str
    source_language: str = "auto"
    strategy: Strategy = "automatic"
    selected_subtitle_path: str = ""
    selected_candidate: open_subtitles.SubtitleCandidate | None = None
    media_roots: list[str] = field(default_factory=list)
    workspace_directory: str = ""
    output_mode: str = "alongside"
    custom_output_directory: str = ""
    save_final_subtitle: bool = True
    create_merged_video: bool = True
    cleanup_intermediates: bool = False
    delete_original_after_merge: bool = False
    openai_api_key: str = ""
    opensubtitles_api_key: str = ""
    translation_model: str = "gpt-5.6-luna"
    reasoning_effort: str = "low"
    prompt_template: str = ""


@dataclass(frozen=True)
class PipelineResult:
    """Paths and decisions produced by a successful operation."""

    video_path: str
    subtitle_path: str
    merged_path: str
    source_language: str
    target_language: str
    target_origin: str
    original_moved_to_trash: bool
    warnings: tuple[str, ...]
    diagnostics: dict = field(default_factory=dict)


@dataclass(frozen=True)
class _Reference:
    path: str
    language_code: str
    label: str
    embedded: bool


@dataclass(frozen=True)
class _PlaybackReference:
    path: str
    language_code: str
    label: str


@dataclass(frozen=True)
class _Target:
    path: str
    origin: str
    embedded: bool
    candidates: tuple[open_subtitles.SubtitleCandidate, ...] = ()
    candidate_id: int | None = None
    search_result: open_subtitles.SubtitleSearchResult | None = None


class CandidateReviewRequired(RuntimeError):
    """Raised when search results exist but none is safe to select silently."""

    def __init__(
        self,
        message: str,
        result: open_subtitles.SubtitleSearchResult,
        *,
        allow_translation: bool = False,
        rejection_reasons: dict[int, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.result = result
        self.allow_translation = allow_translation
        self.rejection_reasons = dict(rejection_reasons or {})


class SubtitlePipeline:
    """Coordinate the existing media helpers through a generic workflow."""

    def __init__(
        self,
        progress: ProgressCallback | None = None,
        *,
        cancellation_token: CancellationToken | None = None,
        diagnostics_recorder: app_diagnostics.DiagnosticsRecorder | None = None,
    ) -> None:
        self.progress = progress or (lambda _stage, _message, _percent: None)
        self.cancellation_token = cancellation_token
        self.diagnostics_recorder = diagnostics_recorder
        self._warnings: list[str] = []
        self._translation_input_tokens = 0
        self._translation_output_tokens = 0

    def inspect(
        self,
        video_path: str,
        *,
        target_language: str,
        media_roots: list[str] | None = None,
    ) -> MediaInspection:
        """Inventory embedded and sidecar subtitles without changing media."""
        self._check_cancelled()
        video = Path(video_path).expanduser().resolve()
        streams = extractor.probe_subtitle_streams(str(video))
        target = languages.get_language(target_language)
        summaries: list[TrackSummary] = []
        for stream in streams:
            profile = extractor.stream_language(stream)
            tags = stream.get("tags") or {}
            summaries.append(
                TrackSummary(
                    index=int(stream.get("index", -1)),
                    codec=str(stream.get("codec_name", "unknown")),
                    language_code=profile.code if profile else "und",
                    language_name=profile.name if profile else "Unknown",
                    title=str(tags.get("title", tags.get("TITLE", ""))),
                    text_based=extractor.is_text_stream(stream),
                    forced=bool(stream.get("disposition", {}).get("forced")),
                )
            )

        sidecars = extractor.find_external_subtitles(
            str(video),
            media_roots=media_roots or [],
        )
        source_stream = extractor.pick_reference_stream(
            streams,
            excluded_language=target.code,
        )
        source_profile = (
            extractor.stream_language(source_stream) if source_stream else None
        )
        if source_profile is None:
            source_sidecar = next(
                (
                    item
                    for item in sidecars
                    if item.language and item.language.code != target.code
                ),
                None,
            )
            source_profile = source_sidecar.language if source_sidecar else None
        target_available = bool(
            extractor.pick_language_stream(streams, target.code)
            or any(
                item.language and item.language.code == target.code
                for item in sidecars
            )
        )
        try:
            duration_seconds = muxer.media_duration_seconds(video)
        except Exception:
            duration_seconds = 0.0
        return MediaInspection(
            str(video),
            tuple(summaries),
            tuple(sidecars),
            source_profile.code if source_profile else "auto",
            target_available,
            duration_seconds,
        )

    def search(
        self,
        api_key: str,
        video_path: str,
        target_language: str,
        *,
        query_override: str | None = None,
    ) -> open_subtitles.SubtitleSearchResult:
        """Return automatic and manual-review search candidates."""
        return open_subtitles.search_results(
            api_key,
            video_path,
            target_language,
            query_override=query_override,
            cancellation_token=self.cancellation_token,
            event_callback=lambda action, details: self._record_external_event(
                "opensubtitles",
                action,
                details,
            ),
        )

    def run(self, options: PipelineOptions) -> PipelineResult:
        """Prepare a target subtitle and optionally create a verified MKV."""
        self._warnings = []
        self._translation_input_tokens = 0
        self._translation_output_tokens = 0
        self._check_cancelled()
        video = Path(options.video_path).expanduser().resolve()
        if not video.is_file():
            raise FileNotFoundError(f"Media file not found: {video}")
        target_language = languages.get_language(options.target_language)
        workspace = Path(
            options.workspace_directory or app_paths.WORKSPACE_DIR
        ).expanduser()
        app_paths.ensure_output_dirs(workspace)

        self._emit("inspect", "Inspecting media and subtitle tracks", 5)
        streams = extractor.probe_subtitle_streams(str(video))
        job_directory = _new_job_directory(workspace, video)
        reference = self._resolve_reference(
            video,
            streams,
            options,
            job_directory,
        )

        self._emit("target", f"Preparing {target_language.name} subtitles", 30)
        target = self._resolve_target(
            video,
            streams,
            reference,
            options,
            job_directory,
        )

        if not target.embedded and target.origin != "translation":
            self._emit("sync", "Validating subtitle timing across the runtime", 55)
            target = self._sync_or_retry(
                video,
                target,
                reference,
                options,
                job_directory,
            )

        self._validate_duration(video, target.path)
        output_directory = self._output_directory(video, options)
        final_subtitle = ""
        if options.save_final_subtitle:
            self._emit("save", "Saving the clean subtitle", 72)
            final_subtitle = self._save_final_subtitle(
                video,
                target.path,
                target_language,
                output_directory,
            )

        merged_path = ""
        moved_original = False
        playback_reference: _PlaybackReference | None = None
        if options.create_merged_video:
            if reference is None:
                playback_reference = self._prepare_pgs_playback_reference(
                    video,
                    streams,
                    options,
                    job_directory,
                )
            self._emit("merge", "Creating and verifying the MKV", 82)
            merge_tracks = self._build_merge_tracks(
                final_subtitle or target.path,
                target_language,
                reference,
                playback_reference,
            )
            merged_path = muxer.mux_tracks(
                str(video),
                merge_tracks,
                output_directory=output_directory,
                cancellation_token=self.cancellation_token,
            )
            if options.delete_original_after_merge:
                self._check_cancelled()
                self._emit("cleanup", "Moving the verified original to Trash", 94)
                try:
                    send2trash(str(video))
                    moved_original = True
                except Exception as exc:  # noqa: BLE001
                    self._warn(
                        "The merged file is valid, but the original could not "
                        f"be moved to Trash: {exc}"
                    )

        if options.cleanup_intermediates:
            try:
                shutil.rmtree(job_directory)
            except OSError as exc:
                self._warn(
                    "The job finished, but its working files could not be "
                    f"removed: {exc}"
                )
        else:
            try:
                self._write_job_summary(
                    job_directory,
                    video,
                    reference,
                    playback_reference,
                    target,
                    final_subtitle,
                    merged_path,
                )
            except OSError as exc:
                self._warn(
                    "The output is ready, but the local job summary could not "
                    f"be saved: {exc}"
                )

        self._emit(
            "complete",
            "Ready to watch",
            100,
            check_cancellation=False,
        )
        source_language_code = (
            reference.language_code
            if reference
            else (
                playback_reference.language_code
                if playback_reference
                else "und"
            )
        )
        self._update_diagnostics_summary(
            status="completed",
            source_language=source_language_code,
            target_language=target_language.code,
            target_origin=target.origin,
            final_subtitle_filename=(
                Path(final_subtitle).name if final_subtitle else ""
            ),
            merged_filename=Path(merged_path).name if merged_path else "",
            warning_count=len(self._warnings),
            translation_input_tokens=self._translation_input_tokens,
            translation_output_tokens=self._translation_output_tokens,
            translation_cost_usd=translation_cost.cost_from_usage(
                options.translation_model,
                self._translation_input_tokens,
                self._translation_output_tokens,
            ),
        )
        return PipelineResult(
            str(video),
            final_subtitle,
            merged_path,
            source_language_code,
            target_language.code,
            target.origin,
            moved_original,
            tuple(self._warnings),
            (
                self.diagnostics_recorder.report()
                if self.diagnostics_recorder
                else {}
            ),
        )

    def _prepare_pgs_playback_reference(
        self,
        video: Path,
        streams: list[dict],
        options: PipelineOptions,
        job_directory: Path,
    ) -> _PlaybackReference | None:
        stream = extractor.pick_playback_pgs_stream(
            streams,
            preferred_language=options.source_language,
            excluded_language=options.target_language,
        )
        if stream is None:
            return None

        profile = extractor.stream_language(stream) or languages.UNKNOWN_LANGUAGE
        stream_index = stream.get("index", "?")
        self._emit(
            "source",
            f"Preserving embedded {profile.name} PGS track for playback",
            78,
        )
        extracted = extractor.extract_pgs_subtitle_stream(
            str(video),
            stream,
            output_directory=job_directory,
        )
        stable_path = self._copy_into_job(
            extracted,
            job_directory,
            f"playback-source.{profile.code}.sup",
        )
        return _PlaybackReference(
            stable_path,
            profile.code,
            f"embedded {profile.name} PGS track {stream_index}",
        )

    @staticmethod
    def _build_merge_tracks(
        target_path: str,
        target_language: languages.LanguageProfile,
        reference: _Reference | None,
        playback_reference: _PlaybackReference | None,
    ) -> list[muxer.SubtitleTrack]:
        if playback_reference:
            source_language = languages.get_language(
                playback_reference.language_code
            )
            return [
                muxer.SubtitleTrack(
                    playback_reference.path,
                    source_language.code,
                    f"{source_language.name} (PGS)",
                    True,
                ),
                muxer.SubtitleTrack(
                    target_path,
                    target_language.code,
                    target_language.name,
                    False,
                ),
            ]

        if reference and Path(reference.path).is_file():
            source_language = languages.get_language(reference.language_code)
            if source_language.code != target_language.code:
                if source_language.code == "en" and target_language.code == "vi":
                    return [
                        muxer.SubtitleTrack(
                            reference.path,
                            source_language.code,
                            source_language.name,
                            True,
                        ),
                        muxer.SubtitleTrack(
                            target_path,
                            target_language.code,
                            target_language.name,
                            False,
                        ),
                    ]
                return [
                    muxer.SubtitleTrack(
                        target_path,
                        target_language.code,
                        target_language.name,
                        True,
                    ),
                    muxer.SubtitleTrack(
                        reference.path,
                        source_language.code,
                        source_language.name,
                        False,
                    ),
                ]
        return [
            muxer.SubtitleTrack(
                target_path,
                target_language.code,
                target_language.name,
                True,
            )
        ]

    def _resolve_reference(
        self,
        video: Path,
        streams: list[dict],
        options: PipelineOptions,
        job_directory: Path,
    ) -> _Reference | None:
        target_code = languages.get_language(options.target_language).code
        preferred = options.source_language
        embedded_candidates = extractor.reference_stream_candidates(
            streams,
            preferred_language=preferred,
            excluded_language=target_code,
        )
        for stream in embedded_candidates:
            profile = extractor.stream_language(stream)
            if preferred != "auto":
                profile = languages.get_language(preferred)
            profile = profile or languages.UNKNOWN_LANGUAGE
            self._emit(
                "source",
                f"Extracting embedded {profile.name} reference",
                16,
            )
            path = extractor.extract_subtitle_stream(
                str(video),
                stream,
                output_directory=job_directory,
            )
            if extractor.is_probable_progressive_caption_srt(path):
                collapsed_path, collapse = (
                    extractor.collapse_repeated_progressive_caption_cues(
                        path,
                        output_directory=job_directory,
                    )
                )
                if (
                    collapse.output_cues >= 25
                    and collapse.collapsed_source_cues > 0
                    and not extractor.is_probable_progressive_caption_srt(
                        collapsed_path
                    )
                ):
                    self._emit(
                        "source",
                        "Collapsed repeated animation frames into stable "
                        "subtitle cues",
                        17,
                    )
                    path = collapsed_path
                else:
                    self._emit(
                        "source",
                        "Skipping an unusually dense progressive-caption track",
                        17,
                    )
                    continue
            stable_path = self._copy_into_job(
                path,
                job_directory,
                f"source.{profile.code}.srt",
            )
            return _Reference(
                stable_path,
                profile.code,
                f"embedded {profile.name} track {stream.get('index', '?')}",
                True,
            )

        sidecars = extractor.find_external_subtitles(
            str(video),
            media_roots=options.media_roots,
        )
        candidates = [
            item
            for item in sidecars
            if not item.language or item.language.code != target_code
        ]
        if preferred != "auto":
            preferred_profile = languages.get_language(preferred)
            candidates = [
                item
                for item in candidates
                if item.language and item.language.code == preferred_profile.code
            ]

        for candidate in candidates:
            profile = (
                languages.get_language(preferred)
                if preferred != "auto"
                else candidate.language or languages.UNKNOWN_LANGUAGE
            )
            self._emit(
                "source",
                f"Checking sidecar {profile.name} reference",
                18,
            )
            normalized = self._normalize_subtitle(
                str(candidate.path),
                video,
                job_directory,
                f"source.{profile.code}.srt",
            )
            checked = self._validate_external_reference(
                video,
                normalized,
                options,
                job_directory,
            )
            if checked:
                return _Reference(
                    checked,
                    profile.code,
                    f"sidecar {candidate.path.name}",
                    False,
                )

        return None

    def _resolve_target(
        self,
        video: Path,
        streams: list[dict],
        reference: _Reference | None,
        options: PipelineOptions,
        job_directory: Path,
    ) -> _Target:
        target = languages.get_language(options.target_language)
        if options.selected_subtitle_path:
            normalized = self._normalize_subtitle(
                options.selected_subtitle_path,
                video,
                job_directory,
                f"selected.{target.code}.srt",
            )
            return _Target(normalized, "selected file", False)

        if options.selected_candidate:
            self._record_candidate(
                options.selected_candidate,
                decision="selected by user",
            )
            path = open_subtitles.download_subtitle(
                options.opensubtitles_api_key,
                options.selected_candidate,
                str(video),
                language_code=target.code,
                workspace_directory=options.workspace_directory,
                output_directory=job_directory,
                cancellation_token=self.cancellation_token,
                event_callback=lambda action, details: self._record_external_event(
                    "opensubtitles",
                    action,
                    details,
                ),
            )
            normalized = self._normalize_subtitle(
                path,
                video,
                job_directory,
                f"selected-search.{target.code}.srt",
            )
            return _Target(
                normalized,
                "reviewed OpenSubtitles result",
                False,
                candidate_id=options.selected_candidate.file_id,
            )

        if options.strategy != "translate":
            embedded = extractor.pick_language_stream(streams, target.code)
            if embedded is not None:
                path = extractor.extract_subtitle_stream(
                    str(video),
                    embedded,
                    output_directory=job_directory,
                )
                stable = self._copy_into_job(
                    path,
                    job_directory,
                    f"embedded-target.{target.code}.srt",
                )
                return _Target(stable, "embedded track", True)

            sidecar = extractor.find_external_subtitle(
                str(video),
                target.code,
                media_roots=options.media_roots,
            )
            if sidecar:
                normalized = self._normalize_subtitle(
                    str(sidecar.path),
                    video,
                    job_directory,
                    f"sidecar-target.{target.code}.srt",
                )
                return _Target(normalized, "sidecar file", False)

        search_result: open_subtitles.SubtitleSearchResult | None = None
        search_candidates: tuple[open_subtitles.SubtitleCandidate, ...] = ()
        if options.strategy in {"automatic", "find"} and options.opensubtitles_api_key:
            self._emit(
                "search",
                f"Searching OpenSubtitles for {target.name}",
                36,
            )
            search_result = open_subtitles.search_results(
                options.opensubtitles_api_key,
                str(video),
                target.code,
                limit=50,
                cancellation_token=self.cancellation_token,
                event_callback=lambda action, details: self._record_external_event(
                    "opensubtitles",
                    action,
                    details,
                ),
            )
            search_candidates = search_result.candidates[:12]
            if search_result.automatic_matches:
                candidate = search_result.automatic_matches[0]
                self._record_candidate(
                    candidate,
                    decision="automatic title match",
                )
                path = open_subtitles.download_subtitle(
                    options.opensubtitles_api_key,
                    candidate,
                    str(video),
                    language_code=target.code,
                    workspace_directory=options.workspace_directory,
                    output_directory=job_directory,
                    cancellation_token=self.cancellation_token,
                    event_callback=lambda action, details: self._record_external_event(
                        "opensubtitles",
                        action,
                        details,
                    ),
                )
                normalized = self._normalize_subtitle(
                    path,
                    video,
                    job_directory,
                    f"search-target.{target.code}.{candidate.file_id}.srt",
                )
                return _Target(
                    normalized,
                    "OpenSubtitles",
                    False,
                    search_candidates,
                    candidate.file_id,
                    search_result,
                )
            if options.strategy == "find" and search_result.candidates:
                raise CandidateReviewRequired(
                    "Search results need manual review before download.",
                    search_result,
                )
            if options.strategy == "find":
                raise RuntimeError(
                    f"No {target.name} subtitles were found on OpenSubtitles."
                )

        if options.strategy == "find" and not options.opensubtitles_api_key:
            raise RuntimeError("An OpenSubtitles API key is required for search.")
        if options.strategy == "automatic":
            review_result = search_result or open_subtitles.SubtitleSearchResult(
                query=video.stem,
                candidates=(),
                automatic_matches=(),
                matched_by_hash=False,
            )
            translation_available = bool(
                reference
                and reference.path
                and reference.language_code != "und"
                and options.openai_api_key.strip()
            )
            if review_result.candidates or translation_available:
                raise CandidateReviewRequired(
                    "No target-language subtitle was safe to select automatically. "
                    "Review the search results or explicitly approve translation.",
                    review_result,
                    allow_translation=translation_available,
                )
        if not reference or not reference.path:
            image_reference = extractor.extract_image_subtitle_timings(
                str(video),
                preferred_language=options.source_language,
                excluded_language=target.code,
            )
            if image_reference:
                raise RuntimeError(
                    "The available source subtitle is image-based. It can help "
                    "validate timing, but OCR is required before it can be translated."
                )
            raise RuntimeError(
                "No text subtitle is available to translate. Select a text "
                "sidecar subtitle or use OpenSubtitles search."
            )
        if reference.language_code == "und":
            raise RuntimeError(
                "The source subtitle language could not be identified. Choose "
                "its language explicitly before translating."
            )
        if not options.openai_api_key:
            raise RuntimeError("An OpenAI API key is required for translation.")

        self._emit(
            "translate",
            f"Translating {languages.get_language(reference.language_code).name} "
            f"to {target.name}",
            42,
        )
        translated = translator.translate_srt(
            reference.path,
            options.openai_api_key,
            options.translation_model,
            options.reasoning_effort,
            source_language=reference.language_code,
            target_language=target.code,
            prompt_template=options.prompt_template or None,
            progress_callback=lambda current, total: self._emit(
                "translate",
                f"Translating chunk {current} of {total}",
                42 + int(12 * current / max(1, total)),
            ),
            cancellation_token=self.cancellation_token,
            event_callback=lambda action, details: self._record_external_event(
                "openai",
                action,
                details,
            ),
        )
        path = job_directory / f"translated.{target.code}.srt"
        path.write_text(translated, encoding="utf-8")
        return _Target(
            str(path),
            "translation",
            False,
            search_candidates,
            search_result=search_result,
        )

    def _sync_or_retry(
        self,
        video: Path,
        target: _Target,
        reference: _Reference | None,
        options: PipelineOptions,
        job_directory: Path,
    ) -> _Target:
        result = self._sync_target(
            video,
            target.path,
            reference,
            options,
            job_directory,
            "selected subtitle",
        )
        if result and result.confidence != "low":
            return _Target(
                result.output_path,
                target.origin,
                False,
                target.candidates,
                target.candidate_id,
                target.search_result,
            )

        api_key = options.opensubtitles_api_key.strip()
        if not api_key:
            if result is None:
                self._warn(
                    "No independent subtitle timing reference was available; "
                    "the selected subtitle was merged without an automatic shift."
                )
                return target
            raise RuntimeError(
                f"Subtitle timing could not be reconciled: {result.message}"
            )

        candidates = list(target.candidates)
        if not candidates:
            try:
                candidates = open_subtitles.search_subtitles(
                    api_key,
                    str(video),
                    options.target_language,
                    limit=12,
                    cancellation_token=self.cancellation_token,
                    event_callback=lambda action, details: self._record_external_event(
                        "opensubtitles",
                        action,
                        details,
                    ),
                )
            except open_subtitles.OpenSubtitlesError:
                candidates = []

        rejected: list[str] = []
        rejection_reasons: dict[int, str] = {}
        if (
            result
            and result.confidence == "low"
            and target.candidate_id is not None
        ):
            rejection_reasons[target.candidate_id] = result.message
        for index, candidate in enumerate(candidates, start=1):
            self._check_cancelled()
            if candidate.file_id == target.candidate_id:
                continue
            self._emit(
                "sync",
                f"Trying subtitle candidate {index} of {len(candidates)}",
                min(70, 55 + index),
            )
            self._record_candidate(
                candidate,
                decision=f"timing validation attempt {index}",
            )
            try:
                downloaded = open_subtitles.download_subtitle(
                    api_key,
                    candidate,
                    str(video),
                    language_code=options.target_language,
                    workspace_directory=options.workspace_directory,
                    output_directory=job_directory,
                    cancellation_token=self.cancellation_token,
                    event_callback=lambda action, details: self._record_external_event(
                        "opensubtitles",
                        action,
                        details,
                    ),
                )
                normalized = self._normalize_subtitle(
                    downloaded,
                    video,
                    job_directory,
                    f"candidate.{candidate.file_id}.srt",
                )
                alternate_result = self._sync_target(
                    video,
                    normalized,
                    reference,
                    options,
                    job_directory,
                    f"OpenSubtitles candidate {candidate.file_id}",
                )
                if alternate_result is None:
                    self._warn(
                        "No independent timing reference was available for the "
                        "downloaded subtitle."
                    )
                    return _Target(
                        normalized,
                        "OpenSubtitles",
                        False,
                        tuple(candidates),
                        candidate.file_id,
                        target.search_result,
                    )
                if alternate_result.confidence != "low":
                    self._record_candidate(
                        candidate,
                        decision="accepted after timing validation",
                        status="accepted",
                    )
                    return _Target(
                        alternate_result.output_path,
                        "OpenSubtitles",
                        False,
                        tuple(candidates),
                        candidate.file_id,
                        target.search_result,
                    )
                rejected.append(alternate_result.message)
                rejection_reasons[candidate.file_id] = alternate_result.message
                self._record_candidate(
                    candidate,
                    decision=alternate_result.message,
                    status="rejected",
                )
            except OperationCancelled:
                raise
            except Exception as exc:  # noqa: BLE001
                rejected.append(str(exc))
                rejection_reasons[candidate.file_id] = str(exc)
                self._record_candidate(
                    candidate,
                    decision=str(exc),
                    status="rejected",
                )

        detail = rejected[-1] if rejected else (
            result.message if result else "No candidate could be validated."
        )
        if target.search_result:
            review_result = open_subtitles.SubtitleSearchResult(
                query=target.search_result.query,
                candidates=target.search_result.candidates,
                automatic_matches=(),
                matched_by_hash=target.search_result.matched_by_hash,
            )
        else:
            review_result = open_subtitles.SubtitleSearchResult(
                query=video.stem,
                candidates=tuple(candidates),
                automatic_matches=(),
                matched_by_hash=False,
            )
        translation_available = bool(
            options.strategy == "automatic"
            and reference
            and reference.path
            and reference.language_code != "und"
            and options.openai_api_key.strip()
        )
        raise CandidateReviewRequired(
            "No target-language subtitle candidate matched the available "
            f"timing reference. Last result: {detail}",
            review_result,
            allow_translation=translation_available,
            rejection_reasons=rejection_reasons,
        )

    def _sync_target(
        self,
        video: Path,
        target_path: str,
        reference: _Reference | None,
        options: PipelineOptions,
        job_directory: Path,
        label: str,
    ) -> subtitle_sync.SyncResult | None:
        output_path = job_directory / f"synced-{int(time.time_ns())}.srt"
        if reference and Path(reference.path).resolve() != Path(target_path).resolve():
            result = subtitle_sync.sync_to_reference(
                reference.path,
                target_path,
                str(output_path),
            )
            self._record_sync(label, result)
            if result.confidence != "low":
                self._validate_duration(video, result.output_path)
            return result

        image_reference = extractor.extract_image_subtitle_timings(
            str(video),
            preferred_language=options.source_language,
            excluded_language=options.target_language,
        )
        if not image_reference:
            image_reference = extractor.find_external_image_subtitle_timings(
                str(video),
                media_roots=options.media_roots,
            )
        if image_reference:
            cues, reference_label = image_reference
            result = subtitle_sync.sync_to_reference_cues(
                cues,
                target_path,
                str(output_path),
                reference_label=reference_label,
                tolerance_ms=1500,
            )
            self._record_sync(label, result)
            if result.confidence != "low":
                self._validate_duration(video, result.output_path)
            return result

        try:
            activity = audio_activity.extract_activity(
                str(video),
                cache_directory=Path(
                    options.workspace_directory or app_paths.WORKSPACE_DIR
                )
                / "Cache",
                cancellation_token=self.cancellation_token,
            )
        except OperationCancelled:
            raise
        except Exception:
            return None
        if not subtitle_sync.activity_reference_is_informative(activity):
            return None
        result = subtitle_sync.validate_against_activity(
            activity,
            target_path,
            str(output_path),
            reference_label=f"audio activity for {label}",
        )
        self._record_sync(label, result)
        if result.confidence != "low":
            self._validate_duration(video, result.output_path)
        return result

    def _validate_external_reference(
        self,
        video: Path,
        reference_path: str,
        options: PipelineOptions,
        job_directory: Path,
    ) -> str | None:
        image_reference = extractor.extract_image_subtitle_timings(
            str(video),
            preferred_language=options.source_language,
            excluded_language=options.target_language,
        )
        output = job_directory / f"validated-source-{int(time.time_ns())}.srt"
        if image_reference:
            cues, label = image_reference
            result = subtitle_sync.sync_to_reference_cues(
                cues,
                reference_path,
                str(output),
                reference_label=label,
                tolerance_ms=1500,
            )
            self._record_sync("external source subtitle", result)
            if result.confidence == "low":
                return None
            return result.output_path

        try:
            activity = audio_activity.extract_activity(
                str(video),
                cache_directory=Path(
                    options.workspace_directory or app_paths.WORKSPACE_DIR
                )
                / "Cache",
                cancellation_token=self.cancellation_token,
            )
        except OperationCancelled:
            raise
        except Exception:
            self._warn(
                "The external source subtitle could not be independently "
                "validated; its existing timing was retained."
            )
            return reference_path
        if not subtitle_sync.activity_reference_is_informative(activity):
            self._warn(
                "Audio activity was inconclusive for the external source "
                "subtitle; its existing timing was retained."
            )
            return reference_path
        result = subtitle_sync.validate_against_activity(
            activity,
            reference_path,
            str(output),
            reference_label="video audio activity",
        )
        self._record_sync("external source subtitle", result)
        return result.output_path if result.confidence != "low" else None

    def _normalize_subtitle(
        self,
        subtitle_path: str,
        video: Path,
        job_directory: Path,
        filename: str,
    ) -> str:
        normalized = extractor.convert_to_srt(
            subtitle_path,
            output_directory=job_directory,
        )
        try:
            duration_ms = int(round(muxer.media_duration_seconds(video) * 1000))
        except Exception:
            duration_ms = None
        cleaned, report = extractor.remove_probable_promotional_cues(
            normalized,
            video_duration_ms=duration_ms,
            output_directory=job_directory,
        )
        if report.removed_cues:
            self._emit("clean", report.summary(), 46)
        return self._copy_into_job(cleaned, job_directory, filename)

    def _save_final_subtitle(
        self,
        video: Path,
        subtitle_path: str,
        target: languages.LanguageProfile,
        output_directory: Path,
    ) -> str:
        output = app_paths.unique_output_path(
            video,
            output_directory,
            suffix=f" [{target.name}]",
            extension=".srt",
        )
        shutil.copy2(subtitle_path, output)
        return str(output)

    @staticmethod
    def _output_directory(video: Path, options: PipelineOptions) -> Path:
        if options.output_mode == "custom" and options.custom_output_directory:
            output = Path(options.custom_output_directory).expanduser()
        else:
            output = video.parent
        output.mkdir(parents=True, exist_ok=True)
        return output

    @staticmethod
    def _copy_into_job(
        source: str | Path,
        job_directory: Path,
        filename: str,
    ) -> str:
        destination = job_directory / filename
        if Path(source).resolve() != destination.resolve():
            shutil.copy2(source, destination)
        return str(destination)

    @staticmethod
    def _validate_duration(video: Path, subtitle_path: str) -> None:
        cues = subtitle_sync.parse_srt_timings(subtitle_path)
        if not cues:
            raise RuntimeError("Subtitle contains no valid timing cues.")
        video_duration_ms = int(round(muxer.media_duration_seconds(video) * 1000))
        subtitle_end = max(cue.end_ms for cue in cues)
        tolerance = max(120_000, int(video_duration_ms * 0.03))
        if subtitle_end > video_duration_ms + tolerance:
            overrun = (subtitle_end - video_duration_ms) / 1000
            raise RuntimeError(
                f"Subtitle runs {overrun:.1f}s beyond the media and was rejected."
            )

    def _write_job_summary(
        self,
        job_directory: Path,
        video: Path,
        reference: _Reference | None,
        playback_reference: _PlaybackReference | None,
        target: _Target,
        final_subtitle: str,
        merged_path: str,
    ) -> None:
        source_language = (
            reference.language_code
            if reference
            else (
                playback_reference.language_code
                if playback_reference
                else "und"
            )
        )
        summary = {
            "media_filename": video.name,
            "source_language": source_language,
            "playback_reference": (
                playback_reference.label if playback_reference else ""
            ),
            "target_origin": target.origin,
            "final_subtitle_filename": Path(final_subtitle).name if final_subtitle else "",
            "merged_filename": Path(merged_path).name if merged_path else "",
            "warnings": self._warnings,
        }
        path = job_directory / "job.json"
        path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    def _warn(self, message: str) -> None:
        self._warnings.append(message)
        self._emit("warning", message, 0)

    def _emit(
        self,
        stage: str,
        message: str,
        percent: int,
        *,
        check_cancellation: bool = True,
    ) -> None:
        if check_cancellation:
            self._check_cancelled()
        print(message)
        if self.diagnostics_recorder:
            self.diagnostics_recorder.record(
                "pipeline",
                stage,
                message=message,
                percent=max(0, min(100, percent)),
            )
        self.progress(stage, message, max(0, min(100, percent)))

    def _check_cancelled(self) -> None:
        if self.cancellation_token:
            self.cancellation_token.raise_if_cancelled()

    def _record_external_event(
        self,
        provider: str,
        action: str,
        details: dict,
    ) -> None:
        if provider == "openai" and action == "chunk_completed":
            usage = details.get("usage")
            if isinstance(usage, dict):
                self._translation_input_tokens += _safe_int(
                    usage.get("input_tokens")
                )
                self._translation_output_tokens += _safe_int(
                    usage.get("output_tokens")
                )
        if self.diagnostics_recorder:
            self.diagnostics_recorder.record(
                provider,
                action,
                **details,
            )

    def _record_candidate(
        self,
        candidate: open_subtitles.SubtitleCandidate,
        *,
        decision: str,
        status: str = "considered",
    ) -> None:
        if self.diagnostics_recorder:
            self.diagnostics_recorder.record(
                "candidate",
                "decision",
                status=status,
                file_id=candidate.file_id,
                release_name=candidate.release_name,
                file_name=candidate.file_name,
                trusted=candidate.trusted,
                rating=candidate.rating,
                decision=decision,
            )

    def _record_sync(
        self,
        label: str,
        result: subtitle_sync.SyncResult,
    ) -> None:
        if self.diagnostics_recorder:
            self.diagnostics_recorder.record(
                "timing",
                "validation",
                status=(
                    "accepted"
                    if result.confidence != "low"
                    else "rejected"
                ),
                label=label,
                method=result.method,
                confidence=result.confidence,
                applied=result.applied,
                offset_ms=result.offset_ms,
                scale=result.scale,
                median_error_ms=result.median_error_ms,
                p80_error_ms=result.p80_error_ms,
                match_ratio=result.match_ratio,
                coverage_ratio=result.coverage_ratio,
                local_spread_ms=result.local_spread_ms,
                max_local_jump_ms=result.max_local_jump_ms,
                discontinuity=result.discontinuity,
                message=result.message,
            )

    def _update_diagnostics_summary(self, **values: object) -> None:
        if self.diagnostics_recorder:
            self.diagnostics_recorder.update_summary(**values)


def _new_job_directory(workspace: Path, video: Path) -> Path:
    root = workspace / "Subtitles"
    root.mkdir(parents=True, exist_ok=True)
    safe_stem = "".join(
        character if character.isalnum() or character in " ._-" else "_"
        for character in video.stem
    ).strip()[:80]
    directory = Path(
        tempfile.mkdtemp(
            prefix=f"{safe_stem or 'Media'}-",
            dir=root,
        )
    )
    return directory


def _safe_int(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0
