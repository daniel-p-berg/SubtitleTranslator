"""
chunker.py - Split SRT subtitle files into manageable chunks for API translation,
             then reassemble translated chunks back into a single valid SRT file.

SRT format recap:
  <index>
  <start> --> <end>
  <text line 1>
  [<text line 2> ...]
  <blank line>
"""

import re
from pathlib import Path


# Regex that matches a valid SRT timestamp line, e.g.:
#   00:01:23,456 --> 00:01:25,789
_TIMESTAMP_RE = re.compile(
    r"^\d{1,2}:\d{2}:\d{2}[,\.]\d{1,3}\s*-->\s*\d{1,2}:\d{2}:\d{2}[,\.]\d{1,3}"
)


def _parse_srt_blocks(srt_text: str) -> list[list[str]]:
    """
    Parse raw SRT text into a list of blocks.

    Each block is a list of non-empty lines belonging to one subtitle entry
    (index line, timestamp line, one or more text lines).  Blank lines
    between blocks are used as delimiters and are NOT included in the
    returned lists.

    Args:
        srt_text: Raw content of an SRT file as a string.

    Returns:
        A list of blocks, where each block is a list of strings (lines).
        Empty/whitespace-only input returns an empty list.
    """
    blocks: list[list[str]] = []
    current_block: list[str] = []

    for line in srt_text.splitlines():
        stripped = line.rstrip("\r")          # normalise Windows line endings
        if stripped.strip() == "":
            # Blank line signals the end of the current block
            if current_block:
                blocks.append(current_block)
                current_block = []
        else:
            current_block.append(stripped)

    # Flush the last block if the file doesn't end with a blank line
    if current_block:
        blocks.append(current_block)

    return blocks


def _block_to_str(block: list[str]) -> str:
    """
    Convert a block (list of lines) back to a SRT-formatted string.

    The block will be terminated by a trailing blank line so that adjacent
    blocks remain correctly separated when concatenated.

    Args:
        block: List of lines for one subtitle entry.

    Returns:
        A string representation ending with "\\n\\n".
    """
    return "\n".join(block) + "\n\n"


def chunk_srt(srt_path: str, max_lines_per_chunk: int = 200) -> list[str]:
    """
    Split an SRT file into chunks of at most *max_lines_per_chunk* subtitle
    blocks each.

    Blocks are never split in half: a chunk boundary always falls between
    complete subtitle entries.  The original block index numbers are
    preserved inside each chunk (they are not renumbered here; renumbering
    happens only in :func:`reassemble_srt`).

    Args:
        srt_path: Path to the source .srt file.
        max_lines_per_chunk: Maximum number of subtitle *blocks* per chunk
            (not raw text lines).  Defaults to 200.

    Returns:
        A list of strings.  Each string is a valid, self-contained SRT
        document covering up to *max_lines_per_chunk* subtitle blocks.

    Raises:
        FileNotFoundError: If the SRT file does not exist.
        ValueError: If *max_lines_per_chunk* is less than 1, or if the SRT
            file contains no parseable subtitle blocks.
    """
    if max_lines_per_chunk < 1:
        raise ValueError("max_lines_per_chunk must be >= 1")

    path = Path(srt_path)
    if not path.exists():
        raise FileNotFoundError(f"SRT file not found: '{srt_path}'")

    srt_text = path.read_text(encoding="utf-8-sig")  # strip BOM if present
    blocks = _parse_srt_blocks(srt_text)

    if not blocks:
        raise ValueError(f"No subtitle blocks found in '{srt_path}'")

    chunks: list[str] = []
    for start in range(0, len(blocks), max_lines_per_chunk):
        slice_ = blocks[start : start + max_lines_per_chunk]
        chunk_str = "".join(_block_to_str(b) for b in slice_)
        chunks.append(chunk_str)

    return chunks


def reassemble_srt(chunks: list[str]) -> str:
    """
    Join a list of translated SRT chunks into a single valid SRT string,
    renumbering all subtitle blocks sequentially from 1.

    This function is called after each chunk has been translated.  Because
    the translator may have preserved the original (non-sequential) block
    index numbers, this function discards them and assigns fresh sequential
    numbers so the final file is well-formed.

    Args:
        chunks: List of SRT-formatted strings, typically the translated
            versions of the chunks produced by :func:`chunk_srt`.

    Returns:
        A single SRT string with all blocks numbered from 1 upwards,
        suitable for writing directly to a .srt file.

    Raises:
        ValueError: If the combined chunks contain no parseable blocks.
    """
    all_blocks: list[list[str]] = []
    for chunk in chunks:
        all_blocks.extend(_parse_srt_blocks(chunk))

    if not all_blocks:
        raise ValueError("No subtitle blocks found in the provided chunks.")

    output_lines: list[str] = []
    for new_index, block in enumerate(all_blocks, start=1):
        if not block:
            continue

        # Replace the first line (original index) with the new sequential index
        reassembled_block = [str(new_index)] + block[1:]
        output_lines.append("\n".join(reassembled_block))
        output_lines.append("")  # blank separator line

    return "\n".join(output_lines)
