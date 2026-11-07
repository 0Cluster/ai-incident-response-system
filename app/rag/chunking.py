"""Chunk markdown runbooks into section-level documents for RAG."""
import re

MAX_CHARS = 1500
CHUNK_OVERLAP_CHARS = 200


def slug(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-") or "section"


def _chunk_id(source: str, section: str, version: int, n: int = 0) -> str:
    if n > 0:
        return f"{source}#{section}-v{version}-{n}"
    return f"{source}#{section}-v{version}"


def _split_long_section(
    source: str,
    section: str,
    version: int,
    content: str,
    max_chars: int,
    overlap_chars: int,
) -> list[dict]:
    """Split a long section into overlapping chunks on paragraph boundaries."""
    chunks: list[dict] = []
    paras = [p for p in re.split(r"\n\s*\n", content) if p.strip()]
    buf = ""
    n = 0
    for p in paras:
        candidate = f"{buf}\n\n{p}" if buf else p
        if len(candidate) > max_chars and buf:
            chunks.append(
                {
                    "id": _chunk_id(source, section, version, n),
                    "document": buf.strip(),
                    "metadata": {"source": source, "section": section, "version": version},
                }
            )
            n += 1
            overlap = buf[-overlap_chars:] if overlap_chars > 0 else ""
            buf = f"{overlap}\n\n{p}".strip() if overlap else p
        else:
            buf = candidate
    if buf.strip():
        chunks.append(
            {
                "id": _chunk_id(source, section, version, n),
                "document": buf.strip(),
                "metadata": {"source": source, "section": section, "version": version},
            }
        )
    return chunks


def chunk_markdown(
    source: str,
    text: str,
    version: int = 1,
    max_chars: int = MAX_CHARS,
    overlap_chars: int | None = None,
) -> list[dict]:
    """Split on ## headings; long sections split on blank lines.

    Returns [{id, document, metadata}] with metadata {source, section, version}.
    Adjacent chunks within the same section overlap by ``overlap_chars`` so
    context is not lost at chunk boundaries. When ``overlap_chars`` is omitted,
    the configured ``CHUNK_OVERLAP_CHARS`` value is used.
    """
    if overlap_chars is None:
        try:
            from app.core.config import settings

            overlap_chars = settings.CHUNK_OVERLAP_CHARS
        except Exception:  # configuration must not break pure chunking helpers
            overlap_chars = CHUNK_OVERLAP_CHARS
    overlap_chars = max(0, min(overlap_chars, max_chars))

    parts = re.split(r"(?m)^##\s+(.*)$", text)
    # parts: [intro, heading1, body1, heading2, body2, ...]
    chunks: list[dict] = []
    intro = parts[0].strip() if parts else ""
    if intro:
        chunks.append(
            {
                "id": f"{source}#overview-v{version}",
                "document": intro[:max_chars],
                "metadata": {"source": source, "section": "overview", "version": version},
            }
        )
    i = 1
    while i < len(parts):
        heading = parts[i].strip()
        body = parts[i + 1] if i + 1 < len(parts) else ""
        section = slug(heading)
        content = f"## {heading}\n{body.strip()}".strip()
        if len(content) <= max_chars:
            if content:
                chunks.append(
                    {
                        "id": _chunk_id(source, section, version),
                        "document": content,
                        "metadata": {"source": source, "section": section, "version": version},
                    }
                )
        else:
            chunks.extend(
                _split_long_section(
                    source,
                    section,
                    version,
                    content,
                    max_chars=max_chars,
                    overlap_chars=overlap_chars,
                )
            )
        i += 2
    return [c for c in chunks if c["document"].strip()]
