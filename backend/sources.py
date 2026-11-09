"""Signal connectors.

Every piece of evidence in a run comes from here, with a real URL and a real
publication date. The LLM never produces a citation -- it can only select from
what these functions actually fetched. That is what makes the "every claim links
to a source" rule enforceable rather than aspirational.

Connectors are free and keyless on purpose, so the demo has no paid dependency:
  google_news  -- news.google.com RSS search (fresh, dated, publisher-attributed)
  bing_news    -- bing.com/news RSS (a different index; reaches further back, so
                  it is what actually exercises the staleness filter)
  hackernews   -- hn.algolia.com (dev-tool and infra chatter)
  duckduckgo   -- html.duckduckgo.com (profiles, careers pages, long tail).
                  Best-effort only: DDG throttles scrapers and answers 202 with
                  an empty page, so a run must never depend on it.
  fixtures     -- a deterministic local corpus, for demo-safe replay
"""
from __future__ import annotations

import hashlib
import re
import urllib.parse
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from concurrent.futures import ThreadPoolExecutor
from typing import Iterable, Optional
from xml.etree import ElementTree

import requests

from . import config
from .models import Evidence

UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    )
}

# Publisher tiers drive the source_quality score. Not exhaustive -- a working
# heuristic an operator can edit.
TIER1 = {
    "reuters.com", "bloomberg.com", "ft.com", "wsj.com", "techcrunch.com",
    "economictimes.indiatimes.com", "livemint.com", "moneycontrol.com",
    "business-standard.com", "forbes.com", "cnbc.com", "theinformation.com",
    "entrackr.com", "inc42.com", "yourstory.com", "venturebeat.com",
}
TIER2 = {
    "medium.com", "substack.com", "prnewswire.com", "businesswire.com",
    "globenewswire.com", "news.ycombinator.com",
}


def _hid(*parts: str) -> str:
    return "ev_" + hashlib.sha1("|".join(parts).encode("utf-8", "ignore")).hexdigest()[:10]


def _domain(url: str) -> str:
    try:
        host = urllib.parse.urlparse(url).netloc.lower()
        return host[4:] if host.startswith("www.") else host
    except Exception:
        return ""


def _age_days(iso: Optional[str]) -> Optional[int]:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0, (datetime.now(timezone.utc) - dt).days)
    except Exception:
        return None


def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    for bad, good in (
        ("&amp;", "&"), ("&quot;", '"'), ("&#39;", "'"),
        ("&lt;", "<"), ("&gt;", ">"), ("&nbsp;", " "),
    ):
        text = text.replace(bad, good)
    return re.sub(r"\s+", " ", text).strip()


def _unwrap(url: str) -> str:
    """Pull the real article URL out of a redirector.

    Bing News RSS hands back bing.com/news/apiclick.aspx?...&url=<encoded>, which
    would make every citation read "bing.com" and flatten the source-quality
    score. Google News uses an opaque base64 path, so those stay wrapped -- they
    still resolve, and the publisher name comes from the RSS <source> tag.
    """
    try:
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    except Exception:
        return url
    for key in ("url", "uddg", "u"):
        inner = qs.get(key, [""])[0]
        if inner.startswith(("http://", "https://")):
            return urllib.parse.unquote(inner)
    return url


def source_quality(url: str, publisher: str) -> int:
    """0-15. Official company domains and tier-1 press outrank aggregators."""
    dom = _domain(url)
    pub = (publisher or "").lower()
    if dom in TIER1 or any(t in pub for t in ("reuters", "bloomberg", "techcrunch", "mint")):
        return 15
    if dom.endswith((".gov", ".gov.in", ".edu")):
        return 15
    if dom.endswith(("linkedin.com", "crunchbase.com")):
        return 11
    if dom in TIER2:
        return 8
    if dom:
        return 10
    return 5


# ------------------------------------------------------------------ connectors

def _parse_rss(xml: bytes, *, connector: str, query: str, limit: int) -> list[Evidence]:
    """Shared RSS -> Evidence mapping for the two news connectors."""
    try:
        items = ElementTree.fromstring(xml).findall(".//item")
    except ElementTree.ParseError:
        return []

    out: list[Evidence] = []
    for item in items[:limit]:
        title = _clean(item.findtext("title") or "")
        link = _unwrap((item.findtext("link") or "").strip())
        if not title or not link:
            continue

        publisher = _clean(item.findtext("source") or "")
        # Google News appends " - Publisher" to the headline; drop the duplicate.
        suffix = " - " + publisher
        if publisher and title.endswith(suffix):
            title = title[: -len(suffix)].strip()

        iso = None
        raw_date = item.findtext("pubDate")
        if raw_date:
            try:
                iso = parsedate_to_datetime(raw_date).astimezone(timezone.utc).date().isoformat()
            except Exception:
                iso = None

        out.append(
            Evidence(
                id=_hid(connector, title, link),
                title=title,
                url=link,
                publisher=publisher or _domain(link),
                published_at=iso,
                age_days=_age_days(iso),
                snippet=_clean(item.findtext("description") or "")[:400],
                connector=connector,
                query=query,
            )
        )
    return out


def google_news(query: str, *, limit: int = 8) -> list[Evidence]:
    """Fresh, dated, publisher-attributed news. The workhorse connector."""
    url = (
        "https://news.google.com/rss/search?q="
        + urllib.parse.quote(query)
        + "&hl=en-IN&gl=IN&ceid=IN:en"
    )
    resp = requests.get(url, headers=UA, timeout=config.HTTP_TIMEOUT)
    resp.raise_for_status()
    return _parse_rss(resp.content, connector="google_news", query=query, limit=limit)


def bing_news(query: str, *, limit: int = 8) -> list[Evidence]:
    """A second news index. Reaches further back than Google News, which is how
    the staleness filter gets something real to reject."""
    url = "https://www.bing.com/news/search?q=" + urllib.parse.quote(query) + "&format=RSS"
    resp = requests.get(url, headers=UA, timeout=config.HTTP_TIMEOUT)
    resp.raise_for_status()
    return _parse_rss(resp.content, connector="bing_news", query=query, limit=limit)


_DDG_BLOCK = re.compile(
    r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>'
    r'(.*?)(?=<a[^>]*class="result__a"|\Z)',
    re.S,
)
_DDG_SNIPPET = re.compile(r'class="result__snippet"[^>]*>(.*?)</a>', re.S)


def duckduckgo(query: str, *, limit: int = 6) -> list[Evidence]:
    """Undated web results for identity checks and the long tail.

    Best-effort by design. DDG throttles scraped traffic and replies 202 with a
    results-free page; we return [] rather than raising so one throttled lookup
    degrades a run instead of failing it.
    """
    resp = requests.post(
        "https://html.duckduckgo.com/html/",
        data={"q": query},
        headers=UA,
        timeout=config.HTTP_TIMEOUT,
    )
    if resp.status_code == 202:
        return []
    resp.raise_for_status()

    out: list[Evidence] = []
    for href, title_html, tail in _DDG_BLOCK.findall(resp.text)[:limit]:
        link = href
        if "uddg=" in href:  # DDG wraps outbound links in a redirector
            try:
                qs = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
                link = urllib.parse.unquote(qs["uddg"][0])
            except Exception:
                link = href
        if link.startswith("//"):
            link = "https:" + link
        title = _clean(title_html)
        if not title:
            continue
        snip = _DDG_SNIPPET.search(tail)
        out.append(
            Evidence(
                id=_hid("ddg", title, link),
                title=title,
                url=link,
                publisher=_domain(link),
                published_at=None,
                age_days=None,
                snippet=_clean(snip.group(1))[:400] if snip else "",
                connector="duckduckgo",
                query=query,
            )
        )
    return out


def hackernews(query: str, *, limit: int = 5) -> list[Evidence]:
    """Useful when the prospect sells to, or hires, engineers."""
    resp = requests.get(
        "https://hn.algolia.com/api/v1/search",
        params={"query": query, "tags": "story", "hitsPerPage": limit},
        timeout=config.HTTP_TIMEOUT,
    )
    resp.raise_for_status()

    out: list[Evidence] = []
    for hit in resp.json().get("hits", [])[:limit]:
        title = _clean(hit.get("title") or hit.get("story_title") or "")
        if not title:
            continue
        link = hit.get("url") or (
            "https://news.ycombinator.com/item?id=" + str(hit.get("objectID"))
        )
        created = (hit.get("created_at") or "")[:10] or None
        out.append(
            Evidence(
                id=_hid("hn", title, link),
                title=title,
                url=link,
                publisher="Hacker News",
                published_at=created,
                age_days=_age_days(created),
                snippet=_clean(hit.get("story_text") or "")[:300],
                connector="hackernews",
                query=query,
            )
        )
    return out


CONNECTORS = {
    "google_news": google_news,
    "bing_news": bing_news,
    "duckduckgo": duckduckgo,
    "hackernews": hackernews,
}

# Connectors a run is allowed to lose without being considered degraded.
BEST_EFFORT = {"duckduckgo", "hackernews"}


# ------------------------------------------------------------------ planning

def plan_queries(name: str, company: str, role: str, domain: str) -> list[tuple[str, str]]:
    """Return (connector, query) pairs to run for this prospect.

    Queries are intent-shaped rather than one generic company search, because
    the scoring step needs *competing* signals of different kinds to choose
    between. A single "Acme news" query gives the model one option and no
    judgement to exercise.
    """
    quoted_company = '"' + company + '"'
    quoted_name = '"' + name + '"'

    plan: list[tuple[str, str]] = [
        # Company-level intents -- each one is a different kind of hook.
        ("google_news", quoted_company + " (funding OR raises OR round OR valuation OR IPO)"),
        ("google_news", quoted_company + " (hiring OR layoffs OR headcount OR appoints)"),
        ("google_news", quoted_company + " (launches OR acquires OR partnership OR expansion)"),
        ("bing_news", quoted_company + " (funding OR launch OR expansion OR results)"),
        # Person-level: both a plain lookup and an explicit job-move probe, which
        # is what the "person has changed jobs" edge case keys off.
        ("google_news", quoted_name + " " + quoted_company),
        ("google_news", quoted_name + ' (joins OR appointed OR "steps down" OR exits OR promoted)'),
    ]
    person_query = quoted_name + " " + quoted_company
    if role:
        person_query += " " + role
    plan.append(("duckduckgo", person_query))
    plan.append(("duckduckgo", quoted_name + " " + quoted_company + " linkedin"))
    if domain:
        plan.append(("duckduckgo", "site:" + domain + " careers OR jobs OR press"))
    plan.append(("hackernews", company))
    return plan


def dedupe(items: Iterable[Evidence]) -> list[Evidence]:
    """Collapse the same story arriving from several queries."""
    seen_ids: set[str] = set()
    seen_titles: set[str] = set()
    out: list[Evidence] = []
    for ev in items:
        key = re.sub(r"[^a-z0-9]+", "", ev.title.lower())[:70]
        if ev.id in seen_ids or (key and key in seen_titles):
            continue
        seen_ids.add(ev.id)
        if key:
            seen_titles.add(key)
        out.append(ev)
    return out


def health() -> dict[str, dict]:
    """Per-connector liveness for the UI status rail.

    Probed concurrently. Sequentially this was four round-trips to four
    different hosts, and the slowest of them -- DuckDuckGo, which throttles --
    set the floor for the whole check.
    """
    probes = (
        ("google_news", lambda: google_news("Stripe funding", limit=1)),
        ("bing_news", lambda: bing_news("Stripe funding", limit=1)),
        ("duckduckgo", lambda: duckduckgo("Stripe careers", limit=1)),
        ("hackernews", lambda: hackernews("Stripe", limit=1)),
    )

    def run(item: tuple[str, Any]) -> tuple[str, dict]:
        name, probe = item
        try:
            return name, {"ok": True, "n": len(probe())}
        except Exception as exc:
            return name, {"ok": False, "detail": type(exc).__name__}

    with ThreadPoolExecutor(max_workers=len(probes)) as pool:
        return dict(pool.map(run, probes))
