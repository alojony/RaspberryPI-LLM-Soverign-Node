def chunk_text(text: str, chunk_size: int = 1600, overlap: int = 400) -> list[dict]:
    if len(text) <= chunk_size:
        return [{"text": text, "char_start": 0, "char_end": len(text)}]

    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append({"text": text[start:end], "char_start": start, "char_end": min(end, len(text))})
        if end >= len(text):
            break
        start = end - overlap
    return chunks
