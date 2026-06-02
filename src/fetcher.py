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

KOREAN_RSS_FEEDS = [
    "https://www.yna.co.kr/rss/news.xml",          # 연합뉴스
    "https://www.hani.co.kr/rss/",                  # 한겨레
    "https://www.chosun.com/arc/outboundfeeds/rss/?outputType=xml",  # 조선일보
    "https://fs.jtbc.co.kr/RSS/newsflash.xml",      # JTBC (YTN·MBC·SBS·KBS는 RSS 미제공)
]

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


def _has_korean(text: str) -> bool:
    return any('가' <= c <= '힣' for c in text)


def _translate_query_to_english(topic: str) -> str:
    """한국어 주제를 영어 검색 키워드로 변환한다."""
    import subprocess
    prompt = (
        f"Translate this Korean news topic to concise English search keywords "
        f"(2-5 words max, no punctuation):\n{topic}\n\nReturn ONLY the English keywords."
    )
    try:
        result = subprocess.run(
            ["claude", "--print", "--dangerously-skip-permissions",
             "--model", "claude-haiku-4-5-20251001"],
            input=prompt, capture_output=True, text=True, timeout=15,
        )
        translated = result.stdout.strip().strip('"').strip("'")
        if translated and not _has_korean(translated):
            return translated
    except Exception:
        pass
    return topic


def _search_naver_news(topic: str, count: int = 5) -> list[Article]:
    """Naver 뉴스 검색 API로 국내 기사를 검색한다."""
    import os
    client_id     = os.environ.get("NAVER_CLIENT_ID", "")
    client_secret = os.environ.get("NAVER_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        return []
    try:
        resp = requests.get(
            "https://openapi.naver.com/v1/search/news.json",
            headers={
                "X-Naver-Client-Id":     client_id,
                "X-Naver-Client-Secret": client_secret,
            },
            params={"query": topic, "display": count * 2, "sort": "sim"},  # sim=관련도순
            timeout=10,
        )
        resp.raise_for_status()
        articles = []
        for item in resp.json().get("items", []):
            title = re.sub(r"<[^>]+>", "", item.get("title", ""))
            desc  = re.sub(r"<[^>]+>", "", item.get("description", ""))
            articles.append(Article(
                title=title,
                description=desc[:300],
                content=desc,
                url=item.get("originallink") or item.get("link", ""),
                image_url=None,
                source=item.get("source", "네이버뉴스"),
                published_at=item.get("pubDate", ""),
            ))
            if len(articles) >= count:
                break
        return articles
    except Exception:
        return []


def _search_korean_rss(topic: str, count: int = 5) -> list[Article]:
    """국내 언론사 RSS에서 한국어 키워드로 기사를 검색한다."""
    keywords = {w for w in re.split(r'[\s,]+', topic) if len(w) > 1}
    articles: list[Article] = []
    for url in KOREAN_RSS_FEEDS:
        try:
            resp = requests.get(url, headers=_HEADERS, timeout=8)
            resp.raise_for_status()
            feed = feedparser.parse(resp.content)
            source = feed.feed.get("title", url.split("/")[2])
            for e in feed.entries:
                title = _strip_html(e.get("title", ""))
                desc  = _strip_html(e.get("summary", ""))
                combined = title + " " + desc
                if any(k in combined for k in keywords):
                    articles.append(Article(
                        title=title,
                        description=desc[:300],
                        content=desc,
                        url=e.get("link", ""),
                        image_url=_extract_image(e),
                        source=source,
                        published_at=_parse_published(e),
                    ))
        except Exception:
            continue

    # 키워드 포함 개수로 정렬
    scored = []
    for a in articles:
        score = sum(1 for k in keywords if k in a.title + a.description)
        scored.append((score, a))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [a for _, a in scored[:count]]


def search_by_topic(topic: str, count: int = 5) -> list[Article]:
    """
    주제로 최신 뉴스를 검색한다.
    - 한국어 입력: 국내 RSS 우선 검색 + 영어 번역 후 NewsAPI 병행
    - 영어 입력: NewsAPI /everything → 관련성 기준 필터링
    - 폴백: RSS 전체에서 키워드 매칭
    """
    import os

    is_korean = _has_korean(topic)

    # 한국어 쿼리: Naver API → RSS 순으로 검색
    if is_korean:
        naver = _search_naver_news(topic, count)
        if naver:
            return naver
        rss = _search_korean_rss(topic, count)
        if rss:
            return rss

    # 영어로 변환 후 NewsAPI 검색
    search_query = _translate_query_to_english(topic) if is_korean else topic

    api_key = os.environ.get("NEWS_API_KEY", "")
    if api_key:
        try:
            resp = requests.get(
                "https://newsapi.org/v2/everything",
                params={
                    "apiKey": api_key,
                    "q": search_query,
                    "language": "en",
                    "pageSize": count * 3,     # 더 많이 가져와서 필터링
                    "sortBy": "relevancy",      # 관련성 우선
                },
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()

            # 쿼리 키워드가 제목 또는 설명에 포함된 기사만 채택
            keywords = {w.lower() for w in re.split(r'\W+', search_query) if len(w) > 2}
            articles = []
            for item in data.get("articles", []):
                title = item.get("title", "") or ""
                desc  = item.get("description", "") or ""
                # 키워드가 하나라도 포함된 기사만
                combined = (title + " " + desc).lower()
                if not any(k in combined for k in keywords):
                    continue
                content = item.get("content") or desc
                if "[+" in content:
                    content = content.split("[+")[0].strip()
                articles.append(Article(
                    title=title,
                    description=desc,
                    content=content,
                    url=item.get("url", ""),
                    image_url=item.get("urlToImage"),
                    source=item.get("source", {}).get("name", ""),
                    published_at=item.get("publishedAt", ""),
                ))
                if len(articles) >= count:
                    break

            if articles:
                return articles
        except Exception:
            pass

    # 폴백: RSS 전체에서 키워드 매칭
    keywords = {w.lower() for w in re.split(r'\W+', search_query)
                if len(w) > 2 and w.lower() not in {'the','a','an','is','of','in','for','and','or'}}
    all_articles: list[Article] = []
    for feed_urls in RSS_FEEDS.values():
        for url in feed_urls:
            all_articles.extend(_fetch_feed(url))
    scored = []
    for a in all_articles:
        combined = (a.title + " " + a.description).lower()
        score = sum(1 for k in keywords if k in combined)
        if score > 0:
            scored.append((score, a))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [a for _, a in scored[:count]]


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
