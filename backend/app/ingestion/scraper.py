"""
ingestion/scraper.py — Scrapes public RBI and SEBI circular listing pages.

Fetches the list of recent circulars from each regulator's public HTML page,
extracts title, date, URL, and PDF download link for each document.

No authentication or session cookies are required — these are public pages.
Respects the structure of the HTML as of mid-2024; update selectors if pages change.
"""
import re
from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup
from loguru import logger

# ── Base URLs ────────────────────────────────────────────────────────────────
RBI_BASE = "https://rbi.org.in"
RBI_CIRCULAR_URL = "https://rbi.org.in/Scripts/BS_CircularIndexDisplay.aspx"

SEBI_BASE = "https://www.sebi.gov.in"
SEBI_CIRCULAR_URL = (
    "https://www.sebi.gov.in/sebiweb/other/OtherAction.do"
    "?doListing=yes&sid=3&ssid=15&smid=0"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

TIMEOUT = httpx.Timeout(30.0, connect=10.0)


# ── Main Scraper Entry ────────────────────────────────────────────────────────

def scrape_circulars(
    regulators: List[str] = None,
    max_docs: int = 10,
) -> List[Dict]:
    """
    Scrapes circular listings from the specified regulators.

    Args:
        regulators: List of regulator codes. Defaults to ["RBI", "SEBI"].
        max_docs:   Maximum number of documents to return per regulator.

    Returns:
        List of dicts with keys: regulator, title, url, pdf_url, date, doc_type.
    """
    if regulators is None:
        regulators = ["RBI", "SEBI"]

    results = []

    with httpx.Client(headers=HEADERS, timeout=TIMEOUT, follow_redirects=True) as client:
        for reg in regulators:
            reg = reg.upper()
            try:
                if reg == "RBI":
                    docs = _scrape_rbi(client, max_docs)
                elif reg == "SEBI":
                    docs = _scrape_sebi(client, max_docs)
                else:
                    logger.warning(f"Unknown regulator: {reg}, skipping.")
                    continue

                for doc in docs:
                    doc["regulator"] = reg
                results.extend(docs)
                logger.info(f"✅ Scraped {len(docs)} documents from {reg}")

            except Exception as exc:
                logger.error(f"Failed to scrape {reg}: {exc}")

    return results


# ── RBI Scraper ───────────────────────────────────────────────────────────────

def _scrape_rbi(client: httpx.Client, max_docs: int) -> List[Dict]:
    """
    Scrapes the RBI circular index page.
    Returns list of circular metadata dicts.
    """
    logger.info(f"[SCRAPER RBI] Fetching circular listings from: {RBI_CIRCULAR_URL}")
    resp = client.get(RBI_CIRCULAR_URL)
    logger.info(f"[SCRAPER RBI] Received HTTP Status: {resp.status_code}")
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "lxml")
    results = []

    # RBI uses a table with rows of circulars
    logger.info("[SCRAPER RBI] Locating main circulars table element...")
    table = soup.find("table", {"id": "myTable"}) or soup.find("table", class_="tablebg")
    if not table:
        logger.info("[SCRAPER RBI] Primary table select failed. Scanning all tables in page...")
        # Fallback: find any table with circular links
        tables = soup.find_all("table")
        table = next(
            (t for t in tables if t.find("a", href=re.compile(r"\.pdf|Notification|Circular", re.I))),
            None,
        )

    if not table:
        logger.warning("[SCRAPER RBI] Could not find any circular table element, attempting link-only index scan.")
        return _scrape_rbi_fallback(soup, max_docs)

    rows = table.find_all("tr")[1:]  # skip header row

    for row in rows[:max_docs]:
        cells = row.find_all("td")
        if len(cells) < 2:
            continue

        link_tag = cells[0].find("a") or cells[1].find("a")
        if not link_tag:
            continue

        href = link_tag.get("href", "")
        url = urljoin(RBI_BASE, href)
        title = link_tag.get_text(strip=True) or f"RBI Circular {len(results)+1}"

        # Try to extract date from adjacent cell
        date_str = cells[-1].get_text(strip=True) if len(cells) > 1 else ""
        date = _parse_date(date_str)

        pdf_url = url if url.endswith(".pdf") else None

        results.append({
            "title": title,
            "url": url,
            "pdf_url": pdf_url,
            "date": date.isoformat() if date else None,
            "doc_type": "circular",
        })

    return results


def _scrape_rbi_fallback(soup: BeautifulSoup, max_docs: int) -> List[Dict]:
    """
    Fallback RBI scraper: extracts all links that look like circulars.
    Used when the table structure has changed.
    """
    results = []
    seen = set()

    for link in soup.find_all("a", href=True):
        href = link["href"]
        if not re.search(r"Circular|Notification|Guideline|\.pdf", href, re.I):
            continue

        url = urljoin(RBI_BASE, href)
        if url in seen:
            continue
        seen.add(url)

        title = link.get_text(strip=True) or url.split("/")[-1]
        if len(title) < 5:
            continue

        results.append({
            "title": title,
            "url": url,
            "pdf_url": url if url.endswith(".pdf") else None,
            "date": None,
            "doc_type": "circular",
        })

        if len(results) >= max_docs:
            break

    return results


# ── SEBI Scraper ──────────────────────────────────────────────────────────────

def _scrape_sebi(client: httpx.Client, max_docs: int) -> List[Dict]:
    """
    Scrapes the SEBI circular listing page.
    Returns list of circular metadata dicts.
    """
    logger.info(f"[SCRAPER SEBI] Requesting circular listings from: {SEBI_CIRCULAR_URL}")
    resp = client.get(SEBI_CIRCULAR_URL)
    logger.info(f"[SCRAPER SEBI] Received HTTP Status: {resp.status_code}")
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "lxml")
    results = []

    # SEBI uses a list of links in a content div
    logger.info("[SCRAPER SEBI] Locating page content container...")
    content_div = (
        soup.find("div", {"id": "nav-tabContent"})
        or soup.find("div", class_="content")
        or soup.find("div", id="doListing")
        or soup.body
    )
    logger.info(f"[SCRAPER SEBI] Content container element ID/Class resolved to parent tag: {content_div.name if content_div else 'None'}")

    links = content_div.find_all("a", href=re.compile(r"\.pdf|sebi\.gov\.in", re.I)) if content_div else []
    logger.info(f"[SCRAPER SEBI] Found {len(links)} links matching selector pattern.")

    for link in links[:max_docs]:
        href = link.get("href", "")
        url = urljoin(SEBI_BASE, href) if not href.startswith("http") else href
        title = link.get_text(strip=True)

        if not title or len(title) < 5:
            clean_url = url.rstrip("/")
            title = clean_url.split("/")[-1].replace("-", " ").replace("_", " ") if clean_url else ""
            if not title or len(title) < 5:
                title = "SEBI Circular"

        # Try to find date near this link
        parent = link.parent
        date_text = parent.get_text(" ", strip=True) if parent else ""
        date = _parse_date(date_text)

        results.append({
            "title": title,
            "url": url,
            "pdf_url": url if url.endswith(".pdf") else None,
            "date": date.isoformat() if date else None,
            "doc_type": "circular",
        })

    if not results:
        logger.warning("SEBI: Primary selector found no results, trying fallback.")
        results = _scrape_sebi_fallback(soup, max_docs)

    return results


def _scrape_sebi_fallback(soup: BeautifulSoup, max_docs: int) -> List[Dict]:
    """Fallback: pull any links from SEBI page that look like circulars."""
    results = []
    seen = set()

    for link in soup.find_all("a", href=True):
        href = link["href"]
        text = link.get_text(strip=True)

        if len(text) < 10:
            continue
        if "circular" not in text.lower() and "circular" not in href.lower():
            if not href.endswith(".pdf"):
                continue

        url = urljoin(SEBI_BASE, href) if not href.startswith("http") else href
        if url in seen:
            continue
        seen.add(url)

        results.append({
            "title": text[:300],
            "url": url,
            "pdf_url": url if url.endswith(".pdf") else None,
            "date": None,
            "doc_type": "circular",
        })

        if len(results) >= max_docs:
            break

    return results


# ── Date Parsing Helper ───────────────────────────────────────────────────────

_DATE_PATTERNS = [
    (r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", "%d/%m/%Y"),
    (r"(\w+ \d{1,2},? \d{4})", "%B %d, %Y"),
    (r"(\d{4}-\d{2}-\d{2})", "%Y-%m-%d"),
    (r"(\d{1,2} \w+ \d{4})", "%d %B %Y"),
]


def _parse_date(text: str) -> Optional[datetime]:
    """Attempts to extract a date from a text string using common patterns."""
    for pattern, fmt in _DATE_PATTERNS:
        match = re.search(pattern, text)
        if match:
            try:
                raw = match.group(0).replace(",", "")
                return datetime.strptime(raw.strip(), fmt.replace(",", ""))
            except ValueError:
                continue
    return None


def download_document(url: str, dest_path: str) -> bool:
    """
    Downloads a document (PDF or HTML) from a URL to a local file.

    Args:
        url:       Source URL.
        dest_path: Local filesystem path to save to.

    Returns:
        True on success, False on failure.
    """
    try:
        logger.info(f"[DOWNLOADER] Initiating request to download: {url}")
        with httpx.Client(headers=HEADERS, timeout=TIMEOUT, follow_redirects=True) as client:
            resp = client.get(url)
            logger.info(f"[DOWNLOADER] Download HTTP Status: {resp.status_code}")
            resp.raise_for_status()

            with open(dest_path, "wb") as f:
                f.write(resp.content)

            logger.info(f"[DOWNLOADER] Success: saved {url} → {dest_path} ({len(resp.content)/1024:.1f} KB)")
            return True

    except Exception as e:
        logger.error(f"[DOWNLOADER] Exception occurred while downloading from {url}: {e}")
        return False
