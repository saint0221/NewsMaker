import json
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import feedparser
import requests
import trafilatura

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
}

RSS_FEEDS: dict[str, list[str]] = {
    "technology": [
        "https://www.theverge.com/rss/index.xml",
        "https://techcrunch.com/feed/",
        "https://www.wired.com/feed/rss",
    ],
    "business": [
        "https://feeds.bbci.co.uk/news/business/rss.xml",
        "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml",
    ],
    "science": [
        "https://www.sciencedaily.com/rss/all.xml",
        "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml",
    ],
    "health": [
        "https://feeds.bbci.co.uk/news/health/rss.xml",
        "https://rss.nytimes.com/services/xml/rss/nyt/Health.xml",
    ],
    "entertainment": [
        "https://feeds.bbci.co.uk/news/entertainment_and_arts/rss.xml",
        "https://variety.com/feed/",
    ],
    "sports": [
        "https://feeds.bbci.co.uk/sport/rss.xml",
        "https://www.espn.com/espn/rss/news",
    ],
    "general": [
        "https://feeds.bbci.co.uk/news/rss.xml",
        "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml",
    ],
}


@dataclass
class Article:
    title: str
    description: str
    content: str
    url: str
    image_url: str | None
    source: str
    published_at: str


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()


def _parse_published(entry) -> str:
    """RSS 날짜를 ISO 8601 UTC 문자열로 정규화."""
    raw = entry.get("published") or entry.get("updated") or ""
    if not raw:
        return datetime.now(timezone.utc).isoformat()
    try:
        return parsedate_to_datetime(raw).astimezone(timezone.utc).isoformat()
    except Exception:
        pass
    # ISO 8601 계열 (e.g. 2026-05-29T04:03:45-04:00)
    try:
        return datetime.fromisoformat(raw).astimezone(timezone.utc).isoformat()
    except Exception:
        return raw


def _extract_image(entry) -> str | None:
    if media := getattr(entry, "media_thumbnail", None):
        return media[0].get("url")
    if media := getattr(entry, "media_content", None):
        for m in media:
            if "image" in m.get("type", "") or m.get("medium") == "image":
                return m.get("url")
    if enc := getattr(entry, "enclosures", None):
        for e in enc:
            if "image" in e.get("type", ""):
                return e.get("href") or e.get("url")
    return None


def _fetch_feed(url: str) -> list[Article]:
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=8)
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
        source = feed.feed.get("title", url.split("/")[2])
        articles = []
        for e in feed.entries:
            title = _strip_html(e.get("title", ""))
            if not title:
                continue
            description = _strip_html(e.get("summary", ""))
            content_blocks = e.get("content", [])
            content = _strip_html(content_blocks[0].get("value", "")) if content_blocks else description
            articles.append(Article(
                title=title,
                description=description[:300],
                content=content[:1500],
                url=e.get("link", ""),
                image_url=_extract_image(e),
                source=source,
                published_at=_parse_published(e),
            ))
        return articles
    except Exception:
        return []


def fetch_full_content(url: str) -> str:
    """기사 URL에서 전문(full body)을 추출한다."""
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=12)
        resp.raise_for_status()
        text = trafilatura.extract(resp.text, include_comments=False, no_fallback=False)
        return (text or "").strip()[:6000]   # 최대 6000자
    except Exception:
        return ""


class NewsFetcher:
    def fetch(self, category: str = "technology", count: int = 10) -> list[Article]:
        urls = RSS_FEEDS.get(category, RSS_FEEDS["general"])
        articles: list[Article] = []
        for url in urls:
            articles.extend(_fetch_feed(url))
            if len(articles) >= count * 3:
                break
        articles.sort(key=lambda a: a.published_at, reverse=True)
        return articles[:count]

    def find_related(self, article: Article, category: str, count: int = 2) -> list[Article]:
        """선택된 기사와 키워드가 겹치는 관련 기사를 반환한다."""
        stop = {'the','a','an','is','are','was','were','to','of','in','for',
                'on','with','at','by','from','as','it','its','this','that',
                'and','or','but','has','have','had','be','been','will','would'}
        keywords = {w.lower() for w in re.split(r'\W+', article.title)
                    if len(w) > 3 and w.lower() not in stop}

        candidates = self.fetch(category=category, count=20)
        scored = []
        for a in candidates:
            if a.url == article.url:
                continue
            a_words = {w.lower() for w in re.split(r'\W+', a.title)}
            overlap = len(keywords & a_words)
            if overlap >= 1:
                scored.append((overlap, a))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [a for _, a in scored[:count]]

    def prepare_workspace(self, article: Article, base_dir: Path) -> Path:
        base_dir.mkdir(parents=True, exist_ok=True)

        with open(base_dir / "article.json", "w", encoding="utf-8") as f:
            json.dump(asdict(article), f, ensure_ascii=False, indent=2)

        (base_dir / "research.md").write_text(f"""# {article.title}

**Source:** {article.source}
**Published:** {article.published_at}
**URL:** {article.url}

## Summary
{article.description}

## Content
{article.content}
""", encoding="utf-8")

        (base_dir / "brief.md").write_text(f"""# Video Brief

## Topic
{article.title}

## Format
- Platform: YouTube Shorts
- Length: 60 seconds
- Language: English narration and subtitles
- Style: News commentary

## Key Message
{article.description}

## Target Audience
English-speaking viewers interested in news
""", encoding="utf-8")

        return base_dir
