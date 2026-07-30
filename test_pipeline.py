"""
test_pipeline.py - Tests for the subtitle translation pipeline.

Runs automated tests against chunker.py using a synthetic SRT file,
then prints a clear PASS/FAIL summary.

Usage:
    python test_pipeline.py
"""

import os
import json
import sys
import tempfile
from types import SimpleNamespace
from pathlib import Path

import app_paths
import chunker
import extractor
import media_launcher
import muxer
import open_subtitles
import pipeline
import subtitle_sync


# ── Synthetic test data ────────────────────────────────────────────────────────

# 10 subtitle blocks with realistic anime-style English dialogue.
SYNTHETIC_SRT = """\
1
00:00:05,000 --> 00:00:07,500
Wait... is that the demon lord's castle?

2
00:00:08,000 --> 00:00:10,200
I can sense an overwhelming aura from here.

3
00:00:12,400 --> 00:00:15,100
Ryou! Get back, it's too dangerous!

4
00:00:16,000 --> 00:00:18,800
I know. But if we don't stop him now,
the whole village will be destroyed.

5
00:00:20,000 --> 00:00:22,500
Then we go together. That was always the plan.

6
00:00:24,100 --> 00:00:26,900
Heh. You never change, do you, Yuki?

7
00:00:28,000 --> 00:00:30,400
Ready your mana. The barrier will drop in ten seconds.

8
00:00:32,500 --> 00:00:35,000
This power... it's incredible. Is this what S-rank feels like?

9
00:00:37,200 --> 00:00:39,800
Focus! Here he comes!

10
00:00:41,000 --> 00:00:44,500
Even if I fall here, protect the others.
That's an order, Ryou.

"""


# ── Helper utilities ───────────────────────────────────────────────────────────

def _write_temp_srt(content: str) -> str:
    """Write *content* to a temporary .srt file and return its path."""
    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".srt",
        delete=False,
        encoding="utf-8",
    )
    tmp.write(content)
    tmp.flush()
    tmp.close()
    return tmp.name


def _normalise_srt(srt_text: str) -> list[tuple[str, str, str]]:
    """
    Parse an SRT string into (index, timestamp, text) tuples for comparison.

    This is used to compare SRT content while ignoring trivial formatting
    differences such as trailing whitespace or renumbered indices.

    Args:
        srt_text: Raw SRT content.

    Returns:
        List of (index, timestamp, text) tuples, one per subtitle block.
    """
    blocks = chunker._parse_srt_blocks(srt_text)
    result = []
    for block in blocks:
        if len(block) < 2:
            continue
        index = block[0].strip()
        timestamp = block[1].strip()
        text = "\n".join(line.strip() for line in block[2:])
        result.append((index, timestamp, text))
    return result


# ── Individual test functions ──────────────────────────────────────────────────

def test_chunk_count_default() -> tuple[bool, str]:
    """
    Verify that a 10-block SRT fits in a single chunk at the default limit.

    With max_lines_per_chunk=200, all 10 blocks should land in one chunk.
    """
    srt_path = _write_temp_srt(SYNTHETIC_SRT)
    try:
        chunks = chunker.chunk_srt(srt_path, max_lines_per_chunk=200)
        if len(chunks) != 1:
            return False, f"Expected 1 chunk, got {len(chunks)}"
        return True, "10 blocks → 1 chunk at limit=200"
    finally:
        os.unlink(srt_path)


def test_chunk_count_small_limit() -> tuple[bool, str]:
    """
    Verify chunking with a limit of 3 blocks produces the correct number of chunks.

    10 blocks ÷ 3 per chunk = 4 chunks (3+3+3+1).
    """
    srt_path = _write_temp_srt(SYNTHETIC_SRT)
    try:
        chunks = chunker.chunk_srt(srt_path, max_lines_per_chunk=3)
        expected = 4  # ceil(10 / 3)
        if len(chunks) != expected:
            return False, f"Expected {expected} chunks, got {len(chunks)}"
        return True, f"10 blocks → {expected} chunks at limit=3"
    finally:
        os.unlink(srt_path)


def test_no_block_is_split() -> tuple[bool, str]:
    """
    Verify that no subtitle block is split across a chunk boundary.

    Each block must appear completely in exactly one chunk.
    """
    srt_path = _write_temp_srt(SYNTHETIC_SRT)
    try:
        # Use limit=3 to create multiple chunks and exercise boundaries
        chunks = chunker.chunk_srt(srt_path, max_lines_per_chunk=3)
        for i, chunk in enumerate(chunks):
            blocks = chunker._parse_srt_blocks(chunk)
            for block in blocks:
                # Every block must have at least: index + timestamp + one text line
                if len(block) < 3:
                    return (
                        False,
                        f"Chunk {i+1} contains a malformed block with "
                        f"only {len(block)} line(s): {block}",
                    )
                # The second line must look like a timestamp
                if "-->" not in block[1]:
                    return (
                        False,
                        f"Chunk {i+1} block missing timestamp arrow: {block[1]!r}",
                    )
        return True, "No blocks split across chunk boundaries"
    finally:
        os.unlink(srt_path)


def test_reassemble_block_count() -> tuple[bool, str]:
    """
    Verify that reassembling chunks preserves the total number of blocks.

    The reassembled SRT must contain the same number of subtitle blocks
    as the original synthetic SRT.
    """
    original_blocks = chunker._parse_srt_blocks(SYNTHETIC_SRT)
    srt_path = _write_temp_srt(SYNTHETIC_SRT)
    try:
        chunks = chunker.chunk_srt(srt_path, max_lines_per_chunk=3)
        reassembled = chunker.reassemble_srt(chunks)
        reassembled_blocks = chunker._parse_srt_blocks(reassembled)
        if len(reassembled_blocks) != len(original_blocks):
            return (
                False,
                f"Original has {len(original_blocks)} blocks, "
                f"reassembled has {len(reassembled_blocks)}",
            )
        return True, f"Reassembled SRT contains all {len(original_blocks)} blocks"
    finally:
        os.unlink(srt_path)


def test_reassemble_content_preserved() -> tuple[bool, str]:
    """
    Verify that timestamps and dialogue text are preserved through the
    chunk → reassemble round-trip.

    Indices are allowed to change (reassemble renumbers them); timestamps
    and text must be identical to the original.
    """
    original_tuples = _normalise_srt(SYNTHETIC_SRT)
    srt_path = _write_temp_srt(SYNTHETIC_SRT)
    try:
        chunks = chunker.chunk_srt(srt_path, max_lines_per_chunk=3)
        reassembled = chunker.reassemble_srt(chunks)
        reassembled_tuples = _normalise_srt(reassembled)

        for i, (orig, reasm) in enumerate(
            zip(original_tuples, reassembled_tuples), start=1
        ):
            _orig_idx, orig_ts, orig_txt = orig
            _reasm_idx, reasm_ts, reasm_txt = reasm

            if orig_ts != reasm_ts:
                return (
                    False,
                    f"Block {i}: timestamp changed from {orig_ts!r} to {reasm_ts!r}",
                )
            if orig_txt != reasm_txt:
                return (
                    False,
                    f"Block {i}: text changed:\n  Before: {orig_txt!r}\n"
                    f"  After:  {reasm_txt!r}",
                )
        return True, "All timestamps and dialogue text preserved through round-trip"
    finally:
        os.unlink(srt_path)


def test_reassemble_sequential_numbering() -> tuple[bool, str]:
    """
    Verify that reassemble_srt renumbers blocks sequentially from 1.
    """
    srt_path = _write_temp_srt(SYNTHETIC_SRT)
    try:
        chunks = chunker.chunk_srt(srt_path, max_lines_per_chunk=3)
        reassembled = chunker.reassemble_srt(chunks)
        blocks = chunker._parse_srt_blocks(reassembled)
        for expected_num, block in enumerate(blocks, start=1):
            actual_num = int(block[0].strip())
            if actual_num != expected_num:
                return (
                    False,
                    f"Block at position {expected_num} has index {actual_num}",
                )
        return True, "Blocks renumbered sequentially from 1"
    finally:
        os.unlink(srt_path)


def test_chunk_limit_one() -> tuple[bool, str]:
    """
    Edge case: verify that max_lines_per_chunk=1 puts each block in its own chunk.
    """
    srt_path = _write_temp_srt(SYNTHETIC_SRT)
    try:
        chunks = chunker.chunk_srt(srt_path, max_lines_per_chunk=1)
        original_blocks = chunker._parse_srt_blocks(SYNTHETIC_SRT)
        if len(chunks) != len(original_blocks):
            return (
                False,
                f"Expected {len(original_blocks)} chunks at limit=1, "
                f"got {len(chunks)}",
            )
        return True, f"limit=1 produces {len(chunks)} individual chunks"
    finally:
        os.unlink(srt_path)


def test_clean_srt_removes_positioning() -> tuple[bool, str]:
    """
    Verify SRT cleanup removes placement/style data but keeps timing and text.
    """
    dirty = (
        "1\n"
        "00:00:01,000 --> 00:00:02,500 X1:100 X2:500 Y1:40 Y2:90\n"
        "{\\an8}<i>Hello</i> <font color=\"#fff\">world</font>\n"
        "\n"
        "2\n"
        "00:00:03.000 --> 00:00:04.000 position:50% line:10%\n"
        "{\\pos(320,50)}Xin chao\n"
    )
    cleaned = extractor._clean_srt_tags(dirty)
    expected = (
        "1\n"
        "00:00:01,000 --> 00:00:02,500\n"
        "Hello world\n"
        "\n"
        "2\n"
        "00:00:03.000 --> 00:00:04.000\n"
        "Xin chao\n"
    )
    if cleaned != expected:
        return False, f"Cleaned output differed:\n{cleaned!r}"
    return True, "Style tags and timestamp placement settings removed"


def test_promotional_cleanup_uses_general_signals() -> tuple[bool, str]:
    """Verify cleanup removes corroborated promotions without harming dialogue."""
    cues = [
        (0, "The website is finally ready."),
        (10_000, "Everything is fine."),
        (610_000, "Everything is fine."),
        (1_210_000, "Everything is fine."),
        (1_220_000, "We should continue before sunrise."),
        (1_230_000, "Visit mediahub.example for more releases"),
        (1_800_000, "CineSource presents"),
        (2_400_000, "CineSource presents"),
        (3_000_000, "CineSource presents"),
        (100_000, "Subtitles provided by Aurora Team"),
        (3_300_000, "A final note"),
    ]
    raw = _make_srt_from_starts(
        [start for start, _text in cues],
        "placeholder",
    )
    blocks = chunker._parse_srt_blocks(raw)
    for block, (_start, text) in zip(blocks, cues):
        block[2] = text
    raw = "\n\n".join("\n".join(block) for block in blocks) + "\n"

    source = _write_temp_srt(raw)
    try:
        cleaned_path, report = extractor.remove_probable_promotional_cues(
            source,
            video_duration_ms=3_200_000,
        )
        cleaned = Path(cleaned_path).read_text(encoding="utf-8")
        if Path(source).read_text(encoding="utf-8") != raw:
            return False, "Cleanup modified the source subtitle"
        if report.removed_cues != 6:
            return False, f"Expected 6 removals, got {report.removed_cues}"
        for preserved in (
            "The website is finally ready.",
            "Everything is fine.",
            "We should continue before sunrise.",
        ):
            if preserved not in cleaned:
                return False, f"Legitimate dialogue was removed: {preserved}"
        for removed in (
            "mediahub.example",
            "CineSource presents",
            "Subtitles provided by Aurora Team",
            "A final note",
        ):
            if removed in cleaned:
                return False, f"Promotional/invalid cue was retained: {removed}"
        cleaned_blocks = chunker._parse_srt_blocks(cleaned)
        if [block[0] for block in cleaned_blocks] != ["1", "2", "3", "4", "5"]:
            return False, "Retained cues were not renumbered sequentially"
    finally:
        os.unlink(source)
    return True, "General promotional signals remove only corroborated cues"


def test_promotional_cleanup_restores_timing_match() -> tuple[bool, str]:
    """Verify removed promo tails no longer distort whole-runtime timing checks."""
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        reference = work / "en.srt"
        vietnamese = work / "vi_with_promos.srt"
        output = work / "synced_vi.srt"

        reference_starts = [20_000 + index * 15_000 for index in range(30)]
        reference.write_text(
            _make_srt_from_starts(reference_starts, "English"),
            encoding="utf-8",
        )

        dialogue = _make_srt_from_starts(
            [start + 150 for start in reference_starts],
            "Vietnamese",
        )
        promo_starts = [
            60_000,
            120_000,
            180_000,
            240_000,
            300_000,
            360_000,
            420_000,
            600_000,
        ]
        promos = _make_srt_from_starts(promo_starts, "captions.example")
        vietnamese.write_text(dialogue + promos, encoding="utf-8")

        cleaned_path, report = extractor.remove_probable_promotional_cues(
            str(vietnamese),
            video_duration_ms=500_000,
        )
        if report.removed_cues != len(promo_starts):
            return (
                False,
                f"Expected {len(promo_starts)} promo removals, "
                f"got {report.removed_cues}",
            )
        result = subtitle_sync.sync_to_reference(
            str(reference),
            cleaned_path,
            str(output),
        )
        if result.confidence != "high":
            return False, f"Expected clean high-confidence match: {result}"
        if result.applied and result.offset_ms != -150:
            return False, f"Unexpected timing correction: {result.offset_ms}"
        cleaned_cues = subtitle_sync.parse_srt_timings(cleaned_path)
        if len(cleaned_cues) != len(reference_starts):
            return False, "Cleanup did not retain every dialogue cue"
    return True, "Promo-tail cleanup restores high-confidence timing comparison"


def test_english_selection_skips_forced_track() -> tuple[bool, str]:
    """Verify full English subtitles are preferred over forced/signs tracks."""
    streams = [
        {
            "index": 6,
            "codec_name": "subrip",
            "tags": {"language": "eng", "title": "English[Forced]"},
            "disposition": {"default": 1},
        },
        {
            "index": 7,
            "codec_name": "subrip",
            "tags": {"language": "eng", "title": "English"},
            "disposition": {"default": 0},
        },
    ]
    chosen = extractor._pick_english_stream(streams)
    if chosen.get("index") != 7:
        return False, f"Expected stream 7, got {chosen.get('index')}"
    return True, "Full English track selected over forced/default track"


def test_english_selection_rejects_pgs_only() -> tuple[bool, str]:
    """Verify image-based PGS subtitles are not selected as text references."""
    streams = [
        {
            "index": 2,
            "codec_name": "hdmv_pgs_subtitle",
            "tags": {"language": "eng", "title": "English PGS"},
            "disposition": {"default": 1},
        }
    ]
    try:
        extractor._pick_english_stream(streams)
    except ValueError as exc:
        message = str(exc)
        if "No text-based English subtitle track" not in message:
            return False, f"Unexpected error message: {message}"
        return True, "PGS-only English subtitle track rejected"
    return False, "Expected PGS-only stream to be rejected"


def test_selected_pgs_track_falls_back_to_no_reference() -> tuple[bool, str]:
    """Verify a manually selected PGS track becomes a recoverable no-reference case."""
    stream = {
        "index": 2,
        "codec_name": "hdmv_pgs_subtitle",
        "tags": {"language": "eng"},
        "disposition": {"default": 1},
    }
    reference = extractor.pick_reference_stream([stream], preferred_language="en")
    timing_stream = extractor._pick_image_subtitle_stream(
        [stream],
        stream,
        preferred_language="en",
    )
    if reference is not None:
        return False, "Image subtitle was incorrectly selected as translation text"
    if timing_stream != stream:
        return False, "Image subtitle was not retained as a timing reference"
    return True, "Selected PGS track handled as timing-only reference"


def test_image_subtitle_timings_parse_packets() -> tuple[bool, str]:
    """Verify PGS packet timestamps can be used as a timing skeleton."""
    with tempfile.TemporaryDirectory() as tmp:
        video = Path(tmp) / "Movie.mkv"
        video.write_bytes(b"not a real video")
        streams = [
            {
                "index": 2,
                "codec_name": "hdmv_pgs_subtitle",
                "tags": {"language": "eng", "title": "English PGS"},
                "disposition": {"default": 1},
            }
        ]
        packets = {
            "packets": [
                {"stream_index": 2, "pts_time": "10.000", "duration_time": "2.000"},
                {"stream_index": 2, "pts_time": "10.100", "duration_time": "2.500"},
                {"stream_index": 2, "pts_time": "25.000", "duration_time": "3.000"},
                {"stream_index": 3, "pts_time": "99.000", "duration_time": "2.000"},
            ]
        }

        original_probe = extractor._probe_subtitle_streams
        original_run = extractor.subprocess.run
        try:
            extractor._probe_subtitle_streams = lambda *_args, **_kwargs: streams
            extractor.subprocess.run = lambda *_args, **_kwargs: SimpleNamespace(
                returncode=0,
                stdout=json.dumps(packets),
                stderr="",
            )
            result = extractor.extract_image_subtitle_timings(str(video))
        finally:
            extractor._probe_subtitle_streams = original_probe
            extractor.subprocess.run = original_run

        if result is None:
            return False, "Expected image subtitle timings"
        cues, label = result
        if "HDMV_PGS_SUBTITLE" not in label:
            return False, f"Unexpected label: {label}"
        if len(cues) != 2:
            return False, f"Expected duplicate packets to coalesce into 2 cues, got {len(cues)}"
        if cues[0].start_ms != 10_000 or cues[0].end_ms != 12_600:
            return False, f"Unexpected first cue timing: {cues[0]}"
    return True, "Image subtitle packet timings parsed and coalesced"


def test_external_image_subtitle_timings_found_in_subfolder() -> tuple[bool, str]:
    """Verify external VobSub/DVD .sub files can provide timing skeletons."""
    with tempfile.TemporaryDirectory() as tmp:
        movie_dir = Path(tmp) / "Blade Runner"
        subs_dir = movie_dir / "Subs"
        subs_dir.mkdir(parents=True)
        video = movie_dir / "Blade.Runner.2049.mp4"
        sub_file = subs_dir / "Blade.Runner.2049.sub"

        video.write_bytes(b"not a real video")
        sub_file.write_bytes(b"fake binary subtitle")

        streams = [
            {
                "index": 0,
                "codec_name": "dvd_subtitle",
                "tags": {},
                "disposition": {"default": 0},
            },
            {
                "index": 1,
                "codec_name": "dvd_subtitle",
                "tags": {},
                "disposition": {"default": 0},
            },
        ]
        packets = {
            "packets": [
                *(
                    {
                        "stream_index": 0,
                        "pts_time": f"{10 + index * 12:.3f}",
                        "duration_time": "2.000",
                    }
                    for index in range(8)
                ),
                *(
                    {
                        "stream_index": 1,
                        "pts_time": f"{10 + index * 20:.3f}",
                        "duration_time": "2.000",
                    }
                    for index in range(4)
                ),
            ]
        }

        original_probe = extractor._probe_subtitle_streams
        original_run = extractor.subprocess.run
        try:
            extractor._probe_subtitle_streams = lambda *_args, **_kwargs: streams
            extractor.subprocess.run = lambda *_args, **_kwargs: SimpleNamespace(
                returncode=0,
                stdout=json.dumps(packets),
                stderr="",
            )
            result = extractor.find_external_image_subtitle_timings(str(video))
        finally:
            extractor._probe_subtitle_streams = original_probe
            extractor.subprocess.run = original_run

        if result is None:
            return False, "Expected external image subtitle timings"
        cues, label = result
        if len(cues) != 8:
            return False, f"Expected densest .sub stream with 8 cues, got {len(cues)}"
        if "external image Blade.Runner.2049.sub" not in label:
            return False, f"Unexpected label: {label}"
    return True, "External .sub timing skeleton found in Subs folder"


def test_external_english_subtitle_found_in_subfolder() -> tuple[bool, str]:
    """Verify an English subtitle in a nested Subs folder is discovered."""
    with tempfile.TemporaryDirectory() as tmp:
        movie_dir = Path(tmp) / "Movie Release"
        subs_dir = movie_dir / "Subs"
        subs_dir.mkdir(parents=True)
        video = movie_dir / "Movie.Name.2026.1080p.mp4"
        english = subs_dir / "English.srt"
        vietnamese = subs_dir / "Vietnamese.srt"

        video.write_bytes(b"not a real video")
        english.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello\n\n", encoding="utf-8")
        vietnamese.write_text("1\n00:00:00,000 --> 00:00:01,000\nXin chao\n\n", encoding="utf-8")

        found = extractor.find_external_english_subtitle(str(video))
        if not found:
            return False, "No external English subtitle was found"
        clean_srt, source = found
        if Path(source).resolve() != english.resolve():
            return False, f"Expected {english}, got {source}"
        if "Hello" not in Path(clean_srt).read_text(encoding="utf-8"):
            return False, "Cleaned external subtitle did not contain English text"
    return True, "External English subtitle found in nested Subs folder"


def test_external_english_subtitle_rejects_forced() -> tuple[bool, str]:
    """Verify forced/signs subtitles are not used as the English reference."""
    with tempfile.TemporaryDirectory() as tmp:
        movie_dir = Path(tmp) / "Movie Release"
        subs_dir = movie_dir / "Subtitles"
        subs_dir.mkdir(parents=True)
        video = movie_dir / "Movie.Name.2026.1080p.mp4"
        forced = subs_dir / "English Forced.srt"
        full = subs_dir / "Movie.Name.2026.eng.srt"

        video.write_bytes(b"not a real video")
        forced.write_text("1\n00:00:00,000 --> 00:00:01,000\nSign\n\n", encoding="utf-8")
        full.write_text("1\n00:00:00,000 --> 00:00:01,000\nFull line\n\n", encoding="utf-8")

        found = extractor.find_external_english_subtitle(str(video))
        if not found:
            return False, "No external English subtitle was found"
        _clean_srt, source = found
        if Path(source).resolve() != full.resolve():
            return False, f"Expected full subtitle {full}, got {source}"
    return True, "Forced English subtitle rejected in favor of full subtitle"


def test_external_english_prefers_dialogue_over_sdh() -> tuple[bool, str]:
    """Verify dialogue-style English beats a larger SDH-style English file."""
    with tempfile.TemporaryDirectory() as tmp:
        movie_dir = Path(tmp) / "Gattaca.1997.1080p"
        subs_dir = movie_dir / "Subs"
        subs_dir.mkdir(parents=True)
        video = movie_dir / "Gattaca.1997.1080p.mp4"
        dialogue = subs_dir / "2_Eng.srt"
        sdh = subs_dir / "3_Eng.srt"

        video.write_bytes(b"not a real video")
        dialogue.write_text(
            "\n".join(
                [
                    "1\n00:04:17,841 --> 00:04:21,344\nWelcome to Gattaca.\n",
                    "2\n00:05:19,903 --> 00:05:23,572\nYou keep your workstation so clean.\n",
                    "3\n00:05:24,574 --> 00:05:26,409\nIt's next to godliness.\n",
                    "4\n00:05:30,205 --> 00:05:34,959\nI reviewed your flight plan.\n",
                    "5\n00:05:35,252 --> 00:05:40,423\nPhenomenal work.\n",
                ]
            ),
            encoding="utf-8",
        )
        sdh.write_text(
            "\n".join(
                [
                    "1\n00:00:35,786 --> 00:00:38,788\n[♪♪♪]\n",
                    "2\n00:01:27,254 --> 00:01:30,006\n[METAL CLINKING]\n",
                    "3\n00:03:05,686 --> 00:03:07,436\n[FLAMES ROAR]\n",
                    "4\n00:04:17,841 --> 00:04:21,344\nWOMAN [OVER PA]:\nWelcome to Gattaca.\n",
                    "5\n00:04:23,513 --> 00:04:25,139\n[BEEPS]\n",
                    "6\n00:05:19,695 --> 00:05:23,406\nYou keep your workstation so clean.\n",
                    "7\n00:05:24,366 --> 00:05:27,535\nIt's next to godliness.\n",
                    "8\n00:05:27,911 --> 00:05:30,037\nGodliness.\n",
                ]
            )
            + "\n[STATIC]\n" * 20,
            encoding="utf-8",
        )

        found = extractor.find_external_english_subtitle(str(video))
        if not found:
            return False, "No external English subtitle was found"
        _clean_srt, source = found
        if Path(source).resolve() != dialogue.resolve():
            return False, f"Expected dialogue subtitle {dialogue}, got {source}"
    return True, "Dialogue English subtitle selected over larger SDH file"


def test_opensubtitles_rejects_unrelated_s01e01() -> tuple[bool, str]:
    """Verify broad filename search results do not accept unrelated episodes."""
    video = (
        "/tmp/S01E01 The Ghost in the Shell Episodio 01 Prologue + "
        "Super Spartan I (2026) WEBRip 1080p x264.mkv"
    )
    bad = open_subtitles.SubtitleCandidate(
        file_id=1,
        release_name="Lady.in.the.Lake.S01E01.1080p.WEB.H264-SuccessfulCrab44_[vie]",
        file_name="lady.in.the.lake.s01e01.srt",
        language="vi",
        download_count=0,
        rating=0.0,
        trusted=True,
        source={"attributes": {"feature_details": {"title": "Lady in the Lake"}}},
    )
    good = open_subtitles.SubtitleCandidate(
        file_id=2,
        release_name="Ghost in the Shell S01E01 Prologue",
        file_name="ghost.in.the.shell.s01e01.srt",
        language="vi",
        download_count=0,
        rating=0.0,
        trusted=False,
        source={"attributes": {"feature_details": {"title": "Ghost in the Shell"}}},
    )
    filtered = open_subtitles._filter_filename_candidates([bad, good], video)
    if filtered != [good]:
        return False, f"Expected only Ghost candidate, got {[c.release_name for c in filtered]}"
    return True, "Unrelated S01E01 result rejected by title filter"


def test_opensubtitles_rejects_shared_word_short_title() -> tuple[bool, str]:
    """Reject MF Ghost when searching for the short title Ghost in the Shell."""
    video = "/tmp/[DKB] The Ghost in the Shell - S01E03 [1080p].mkv"
    wrong_show = open_subtitles.SubtitleCandidate(
        file_id=1,
        release_name="MF.Ghost.S01E03.JAPANESE.WEBRip.AMZN",
        file_name="mf.ghost.s01e03.srt",
        language="vi",
        download_count=10,
        rating=0.0,
        trusted=True,
        source={"attributes": {"feature_details": {"title": "MF Ghost"}}},
    )
    correct_show = open_subtitles.SubtitleCandidate(
        file_id=2,
        release_name="The Ghost in the Shell S01E03",
        file_name="the.ghost.in.the.shell.s01e03.srt",
        language="vi",
        download_count=1,
        rating=0.0,
        trusted=False,
        source={"attributes": {"feature_details": {"title": "Ghost in the Shell"}}},
    )
    filtered = open_subtitles._filter_filename_candidates([wrong_show, correct_show], video)
    if filtered != [correct_show]:
        return False, f"Expected only Ghost in the Shell, got {[c.release_name for c in filtered]}"
    return True, "Shared-word MF Ghost result rejected for Ghost in the Shell"


def test_opensubtitles_retains_rejected_candidate_for_review() -> tuple[bool, str]:
    """Keep plausible filename results available when automatic matching fails."""
    payload = {
        "data": [
            {
                "attributes": {
                    "release": "The.Perfection.2019.720p.NF.WEB-DL.DDP5.1.x264-NTG",
                    "download_count": 548,
                    "ratings": 0,
                    "from_trusted": False,
                    "language": "vi",
                    "feature_details": {
                        "title": "The Perfection",
                        "year": 2018,
                    },
                    "files": [
                        {
                            "file_id": 7778003,
                            "file_name": "The.Perfection.2019.720p.NF.WEB-DL.DDP5.1.x264-NTG_vie",
                        }
                    ],
                }
            }
        ]
    }
    original_hash = open_subtitles.movie_hash
    original_request = open_subtitles._request_json
    try:
        open_subtitles.movie_hash = lambda _path: "1234567890abcdef"
        open_subtitles._request_json = (
            lambda _method, _path, _key, *, query=None, body=None:
            {"data": []} if query and "moviehash" in query else payload
        )
        results = open_subtitles.search_vietnamese_results(
            "test-key",
            "/tmp/The.Perfection.2018.1080p.NF.WEB-DL.DD5.1.H264-CMRG.mkv",
        )
    finally:
        open_subtitles.movie_hash = original_hash
        open_subtitles._request_json = original_request

    if results.automatic_matches:
        return False, "Release-noise mismatch should not be selected automatically"
    if len(results.candidates) != 1:
        return False, f"Expected one review candidate, got {len(results.candidates)}"
    candidate = results.candidates[0]
    if candidate.feature_title != "The Perfection" or candidate.feature_year != "2018":
        return False, "Canonical title metadata was not retained for review"
    return True, "Rejected Perfection result retained with canonical title metadata"


def test_embedded_vietnamese_text_track_selection() -> tuple[bool, str]:
    """Prefer a full Vietnamese text track over forced or image subtitles."""
    streams = [
        {
            "index": 2,
            "codec_name": "subrip",
            "tags": {"language": "eng", "title": "English"},
            "disposition": {"default": 1},
        },
        {
            "index": 3,
            "codec_name": "hdmv_pgs_subtitle",
            "tags": {"language": "vie", "title": "Vietnamese"},
            "disposition": {"default": 1},
        },
        {
            "index": 4,
            "codec_name": "subrip",
            "tags": {"language": "vie", "title": "Vietnamese Forced"},
            "disposition": {"forced": 1},
        },
        {
            "index": 5,
            "codec_name": "subrip",
            "tags": {"language": "vie", "title": "Vietnamese"},
            "disposition": {"default": 0},
        },
    ]
    selected = extractor.pick_vietnamese_stream(streams)
    if selected is None or selected.get("index") != 5:
        return False, f"Expected full text track 5, got {selected}"
    return True, "Full Vietnamese text track selected for direct playback"


def test_media_discovery_searches_newest_folder() -> tuple[bool, str]:
    """Verify auto-discovery finds the main video inside a new release folder."""
    with tempfile.TemporaryDirectory() as tmp:
        media_dir = Path(tmp)
        old_root = media_dir / "old_movie.mp4"
        folder = media_dir / "Newest Movie"
        folder.mkdir()
        sample = folder / "sample.mkv"
        movie = folder / "Newest.Movie.1080p.mkv"

        old_root.write_bytes(b"old")
        sample.write_bytes(b"s")
        movie.write_bytes(b"movie" * 10)

        old_time = 1_700_000_000
        new_time = old_time + 100
        os.utime(old_root, (old_time, old_time))
        os.utime(sample, (new_time, new_time))
        os.utime(movie, (new_time, new_time))
        os.utime(folder, (new_time, new_time))

        found = app_paths.find_latest_video_in_media_dir(media_dir)
        if found != movie:
            return False, f"Expected {movie}, got {found}"
    return True, "Newest release folder selects full movie, not sample"


def test_media_discovery_ignores_app_folders() -> tuple[bool, str]:
    """Verify generated app folders are ignored during auto-discovery."""
    with tempfile.TemporaryDirectory() as tmp:
        media_dir = Path(tmp)
        workspace = media_dir / "SubtitleTranslator Workspace"
        workspace.mkdir()
        generated = workspace / "new_generated_subbed.mkv"
        direct = media_dir / "fresh_download.mkv"

        generated.write_bytes(b"generated" * 10)
        direct.write_bytes(b"direct")

        old_time = 1_700_000_000
        new_time = old_time + 100
        os.utime(direct, (old_time, old_time))
        os.utime(generated, (new_time, new_time))
        os.utime(workspace, (new_time, new_time))

        original_managed = app_paths.APP_MANAGED_DIRS
        try:
            app_paths.APP_MANAGED_DIRS = (workspace,)
            found = app_paths.find_latest_video_in_media_dir(media_dir)
            if found != direct:
                return False, f"Expected {direct}, got {found}"
        finally:
            app_paths.APP_MANAGED_DIRS = original_managed
    return True, "App-managed output folders ignored"


def _make_timing_srt(count: int, text_prefix: str, gap_ms: int = 2000) -> str:
    """Build a small SRT string with predictable timing."""
    blocks = []
    for i in range(1, count + 1):
        start = (i - 1) * gap_ms
        end = start + 1000
        blocks.append(
            f"{i}\n{_test_ts(start)} --> {_test_ts(end)}\n{text_prefix} {i}\n"
        )
    return "\n".join(blocks) + "\n"


def _test_ts(ms: int) -> str:
    seconds, millis = divmod(ms, 1000)
    minutes, seconds = divmod(seconds, 60)
    return f"00:{minutes:02}:{seconds:02},{millis:03}"


def _make_srt_from_starts(starts_ms: list[int], text_prefix: str) -> str:
    """Build an SRT string from explicit cue start times."""
    blocks = []
    for index, start in enumerate(starts_ms, start=1):
        end = start + 900
        blocks.append(
            f"{index}\n{_test_ts(start)} --> {_test_ts(end)}\n{text_prefix} {index}\n"
        )
    return "\n".join(blocks) + "\n"


def test_sync_accepts_aligned_split_cues() -> tuple[bool, str]:
    """Verify aligned subtitles can have extra split cues without rejection."""
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        reference = work / "en.srt"
        vietnamese = work / "vi.srt"
        output = work / "synced_vi.srt"

        reference_starts = [60_000 + index * 15_000 for index in range(12)]
        split_starts = []
        for start in reference_starts:
            split_starts.append(start)
            split_starts.append(start + 1_500)

        reference.write_text(
            _make_srt_from_starts(reference_starts, "English"),
            encoding="utf-8",
        )
        vietnamese.write_text(
            _make_srt_from_starts(split_starts, "Vietnamese split"),
            encoding="utf-8",
        )

        result = subtitle_sync.sync_to_reference(str(reference), str(vietnamese), str(output))
        if result.confidence == "low":
            return False, f"Expected accepted timing, got: {result.message}"
        if result.applied:
            return False, f"Expected no timing rewrite, got {result.method}"
        if "Vietnamese split 24" not in output.read_text(encoding="utf-8"):
            return False, "Synced output did not preserve all split cues"
    return True, "Aligned subtitle accepted despite split cue count"


def test_sync_rejects_start_only_match() -> tuple[bool, str]:
    """Verify a subtitle matching only the opening cues is rejected."""
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        reference = work / "en.srt"
        vietnamese = work / "wrong_cut_vi.srt"
        output = work / "synced_wrong_cut_vi.srt"

        reference_starts = [index * 15_000 for index in range(12)]
        wrong_cut_starts = reference_starts[:4] + [
            1_800_000 + index * 21_000 for index in range(8)
        ]

        reference.write_text(
            _make_srt_from_starts(reference_starts, "English"),
            encoding="utf-8",
        )
        vietnamese.write_text(
            _make_srt_from_starts(wrong_cut_starts, "Wrong cut"),
            encoding="utf-8",
        )

        result = subtitle_sync.sync_to_reference(str(reference), str(vietnamese), str(output))
        if result.confidence != "low":
            return False, f"Expected low confidence, got {result.confidence}: {result.message}"
        if result.applied:
            return False, f"Wrong-cut subtitle should not be rewritten via {result.method}"
    return True, "Start-only timing match rejected"


def test_sync_to_reference_cues_applies_offset() -> tuple[bool, str]:
    """Verify non-text cue references can correct a constant subtitle offset."""
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        vietnamese = work / "vi_offset.srt"
        output = work / "vi_synced.srt"

        reference_cues = [
            subtitle_sync.CueTiming(60_000 + index * 12_000, 63_000 + index * 12_000)
            for index in range(12)
        ]
        shifted_starts = [cue.start_ms + 2_000 for cue in reference_cues]
        vietnamese.write_text(
            _make_srt_from_starts(shifted_starts, "Vietnamese"),
            encoding="utf-8",
        )

        result = subtitle_sync.sync_to_reference_cues(
            reference_cues,
            str(vietnamese),
            str(output),
            reference_label="PGS timing skeleton",
            tolerance_ms=1500,
        )
        if result.confidence == "low":
            return False, f"Expected offset sync to pass, got: {result.message}"
        if not result.applied or result.method != "constant offset":
            return False, f"Expected constant offset correction, got {result.method}"
        synced = output.read_text(encoding="utf-8")
        if "00:01:00,000 --> 00:01:00,900" not in synced:
            return False, f"Expected first cue shifted to reference time:\n{synced}"
    return True, "PGS-style cue reference corrected constant offset"


def test_sync_prefers_clear_offset_over_dense_no_shift_match() -> tuple[bool, str]:
    """Verify dense neighboring cues do not hide a useful constant offset."""
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        reference = work / "en_dense.srt"
        vietnamese = work / "vi_early.srt"
        output = work / "vi_shifted.srt"

        reference_starts: list[int] = []
        for index in range(20):
            base = 30_000 + index * 10_000
            reference_starts.extend([base, base + 3_000])
        shifted_starts = [start - 3_000 for start in reference_starts]

        reference.write_text(
            _make_srt_from_starts(reference_starts, "English"),
            encoding="utf-8",
        )
        vietnamese.write_text(
            _make_srt_from_starts(shifted_starts, "Vietnamese"),
            encoding="utf-8",
        )

        result = subtitle_sync.sync_to_reference(str(reference), str(vietnamese), str(output))
        if result.confidence == "low":
            return False, f"Expected accepted offset, got: {result.message}"
        if not result.applied or result.method != "constant offset":
            return False, f"Expected constant offset, got {result.method}"
        if not 2_500 <= result.offset_ms <= 3_500:
            return False, f"Expected about +3000 ms offset, got {result.offset_ms}"
        shifted_text = output.read_text(encoding="utf-8")
        if "00:00:30,000 --> 00:00:30,900" not in shifted_text:
            return False, f"First cue was not shifted onto the reference:\n{shifted_text}"
    return True, "Clear offset beats misleading dense no-shift match"


def test_sync_applies_stable_micro_offset() -> tuple[bool, str]:
    """Verify a stable 150 ms whole-runtime mismatch is corrected."""
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        reference = work / "en.srt"
        vietnamese = work / "vi_early.srt"
        output = work / "vi_shifted.srt"

        reference_starts: list[int] = []
        timestamp = 30_000
        gaps = [4_300, 7_100, 5_200, 8_900, 6_100, 4_700, 7_600, 5_400]
        for index in range(64):
            reference_starts.append(timestamp)
            timestamp += gaps[index % len(gaps)] + (index % 3) * 170

        reference.write_text(
            _make_srt_from_starts(reference_starts, "English"),
            encoding="utf-8",
        )
        vietnamese.write_text(
            _make_srt_from_starts(
                [start - 150 for start in reference_starts],
                "Vietnamese",
            ),
            encoding="utf-8",
        )

        result = subtitle_sync.sync_to_reference(
            str(reference),
            str(vietnamese),
            str(output),
        )
        if not result.applied or result.method != "constant offset":
            return False, f"Expected stable micro-correction, got: {result}"
        if result.offset_ms != 150:
            return False, f"Expected +150 ms, got {result.offset_ms}"
        if "150 ms to 0 ms" not in result.message:
            return False, f"Expected before/after timing report: {result.message}"
        shifted = output.read_text(encoding="utf-8")
        if "00:00:30,000 --> 00:00:30,900" not in shifted:
            return False, f"First cue was not corrected:\n{shifted}"
    return True, "Stable 150 ms offset corrected across the full runtime"


def test_sync_does_not_apply_inconsistent_micro_offset() -> tuple[bool, str]:
    """Verify a small offset that changes later in the runtime is not rewritten."""
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        reference = work / "en.srt"
        vietnamese = work / "vi_mixed_offset.srt"
        output = work / "vi_unchanged.srt"

        reference_starts: list[int] = []
        timestamp = 30_000
        gaps = [4_300, 7_100, 5_200, 8_900, 6_100, 4_700, 7_600, 5_400]
        for index in range(64):
            reference_starts.append(timestamp)
            timestamp += gaps[index % len(gaps)] + (index % 3) * 170

        mixed_starts = [
            start - 150 if index < 48 else start + 150
            for index, start in enumerate(reference_starts)
        ]
        reference.write_text(
            _make_srt_from_starts(reference_starts, "English"),
            encoding="utf-8",
        )
        original = _make_srt_from_starts(mixed_starts, "Vietnamese")
        vietnamese.write_text(original, encoding="utf-8")

        result = subtitle_sync.sync_to_reference(
            str(reference),
            str(vietnamese),
            str(output),
        )
        if result.applied:
            return False, f"Inconsistent micro-offset was rewritten: {result}"
        if output.read_text(encoding="utf-8") != original:
            return False, "Rejected micro-correction did not preserve timestamps"
    return True, "Changing small offset left untouched"


def test_sync_rejects_local_timing_discontinuity() -> tuple[bool, str]:
    """Verify a locally shifted middle section is rejected as a different cut."""
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        reference = work / "en.srt"
        vietnamese = work / "vi_discontinuous.srt"
        output = work / "vi_checked.srt"

        starts: list[int] = []
        timestamp = 30_000
        gaps = [4_300, 7_100, 5_200, 8_900, 6_100, 4_700, 7_600, 5_400]
        for index in range(64):
            starts.append(timestamp)
            timestamp += gaps[index % len(gaps)] + (index % 3) * 170

        discontinuous = [
            start - 3_500 if 22 <= index < 43 else start
            for index, start in enumerate(starts)
        ]
        reference.write_text(_make_srt_from_starts(starts, "English"), encoding="utf-8")
        vietnamese.write_text(
            _make_srt_from_starts(discontinuous, "Vietnamese"),
            encoding="utf-8",
        )

        result = subtitle_sync.sync_to_reference(
            str(reference),
            str(vietnamese),
            str(output),
        )
        if result.confidence != "low" or result.applied:
            return False, f"Expected discontinuity rejection, got: {result}"
        if "changes abruptly" not in result.message:
            return False, f"Expected local-jump explanation, got: {result.message}"
    return True, "Abrupt middle-of-runtime timing change rejected"


def test_external_english_validation_corrects_offset() -> tuple[bool, str]:
    """Verify an external English reference can be corrected by image timings."""
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        video = work / "movie.mkv"
        english = work / "english.srt"
        video.write_bytes(b"not a real video; duration check is patched")

        reference_cues = [
            subtitle_sync.CueTiming(30_000 + index * 12_000, 32_000 + index * 12_000)
            for index in range(12)
        ]
        english.write_text(
            _make_srt_from_starts(
                [cue.start_ms + 2_000 for cue in reference_cues],
                "English",
            ),
            encoding="utf-8",
        )

        worker = pipeline.SubtitlePipeline()
        options = pipeline.PipelineOptions(
            video_path=str(video),
            target_language="vi",
            source_language="en",
        )
        original_image_reference = extractor.extract_image_subtitle_timings
        try:
            extractor.extract_image_subtitle_timings = (
                lambda *_args, **_kwargs: (
                    reference_cues,
                    "embedded PGS timing",
                )
            )
            checked = worker._validate_external_reference(
                video,
                str(english),
                options,
                work,
            )
        finally:
            extractor.extract_image_subtitle_timings = original_image_reference
        if checked is None:
            return False, "Expected validated English path"
        text = Path(checked).read_text(encoding="utf-8")
        if "00:00:30,000 --> 00:00:30,900" not in text:
            return False, f"External English offset was not corrected:\n{text}"
    return True, "External English offset corrected against image timing"


def test_audio_activity_validation_accepts_overlap() -> tuple[bool, str]:
    """Verify audio-activity validation accepts subtitles over active segments."""
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        vietnamese = work / "vi.srt"
        output = work / "vi_audio_checked.srt"

        starts = [30_000 + index * 10_000 for index in range(12)]
        activity = [
            subtitle_sync.CueTiming(start - 500, start + 2_000)
            for start in starts
        ]
        vietnamese.write_text(
            _make_srt_from_starts(starts, "Vietnamese"),
            encoding="utf-8",
        )

        result = subtitle_sync.validate_against_activity(
            activity,
            str(vietnamese),
            str(output),
        )
        if result.confidence == "low":
            return False, f"Expected audio validation to pass, got: {result.message}"
        if result.applied:
            return False, "Audio validation should not rewrite timestamps"
    return True, "Audio activity accepted overlapping subtitle cues"


def test_audio_activity_validation_rejects_dense_or_wrong_timing() -> tuple[bool, str]:
    """Verify audio validation rejects unusably dense or mismatched activity."""
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        vietnamese = work / "vi_wrong.srt"
        dense_out = work / "dense.srt"
        wrong_out = work / "wrong.srt"

        starts = [30_000 + index * 10_000 for index in range(12)]
        vietnamese.write_text(
            _make_srt_from_starts(starts, "Vietnamese"),
            encoding="utf-8",
        )

        dense_activity = [subtitle_sync.CueTiming(0, 180_000)]
        dense_result = subtitle_sync.validate_against_activity(
            dense_activity,
            str(vietnamese),
            str(dense_out),
        )
        if dense_result.confidence != "low":
            return False, "Dense audio activity should be rejected as uninformative"

        wrong_activity = [
            subtitle_sync.CueTiming(300_000 + index * 10_000, 302_000 + index * 10_000)
            for index in range(12)
        ]
        wrong_result = subtitle_sync.validate_against_activity(
            wrong_activity,
            str(vietnamese),
            str(wrong_out),
        )
        if wrong_result.confidence != "low":
            return False, "Wrong-timing audio activity should be rejected"
    return True, "Audio activity rejects dense or mismatched references"


def test_merge_retry_uses_alternate_subtitle() -> tuple[bool, str]:
    """Verify failed timing sync triggers an alternate OpenSubtitles candidate."""
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        reference = work / "en.srt"
        bad = work / "bad_vi.srt"
        alternate = work / "alternate_vi.srt"
        video = work / "video.mkv"
        video.write_bytes(b"not a real video; duration check is patched")

        reference.write_text(_make_timing_srt(6, "English"), encoding="utf-8")
        bad.write_text(_make_timing_srt(20, "Wrong cut"), encoding="utf-8")
        alternate.write_text(_make_timing_srt(6, "Alternate"), encoding="utf-8")

        candidate = open_subtitles.SubtitleCandidate(
            file_id=99,
            release_name="Matching release",
            file_name="matching.srt",
            language="vi",
            download_count=0,
            rating=0.0,
            trusted=False,
            source={},
        )

        original_search = open_subtitles.search_subtitles
        original_download = open_subtitles.download_subtitle
        try:
            open_subtitles.search_subtitles = lambda *_args, **_kwargs: [candidate]
            open_subtitles.download_subtitle = lambda *_args, **_kwargs: str(alternate)

            worker = pipeline.SubtitlePipeline()
            worker._validate_duration = lambda *_args, **_kwargs: None
            result = worker._sync_or_retry(
                video,
                pipeline._Target(str(bad), "selected file", False),
                pipeline._Reference(str(reference), "en", "English", True),
                pipeline.PipelineOptions(
                    video_path=str(video),
                    target_language="vi",
                    opensubtitles_api_key="fake-open-subtitles-key",
                    workspace_directory=str(work),
                ),
                work,
            )
        finally:
            open_subtitles.search_subtitles = original_search
            open_subtitles.download_subtitle = original_download

        text = Path(result.path).read_text(encoding="utf-8")
        if "Alternate 1" not in text or "Wrong cut" in text:
            return False, f"Final subtitle did not use alternate:\n{text}"
    return True, "Rejected bad subtitle and saved alternate candidate"


def test_mux_transaction_preserves_finished_output_on_failure() -> tuple[bool, str]:
    """Verify mux failures remove partial data without replacing prior output."""
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        merged = work / "merged"
        merged.mkdir()
        video = work / "movie.mp4"
        vietnamese = work / "vi.srt"
        video.write_bytes(b"source media")
        vietnamese.write_text(_make_timing_srt(6, "Vietnamese"), encoding="utf-8")
        final = merged / "movie [Subtitled].mkv"
        final.write_bytes(b"previous finished output")

        original_space = muxer._ensure_free_space
        original_mux = muxer._run_mkvmerge
        original_verify = muxer._verify_mux_output
        try:
            muxer._ensure_free_space = lambda *_args, **_kwargs: None

            def fail_after_partial(_source, _tracks, output_path):
                Path(output_path).write_bytes(b"partial broken output")
                raise RuntimeError("synthetic mux failure")

            muxer._run_mkvmerge = fail_after_partial
            muxer._verify_mux_output = lambda *_args, **_kwargs: None
            try:
                muxer.mux_tracks(
                    str(video),
                    [muxer.SubtitleTrack(str(vietnamese), "vi", "Vietnamese", True)],
                    output_directory=merged,
                )
            except RuntimeError as exc:
                if "synthetic mux failure" not in str(exc):
                    return False, f"Unexpected mux error: {exc}"
            else:
                return False, "Expected synthetic mux failure"
        finally:
            muxer._ensure_free_space = original_space
            muxer._run_mkvmerge = original_mux
            muxer._verify_mux_output = original_verify

        if final.read_bytes() != b"previous finished output":
            return False, "Existing finished output was replaced after failure"
        if list(merged.glob(".*.partial.mkv")):
            return False, "Partial output was not cleaned after failure"
    return True, "Transactional mux preserved prior output and removed partial file"


def test_mux_preflight_rejects_low_disk_space() -> tuple[bool, str]:
    """Verify muxing stops before writing when free disk space is insufficient."""
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        video = work / "movie.mkv"
        video.write_bytes(b"x" * 1024)
        original_disk_usage = muxer.shutil.disk_usage
        try:
            muxer.shutil.disk_usage = lambda *_args, **_kwargs: SimpleNamespace(free=100)
            try:
                muxer._ensure_free_space(str(video), work)
            except RuntimeError as exc:
                if "Not enough free disk space" not in str(exc):
                    return False, f"Unexpected preflight error: {exc}"
                return True, "Low disk space rejected before muxing"
        finally:
            muxer.shutil.disk_usage = original_disk_usage
    return False, "Expected disk-space preflight failure"


def test_recent_merged_files_are_sorted_and_filtered() -> tuple[bool, str]:
    """Verify the launch menu receives recent playable files in newest-first order."""
    with tempfile.TemporaryDirectory() as tmp:
        merged = Path(tmp) / "3 Merged"
        nested = merged / "Archive"
        nested.mkdir(parents=True)
        older = merged / "Older Movie.mkv"
        newest = nested / "Newest Movie.mp4"
        ignored = merged / "notes.txt"
        hidden = merged / ".partial.mp4"
        older.write_bytes(b"old")
        newest.write_bytes(b"new")
        ignored.write_text("ignore", encoding="utf-8")
        hidden.write_bytes(b"partial")
        os.utime(older, (100, 100))
        os.utime(newest, (200, 200))
        os.utime(hidden, (300, 300))

        result = media_launcher.recent_merged_files(limit=5, directory=merged)
        if result != [newest, older]:
            return False, f"Unexpected recent-media order/filtering: {result}"
    return True, "Recent merged media sorted newest-first and partials ignored"


def test_mpv_launch_uses_detached_direct_arguments() -> tuple[bool, str]:
    """Verify media paths are passed directly to detached mpv without a shell."""
    with tempfile.TemporaryDirectory() as tmp:
        media = Path(tmp) / "Movie With Spaces.mkv"
        media.write_bytes(b"media")
        captured: dict[str, object] = {}

        class FakeProcess:
            pid = 4242

            @staticmethod
            def wait() -> int:
                return 0

        original_resolve = media_launcher.resolve_mpv_executable
        original_popen = media_launcher.subprocess.Popen
        try:
            media_launcher.resolve_mpv_executable = lambda: "/fake/bin/mpv"

            def fake_popen(args, **kwargs):
                captured["args"] = args
                captured["kwargs"] = kwargs
                return FakeProcess()

            media_launcher.subprocess.Popen = fake_popen
            result = media_launcher.launch_in_mpv(media)
        finally:
            media_launcher.resolve_mpv_executable = original_resolve
            media_launcher.subprocess.Popen = original_popen

        if captured.get("args") != ["/fake/bin/mpv", "--", str(media.resolve())]:
            return False, f"Unexpected mpv argument list: {captured.get('args')}"
        kwargs = captured.get("kwargs", {})
        if not isinstance(kwargs, dict) or not kwargs.get("start_new_session"):
            return False, "mpv process was not launched in a detached session"
        if "shell" in kwargs:
            return False, "mpv launch should not invoke a shell"
        if result.pid != 4242:
            return False, f"Unexpected launch PID: {result.pid}"
    return True, "mpv launch uses safe direct arguments and a detached process"


# ── Test runner ────────────────────────────────────────────────────────────────

def run_all_tests() -> None:
    """Run all tests and print a formatted PASS/FAIL summary."""
    tests = [
        ("Chunk count (default limit=200)",   test_chunk_count_default),
        ("Chunk count (limit=3)",             test_chunk_count_small_limit),
        ("No block split at boundaries",      test_no_block_is_split),
        ("Reassemble preserves block count",  test_reassemble_block_count),
        ("Reassemble preserves content",      test_reassemble_content_preserved),
        ("Reassemble sequential numbering",   test_reassemble_sequential_numbering),
        ("Edge case: limit=1",               test_chunk_limit_one),
        ("SRT cleanup removes positioning",   test_clean_srt_removes_positioning),
        ("SRT cleanup removes promotions",    test_promotional_cleanup_uses_general_signals),
        ("Promo cleanup restores timing",     test_promotional_cleanup_restores_timing_match),
        ("English selection skips forced",    test_english_selection_skips_forced_track),
        ("English selection rejects PGS",     test_english_selection_rejects_pgs_only),
        ("Selected PGS falls back",           test_selected_pgs_track_falls_back_to_no_reference),
        ("Image subtitle timings parse",      test_image_subtitle_timings_parse_packets),
        ("External image timings found",      test_external_image_subtitle_timings_found_in_subfolder),
        ("External English in subfolder",     test_external_english_subtitle_found_in_subfolder),
        ("External English rejects forced",   test_external_english_subtitle_rejects_forced),
        ("External English prefers dialogue", test_external_english_prefers_dialogue_over_sdh),
        ("OpenSubtitles rejects unrelated",   test_opensubtitles_rejects_unrelated_s01e01),
        ("OpenSubtitles rejects shared word", test_opensubtitles_rejects_shared_word_short_title),
        ("OpenSubtitles retains review item", test_opensubtitles_retains_rejected_candidate_for_review),
        ("Embedded Vietnamese selection",     test_embedded_vietnamese_text_track_selection),
        ("Media discovery newest folder",     test_media_discovery_searches_newest_folder),
        ("Media discovery ignores app dirs",  test_media_discovery_ignores_app_folders),
        ("Sync accepts split cues",           test_sync_accepts_aligned_split_cues),
        ("Sync rejects start-only match",     test_sync_rejects_start_only_match),
        ("Cue reference applies offset",      test_sync_to_reference_cues_applies_offset),
        ("Sync prefers clear offset",         test_sync_prefers_clear_offset_over_dense_no_shift_match),
        ("Sync applies stable micro-offset",  test_sync_applies_stable_micro_offset),
        ("Sync rejects mixed micro-offset",   test_sync_does_not_apply_inconsistent_micro_offset),
        ("Sync rejects local discontinuity",  test_sync_rejects_local_timing_discontinuity),
        ("External English validation",       test_external_english_validation_corrects_offset),
        ("Audio activity accepts overlap",    test_audio_activity_validation_accepts_overlap),
        ("Audio activity rejects bad refs",   test_audio_activity_validation_rejects_dense_or_wrong_timing),
        ("Merge retry uses alternate",        test_merge_retry_uses_alternate_subtitle),
        ("Mux transaction preserves output",  test_mux_transaction_preserves_finished_output_on_failure),
        ("Mux preflight checks disk space",    test_mux_preflight_rejects_low_disk_space),
        ("Recent merged launcher list",        test_recent_merged_files_are_sorted_and_filtered),
        ("MPV launch uses direct arguments",   test_mpv_launch_uses_detached_direct_arguments),
    ]

    width = 50
    print("=" * width)
    print(" Subtitle Pipeline — Chunker Test Suite")
    print("=" * width)

    passed = 0
    failed = 0
    errors: list[str] = []

    for name, test_fn in tests:
        try:
            ok, message = test_fn()
        except Exception as exc:  # noqa: BLE001
            ok = False
            message = f"EXCEPTION: {exc}"

        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {name}")
        if ok:
            print(f"         → {message}")
            passed += 1
        else:
            print(f"         ✗ {message}")
            errors.append(f"{name}: {message}")
            failed += 1

    print("-" * width)
    print(f"Results: {passed} passed, {failed} failed out of {len(tests)} tests")
    print("=" * width)

    if failed > 0:
        print("\nFailed tests:")
        for err in errors:
            print(f"  • {err}")
        sys.exit(1)
    else:
        print("\nAll tests PASSED.")


# ── Full pipeline example (commented out) ─────────────────────────────────────
#
# To run the full end-to-end pipeline on a real video file, uncomment and
# fill in the variables below, then run:  python test_pipeline.py
#
# ---------------------------------------------------------------------------
# import extractor
# import translator
# import muxer
#
# VIDEO_PATH = "/path/to/Your Anime Show S01E01.mkv"  # ← change this
# API_KEY    = "sk-..."                               # ← your OpenAI key
# MODEL      = "gpt-5.6-luna"
#
# def run_full_pipeline(video_path: str, api_key: str, model: str) -> None:
#     print(f"\n{'='*60}")
#     print("Step 1: Extracting English subtitles...")
#     srt_path = extractor.extract_english_subtitles(video_path)
#     print(f"  Extracted to: {srt_path}")
#
#     print("\nStep 2: Translating to Vietnamese...")
#     translated_content = translator.translate_srt(srt_path, api_key, model)
#
#     print("\nStep 3: Saving translated SRT...")
#     vi_srt_path = translator.save_translated_srt(translated_content, video_path)
#
#     print("\nStep 4: Muxing subtitle into video...")
#     output_video = muxer.mux_subtitles(video_path, srt_path, vi_srt_path)
#
#     print(f"\nDone! Output file: {output_video}")
#     print(f"      Subtitle SRT:  {vi_srt_path}")
#
# run_full_pipeline(VIDEO_PATH, API_KEY, MODEL)
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    run_all_tests()
