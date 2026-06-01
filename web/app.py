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

SCRIPT_PROMPT = """\
You are a YouTube Shorts news scriptwriter. Write a 60-second English narration script.

Article title: {title}
Summary: {description}
Content: {content}
Source: {source}

Write EXACTLY this format (3 scenes, English only, ~150 words total):

# YouTube Shorts Script: {title}

## [SCENE 01 - Hook]
**나레이션**:
"[strong hook sentence, 1-2 sentences]"

## [SCENE 02 - Details]
**나레이션**:
"[key facts, 3-4 sentences]"

## [SCENE 03 - Call to Action]
**나레이션**:
"[engaging CTA, 1-2 sentences]"

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
    global _news_cache
    import random
    # 10개 가져와서 랜덤 3개 — 매번 다른 기사
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

        # 1. 대본 생성
        yield event("script", "running", f"대본 생성 중...")
        try:
            prompt = SCRIPT_PROMPT.format(
                title=article.title,
                description=article.description or "",
                content=(article.content or "")[:800],
                source=article.source,
            )
            script_md = await asyncio.to_thread(_run_claude, prompt)
            (article_dir / "script-final.md").write_text(script_md)
            narrations = _extract_narrations(script_md)
            yield event("script", "done", f"대본 완성 ({len(narrations)}개 씬)")
        except Exception as e:
            yield event("script", "error", str(e))
            return

        # 2. TTS
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
