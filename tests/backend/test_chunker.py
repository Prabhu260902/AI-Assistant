from services.chunker import chunk_text


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
