"""
diffing/clause_splitter.py — Splits regulatory document text into clause-level units.

Regulatory documents follow predictable structures:
  1.    Major sections
  1.1   Sub-sections
  (a)   Lettered items
  (i)   Roman numeral sub-items

This module uses regex patterns + heuristics to extract clause-level units
from both structured (numbered) and unstructured regulatory text.
"""
import re
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Clause:
    """
    A single clause extracted from a regulatory document.

    Attributes:
        id:          Sequential index within the document.
        text:        Full clause text (trimmed).
        section_ref: Detected section reference (e.g., "1.2", "(a)", "Clause 5").
        level:       Nesting level (0=top, 1=sub, 2=sub-sub).
    """
    id: int
    text: str
    section_ref: Optional[str] = None
    level: int = 0


# ── Regex Patterns ────────────────────────────────────────────────────────────

# Matches patterns like: 1. | 1.1 | 1.1.1 | 1.1.1.1
_NUMERIC_SECTION = re.compile(
    r"^(\d+(?:\.\d+){0,3}\.?)\s+(.+)",
    re.MULTILINE,
)

# Matches patterns like: (a) | (b) | (i) | (ii) | (iii)
_ALPHA_ITEM = re.compile(
    r"^\s*\(([a-z]{1,3}|[ivxlc]+)\)\s+(.+)",
    re.MULTILINE,
)

# Matches "Clause N" or "Section N" headers
_CLAUSE_HEADER = re.compile(
    r"^(Clause|Section|Article|Chapter|Part|Paragraph)\s+(\d+[\w.]*)",
    re.MULTILINE | re.IGNORECASE,
)

# Matches lines that are clearly headers (short, title-case, no period at end)
_HEADER_LINE = re.compile(
    r"^[A-Z][A-Za-z\s,/&-]{5,80}$",
    re.MULTILINE,
)

# Minimum characters for a clause to be meaningful
MIN_CLAUSE_LENGTH = 40


def split_into_clauses(text: str) -> List[Clause]:
    """
    Splits regulatory document text into clause-level units.

    Strategy:
      1. Try structured extraction (numbered sections, lettered items)
      2. Fall back to paragraph-level splitting for unstructured text
      3. Apply minimum length filter to remove headers/page numbers

    Args:
        text: Full document text from the parser.

    Returns:
        List of Clause objects, in document order.
    """
    clauses = _extract_structured_clauses(text)

    if len(clauses) < 3:
        # Structured extraction found very little — fall back to paragraph splitting
        clauses = _extract_paragraph_clauses(text)

    # Filter out very short clauses (headers, page numbers)
    clauses = [c for c in clauses if len(c.text.strip()) >= MIN_CLAUSE_LENGTH]

    # Re-index after filtering
    for i, clause in enumerate(clauses):
        clause.id = i

    return clauses


def _extract_structured_clauses(text: str) -> List[Clause]:
    """
    Attempts to extract clauses using numbered/lettered structure markers.
    Uses split-on-boundary approach: everything between two markers is one clause.
    """
    # Find all boundary positions (where a new section/clause starts)
    boundaries: List[tuple] = []  # (start_pos, section_ref, level)

    for match in _NUMERIC_SECTION.finditer(text):
        boundaries.append((match.start(), match.group(1), 0))

    for match in _ALPHA_ITEM.finditer(text):
        boundaries.append((match.start(), f"({match.group(1)})", 1))

    for match in _CLAUSE_HEADER.finditer(text):
        boundaries.append((match.start(), f"{match.group(1)} {match.group(2)}", 0))

    if len(boundaries) < 3:
        return []

    # Sort boundaries by position
    boundaries.sort(key=lambda x: x[0])

    clauses = []
    for i, (start, section_ref, level) in enumerate(boundaries):
        end = boundaries[i + 1][0] if i + 1 < len(boundaries) else len(text)
        clause_text = text[start:end].strip()

        if clause_text:
            clauses.append(
                Clause(
                    id=i,
                    text=clause_text,
                    section_ref=section_ref,
                    level=level,
                )
            )

    return clauses


def _extract_paragraph_clauses(text: str) -> List[Clause]:
    """
    Fallback: splits on double newlines (paragraph boundaries).
    Used for unstructured regulatory text.
    """
    paragraphs = re.split(r"\n{2,}", text)
    clauses = []

    for i, para in enumerate(paragraphs):
        para = para.strip()
        if not para:
            continue

        # Try to detect a section reference in the first line
        first_line = para.split("\n")[0].strip()
        section_ref = None

        if _NUMERIC_SECTION.match(first_line):
            m = _NUMERIC_SECTION.match(first_line)
            section_ref = m.group(1)
        elif _CLAUSE_HEADER.match(first_line):
            m = _CLAUSE_HEADER.match(first_line)
            section_ref = f"{m.group(1)} {m.group(2)}"

        clauses.append(
            Clause(
                id=i,
                text=para,
                section_ref=section_ref,
                level=0,
            )
        )

    return clauses
