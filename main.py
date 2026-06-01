#!/usr/bin/env python3
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import click
from dotenv import load_dotenv

load_dotenv()


def _validate_env():
    missing = [k for k in ("ELEVENLABS_API_KEY",) if not os.environ.get(k)]
    if missing:
        click.echo(f"[오류] 환경변수 누락: {', '.join(missing)}", err=True)
        sys.exit(1)


def _parse_scene_ids(script_md: str) -> list[str]:
    return re.findall(r'##\s+\[SCENE\s+(\d+)', script_md, re.IGNORECASE)


@click.group()
def cli():
    """뉴스 숏폼 영상 자동화 파이프라인"""


@cli.command()
@click.option("--category", default="technology", show_default=True,
              type=click.Choice(["business", "entertainment", "health", "science", "sports", "technology", "general"]))
@click.option("--count", default=1, show_default=True)
@click.option("--output-dir", default="./output", show_default=True)
def run(category: str, count: int, output_dir: str):
    """뉴스 수집 → 대본(Claude 에이전트) → TTS → CapCut(VideoMaker 포맷)"""
    _validate_env()

    from src.fetcher import NewsFetcher
    from src.tts import TTSGenerator

    base = Path(output_dir) / datetime.now().strftime("%Y%m%d_%H%M%S")

    # ── 1. 뉴스 수집 ──────────────────────────────────────────────────────
    click.echo(f"[1/4] 뉴스 수집 중... (카테고리: {category})")
    articles = NewsFetcher().fetch(category=category, count=count)
    if not articles:
        click.echo("[오류] 기사를 가져올 수 없습니다.", err=True)
        sys.exit(1)

    tts = TTSGenerator()

    for i, article in enumerate(articles, 1):
        article_dir = base / f"article_{i:02d}"
        (article_dir / "audio").mkdir(parents=True, exist_ok=True)
        (article_dir / "subtitles").mkdir(parents=True, exist_ok=True)

        NewsFetcher().prepare_workspace(article, article_dir)
        click.echo(f"\n[기사 {i}/{len(articles)}] {article.title[:70]}")

        # ── 2. 대본은 Claude 에이전트가 script-final.md로 작성 ────────────
        click.echo("[2/4] 대본을 script-final.md에서 읽는 중...")
        script_path = article_dir / "script-final.md"
        if not script_path.exists():
            click.echo(f"  [건너뜀] script-final.md 없음 — 먼저 Claude 에이전트로 대본을 생성하세요.")
            continue
        script_md = script_path.read_text(encoding="utf-8")
        scene_ids = _parse_scene_ids(script_md)
        click.echo(f"  씬 {len(scene_ids)}개: {scene_ids}")

        # ── 3. TTS (with-timestamps) ─────────────────────────────────────
        click.echo("[3/4] TTS 생성 중 (ElevenLabs with-timestamps)...")
        narrations = _extract_narrations(script_md)
        for sid, text in narrations.items():
            audio_path = str(article_dir / "audio" / f"scene_{sid}.mp3")
            result = tts.generate(text, audio_path)
            (article_dir / "subtitles" / f"scene_{sid}.srt").write_text(result.srt_word)
            (article_dir / "subtitles" / f"scene_{sid}_sentences.srt").write_text(result.srt_sentence)
            import json as _json
            (article_dir / "subtitles" / f"scene_{sid}_words.json").write_text(
                _json.dumps(result.words, ensure_ascii=False)
            )
            click.echo(f"  씬 {sid} 완료 → {audio_path}")

        # ── 4. VideoMaker 프로젝트 생성 + CapCut 내보내기 ─────────────────
        click.echo("[4/4] VideoMaker 프로젝트 생성 + CapCut 내보내기 중...")
        from src.videomaker_export import export, trigger_capcut
        slug = export(article_dir, script_md, list(narrations.keys()))
        click.echo(f"  VideoMaker 프로젝트: {slug}")
        capcut_path = trigger_capcut(slug)
        click.echo(f"  CapCut 경로: {capcut_path}")

    click.echo(f"\n완료. 결과 위치: {base}")


def _extract_narrations(script_md: str) -> dict[str, str]:
    """script-final.md에서 씬 ID → 나레이션 텍스트 매핑 추출."""
    result = {}
    blocks = re.split(r'(?=##\s+\[SCENE\s+\d+)', script_md, flags=re.IGNORECASE)
    for block in blocks:
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
        text = narr_m.group(1).strip()
        text = re.sub(r'^[""„\'"\']+|[""„\'"\']+$', '', text).strip()
        if text:
            result[sid] = text
    return result


@cli.command()
@click.option("--category", default="technology", show_default=True,
              type=click.Choice(["business", "entertainment", "health", "science", "sports", "technology", "general"]))
@click.option("--count", default=1, show_default=True)
@click.option("--output-dir", default="./output", show_default=True)
def fetch(category: str, count: int, output_dir: str):
    """뉴스만 수집하고 research.md/brief.md 준비 (Claude 에이전트용)."""
    if not os.environ.get("NEWS_API_KEY"):
        click.echo("[오류] NEWS_API_KEY 없음", err=True)
        sys.exit(1)

    from src.fetcher import NewsFetcher

    base = Path(output_dir) / datetime.now().strftime("%Y%m%d_%H%M%S")
    click.echo(f"뉴스 수집 중... (카테고리: {category})")
    articles = NewsFetcher().fetch(category=category, count=count)
    if not articles:
        click.echo("[오류] 기사를 가져올 수 없습니다.", err=True)
        sys.exit(1)

    for i, article in enumerate(articles, 1):
        workspace = NewsFetcher().prepare_workspace(article, base / f"article_{i:02d}")
        click.echo(f"[{i}] {article.title[:70]}\n    → {workspace}")

    click.echo(f"\n완료: {len(articles)}개 작업 폴더 생성")


@cli.command()
@click.option("--port", default=8899, show_default=True)
def serve(port: int):
    """웹 UI 서버 실행 (http://localhost:{port})"""
    import uvicorn
    click.echo(f"웹 UI: http://localhost:{port}")
    uvicorn.run("web.app:app", host="0.0.0.0", port=port, reload=True)


if __name__ == "__main__":
    cli()
