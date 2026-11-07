from app.rag.chunking import chunk_markdown


def test_chunks_split_on_headings():
    text = "# T\n\nintro\n\n## A\n\na-body\n\n## B\n\nb-body\n"
    chunks = chunk_markdown("cpu", text)
    ids = [c["id"] for c in chunks]
    assert "cpu#overview-v1" in ids
    assert "cpu#a-v1" in ids
    assert "cpu#b-v1" in ids
    assert all(c["metadata"]["source"] == "cpu" for c in chunks)
    assert all(c["metadata"]["version"] == 1 for c in chunks)


def test_long_section_splits():
    body = "\n\n".join([f"para {i} " + "x" * 400 for i in range(10)])
    chunks = chunk_markdown("mem", f"## Big\n\n{body}\n")
    assert len(chunks) > 1
    assert all(len(c["document"]) <= 1600 for c in chunks)
