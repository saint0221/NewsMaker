import asyncio
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.fetcher import NewsFetcher, Article

app = FastAPI()

# ── 뉴스 일시 캐시 ──────────────────────────────────────────────
_news_cache: list[Article] = []
_current_category: str = "technology"

SCRIPT_PROMPT = """\
You are a news explainer creating a 2-3 minute video script for a general audience, \
including high school students with no prior knowledge of the topic.

You have the following article(s) with full content. Write a clear, accessible English narration \
that synthesizes the information, adds analysis and insights, and makes complex topics easy to understand.

Rules:
- DO NOT mention specific news sources (BBC, Reuters, etc.) by name
- Explain jargon and technical terms in plain language when they first appear
- Use relatable analogies and real-world examples to explain complex ideas
- Conversational, friendly tone — like explaining to a smart friend, not a lecture
- Short sentences. Avoid complex sentence structures.
- Total: ~350-400 words (~2.5 minutes spoken)
- 5-6 scenes, each ~60-70 words (~25-30 seconds)

{articles_section}

Write EXACTLY this format:

# News Script: {title}

## [SCENE 01 - Hook Opening]
**나레이션**:
"[powerful hook that grabs attention in first 3 seconds]"

## [SCENE 02 - Context & Background]
**나레이션**:
"[background context and why this matters now]"

## [SCENE 03 - Key Facts]
**나레이션**:
"[main facts synthesized from the source material]"

## [SCENE 04 - Analysis & Insight]
**나레이션**:
"[deeper analysis: implications, broader context, expert perspective]"

## [SCENE 05 - Impact]
**나레이션**:
"[who is affected and how, real-world significance]"

## [SCENE 06 - Outlook & CTA]
**나레이션**:
"[what happens next, thought-provoking close]"

Return ONLY the script. No extra commentary."""


def _save_sources_html(article_dir: Path, primary, full_body: str, related: list) -> None:
    """크롤링된 기사 출처를 sources.html로 저장한다."""
    from datetime import datetime

    def card(title, source, url, published, body_len, role):
        color = "#4a90d9" if role == "primary" else "#888"
        badge = "주요 기사" if role == "primary" else f"관련 기사 {role}"
        return f"""
        <div class="card">
          <div class="badge" style="background:{color}">{badge}</div>
          <h2><a href="{url}" target="_blank">{title}</a></h2>
          <div class="meta">
            <span>📰 {source}</span>
            <span>📅 {published[:10] if published else '-'}</span>
            <span>📝 본문 {body_len:,}자 크롤링</span>
          </div>
          <div class="url">{url}</div>
        </div>"""

    cards = card(
        primary.title, primary.source, primary.url,
        primary.published_at, len(full_body), "primary"
    )
    for i, r in enumerate(related, 1):
        cards += card(r.title, r.source, r.url, r.published_at, 0, i)

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>출처 기록</title>
<style>
  body {{ font-family: -apple-system, sans-serif; max-width: 800px; margin: 40px auto;
         padding: 0 20px; background: #f8f8f8; color: #222; }}
  h1   {{ font-size: 20px; color: #444; border-bottom: 2px solid #ddd; padding-bottom: 10px; }}
  .card {{ background: white; border-radius: 10px; padding: 20px; margin: 16px 0;
           box-shadow: 0 1px 4px rgba(0,0,0,.08); }}
  .badge {{ display: inline-block; color: white; font-size: 11px; font-weight: 600;
            padding: 3px 10px; border-radius: 20px; margin-bottom: 10px; }}
  h2   {{ font-size: 16px; margin: 6px 0; }}
  h2 a {{ color: #1a73e8; text-decoration: none; }}
  h2 a:hover {{ text-decoration: underline; }}
  .meta {{ font-size: 13px; color: #666; margin-top: 8px; display: flex; gap: 16px; flex-wrap: wrap; }}
  .url  {{ font-size: 11px; color: #aaa; margin-top: 6px; word-break: break-all; }}
  .ts   {{ font-size: 12px; color: #aaa; text-align: right; margin-top: 20px; }}
</style>
</head>
<body>
<h1>📰 뉴스 크롤링 출처 기록</h1>
{cards}
<p class="ts">생성: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
</body>
</html>"""

    (article_dir / "sources.html").write_text(html, encoding="utf-8")


def _run_claude(prompt: str) -> str:
    result = subprocess.run(
        ["claude", "--print", "--dangerously-skip-permissions",
         "--model", "claude-haiku-4-5-20251001"],
        input=prompt,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Claude 오류: {result.stderr[:300]}")
    return result.stdout.strip()


def _extract_narrations(script_md: str) -> dict[str, str]:
    result = {}
    for block in re.split(r'(?=##\s+\[SCENE\s+\d+)', script_md, flags=re.IGNORECASE):
        id_m = re.search(r'##\s+\[SCENE\s+(\d+)', block, re.IGNORECASE)
        if not id_m:
            continue
        sid = id_m.group(1).zfill(2)
        narr_m = re.search(
            r'\*\*(?:나레이션|Narration)\*\*:[ \t]*\n+([\s\S]+?)(?=\n\s*\n\*\*|\n---|\n##|$)',
            block, re.IGNORECASE
        )
        if not narr_m:
            continue
        text = re.sub(r'^["""\'\']+|["""\'\']+$', '', narr_m.group(1).strip())
        if text:
            result[sid] = text
    return result


# ── API ─────────────────────────────────────────────────────────

class ArticleRef(BaseModel):
    index: int

class NewsRequest(BaseModel):
    category: str = "technology"

class TopicRequest(BaseModel):
    topic: str
    selected_indices: list[int] = []   # 비어있으면 전체 사용


@app.get("/")
async def index():
    html = (Path(__file__).parent / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(html)


@app.post("/api/news")
async def fetch_news(req: NewsRequest):
    global _news_cache, _current_category
    import random
    _current_category = req.category
    articles = NewsFetcher().fetch(category=req.category, count=10)
    random.shuffle(articles)
    articles = articles[:3]
    _news_cache = articles
    return [
        {
            "index": i,
            "title": a.title,
            "description": a.description or "",
            "source": a.source,
            "image_url": a.image_url,
            "url": a.url,
        }
        for i, a in enumerate(articles)
    ]


@app.post("/api/search")
async def search_topic(req: TopicRequest):
    """특정 주제로 뉴스 기사를 검색한다."""
    from src.fetcher import search_by_topic
    global _news_cache, _current_category
    _current_category = "general"
    articles = await asyncio.to_thread(search_by_topic, req.topic, 5)
    _news_cache = articles
    return {
        "topic": req.topic,
        "count": len(articles),
        "articles": [
            {
                "index": i,
                "title": a.title,
                "description": a.description or "",
                "source": a.source,
                "image_url": a.image_url,
                "url": a.url,
                "published_at": a.published_at[:10] if a.published_at else "",
            }
            for i, a in enumerate(articles)
        ],
    }


@app.post("/api/run-topic")
async def run_topic_pipeline(req: TopicRequest):
    """주제 입력 → 뉴스 크롤링 → 대본 → 영상 전체 파이프라인."""
    from src.fetcher import search_by_topic, fetch_full_content

    async def stream():
        def event(step: str, status: str, msg: str) -> str:
            return f"data: {json.dumps({'step': step, 'status': status, 'message': msg}, ensure_ascii=False)}\n\n"

        base_dir = Path("output") / datetime.now().strftime("%Y%m%d_%H%M%S")
        article_dir = base_dir / "article_01"
        (article_dir / "audio").mkdir(parents=True, exist_ok=True)
        (article_dir / "subtitles").mkdir(parents=True, exist_ok=True)

        # 1. 주제로 뉴스 검색 + 전문 크롤링
        yield event("script", "running", f"'{req.topic}' 관련 뉴스 검색 중...")
        try:
            articles = await asyncio.to_thread(search_by_topic, req.topic, 5)
            if not articles:
                yield event("script", "error", "관련 뉴스를 찾을 수 없습니다.")
                return

            # 선택된 인덱스로 필터링 (없으면 전체)
            if req.selected_indices:
                articles = [a for i, a in enumerate(articles) if i in req.selected_indices]
            if not articles:
                yield event("script", "error", "선택된 기사가 없습니다.")
                return

            yield event("script", "running", f"{len(articles)}개 기사 사용 → 전문 크롤링 중...")

            # 첫 번째 기사를 주요 기사로, 나머지를 관련 기사로
            primary = articles[0]
            related_arts = articles[1:]

            # article.json 저장
            (article_dir / "article.json").write_text(json.dumps({
                "title": primary.title, "description": primary.description,
                "content": primary.content, "url": primary.url,
                "image_url": primary.image_url, "source": primary.source,
                "published_at": primary.published_at,
            }, ensure_ascii=False, indent=2))

            # 전문 크롤링
            full_body = await asyncio.to_thread(fetch_full_content, primary.url)
            if not full_body:
                full_body = primary.description or primary.content or ""

            related_bodies = []
            for r in related_arts[:3]:
                body = await asyncio.to_thread(fetch_full_content, r.url)
                if body:
                    related_bodies.append((r.title, body))

            # 출처 기록
            _save_sources_html(article_dir, primary, full_body, related_arts[:3])
            yield event("script", "running",
                        f"크롤링 완료: 주요 기사 {len(full_body):,}자 + 관련 {len(related_bodies)}개")

            # 대본 생성
            articles_section = f"## Primary Article\nTitle: {primary.title}\n\n{full_body}"
            for i, (rtitle, rbody) in enumerate(related_bodies, 1):
                articles_section += f"\n\n## Related Article {i}\nTitle: {rtitle}\n\n{rbody[:2000]}"

            yield event("script", "running", "2~3분 대본 생성 중 (Claude)...")
            prompt = SCRIPT_PROMPT.format(title=req.topic, articles_section=articles_section)
            script_md = await asyncio.to_thread(_run_claude, prompt)
            (article_dir / "script-final.md").write_text(script_md)
            narrations = _extract_narrations(script_md)
            all_sources = [full_body] + [b for _, b in related_bodies]
            yield event("script", "done", f"대본 완성 ({len(narrations)}개 씬, {1+len(related_bodies)}개 소스)")

        except Exception as e:
            yield event("script", "error", str(e))
            return

        # 이후 단계는 기존 파이프라인과 동일 — article을 primary로 설정
        article = primary

        # 팩트 체크
        yield event("factcheck", "running", "팩트 체크 중...")
        try:
            from src.fact_checker import fact_check
            corrected, issues = await asyncio.to_thread(fact_check, script_md, all_sources)
            if issues:
                script_md = corrected
                (article_dir / "script-final.md").write_text(script_md)
                narrations = _extract_narrations(script_md)
                (article_dir / "fact-check.md").write_text(
                    "# 팩트 체크\n\n" + "\n".join(f"- {i}" for i in issues))
                yield event("factcheck", "done", f"{len(issues)}개 수정됨")
            else:
                yield event("factcheck", "done", "이슈 없음")
        except Exception as e:
            yield event("factcheck", "error", f"팩트 체크 실패: {e}")

        # AI 이미지
        yield event("image", "running", "AI 이미지 생성 중...")
        try:
            from src.image_generator import generate_scene_image
            from src.videomaker_export import _make_common_title
            images_dir = article_dir / "images"
            images_dir.mkdir(exist_ok=True)
            article_img = str(images_dir / "article.jpg")
            if not Path(article_img).exists():
                ct = await asyncio.to_thread(_make_common_title, script_md, req.topic)
                first_narration = list(narrations.values())[0] if narrations else ""
                ok = await asyncio.to_thread(generate_scene_image, ct, first_narration, article_img)
                yield event("image", "done" if ok else "error",
                            "이미지 생성 완료" if ok else "이미지 생성 실패")
            else:
                yield event("image", "done", "캐시 이미지 사용")
        except Exception as e:
            yield event("image", "error", str(e))

        # TTS
        yield event("tts", "running", f"음성 생성 중 ({len(narrations)}개 씬)...")
        try:
            from src.tts import TTSGenerator
            tts = TTSGenerator()
            for sid, text in narrations.items():
                audio_path = str(article_dir / "audio" / f"scene_{sid}.mp3")
                result = await asyncio.to_thread(tts.generate, text, audio_path)
                (article_dir / "subtitles" / f"scene_{sid}.srt").write_text(result.srt_word)
                (article_dir / "subtitles" / f"scene_{sid}_sentences.srt").write_text(result.srt_sentence)
                (article_dir / "subtitles" / f"scene_{sid}_words.json").write_text(
                    json.dumps(result.words, ensure_ascii=False))
                yield event("tts", "running", f"씬 {sid} 완료")
            yield event("tts", "done", "음성 생성 완료")
        except Exception as e:
            yield event("tts", "error", str(e))
            return

        # 한국어 번역
        yield event("translate", "running", f"한국어 번역 중 ({len(narrations)}개 씬)...")
        try:
            from src.translator import translate_to_korean
            from src.chunker import chunk_words as _cw
            for sid in narrations.keys():
                wp = article_dir / "subtitles" / f"scene_{sid}_words.json"
                kp = article_dir / "subtitles" / f"scene_{sid}_chunk_ko.json"
                if not wp.exists(): continue
                wd = json.loads(wp.read_text())
                ch = _cw(wd)
                ca = json.loads(kp.read_text()) if kp.exists() else []
                if ca and len(ca) == len(ch):
                    continue
                for _ in range(3):
                    ko = await asyncio.to_thread(translate_to_korean, ch)
                    if ko and len(ko) == len(ch):
                        kp.write_text(json.dumps(ko, ensure_ascii=False))
                        break
            yield event("translate", "done", "번역 완료")
        except Exception as e:
            yield event("translate", "error", str(e))

        # CapCut
        yield event("capcut", "running", "CapCut 프로젝트 생성 중...")
        try:
            from src.videomaker_export import export
            capcut_path = await asyncio.to_thread(
                export, article_dir, script_md, list(narrations.keys()),
                article.url or "", article.image_url or "")
            yield event("capcut", "done", json.dumps(
                {"path": capcut_path, "sourceUrl": article.url or ""}, ensure_ascii=False))
        except Exception as e:
            yield event("capcut", "error", str(e))

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.post("/api/run")
async def run_pipeline(ref: ArticleRef, request: Request):
    if ref.index >= len(_news_cache):
        return {"error": "뉴스를 먼저 불러오세요"}

    article = _news_cache[ref.index]

    async def stream():
        def event(step: str, status: str, msg: str) -> str:
            return f"data: {json.dumps({'step': step, 'status': status, 'message': msg}, ensure_ascii=False)}\n\n"

        base_dir = Path("output") / datetime.now().strftime("%Y%m%d_%H%M%S")
        article_dir = base_dir / "article_01"
        (article_dir / "audio").mkdir(parents=True, exist_ok=True)
        (article_dir / "subtitles").mkdir(parents=True, exist_ok=True)

        # article.json 즉시 저장 — 이후 단계에서 image_url 등 참조 가능
        (article_dir / "article.json").write_text(json.dumps({
            "title": article.title,
            "description": article.description,
            "content": article.content,
            "url": article.url,
            "image_url": article.image_url,
            "source": article.source,
            "published_at": article.published_at,
        }, ensure_ascii=False, indent=2))

        # 1. 기사 전문 크롤링 + 관련 기사 탐색
        yield event("script", "running", "기사 전문 크롤링 중...")
        full_body = ""
        related_bodies = []
        related_articles = []
        try:
            from src.fetcher import fetch_full_content

            full_body = await asyncio.to_thread(fetch_full_content, article.url)
            if not full_body:
                full_body = article.description or article.content or ""

            # 관련 기사 탐색 (같은 카테고리, 키워드 겹치는 것)
            fetcher = NewsFetcher()
            related = await asyncio.to_thread(
                fetcher.find_related, article, _current_category, 2
            )
            yield event("script", "running",
                        f"관련 기사 {len(related)}개 발견 → 전문 수집 중...")

            for r in related:
                body = await asyncio.to_thread(fetch_full_content, r.url)
                if body:
                    related_bodies.append((r.title, body))
                    related_articles.append(r)

        except Exception as e:
            yield event("script", "error", str(e))
            return
        finally:
            # 크롤링 성공·실패 무관하게 출처 반드시 기록
            _save_sources_html(article_dir, article, full_body, related_articles)

        try:
            # 프롬프트 구성
            articles_section = f"## Primary Article\nTitle: {article.title}\n\n{full_body}"
            for i, (rtitle, rbody) in enumerate(related_bodies, 1):
                articles_section += f"\n\n## Related Article {i}\nTitle: {rtitle}\n\n{rbody[:2000]}"

            yield event("script", "running", "2~3분 대본 생성 중 (Claude)...")
            prompt = SCRIPT_PROMPT.format(
                title=article.title,
                articles_section=articles_section,
            )
            script_md = await asyncio.to_thread(_run_claude, prompt)
            (article_dir / "script-final.md").write_text(script_md)
            narrations = _extract_narrations(script_md)
            yield event("script", "done",
                        f"대본 완성 ({len(narrations)}개 씬, "
                        f"소스 {1 + len(related_bodies)}개)")

            # 모든 소스 텍스트 수집 (팩트 체크용)
            all_sources = [full_body] + [b for _, b in related_bodies]

        except Exception as e:
            yield event("script", "error", str(e))
            return

        # 1-b. 팩트 체크
        yield event("factcheck", "running", "팩트 체크 중 (원문 대조)...")
        try:
            from src.fact_checker import fact_check
            corrected, issues = await asyncio.to_thread(
                fact_check, script_md, all_sources
            )
            if issues:
                script_md = corrected
                (article_dir / "script-final.md").write_text(script_md)
                narrations = _extract_narrations(script_md)
                (article_dir / "fact-check.md").write_text(
                    "# 팩트 체크 결과\n\n" + "\n".join(f"- {i}" for i in issues)
                )
                yield event("factcheck", "done", f"{len(issues)}개 수정됨")
            else:
                yield event("factcheck", "done", "이슈 없음 — 대본 확인 완료")
        except Exception as e:
            yield event("factcheck", "error", f"팩트 체크 실패 (원본 사용): {e}")

        # 2. AI 이미지 생성 — 기사당 1장
        yield event("image", "running", "AI 이미지 생성 중 (fal.ai Flux, 기사당 1장)...")
        try:
            from src.image_generator import generate_scene_image
            from src.videomaker_export import _make_common_title
            images_dir = article_dir / "images"
            images_dir.mkdir(exist_ok=True)
            article_img = str(images_dir / "article.jpg")
            if not Path(article_img).exists():
                common_title_img = await asyncio.to_thread(_make_common_title, script_md, article.title)
                first_narration = list(narrations.values())[0] if narrations else ""
                ok = await asyncio.to_thread(
                    generate_scene_image, common_title_img, first_narration, article_img
                )
                yield event("image", "done" if ok else "error",
                            "이미지 생성 완료" if ok else "이미지 생성 실패 (썸네일 사용)")
            else:
                yield event("image", "done", "캐시된 이미지 사용")
        except Exception as e:
            yield event("image", "error", f"이미지 생성 실패 (썸네일 사용): {e}")

        # 3. TTS
        yield event("tts", "running", "음성 생성 중 (ElevenLabs)...")
        try:
            from src.tts import TTSGenerator
            tts = TTSGenerator()
            for sid, text in narrations.items():
                audio_path = str(article_dir / "audio" / f"scene_{sid}.mp3")
                result = await asyncio.to_thread(tts.generate, text, audio_path)
                (article_dir / "subtitles" / f"scene_{sid}.srt").write_text(result.srt_word)
                (article_dir / "subtitles" / f"scene_{sid}_sentences.srt").write_text(result.srt_sentence)
                (article_dir / "subtitles" / f"scene_{sid}_words.json").write_text(
                    json.dumps(result.words, ensure_ascii=False)
                )
                yield event("tts", "running", f"씬 {sid} 완료")
            yield event("tts", "done", "음성 생성 완료")
        except Exception as e:
            yield event("tts", "error", str(e))
            return

        # 3-b. 한국어 번역 (TTS 직후 명시적 실행, 실패 시 즉시 재시도)
        yield event("translate", "running", f"한국어 번역 중 ({len(narrations)}개 씬)...")
        try:
            from src.translator import translate_to_korean
            from src.chunker import chunk_words as _chunk_words   # 단일 정규 함수

            for sid in narrations.keys():
                words_path = article_dir / "subtitles" / f"scene_{sid}_words.json"
                ko_path    = article_dir / "subtitles" / f"scene_{sid}_chunk_ko.json"
                if not words_path.exists():
                    continue
                words_data = json.loads(words_path.read_text())
                chunks_6w  = _chunk_words(words_data)
                cached     = json.loads(ko_path.read_text()) if ko_path.exists() else []

                if cached and len(cached) == len(chunks_6w):
                    yield event("translate", "running", f"씬 {sid} 캐시 사용")
                    continue

                # 번역 실행 (최대 3회)
                translated = []
                for attempt in range(3):
                    translated = await asyncio.to_thread(translate_to_korean, chunks_6w)
                    if translated and len(translated) == len(chunks_6w):
                        break
                    translated = []

                if translated:
                    ko_path.write_text(json.dumps(translated, ensure_ascii=False))
                    yield event("translate", "running", f"씬 {sid} 완료 ({len(translated)}개)")
                else:
                    yield event("translate", "error", f"씬 {sid} 번역 실패 — 번역 없이 진행")

            yield event("translate", "done", "번역 완료")
        except Exception as e:
            yield event("translate", "error", f"번역 오류: {e}")

        # 4. CapCut 프로젝트 생성
        yield event("capcut", "running", "CapCut 프로젝트 생성 중...")
        try:
            from src.videomaker_export import export

            capcut_path = await asyncio.to_thread(
                export, article_dir, script_md, list(narrations.keys()),
                article.url or "", article.image_url or ""
            )
            yield event("capcut", "done", json.dumps({
                "path": capcut_path,
                "sourceUrl": article.url or "",
            }, ensure_ascii=False))
        except Exception as e:
            yield event("capcut", "error", str(e))
            return

    return StreamingResponse(stream(), media_type="text/event-stream")
