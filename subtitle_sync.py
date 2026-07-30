"""Lightweight SRT timing checks and correction."""

from __future__ import annotations

import math
import re
import shutil
import bisect
from dataclasses import dataclass
from pathlib import Path


_TIMESTAMP_RE = re.compile(
    r"(?P<start>\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})"
    r"(?P<middle>\s*-->\s*)"
    r"(?P<end>\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})"
    r"(?P<suffix>.*)"
)
_MIN_CORRECTABLE_OFFSET_MS = 80
_MICRO_OFFSET_CEILING_MS = 250
_MICRO_TARGET_MEDIAN_ERROR_MS = 50
_MICRO_MAX_LOCAL_RESIDUAL_MS = 100


@dataclass(frozen=True)
class CueTiming:
    """Start/end timing for one subtitle cue, in milliseconds."""

    start_ms: int
    end_ms: int


@dataclass(frozen=True)
class SyncResult:
    """Result of a timing sync attempt."""

    output_path: str
    applied: bool
    method: str
    message: str
    confidence: str
    offset_ms: int = 0
    scale: float = 1.0


@dataclass(frozen=True)
class _AlignmentStats:
    """Quality of a timing transform against the reference subtitle."""

    confidence: str
    median_error_ms: float
    p80_error_ms: float
    match_ratio: float
    unique_reference_ratio: float
    coverage_ratio: float
    edge_match_ratio: float


@dataclass(frozen=True)
class _TransformCandidate:
    """A possible timing transform and its alignment quality."""

    scale: float
    offset_ms: float
    stats: _AlignmentStats


@dataclass(frozen=True)
class _LocalOffsetProfile:
    """Reliable local offset estimates sampled across the subtitle runtime."""

    offsets: tuple[tuple[int, float], ...]
    max_jump_ms: float
    spread_ms: float
    discontinuity: bool


def sync_to_reference(reference_srt: str, subtitle_srt: str, output_path: str) -> SyncResult:
    """
    Align *subtitle_srt* timing to *reference_srt* and write *output_path*.

    The reference should be a local subtitle from the exact media release.
    The candidate subtitle should already be SRT. This function
    compares cue timing neighborhoods across the whole runtime, then applies
    either:

    * no change, when timing already appears aligned;
    * a constant offset, when all cues are shifted similarly;
    * a linear stretch/offset, when drift is detected across the episode.

    If the evidence is weak, the subtitle is copied unchanged and the result
    reports ``confidence="low"``.
    """
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    try:
        reference_cues = parse_srt_timings(reference_srt)
    except OSError as exc:
        shutil.copy2(subtitle_srt, output)
        return SyncResult(str(output), False, "copy", f"Timing check skipped: {exc}", "low")

    return sync_to_reference_cues(
        reference_cues,
        subtitle_srt,
        output_path,
        reference_label="subtitle reference",
    )


def sync_to_reference_cues(
    reference_cues: list[CueTiming],
    subtitle_srt: str,
    output_path: str,
    reference_label: str = "timing reference",
    tolerance_ms: int = 1000,
) -> SyncResult:
    """
    Align *subtitle_srt* timing to a non-text cue reference.

    This is used for references such as embedded PGS subtitle packet timings
    where the text is unavailable but cue times are still useful.
    """
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    try:
        subtitle_cues = parse_srt_timings(subtitle_srt)
    except OSError as exc:
        shutil.copy2(subtitle_srt, output)
        return SyncResult(str(output), False, "copy", f"Timing check skipped: {exc}", "low")

    if len(reference_cues) < 5 or len(subtitle_cues) < 5:
        shutil.copy2(subtitle_srt, output)
        return SyncResult(
            str(output),
            False,
            "copy",
            "Timing check skipped: not enough subtitle cues to compare.",
            "low",
        )

    transform = _estimate_transform(reference_cues, subtitle_cues, tolerance_ms)
    if transform is None:
        shutil.copy2(subtitle_srt, output)
        return SyncResult(
            str(output),
            False,
            "copy",
            f"Timing uncertain: subtitle pattern differs too much from the {reference_label}.",
            "low",
        )

    (
        scale,
        offset,
        confidence,
        residual_ms,
        has_discontinuity,
        original_residual_ms,
    ) = transform
    if has_discontinuity:
        shutil.copy2(subtitle_srt, output)
        return SyncResult(
            str(output),
            False,
            "copy",
            (
                "Timing rejected: local subtitle timing changes abruptly "
                f"relative to the {reference_label}."
            ),
            "low",
            int(round(offset)),
            scale,
        )

    needs_scale = abs(scale - 1.0) >= 0.001
    needs_offset = abs(offset) >= _MIN_CORRECTABLE_OFFSET_MS

    if not needs_scale and not needs_offset:
        shutil.copy2(subtitle_srt, output)
        return SyncResult(
            str(output),
            False,
            "already-aligned",
            f"Timing appears aligned (median error about {residual_ms:.0f} ms).",
            confidence,
            int(round(offset)),
            scale,
        )

    if confidence == "low":
        shutil.copy2(subtitle_srt, output)
        return SyncResult(
            str(output),
            False,
            "copy",
            "Timing uncertain: leaving subtitle unchanged.",
            confidence,
            int(round(offset)),
            scale,
        )

    _write_transformed_srt(subtitle_srt, output, scale, offset)
    method = "linear drift correction" if needs_scale else "constant offset"
    return SyncResult(
        str(output),
        True,
        method,
        _format_correction_message(
            method,
            scale,
            offset,
            residual_ms,
            original_residual_ms,
        ),
        confidence,
        int(round(offset)),
        scale,
    )


def parse_srt_timings(srt_path: str) -> list[CueTiming]:
    """Parse cue timing lines from an SRT file."""
    cues: list[CueTiming] = []
    for line in Path(srt_path).read_text(encoding="utf-8-sig").splitlines():
        match = _TIMESTAMP_RE.match(line.strip())
        if not match:
            continue
        cues.append(
            CueTiming(
                _timestamp_to_ms(match.group("start")),
                _timestamp_to_ms(match.group("end")),
            )
        )
    return cues


def validate_against_activity(
    activity_cues: list[CueTiming],
    subtitle_srt: str,
    output_path: str,
    reference_label: str = "audio activity",
) -> SyncResult:
    """
    Validate subtitle cue placement against coarse audio activity.

    Unlike subtitle-to-subtitle sync, this does not rewrite timestamps. The
    audio activity signal is too coarse to be a safe timing editor, but it can
    still reject obvious wrong cuts before muxing.
    """
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    try:
        subtitle_cues = parse_srt_timings(subtitle_srt)
    except OSError as exc:
        shutil.copy2(subtitle_srt, output)
        return SyncResult(str(output), False, "copy", f"Timing check skipped: {exc}", "low")

    if len(activity_cues) < 5 or len(subtitle_cues) < 5:
        shutil.copy2(subtitle_srt, output)
        return SyncResult(
            str(output),
            False,
            "copy",
            "Timing check skipped: not enough audio/subtitle activity to compare.",
            "low",
        )

    if not activity_reference_is_informative(activity_cues):
        shutil.copy2(subtitle_srt, output)
        return SyncResult(
            str(output),
            False,
            "copy",
            "Timing check skipped: audio activity is too dense or sparse to be reliable.",
            "low",
        )

    stats = _activity_stats(activity_cues, subtitle_cues)
    shutil.copy2(subtitle_srt, output)
    if stats.confidence == "low":
        return SyncResult(
            str(output),
            False,
            "copy",
            f"Timing uncertain: subtitle cues do not match the {reference_label}.",
            "low",
        )

    return SyncResult(
        str(output),
        False,
        "audio-validated",
        (
            f"Timing appears consistent with {reference_label} "
            f"({stats.match_ratio:.0%} of cues overlap, "
            f"{stats.coverage_ratio:.0%} timeline coverage)."
        ),
        stats.confidence,
    )


def activity_reference_is_informative(activity_cues: list[CueTiming]) -> bool:
    """Return whether coarse audio activity can meaningfully validate subtitles."""
    if len(activity_cues) < 5:
        return False

    activity_segments = _merge_segments(
        [
            CueTiming(max(0, cue.start_ms - 750), cue.end_ms + 750)
            for cue in activity_cues
            if cue.end_ms > cue.start_ms
        ]
    )
    if len(activity_segments) < 3:
        return False

    active_span = max(1, activity_segments[-1].end_ms - activity_segments[0].start_ms)
    active_duration = sum(cue.end_ms - cue.start_ms for cue in activity_segments)
    active_ratio = active_duration / active_span
    return 0.08 <= active_ratio <= 0.82


def _estimate_transform(
    reference_cues: list[CueTiming],
    subtitle_cues: list[CueTiming],
    tolerance_ms: int = 1000,
) -> tuple[float, float, str, float, bool, float] | None:
    """Estimate ``reference_ms = scale * subtitle_ms + offset``."""
    reference_starts = sorted(cue.start_ms for cue in reference_cues)
    subtitle_starts = sorted(cue.start_ms for cue in subtitle_cues)

    candidates: list[_TransformCandidate] = []

    # Evaluate no-shift, but do not accept it until plausible corrections have
    # also been scored. Dense dialogue can make a shifted subtitle look close to
    # neighboring cues even when a constant offset would be much better.
    no_shift_stats = _alignment_stats(
        reference_starts,
        subtitle_starts,
        1.0,
        0.0,
        tolerance_ms,
    )
    no_shift_candidate: _TransformCandidate | None = None
    if no_shift_stats.confidence != "low":
        no_shift_candidate = _TransformCandidate(1.0, 0.0, no_shift_stats)
        candidates.append(no_shift_candidate)

    # Try constant offsets found by timestamp-neighborhood histograms.
    offset_candidates = _candidate_offsets(reference_starts, subtitle_starts)
    for offset in offset_candidates:
        stats = _alignment_stats(reference_starts, subtitle_starts, 1.0, offset, tolerance_ms)
        if stats.confidence == "low":
            continue
        candidates.append(_TransformCandidate(1.0, offset, stats))

    # Finally try a linear correction. The ordinal fit only proposes a
    # transform; it still has to pass the timestamp-neighborhood quality gate.
    ordinal = _estimate_ordinal_transform(reference_cues, subtitle_cues)
    if ordinal is not None:
        scale, offset = ordinal
        stats = _alignment_stats(reference_starts, subtitle_starts, scale, offset, tolerance_ms)
        if stats.confidence != "low":
            candidates.append(_TransformCandidate(scale, offset, stats))

    if not candidates:
        return None

    best_candidate = max(candidates, key=_transform_candidate_rank)
    if (
        no_shift_candidate is not None
        and not _is_no_shift_candidate(best_candidate)
        and not _correction_clearly_better(best_candidate, no_shift_candidate)
    ):
        best_candidate = no_shift_candidate

    stats = best_candidate.stats
    local_profile = _local_offset_profile(
        reference_starts,
        subtitle_starts,
        best_candidate.scale,
        best_candidate.offset_ms,
        tolerance_ms,
    )
    if (
        no_shift_candidate is not None
        and abs(best_candidate.scale - 1.0) < 0.001
        and _MIN_CORRECTABLE_OFFSET_MS
        <= abs(best_candidate.offset_ms)
        < _MICRO_OFFSET_CEILING_MS
        and not _micro_offset_is_reliable(
            best_candidate,
            no_shift_candidate,
            local_profile,
        )
    ):
        best_candidate = no_shift_candidate
        stats = best_candidate.stats
        local_profile = _local_offset_profile(
            reference_starts,
            subtitle_starts,
            best_candidate.scale,
            best_candidate.offset_ms,
            tolerance_ms,
        )

    original_residual_ms = (
        no_shift_stats.median_error_ms
        if no_shift_stats.confidence != "low"
        else float("inf")
    )
    return (
        best_candidate.scale,
        best_candidate.offset_ms,
        stats.confidence,
        stats.median_error_ms,
        bool(local_profile and local_profile.discontinuity),
        original_residual_ms,
    )


def _local_offset_profile(
    reference_starts: list[int],
    subtitle_starts: list[int],
    scale: float,
    offset_ms: float,
    tolerance_ms: int,
    window_count: int = 8,
) -> _LocalOffsetProfile | None:
    """Estimate local residual offsets and flag abrupt cut changes.

    A global offset or frame-rate correction should leave roughly the same
    residual throughout the runtime. Inserted scenes, removed scenes, and
    commercial-cut differences instead produce stable but different offset
    bands. Timing-only comparisons can be noisy, so only dominant local
    histogram peaks are used.
    """
    if len(reference_starts) < 24 or len(subtitle_starts) < 24:
        return None

    window_count = min(window_count, max(4, len(subtitle_starts) // 8))
    search_radius_ms = max(15_000, tolerance_ms * 8)
    bin_size_ms = 250
    reliable_offsets: list[tuple[int, float]] = []

    for window_index in range(window_count):
        start_index = round(window_index * len(subtitle_starts) / window_count)
        end_index = round((window_index + 1) * len(subtitle_starts) / window_count)
        window = subtitle_starts[start_index:end_index]
        sampled = _sample_evenly(window, 40)
        if len(sampled) < 6:
            continue

        bins: dict[int, list[float]] = {}
        for subtitle_ms in sampled:
            transformed = scale * subtitle_ms + offset_ms
            lo = bisect.bisect_left(reference_starts, transformed - search_radius_ms)
            hi = bisect.bisect_right(reference_starts, transformed + search_radius_ms)

            # Count at most one reference from each residual bin for a cue.
            cue_bins: dict[int, float] = {}
            for reference_ms in reference_starts[lo:hi]:
                residual = float(reference_ms - transformed)
                bin_id = round(residual / bin_size_ms)
                previous = cue_bins.get(bin_id)
                bin_center = bin_id * bin_size_ms
                if previous is None or abs(residual - bin_center) < abs(previous - bin_center):
                    cue_bins[bin_id] = residual
            for bin_id, residual in cue_bins.items():
                bins.setdefault(bin_id, []).append(residual)

        if not bins:
            continue
        ranked = sorted(bins.values(), key=len, reverse=True)
        best = ranked[0]
        second_count = len(ranked[1]) if len(ranked) > 1 else 0
        minimum_support = max(5, math.ceil(len(sampled) * 0.45))
        if len(best) < minimum_support:
            continue
        if second_count and len(best) < second_count * 1.10:
            continue
        reliable_offsets.append((window_index, _median(best)))

    if len(reliable_offsets) < 4:
        return None

    values = [value for _, value in reliable_offsets]
    spread_ms = _percentile(values, 0.90) - _percentile(values, 0.10)
    max_jump_ms = max(
        (
            abs(right_value - left_value)
            for (left_index, left_value), (right_index, right_value)
            in zip(reliable_offsets, reliable_offsets[1:])
            if right_index - left_index <= 2
        ),
        default=0.0,
    )

    discontinuity = False
    if spread_ms >= 1_800:
        for split in range(2, len(reliable_offsets) - 1):
            left = reliable_offsets[max(0, split - 2):split]
            right = reliable_offsets[split:min(len(reliable_offsets), split + 2)]
            if len(left) < 2 or len(right) < 2:
                continue
            if right[0][0] - left[-1][0] > 2:
                continue
            left_values = [value for _, value in left]
            right_values = [value for _, value in right]
            if max(left_values) - min(left_values) > 900:
                continue
            if max(right_values) - min(right_values) > 900:
                continue
            if abs(_median(left_values) - _median(right_values)) >= 1_800:
                discontinuity = True
                break

    return _LocalOffsetProfile(
        tuple(reliable_offsets),
        max_jump_ms,
        spread_ms,
        discontinuity,
    )


def _estimate_ordinal_transform(
    reference_cues: list[CueTiming],
    subtitle_cues: list[CueTiming],
) -> tuple[float, float] | None:
    """Use ordinal positions only to propose a possible drift transform."""
    count_ratio = len(subtitle_cues) / len(reference_cues)
    if count_ratio < 0.45 or count_ratio > 2.2:
        return None

    sample_count = min(30, len(reference_cues), len(subtitle_cues))
    if sample_count < 5:
        return None

    pairs: list[tuple[float, float]] = []
    for i in range(sample_count):
        ref_idx = round(i * (len(reference_cues) - 1) / (sample_count - 1))
        sub_idx = round(i * (len(subtitle_cues) - 1) / (sample_count - 1))
        pairs.append(
            (
                float(subtitle_cues[sub_idx].start_ms),
                float(reference_cues[ref_idx].start_ms),
            )
        )

    scale, offset = _linear_fit(pairs)
    if not 0.90 <= scale <= 1.10:
        return None
    return scale, offset


def _candidate_offsets(
    reference_starts: list[int],
    subtitle_starts: list[int],
) -> list[float]:
    """Find plausible constant offsets from dense timestamp difference bins."""
    sampled_subtitles = _sample_evenly(subtitle_starts, 180)
    max_offset_ms = 10 * 60 * 1000
    bin_size_ms = 500
    bins: dict[int, list[int]] = {}

    for sub_ms in sampled_subtitles:
        lo = bisect.bisect_left(reference_starts, sub_ms - max_offset_ms)
        hi = bisect.bisect_right(reference_starts, sub_ms + max_offset_ms)
        for ref_ms in reference_starts[lo:hi]:
            diff = ref_ms - sub_ms
            bin_id = round(diff / bin_size_ms)
            bins.setdefault(bin_id, []).append(diff)

    if not bins:
        return []

    ranked_bins = sorted(
        bins.values(),
        key=lambda values: (len(values), -abs(_median([float(v) for v in values]))),
        reverse=True,
    )
    offsets: list[float] = []
    for values in ranked_bins[:12]:
        if len(values) < max(5, len(sampled_subtitles) * 0.04):
            continue
        offset = _median([float(value) for value in values])
        if abs(offset) < _MIN_CORRECTABLE_OFFSET_MS:
            continue
        offsets.append(offset)
    return offsets


def _alignment_stats(
    reference_starts: list[int],
    subtitle_starts: list[int],
    scale: float,
    offset_ms: float,
    tolerance_ms: int = 1000,
) -> _AlignmentStats:
    """Score how many transformed subtitle cues land near reference cues."""
    matched_errors: list[float] = []
    matched_reference_indices: set[int] = set()
    segment_totals = [0, 0, 0, 0, 0]
    segment_matches = [0, 0, 0, 0, 0]

    if not reference_starts or not subtitle_starts:
        return _low_alignment()

    transformed_starts = [scale * value + offset_ms for value in subtitle_starts]
    span_start = min(transformed_starts)
    span_end = max(transformed_starts)
    span = max(1.0, span_end - span_start)

    for transformed in transformed_starts:
        segment = min(4, max(0, int(((transformed - span_start) / span) * 5)))
        segment_totals[segment] += 1

        nearest = _nearest_distance(reference_starts, transformed)
        if nearest is None:
            continue
        distance, ref_index = nearest
        if distance <= tolerance_ms:
            matched_errors.append(distance)
            matched_reference_indices.add(ref_index)
            segment_matches[segment] += 1

    if not matched_errors:
        return _low_alignment()

    match_ratio = len(matched_errors) / len(subtitle_starts)
    unique_reference_ratio = len(matched_reference_indices) / len(reference_starts)
    covered_segments = 0
    nonempty_segments = 0
    for total, matched in zip(segment_totals, segment_matches):
        if total == 0:
            continue
        nonempty_segments += 1
        if matched / total >= 0.30:
            covered_segments += 1
    coverage_ratio = covered_segments / max(1, nonempty_segments)
    segment_ratios = [
        matched / total
        for total, matched in zip(segment_totals, segment_matches)
        if total > 0
    ]
    edge_match_ratio = min(segment_ratios[0], segment_ratios[-1]) if segment_ratios else 0.0

    median_error = _median(matched_errors)
    p80_error = _percentile(matched_errors, 0.80)

    if (
        match_ratio >= 0.60
        and unique_reference_ratio >= 0.48
        and coverage_ratio >= 0.80
        and edge_match_ratio >= 0.30
        and median_error <= 500
        and p80_error <= 900
    ):
        confidence = "high"
    elif (
        match_ratio >= 0.42
        and unique_reference_ratio >= 0.34
        and coverage_ratio >= 0.60
        and edge_match_ratio >= 0.30
        and median_error <= 800
        and p80_error <= 1200
    ):
        confidence = "medium"
    else:
        confidence = "low"

    return _AlignmentStats(
        confidence,
        median_error,
        p80_error,
        match_ratio,
        unique_reference_ratio,
        coverage_ratio,
        edge_match_ratio,
    )


def _activity_stats(
    activity_cues: list[CueTiming],
    subtitle_cues: list[CueTiming],
    padding_ms: int = 750,
) -> _AlignmentStats:
    """Score whether subtitle cues overlap coarse audio activity segments."""
    activity_segments = _merge_segments(
        [
            CueTiming(
                max(0, cue.start_ms - padding_ms),
                cue.end_ms + padding_ms,
            )
            for cue in activity_cues
            if cue.end_ms > cue.start_ms
        ]
    )
    subtitle_segments = [
        cue for cue in subtitle_cues if cue.end_ms > cue.start_ms
    ]
    if not activity_segments or not subtitle_segments:
        return _low_alignment()

    active_span = max(1, activity_segments[-1].end_ms - activity_segments[0].start_ms)
    active_duration = sum(cue.end_ms - cue.start_ms for cue in activity_segments)
    active_ratio = active_duration / active_span
    if active_ratio > 0.82:
        return _low_alignment()

    matched = 0
    segment_totals = [0, 0, 0, 0, 0]
    segment_matches = [0, 0, 0, 0, 0]
    span_start = min(cue.start_ms for cue in subtitle_segments)
    span_end = max(cue.end_ms for cue in subtitle_segments)
    span = max(1, span_end - span_start)

    activity_index = 0
    for cue in subtitle_segments:
        segment = min(4, max(0, int(((cue.start_ms - span_start) / span) * 5)))
        segment_totals[segment] += 1

        while (
            activity_index < len(activity_segments)
            and activity_segments[activity_index].end_ms < cue.start_ms
        ):
            activity_index += 1

        if _overlaps_activity(activity_segments, activity_index, cue):
            matched += 1
            segment_matches[segment] += 1

    if matched == 0:
        return _low_alignment()

    match_ratio = matched / len(subtitle_segments)
    covered_segments = 0
    nonempty_segments = 0
    for total, segment_match in zip(segment_totals, segment_matches):
        if total == 0:
            continue
        nonempty_segments += 1
        if segment_match / total >= 0.45:
            covered_segments += 1
    coverage_ratio = covered_segments / max(1, nonempty_segments)
    segment_ratios = [
        segment_match / total
        for total, segment_match in zip(segment_totals, segment_matches)
        if total > 0
    ]
    edge_match_ratio = min(segment_ratios[0], segment_ratios[-1]) if segment_ratios else 0.0

    if match_ratio >= 0.74 and coverage_ratio >= 0.80 and edge_match_ratio >= 0.55:
        confidence = "high"
    elif match_ratio >= 0.62 and coverage_ratio >= 0.60 and edge_match_ratio >= 0.45:
        confidence = "medium"
    else:
        confidence = "low"

    return _AlignmentStats(
        confidence,
        0.0,
        0.0,
        match_ratio,
        match_ratio,
        coverage_ratio,
        edge_match_ratio,
    )


def _merge_segments(cues: list[CueTiming], max_gap_ms: int = 250) -> list[CueTiming]:
    """Merge overlapping or near-adjacent timing segments."""
    if not cues:
        return []

    merged: list[CueTiming] = []
    for cue in sorted(cues, key=lambda item: (item.start_ms, item.end_ms)):
        if not merged or cue.start_ms > merged[-1].end_ms + max_gap_ms:
            merged.append(cue)
            continue
        previous = merged[-1]
        merged[-1] = CueTiming(previous.start_ms, max(previous.end_ms, cue.end_ms))
    return merged


def _overlaps_activity(
    activity_segments: list[CueTiming],
    start_index: int,
    cue: CueTiming,
) -> bool:
    """Return true when *cue* overlaps activity near *start_index*."""
    for index in range(max(0, start_index - 1), min(len(activity_segments), start_index + 2)):
        activity = activity_segments[index]
        if activity.start_ms <= cue.end_ms and activity.end_ms >= cue.start_ms:
            return True
    return False


def _nearest_distance(
    reference_starts: list[int],
    value: float,
) -> tuple[float, int] | None:
    """Return ``(absolute_distance, index)`` for the nearest reference start."""
    if not reference_starts:
        return None
    index = bisect.bisect_left(reference_starts, value)
    options = []
    if index < len(reference_starts):
        options.append((abs(reference_starts[index] - value), index))
    if index > 0:
        options.append((abs(reference_starts[index - 1] - value), index - 1))
    if not options:
        return None
    return min(options, key=lambda item: item[0])


def _sample_evenly(values: list[int], max_count: int) -> list[int]:
    """Return up to *max_count* values sampled across the full list."""
    if len(values) <= max_count:
        return values
    return [
        values[round(index * (len(values) - 1) / (max_count - 1))]
        for index in range(max_count)
    ]


def _confidence_rank(confidence: str) -> int:
    return {"low": 0, "medium": 1, "high": 2}.get(confidence, 0)


def _transform_candidate_rank(
    candidate: _TransformCandidate,
) -> tuple[int, float, float, float, float, float, float, float]:
    """Rank timing transforms by full-cue coverage before residual error."""
    stats = candidate.stats
    correction_penalty = abs(candidate.offset_ms) / 1_000_000 + abs(candidate.scale - 1.0)
    return (
        _confidence_rank(stats.confidence),
        stats.match_ratio,
        stats.unique_reference_ratio,
        stats.coverage_ratio,
        stats.edge_match_ratio,
        -stats.p80_error_ms,
        -stats.median_error_ms,
        -correction_penalty,
    )


def _is_no_shift_candidate(candidate: _TransformCandidate) -> bool:
    return (
        abs(candidate.offset_ms) < _MIN_CORRECTABLE_OFFSET_MS
        and abs(candidate.scale - 1.0) < 0.001
    )


def _correction_clearly_better(
    candidate: _TransformCandidate,
    baseline: _TransformCandidate,
) -> bool:
    """Return true only when a correction materially improves no-shift timing."""
    corrected = candidate.stats
    unshifted = baseline.stats

    if _confidence_rank(corrected.confidence) > _confidence_rank(unshifted.confidence):
        return True

    match_gain = corrected.match_ratio - unshifted.match_ratio
    unique_gain = corrected.unique_reference_ratio - unshifted.unique_reference_ratio
    p80_gain = unshifted.p80_error_ms - corrected.p80_error_ms

    if match_gain >= 0.15:
        return True
    if match_gain >= 0.08 and p80_gain >= 200:
        return True
    if unique_gain >= 0.12 and p80_gain >= 200:
        return True
    if (
        corrected.p80_error_ms <= unshifted.p80_error_ms * 0.55
        and corrected.match_ratio >= unshifted.match_ratio - 0.02
    ):
        return True

    return False


def _micro_offset_is_reliable(
    corrected: _TransformCandidate,
    baseline: _TransformCandidate,
    local_profile: _LocalOffsetProfile | None,
) -> bool:
    """Require unusually strong evidence before rewriting a sub-250 ms offset."""
    corrected_stats = corrected.stats
    baseline_stats = baseline.stats
    if corrected_stats.confidence != "high" or local_profile is None:
        return False
    if local_profile.discontinuity or len(local_profile.offsets) < 4:
        return False

    median_gain = (
        baseline_stats.median_error_ms - corrected_stats.median_error_ms
    )
    p80_gain = baseline_stats.p80_error_ms - corrected_stats.p80_error_ms
    if corrected_stats.median_error_ms > _MICRO_TARGET_MEDIAN_ERROR_MS:
        return False
    if median_gain < _MIN_CORRECTABLE_OFFSET_MS or p80_gain < 50:
        return False
    if corrected_stats.p80_error_ms > max(
        150,
        baseline_stats.p80_error_ms * 0.65,
    ):
        return False
    if corrected_stats.match_ratio < baseline_stats.match_ratio - 0.01:
        return False
    if corrected_stats.unique_reference_ratio < (
        baseline_stats.unique_reference_ratio - 0.01
    ):
        return False

    local_residuals = [residual for _, residual in local_profile.offsets]
    if max(abs(residual) for residual in local_residuals) > (
        _MICRO_MAX_LOCAL_RESIDUAL_MS
    ):
        return False
    if local_profile.spread_ms > _MICRO_MAX_LOCAL_RESIDUAL_MS:
        return False
    if local_profile.max_jump_ms > _MICRO_MAX_LOCAL_RESIDUAL_MS:
        return False
    return True


def _low_alignment() -> _AlignmentStats:
    return _AlignmentStats("low", float("inf"), float("inf"), 0.0, 0.0, 0.0, 0.0)


def _linear_fit(pairs: list[tuple[float, float]]) -> tuple[float, float]:
    """Least-squares fit for ``y = scale * x + offset``."""
    xs = [x for x, _ in pairs]
    ys = [y for _, y in pairs]
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in pairs)
    denominator = sum((x - mean_x) ** 2 for x in xs)
    if math.isclose(denominator, 0.0):
        return 1.0, mean_y - mean_x
    scale = numerator / denominator
    offset = mean_y - scale * mean_x
    return scale, offset


def _write_transformed_srt(
    subtitle_srt: str,
    output_path: Path,
    scale: float,
    offset_ms: float,
) -> None:
    """Write an SRT file with transformed timestamps."""
    lines = []
    for line in Path(subtitle_srt).read_text(encoding="utf-8-sig").splitlines():
        match = _TIMESTAMP_RE.match(line.strip())
        if not match:
            lines.append(line)
            continue

        start_ms = _transform_ms(_timestamp_to_ms(match.group("start")), scale, offset_ms)
        end_ms = _transform_ms(_timestamp_to_ms(match.group("end")), scale, offset_ms)
        if end_ms <= start_ms:
            end_ms = start_ms + 500

        lines.append(
            f"{_ms_to_timestamp(start_ms)}{match.group('middle')}"
            f"{_ms_to_timestamp(end_ms)}{match.group('suffix')}"
        )

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _transform_ms(value: int, scale: float, offset_ms: float) -> int:
    """Apply the timing transform and clamp to zero."""
    return max(0, int(round(scale * value + offset_ms)))


def _timestamp_to_ms(timestamp: str) -> int:
    """Convert an SRT timestamp to milliseconds."""
    hours, minutes, rest = timestamp.replace(".", ",").split(":")
    seconds, millis = rest.split(",")
    millis = millis.ljust(3, "0")[:3]
    return (
        int(hours) * 3_600_000
        + int(minutes) * 60_000
        + int(seconds) * 1_000
        + int(millis)
    )


def _ms_to_timestamp(value: int) -> str:
    """Convert milliseconds to an SRT timestamp."""
    hours, remainder = divmod(value, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1_000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{millis:03}"


def _median(values: list[float]) -> float:
    """Return the median of *values*."""
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def _percentile(values: list[float], percentile: float) -> float:
    """Return an interpolated percentile for *values*."""
    ordered = sorted(values)
    if not ordered:
        return 0.0
    idx = (len(ordered) - 1) * percentile
    lower = math.floor(idx)
    upper = math.ceil(idx)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] * (upper - idx) + ordered[upper] * (idx - lower)


def _format_correction_message(
    method: str,
    scale: float,
    offset_ms: float,
    residual_ms: float,
    original_residual_ms: float,
) -> str:
    """Build a concise log message for an applied correction."""
    offset_s = offset_ms / 1000
    if method == "constant offset":
        message = f"Applied subtitle sync: shifted by {offset_s:+.2f}s."
        if (
            math.isfinite(original_residual_ms)
            and original_residual_ms > residual_ms
        ):
            message += (
                " Median timing difference improved from "
                f"{original_residual_ms:.0f} ms to {residual_ms:.0f} ms."
            )
        return message
    return (
        "Applied subtitle sync: "
        f"scale={scale:.6f}, offset={offset_s:+.2f}s "
        f"(median error about {residual_ms:.0f} ms)."
    )
