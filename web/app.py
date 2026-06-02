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
You are a news analyst creating a 2-3 minute video script.

You have the following article(s) with full content. Write a comprehensive English narration \
that synthesizes the information, adds analysis and insights, and engages the viewer.

Rules:
- DO NOT mention specific news sources (BBC, Reuters, etc.) by name
- Add context, analysis, implications — not just raw facts
- Conversational and engaging tone
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

            # 관련 기사 전문도 크롤링
            related_bodies = []
            for r in related:
                body = await asyncio.to_thread(fetch_full_content, r.url)
                if body:
                    related_bodies.append((r.title, body))

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

        # 2. AI 이미지 생성
        yield event("image", "running", f"AI 이미지 생성 중 (fal.ai Flux, {len(narrations)}개 씬)...")
        try:
            from src.image_generator import generate_scene_image, _make_image_prompt
            images_dir = article_dir / "images"
            images_dir.mkdir(exist_ok=True)
            scene_ids_list = list(narrations.keys())
            scene_titles_map = {}
            # 씬 제목 파싱
            import re as _re
            for m in _re.finditer(r'##\s+\[SCENE\s+(\d+)\s*-\s*([^\]]+)\]', script_md, _re.IGNORECASE):
                scene_titles_map[m.group(1).zfill(2)] = m.group(2).strip()

            for sid, narration_text in narrations.items():
                img_path = str(images_dir / f"scene_{sid}.jpg")
                if not Path(img_path).exists():
                    scene_title = scene_titles_map.get(sid, "News")
                    ok = await asyncio.to_thread(
                        generate_scene_image, scene_title, narration_text, img_path
                    )
                    if ok:
                        yield event("image", "running", f"씬 {sid} 이미지 완료")
            yield event("image", "done", f"{len(narrations)}개 씬 이미지 생성 완료")
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

        # 3. CapCut 프로젝트 생성
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
