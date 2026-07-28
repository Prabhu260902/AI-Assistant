from services.chunker import MIN_CHUNK_CHARS, _merge_small_spans, chunk_text


def test_python_multiple_functions_produce_multiple_chunks():
    src = "def foo():\n    return 1\n\n\ndef bar():\n    return 2\n"

    chunks = chunk_text(src, "example.py")

    assert len(chunks) >= 1
    assert all(c.language == "python" for c in chunks)
    assert all(c.start_line >= 1 and c.end_line >= c.start_line for c in chunks)
    combined = "".join(c.content for c in chunks)
    assert "def foo" in combined
    assert "def bar" in combined


def test_large_function_is_split_into_multiple_chunks():
    body_lines = "\n".join(f"    x{i} = {i}" for i in range(300))
    src = f"def big():\n{body_lines}\n    return x0\n"

    chunks = chunk_text(src, "big.py")

    assert len(chunks) > 1


def test_unmapped_extension_falls_back_to_fixed_size_chunking():
    src = "\n".join(f"line {i}" for i in range(150))

    chunks = chunk_text(src, "notes.unknownext123")

    assert len(chunks) >= 2
    assert chunks[0].language == "text"
    assert chunks[0].start_line == 1


def test_empty_file_produces_no_chunks():
    assert chunk_text("   \n\n", "empty.py") == []


def test_merge_small_spans_glues_tiny_fragments_forward():
    """Regression test: a real 2500-line Dart file made tree-sitter-language-
    pack's chunker return 262 chunks, several under 10 characters — one was
    literally the single word "async". A lone keyword or a bare class
    signature carries no useful information as its own retrieved search
    result, so runs of undersized neighbors should be glued together."""
    spans = [(0, 10), (10, 16), (16, 500), (500, 505), (505, 510), (510, 1200)]

    merged = _merge_small_spans(spans)

    assert merged == [(0, 500), (500, 1200)]
    assert all((end - start) >= MIN_CHUNK_CHARS for start, end in merged)


def test_merge_small_spans_leaves_already_large_spans_untouched():
    spans = [(0, 1000), (1000, 1500), (1500, 1900)]

    assert _merge_small_spans(spans) == spans


def test_merge_small_spans_handles_empty_input():
    assert _merge_small_spans([]) == []
