"""
뉴스 파이프라인 출력물로 CapCut 프로젝트를 생성한다.
모든 중간 파일은 article_dir(/Users/hongss/News/output/...) 안에 유지되며
VideoMaker 서버에 의존하지 않는다.
"""
import json
import re
import subprocess
import tempfile
from pathlib import Path

import requests

from src.capcut_builder import build as _build_capcut


def _get_audio_duration(path: str) -> float:
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", path], text=True
    ).strip()
    return float(out)


def _create_black_video(output_path: str, duration: float):
    subprocess.run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "color=c=black:s=1080x1920:r=30",
        "-t", str(duration),
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-an", output_path,
    ], check=True, capture_output=True)


def _create_thumbnail_video(output_path: str, duration: float, image_url: str):
    try:
        resp = requests.get(image_url, timeout=10)
        resp.raise_for_status()
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(resp.content)
            img_path = f.name
    except Exception:
        _create_black_video(output_path, duration)
        return

    try:
        subprocess.run([
            "ffmpeg", "-y",
            "-loop", "1", "-i", img_path,
            "-vf",
            "scale=1080:1920:force_original_aspect_ratio=increase,"
            "crop=1080:1920,"
            "colorchannelmixer=rr=0.55:gg=0.55:bb=0.55",
            "-t", str(duration),
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-an", output_path,
        ], check=True, capture_output=True)
    except Exception:
        _create_black_video(output_path, duration)
    finally:
        Path(img_path).unlink(missing_ok=True)


from src.chunker import chunk_words as _make_chunks   # 단일 정규 함수


def _translate_chunks(words: list[dict], lang_code: str = "ko") -> list[str]:
    """청크별 번역 (한 번에 배치 처리)."""
    from src.translator import translate_chunks
    chunks = _make_chunks(words)
    return translate_chunks(chunks, lang_code) if chunks else []


def _make_common_title(script_md: str, fallback: str) -> str:
    """스크립트 전체를 관통하는 짧은 공통 주제 타이틀 생성 (Claude Haiku)."""
    import subprocess
    # 나레이션 전문 추출 (최대 600자)
    narrations = re.findall(
        r'\*\*(?:나레이션|Narration)\*\*:[ \t]*\n+([\s\S]+?)(?=\n\s*\n\*\*|\n---|\n##|$)',
        script_md, re.IGNORECASE
    )
    combined = " ".join(n.strip().strip('"') for n in narrations)[:600]

    prompt = (
        f"Based on this news script excerpt, write a SHORT punchy English title "
        f"(5-8 words max) that captures the main theme. "
        f"No quotes, no punctuation at end.\n\n{combined}"
    )
    try:
        result = subprocess.run(
            ["claude", "--print", "--dangerously-skip-permissions",
             "--model", "claude-haiku-4-5-20251001"],
            input=prompt, capture_output=True, text=True, timeout=30,
        )
        t = result.stdout.strip().strip('"').strip("'")
        if t and len(t) < 80:
            return t
    except Exception:
        pass
    return fallback


def _extract_scene_titles(script_md: str) -> dict[str, str]:
    """## [SCENE 01 - Hook Opening] 형식에서 씬 ID → 제목 추출."""
    titles = {}
    for m in re.finditer(r'##\s+\[SCENE\s+(\d+)\s*-\s*([^\]]+)\]', script_md, re.IGNORECASE):
        titles[m.group(1).zfill(2)] = m.group(2).strip()
    return titles


def _extract_source(article_dir: Path) -> str:
    """article.json에서 소스명을 읽는다."""
    p = article_dir / "article.json"
    if p.exists():
        try:
            return json.loads(p.read_text()).get("source", "News")
        except Exception:
            pass
    return "News"


def _ensure_sources_html(article_dir: Path) -> None:
    """sources.html이 없으면 article.json으로 최소 버전을 생성한다."""
    sources_path = article_dir / "sources.html"
    if sources_path.exists():
        return
    article_json = article_dir / "article.json"
    if not article_json.exists():
        return
    try:
        from datetime import datetime
        a = json.loads(article_json.read_text())
        title = a.get("title", "-")
        source = a.get("source", "-")
        url = a.get("url", "#")
        pub = (a.get("published_at") or "")[:10]
        src_url = a.get("sourceUrl", url)
        html = f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8">
<title>출처 기록</title>
<style>body{{font-family:-apple-system,sans-serif;max-width:800px;margin:40px auto;padding:0 20px;background:#f8f8f8}}
.card{{background:white;border-radius:10px;padding:20px;margin:16px 0;box-shadow:0 1px 4px rgba(0,0,0,.08)}}
.badge{{display:inline-block;background:#4a90d9;color:white;font-size:11px;font-weight:600;padding:3px 10px;border-radius:20px;margin-bottom:10px}}
h2{{font-size:16px;margin:6px 0}}h2 a{{color:#1a73e8;text-decoration:none}}
.meta{{font-size:13px;color:#666;margin-top:8px}}.ts{{font-size:12px;color:#aaa;text-align:right;margin-top:20px}}</style>
</head><body>
<h1 style="font-size:20px;color:#444;border-bottom:2px solid #ddd;padding-bottom:10px">📰 뉴스 크롤링 출처 기록</h1>
<div class="card">
  <div class="badge">주요 기사</div>
  <h2><a href="{url}" target="_blank">{title}</a></h2>
  <div class="meta">📰 {source} &nbsp; 📅 {pub}</div>
  <div style="font-size:11px;color:#aaa;margin-top:6px;word-break:break-all">{url}</div>
</div>
<p class="ts">생성: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
</body></html>"""
        sources_path.write_text(html, encoding="utf-8")
    except Exception:
        pass


def export(
    article_dir: Path,
    script_md: str,
    scene_ids: list[str],
    article_url: str = "",
    image_url: str = "",
    lang_code: str = "ko",
    topic: str = "",
) -> str:
    """
    1. videos/{lang_code}/ 에 배경 비디오 생성 (썸네일 or 검은 배경)
    2. capcut_builder로 CapCut 프로젝트 직접 생성
    모든 파일은 article_dir 안에 유지됨.

    Returns: CapCut 프로젝트 경로
    """
    # 출처 기록 보장 — 없으면 article.json으로라도 생성
    _ensure_sources_html(article_dir)

    title_match = re.search(
        r'^#\s+(?:대본:\s*|YouTube Shorts Script:\s*|News Script:\s*)?(.+)',
        script_md, re.MULTILINE
    )
    title = title_match.group(1).strip() if title_match else "뉴스-숏폼"
    slug_base = topic if topic else title
    _base_slug = re.sub(r'[^\w가-힣-]', '-', slug_base).strip('-')[:60]
    slug = f"{_base_slug}-{lang_code}"

    # 공통 타이틀 생성 (모든 씬 동일하게 사용)
    common_title = _make_common_title(script_md, title)

    # 씬별 나레이션 추출 (이미지 프롬프트용)
    def _extract_narration(md: str, sid: str) -> str:
        for block in re.split(r'(?=##\s+\[SCENE\s+\d+)', md, flags=re.IGNORECASE):
            if not re.search(rf'##\s+\[SCENE\s+0*{int(sid)}', block, re.IGNORECASE):
                continue
            m = re.search(r'\*\*(?:나레이션|Narration)\*\*:[ \t]*\n+([\s\S]+?)(?=\n\s*\n\*\*|\n---|\n##|$)',
                          block, re.IGNORECASE)
            if m:
                return re.sub(r'^["""\'\']+|["""\'\']+$', '', m.group(1).strip())
        return ""

    # AI 이미지 — 기사당 1장 생성, 전 씬 공유
    from src.image_generator import generate_scene_image
    images_dir = article_dir / "images"
    images_dir.mkdir(exist_ok=True)

    article_image_path = str(images_dir / "article.jpg")
    if not Path(article_image_path).exists():
        # 첫 씬 나레이션으로 대표 이미지 생성
        first_narration = _extract_narration(script_md, scene_ids[0]) if scene_ids else ""
        generate_scene_image(common_title, first_narration, article_image_path)

    shared_image = article_image_path if Path(article_image_path).exists() else None

    # 스타일드 비디오 생성 (양피지 레이아웃)
    from src.frame_renderer import create_styled_video

    videos_dir = article_dir / "videos" / lang_code
    videos_dir.mkdir(parents=True, exist_ok=True)

    for sid in scene_ids:
        audio_path = article_dir / "audio" / f"scene_{sid}.mp3"
        dur = _get_audio_duration(str(audio_path)) if audio_path.exists() else 5.0
        video_path = str(videos_dir / f"scene_{sid}-A.mp4")

        words_path = article_dir / "subtitles" / f"scene_{sid}_words.json"
        words = json.loads(words_path.read_text()) if words_path.exists() else []

        chunk_trans_path = article_dir / "subtitles" / f"scene_{sid}_chunk_{lang_code}.json"
        if words:
            expected = len(_make_chunks(words))
            cached = json.loads(chunk_trans_path.read_text()) if chunk_trans_path.exists() else []
            if not cached or len(cached) != expected:
                result = _translate_chunks(words, lang_code)
                if result and len(result) == expected:
                    chunk_trans_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
                    cached = result
            # 불변식: ko_chunks 수 == 청크 수 (어긋나면 즉시 에러)
            if cached and len(cached) != expected:
                raise RuntimeError(
                    f"씬 {sid} {lang_code}_chunks 수 불일치: {len(cached)} != {expected}. "
                    "번역을 재실행하거나 캐시를 삭제하세요."
                )
        else:
            cached = []
        ko_chunks = cached

        scene_headline = common_title

        # 이미지 경로: 기사 공유 이미지 > 기사 썸네일 > None
        create_styled_video(
            output_path=video_path,
            headline=scene_headline,
            source=_extract_source(article_dir),
            image_url=final_image if not shared_image else None,
            words=words,
            ko_chunks=ko_chunks,
            total_duration=dur,
            image_path=shared_image,
            scene_index=int(sid) - 1,   # 씬별 다른 Ken Burns 프리셋
            subtitle_lang=lang_code,
        )

    # article.json에 URL 저장
    article_json_path = article_dir / "article.json"
    if article_json_path.exists():
        data = json.loads(article_json_path.read_text())
        data["sourceUrl"] = article_url
        article_json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    # CapCut 프로젝트 직접 생성
    # 텍스트가 비디오 프레임에 이미 렌더링되어 있으므로 CapCut 텍스트 트랙 생략
    capcut_path = _build_capcut(article_dir, slug, skip_text_track=True, videos_subdir=lang_code)
    return capcut_path
