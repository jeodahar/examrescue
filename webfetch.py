"""webfetch.py - find a syllabus online and read it.

1) search_syllabus(exam)  -> list of web results (official sites / PDFs first)
2) fetch_text(url)        -> clean text from a web page or a PDF

Always check the result against the official exam website: syllabi change every year.
"""
import ipaddress
import re
import socket
from urllib.parse import urlparse

import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ExamRescueBot/1.0)"}
MAX_BYTES = 8_000_000
OFFICIAL_HINTS = (
    ".gov", ".edu", "pmc.edu.pk", "pmdc.pk", "fpsc.gov.pk", "ppsc.gop.pk", "nts.org.pk",
    "hec.gov.pk", "fbise.edu.pk", "ets.org", "collegeboard.org", "ielts.org", "mba.com",
)


def _score(r):
    host = urlparse(r["url"]).netloc.lower()
    text = (r["url"] + " " + r["title"]).lower()
    s = 0
    if "syllabus" in text:
        s += 2
    if r["url"].lower().split("?")[0].endswith(".pdf"):
        s += 1
    if any(h in host for h in OFFICIAL_HINTS):
        s += 3
    return s


def search_syllabus(exam, max_results=8):
    """Search the web (DuckDuckGo, no key needed). Returns [{title, url, snippet}]."""
    try:
        from ddgs import DDGS
    except ImportError:
        from duckduckgo_search import DDGS

    seen, out = set(), []
    for q in (f"{exam} syllabus", f"{exam} syllabus pdf official"):
        try:
            hits = DDGS().text(q, max_results=max_results)
        except Exception:
            continue
        for h in hits or []:
            url = h.get("href") or h.get("url")
            if not url or url in seen:
                continue
            seen.add(url)
            out.append({
                "title": (h.get("title") or url)[:120],
                "url": url,
                "snippet": (h.get("body") or "")[:200],
            })
    out.sort(key=_score, reverse=True)
    return out[:10]


def _is_safe_url(url):
    """Block non-web links and private/internal addresses."""
    try:
        p = urlparse(url)
        if p.scheme not in ("http", "https") or not p.hostname:
            return False
        for info in socket.getaddrinfo(p.hostname, None):
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                return False
        return True
    except Exception:
        return False


def fetch_text(url, limit=20000):
    """Download a web page or PDF and return clean text (max `limit` characters)."""
    if not _is_safe_url(url):
        raise ValueError("This link is not allowed or cannot be opened.")
    r = requests.get(url, headers=HEADERS, timeout=25, stream=True)
    r.raise_for_status()
    if not _is_safe_url(r.url):
        raise ValueError("The link redirected to a blocked address.")
    data = b""
    for chunk in r.iter_content(65536):
        data += chunk
        if len(data) > MAX_BYTES:
            break

    ctype = r.headers.get("content-type", "").lower()
    if "pdf" in ctype or url.lower().split("?")[0].endswith(".pdf") or data[:4] == b"%PDF":
        import fitz  # PyMuPDF

        doc = fitz.open(stream=data, filetype="pdf")
        text = "\n".join(page.get_text() for page in doc)
    else:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(data, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form", "noscript"]):
            tag.decompose()
        text = soup.get_text("\n")

    lines = [re.sub(r"\s+", " ", ln).strip() for ln in text.splitlines()]
    text = "\n".join(ln for ln in lines if len(ln) > 2)
    if len(text) < 50:
        raise ValueError("Could not read any text from this link (it may be a scanned PDF or need a login).")
    return text[:limit]
