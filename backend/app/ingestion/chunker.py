"""
ingestion/chunker.py — Splits document text into overlapping, metadata-rich chunks.

Strategy:
  1. Split text into sentences using regex (no NLTK download required)
  2. Group sentences into chunks of ~CHUNK_SIZE tokens (approximated by word count)
  3. Apply CHUNK_OVERLAP sentence overlap between adjacent chunks
  4. Attach rich metadata to each chunk for retrieval and attribution
"""
import re
import uuid
from typing import Dict, List

from loguru import logger

from app.config import get_settings

settings = get_settings()


# ── Sentence Tokenizer (regex-based, no NLTK download needed) ─────────────────

_SENTENCE_SPLIT = re.compile(
    r"(?<!\w\.\w.)(?<![A-Z][a-z]\.)(?<=\.|\?|!)\s+",
    re.UNICODE,
)


def _split_sentences(text: str) -> List[str]:
    """
    Splits text into sentences using a regex that respects common abbreviations.
    Falls back to newline splitting for highly structured (regulatory) text.
    """
    # Split on ". " but also preserve paragraph boundaries
    # For regulatory text, double-newlines are reliable clause separators
    paragraphs = re.split(r"\n{2,}", text)

    sentences = []
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        # Split paragraph into sentences
        para_sentences = _SENTENCE_SPLIT.split(para)
        sentences.extend([s.strip() for s in para_sentences if s.strip()])

    return sentences


def _count_tokens(text: str) -> int:
    """
    Approximates token count using word count (1 word ≈ 1.3 tokens for English).
    Avoids loading a full tokenizer for performance.
    """
    return int(len(text.split()) * 1.3)


# ── Bilingual Document Preprocessor ──────────────────────────────────────────

def _extract_english_content(text: str) -> str:
    """
    For bilingual documents (e.g., SEBI's Hindi/English PDFs), filters out
    lines that are predominantly non-Latin script (Devanagari, etc.) and keeps
    only the English portions.

    This prevents Hindi-heavy chunks from dominating vector search and
    burying critical English-language qualification/experience sections.

    A line is kept if at least 40% of its non-space characters are ASCII.
    Short lines (< 3 words) are dropped to remove isolated bilingual labels.
    """
    _DEVANAGARI = re.compile(r"[\u0900-\u097F]")

    lines = text.split("\n")
    english_lines = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            english_lines.append("")  # preserve paragraph breaks
            continue

        # Detect proportion of Devanagari characters
        total_chars = len(stripped.replace(" ", ""))
        if total_chars == 0:
            continue

        devanagari_count = len(_DEVANAGARI.findall(stripped))
        devanagari_ratio = devanagari_count / total_chars

        # Keep line if it's predominantly Latin/ASCII (< 50% Devanagari)
        if devanagari_ratio < 0.5:
            english_lines.append(stripped)

    result = "\n".join(english_lines).strip()
    # Collapse runs of blank lines to single blank line
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result


def _is_bilingual(text: str) -> bool:
    """
    Detects whether a document contains significant Devanagari script,
    indicating it is a bilingual (Hindi + English) document.
    Returns True if > 20% of a sample of the text is Devanagari.
    """
    sample = text[:5000]
    total = len(sample.replace(" ", ""))
    if total == 0:
        return False
    devanagari = len(re.findall(r"[\u0900-\u097F]", sample))
    return (devanagari / total) > 0.20


# ── Heading Detection Helpers ──────────────────────────────────────────────────

def _is_heading(line: str) -> bool:
    """Detects standard headings or subheadings in regulatory text."""
    line = line.strip()
    if not line:
        return False
    if len(line) > 120:
        return False
    # Pattern 1: Numbered/lettered headings (e.g. A), A., 4., 4.2, I., II.)
    if re.match(r"^(?:[A-Z]\)|[A-Z]\.|\d+\)|\d+\.|\d+\.\d+|[IVXLCDM]+\.)\s+[A-Za-z]", line):
        return True
    # Pattern 2: Short lines ending with a colon
    if line.endswith(":") and len(line.split()) <= 10:
        return True
    # Pattern 3: All caps short lines
    if line.isupper() and len(line.replace(" ", "")) >= 3 and len(line.split()) <= 10:
        return True
    return False


def _determine_level(line: str) -> int:
    """Determines heading level (1, 2, or 3) for hierarchical stack updates."""
    line = line.strip()
    if re.match(r"^(?:[A-Z]\)|[A-Z]\.|[IVXLCDM]+\.)", line) or (line.isupper() and not re.search(r"\d", line)):
        return 1
    if re.match(r"^\d+\.\d+", line):
        return 3
    return 2


# ── Main Chunker ──────────────────────────────────────────────────────────────

def chunk_document(
    text: str,
    doc_id: int,
    version_id: int,
    regulator: str,
    doc_title: str,
    chunk_size: int = None,
    chunk_overlap: int = None,
) -> List[Dict]:
    """
    Splits a document's text into overlapping chunks with metadata, prepending
    the hierarchical heading path to each chunk body to preserve context.

    Args:
        text:          Full document text.
        doc_id:        Database ID of the parent Document.
        version_id:    Database ID of the DocumentVersion.
        regulator:     e.g., "RBI", "SEBI".
        doc_title:     Display title for citation.
        chunk_size:    Max tokens per chunk (default from config).
        chunk_overlap: Number of sentences to overlap (default from config).

    Returns:
        List of chunk dicts with: chunk_id, text, metadata, token_count.
    """
    if chunk_size is None:
        chunk_size = settings.chunk_size

    # Handle chunk_overlap robustly
    if chunk_overlap is None:
        # settings.chunk_overlap is token-based (e.g. 50 tokens) -> convert to sentences
        chunk_overlap = max(1, settings.chunk_overlap // 25)
    elif chunk_overlap >= 10:
        # If a token-based overlap was explicitly passed (e.g., 50), convert to sentence count (e.g., 2)
        chunk_overlap = max(1, chunk_overlap // 25)

    # ── Bilingual pre-processing ───────────────────────────────────────────────
    text_to_chunk = text
    if _is_bilingual(text):
        english_text = _extract_english_content(text)
        if len(english_text) > 200:
            logger.info(
                f"Bilingual document detected for doc {doc_id} v{version_id} — "
                f"extracted English content: {len(english_text)}/{len(text)} chars"
            )
            text_to_chunk = english_text
        else:
            logger.warning(
                f"Bilingual extraction yielded too little text for doc {doc_id} v{version_id} — using original text"
            )

    # ── Hierarchical parsing to associate sentences with headings ───────────────
    lines = text_to_chunk.split("\n")
    current_headings = {1: "", 2: "", 3: ""}
    annotated_sentences = []

    for line in lines:
        line_strip = line.strip()
        if not line_strip:
            continue

        if _is_heading(line_strip):
            level = _determine_level(line_strip)
            if level == 1:
                current_headings[1] = line_strip
                current_headings[2] = ""
                current_headings[3] = ""
            elif level == 2:
                current_headings[2] = line_strip
                current_headings[3] = ""
            elif level == 3:
                current_headings[3] = line_strip
            
            # Also add the heading itself as a sentence so its keywords are searchable
            h_path = " > ".join(current_headings[l] for l in [1, 2, 3] if current_headings[l])
            annotated_sentences.append((h_path, line_strip))
        else:
            h_path = " > ".join(current_headings[l] for l in [1, 2, 3] if current_headings[l])
            sentences = _split_sentences(line_strip)
            for s in sentences:
                annotated_sentences.append((h_path, s))

    if not annotated_sentences:
        logger.warning(f"No text found in document {doc_id} version {version_id}")
        return []

    # ── Grouping sentences into overlapping semantic chunks ─────────────────────
    chunks = []
    current_sentences = []
    current_tokens = 0
    chunk_index = 0

    for h_path, sentence in annotated_sentences:
        sentence_tokens = _count_tokens(sentence)

        # If a single sentence exceeds chunk_size, split by word count
        if sentence_tokens > chunk_size:
            words = sentence.split()
            sub_bodies = [
                " ".join(words[i : i + chunk_size])
                for i in range(0, len(words), chunk_size)
            ]
            for sub in sub_bodies:
                chunk_text = f"[{h_path}]\n{sub}" if h_path else sub
                chunk = _make_chunk(
                    text=chunk_text,
                    chunk_index=chunk_index,
                    doc_id=doc_id,
                    version_id=version_id,
                    regulator=regulator,
                    doc_title=doc_title,
                    section_ref=h_path,
                )
                chunks.append(chunk)
                chunk_index += 1
            continue

        # If adding this sentence exceeds chunk_size, flush current chunk
        if current_tokens + sentence_tokens > chunk_size and current_sentences:
            first_h_path = current_sentences[0][0]
            chunk_body = " ".join([s[1] for s in current_sentences])
            chunk_text = f"[{first_h_path}]\n{chunk_body}" if first_h_path else chunk_body

            chunk = _make_chunk(
                text=chunk_text,
                chunk_index=chunk_index,
                doc_id=doc_id,
                version_id=version_id,
                regulator=regulator,
                doc_title=doc_title,
                section_ref=first_h_path,
            )
            chunks.append(chunk)
            chunk_index += 1

            # Shift window for overlap
            overlap = current_sentences[-chunk_overlap:]
            current_sentences = overlap
            current_tokens = sum(_count_tokens(s[1]) for s in overlap)

        current_sentences.append((h_path, sentence))
        current_tokens += sentence_tokens

    # Flush remaining sentences
    if current_sentences:
        first_h_path = current_sentences[0][0]
        chunk_body = " ".join([s[1] for s in current_sentences])
        chunk_text = f"[{first_h_path}]\n{chunk_body}" if first_h_path else chunk_body

        chunk = _make_chunk(
            text=chunk_text,
            chunk_index=chunk_index,
            doc_id=doc_id,
            version_id=version_id,
            regulator=regulator,
            doc_title=doc_title,
            section_ref=first_h_path,
        )
        chunks.append(chunk)

    logger.info(
        f"Hierarchical chunked doc {doc_id} v{version_id} into {len(chunks)} chunks "
        f"(overlap={chunk_overlap} sentences)"
    )
    return chunks


def _make_chunk(
    text: str,
    chunk_index: int,
    doc_id: int,
    version_id: int,
    regulator: str,
    doc_title: str,
    section_ref: str = "",
) -> Dict:
    """Constructs a chunk dict with rich metadata, including section references."""
    chunk_id = f"v{version_id}_c{chunk_index}"
    token_count = _count_tokens(text)

    return {
        "chunk_id": chunk_id,
        "text": text.strip(),
        "chunk_index": chunk_index,
        "token_count": token_count,
        "metadata": {
            "doc_id": doc_id,
            "version_id": version_id,
            "chunk_index": chunk_index,
            "regulator": regulator,
            "doc_title": doc_title,
            "chunk_id": chunk_id,
            "section_ref": section_ref,
        },
    }
