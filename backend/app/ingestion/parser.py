"""
ingestion/parser.py — Converts PDF and HTML documents to clean plain text.

PDF parsing uses PyMuPDF (fitz) which handles scanned-light PDFs and
preserves structural hints (page numbers, headers).

HTML parsing uses BeautifulSoup4 with aggressive boilerplate stripping.
"""
import re
from typing import Dict

import fitz  # PyMuPDF
import httpx
from bs4 import BeautifulSoup
from loguru import logger


def parse_pdf(file_path: str) -> Dict:
    """
    Extracts clean text from a PDF file.

    Args:
        file_path: Absolute path to the PDF file.

    Returns:
        Dict with keys: text (str), page_count (int), metadata (dict).
    """
    try:
        doc = fitz.open(file_path)
        pages = []

        for page_num in range(len(doc)):
            page = doc[page_num]
            # Extract text with layout preservation
            text = page.get_text("text")
            # Clean up hyphenation across lines
            text = re.sub(r"-\n", "", text)
            # Normalize whitespace within lines but preserve paragraph breaks
            text = re.sub(r"[ \t]+", " ", text)
            text = re.sub(r"\n{3,}", "\n\n", text)
            pages.append(text.strip())

        full_text = "\n\n".join(pages)
        full_text = _clean_text(full_text)

        metadata = {
            "title": doc.metadata.get("title", ""),
            "author": doc.metadata.get("author", ""),
            "creator": doc.metadata.get("creator", ""),
        }
        doc.close()

        logger.info(f"Parsed PDF: {file_path} ({len(pages)} pages, {len(full_text)} chars)")
        return {
            "text": full_text,
            "page_count": len(pages),
            "metadata": metadata,
        }

    except Exception as exc:
        logger.error(f"Failed to parse PDF {file_path}: {exc}")
        raise


def parse_pdf_from_bytes(content: bytes, source_name: str = "document") -> Dict:
    """
    Parses a PDF directly from bytes (e.g., downloaded content).

    Args:
        content:     Raw PDF bytes.
        source_name: A label for logging.

    Returns:
        Same structure as parse_pdf().
    """
    try:
        doc = fitz.open(stream=content, filetype="pdf")
        pages = []

        for page_num in range(len(doc)):
            page = doc[page_num]
            text = page.get_text("text")
            text = re.sub(r"-\n", "", text)
            text = re.sub(r"[ \t]+", " ", text)
            text = re.sub(r"\n{3,}", "\n\n", text)
            pages.append(text.strip())

        full_text = _clean_text("\n\n".join(pages))
        page_count = len(pages)
        doc.close()

        logger.info(f"Parsed PDF bytes from {source_name}: {page_count} pages, {len(full_text)} chars")
        return {
            "text": full_text,
            "page_count": page_count,
            "metadata": {},
        }

    except Exception as exc:
        logger.error(f"Failed to parse PDF bytes from {source_name}: {exc}")
        raise


def parse_html(html_content: str, base_url: str = "") -> Dict:
    """
    Extracts clean text from an HTML string.
    Strips navigation, scripts, styles, headers, and footers.

    Args:
        html_content: Raw HTML string.
        base_url:     Optional base URL for context (used in logging).

    Returns:
        Dict with keys: text (str), page_count (1 for HTML).
    """
    try:
        soup = BeautifulSoup(html_content, "lxml")

        # Remove boilerplate elements
        for tag in soup(["script", "style", "nav", "header", "footer",
                         "noscript", "iframe", "button", "input"]):
            tag.decompose()

        # Remove elements with common navigation/ad class names
        for elem in soup.find_all(class_=re.compile(
            r"nav|menu|sidebar|footer|header|breadcrumb|social|share|ad|banner|cookie",
            re.I,
        )):
            elem.decompose()

        # Extract main content — prefer semantic tags
        main = (
            soup.find("main")
            or soup.find("article")
            or soup.find("div", {"id": re.compile(r"content|main|body", re.I)})
            or soup.find("div", class_=re.compile(r"content|main|body", re.I))
            or soup.body
        )

        if main:
            text = main.get_text(separator="\n", strip=True)
        else:
            text = soup.get_text(separator="\n", strip=True)

        text = _clean_text(text)
        logger.info(f"Parsed HTML from {base_url}: {len(text)} chars")

        return {
            "text": text,
            "page_count": 1,
            "metadata": {"title": soup.title.string if soup.title else ""},
        }

    except Exception as exc:
        logger.error(f"Failed to parse HTML from {base_url}: {exc}")
        raise


def parse_url(url: str) -> Dict:
    """
    Fetches and parses a URL — handles PDF or HTML automatically.

    Args:
        url: The URL to fetch.

    Returns:
        Parsed document dict.
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
    }

    with httpx.Client(headers=headers, timeout=30.0, follow_redirects=True) as client:
        resp = client.get(url)
        resp.raise_for_status()

    content_type = resp.headers.get("content-type", "")

    if "pdf" in content_type or url.lower().endswith(".pdf"):
        return parse_pdf_from_bytes(resp.content, source_name=url)
    else:
        # Check if the HTML is a wrapper page containing a PDF link (very common for SEBI/RBI circulars/careers)
        html_text = resp.text
        
        # 1. Search for absolute PDF URLs
        pdf_url_match = re.search(r"https?://[^\s'\"\(\)]+\.pdf", html_text, re.IGNORECASE)
        pdf_link = None
        if pdf_url_match:
            pdf_link = pdf_url_match.group(0)
        else:
            # 2. Search for relative PDF URLs in href or src attributes
            pdf_href_match = re.search(r"(?:href|src|url)\s*=\s*['\"]([^\s'\"\(]+\.pdf)['\"]", html_text, re.IGNORECASE)
            if pdf_href_match:
                pdf_link = pdf_href_match.group(1)
            else:
                # 3. Fallback: search for any relative PDF path quoted in scripts
                pdf_quote_match = re.search(r"['\"]([^\s'\"\(]+\.pdf)['\"]", html_text, re.IGNORECASE)
                if pdf_quote_match:
                    pdf_link = pdf_quote_match.group(1)

        if pdf_link:
            from urllib.parse import urljoin
            pdf_url = urljoin(url, pdf_link)
            logger.info(f"[PARSER] Found referenced PDF in HTML wrapper: {pdf_url}. Fetching and parsing PDF instead.")
            try:
                with httpx.Client(headers=headers, timeout=30.0, follow_redirects=True) as client2:
                    resp2 = client2.get(pdf_url)
                    resp2.raise_for_status()
                return parse_pdf_from_bytes(resp2.content, source_name=pdf_url)
            except Exception as e:
                logger.warning(f"[PARSER] Failed to parse referenced PDF from {pdf_url}: {e}. Falling back to HTML.")

        return parse_html(resp.text, base_url=url)


# ── Text Cleaning ─────────────────────────────────────────────────────────────

def _clean_text(text: str) -> str:
    """
    Applies universal text cleanup:
    - Strips non-printable characters
    - Normalizes Unicode whitespace
    - Removes excessive blank lines
    - Strips control characters
    """
    # Replace non-breaking spaces and other Unicode whitespace with regular space
    text = re.sub(r"[\xa0\u200b\u2003\u2002\u2001\u2000\ufeff]", " ", text)

    # Strip control characters (except newline and tab)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)

    # Remove lines that are just punctuation/numbers with no content
    lines = text.split("\n")
    lines = [l for l in lines if len(l.strip()) > 2 or l.strip() == ""]

    text = "\n".join(lines)

    # Collapse 3+ blank lines to 2
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()
