"""Structural code chunking via Tree-sitter.

Uses `tree_sitter_language_pack.process()`, which chunks source along
syntax boundaries for whichever of its ~300 supported languages the file's
extension maps to. Files with no detected grammar (or where parsing fails,
e.g. no network to fetch a grammar not yet cached) fall back to fixed-size
line-window chunking — every file still gets indexed either way.

Tree-sitter chunk boundaries are byte-precise and can land mid-line (several
chunks can legitimately share a line when multiple statements sit on one
physical line), so `start_byte`/`end_byte` — not line numbers — are what
callers should use as the uniqueness key; line numbers are derived here
purely for human-readable citations.
"""

from dataclasses import dataclass

import tree_sitter_language_pack as tslp

CHUNK_MAX_CHARS = 2000
MIN_CHUNK_CHARS = 400
FALLBACK_CHUNK_LINES = 60


@dataclass
class Chunk:
    content: str
    start_line: int
    end_line: int
    start_byte: int
    end_byte: int
    language: str


def chunk_text(text: str, path: str) -> list[Chunk]:
    if not text.strip():
        return []

    language = tslp.detect_language_from_path(path)
    if language:
        chunks = _chunk_with_tree_sitter(text, language)
        if chunks:
            return chunks

    return _chunk_fixed_size(text, language or "text")


def _line_number(encoded: bytes, byte_offset: int) -> int:
    """1-indexed line containing the given UTF-8 byte offset."""
    return encoded.count(b"\n", 0, byte_offset) + 1


def _merge_small_spans(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Glue consecutive chunk spans together while the running span is still
    under MIN_CHUNK_CHARS. Some real-world files (observed directly: a 2500-
    line Dart file) make tree-sitter-language-pack's chunker return dozens of
    near-empty fragments — one as small as the single word "async" — instead
    of one coherent function body. A lone keyword or a bare class signature
    is useless as an independently-retrieved search result, so this merges
    runs of small neighbors into one bigger, actually-meaningful chunk.
    Always takes max(end)/min(start) rather than concatenating text, so it's
    correct even if spans overlap or have small gaps between them."""
    if not spans:
        return []
    merged = [spans[0]]
    for start, end in spans[1:]:
        last_start, last_end = merged[-1]
        if (last_end - last_start) < MIN_CHUNK_CHARS:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


def _chunk_with_tree_sitter(text: str, language: str) -> list[Chunk]:
    try:
        result = tslp.process(
            text,
            tslp.ProcessConfig(
                language=language,
                structure=False,
                imports=False,
                exports=False,
                chunk_max_size=CHUNK_MAX_CHARS,
            ),
        )
    except Exception:
        return []

    encoded = text.encode("utf-8")
    raw_spans = [
        (raw_chunk.start_byte, raw_chunk.end_byte) for raw_chunk in (result.chunks or []) if raw_chunk.content.strip()
    ]

    chunks = []
    for start_byte, end_byte in _merge_small_spans(raw_spans):
        content = encoded[start_byte:end_byte].decode("utf-8", errors="replace")
        if not content.strip():
            continue
        chunks.append(
            Chunk(
                content=content,
                start_line=_line_number(encoded, start_byte),
                end_line=_line_number(encoded, max(start_byte, end_byte - 1)),
                start_byte=start_byte,
                end_byte=end_byte,
                language=language,
            )
        )
    return chunks


def _chunk_fixed_size(text: str, language: str) -> list[Chunk]:
    lines = text.splitlines(keepends=True)
    chunks = []
    buffer: list[str] = []
    buffer_start_line = 1
    buffer_start_byte = 0
    byte_cursor = 0
    line_no = 1

    def flush(end_line: int, end_byte: int) -> None:
        content = "".join(buffer)
        if content.strip():
            chunks.append(
                Chunk(
                    content=content,
                    start_line=buffer_start_line,
                    end_line=end_line,
                    start_byte=buffer_start_byte,
                    end_byte=end_byte,
                    language=language,
                )
            )

    for line in lines:
        if not buffer:
            buffer_start_line = line_no
            buffer_start_byte = byte_cursor
        buffer.append(line)
        byte_cursor += len(line.encode("utf-8"))
        line_no += 1
        if len(buffer) >= FALLBACK_CHUNK_LINES:
            flush(line_no - 1, byte_cursor)
            buffer = []

    if buffer:
        flush(line_no - 1, byte_cursor)

    return chunks
