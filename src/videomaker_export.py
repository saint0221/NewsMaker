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


def _make_chunks(words: list[dict]) -> list[str]:
    """words.json → 8단어 청크 영어 텍스트 목록."""
    chunks, i = [], 0
    while i < len(words):
        seg_start = words[i]["start"]
        group, j = [], i
        while j < len(words) and len(group) < 8 and words[j]["end"] - seg_start < 3.5:
            group.append(words[j]["text"])
            j += 1
        if j == i:
            j += 1
        chunks.append(" ".join(group))
        i = j
    return chunks


def _translate_chunks(words: list[dict]) -> list[str]:
    """청크별 한국어 번역 (한 번에 배치 처리)."""
    from src.translator import translate_to_korean
    chunks = _make_chunks(words)
    return translate_to_korean(chunks) if chunks else []


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


def export(
    article_dir: Path,
    script_md: str,
    scene_ids: list[str],
    article_url: str = "",
    image_url: str = "",
) -> str:
    """
    1. videos/ 에 배경 비디오 생성 (썸네일 or 검은 배경)
    2. capcut_builder로 CapCut 프로젝트 직접 생성
    모든 파일은 article_dir 안에 유지됨.

    Returns: CapCut 프로젝트 경로
    """
    title_match = re.search(
        r'^#\s+(?:대본:\s*|YouTube Shorts Script:\s*|News Script:\s*)?(.+)',
        script_md, re.MULTILINE
    )
    title = title_match.group(1).strip() if title_match else "뉴스-숏폼"
    slug = re.sub(r'[^\w가-힣-]', '-', title).strip('-')[:40]

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

    # AI 이미지 생성 (images/ 폴더)
    from src.image_generator import generate_scene_image
    images_dir = article_dir / "images"
    images_dir.mkdir(exist_ok=True)

    # 스타일드 비디오 생성 (양피지 레이아웃)
    from src.frame_renderer import create_styled_video

    videos_dir = article_dir / "videos"
    videos_dir.mkdir(exist_ok=True)

    for sid in scene_ids:
        audio_path = article_dir / "audio" / f"scene_{sid}.mp3"
        dur = _get_audio_duration(str(audio_path)) if audio_path.exists() else 5.0
        video_path = str(videos_dir / f"scene_{sid}-A.mp4")

        words_path = article_dir / "subtitles" / f"scene_{sid}_words.json"
        words = json.loads(words_path.read_text()) if words_path.exists() else []

        # 청크별 한국어 번역 (8단어 청크 단위, 1:1 매핑)
        chunk_ko_path = article_dir / "subtitles" / f"scene_{sid}_chunk_ko.json"
        # 캐시가 없거나 번역 실패(빈 배열)인 경우 재시도
        if words:
            cached = json.loads(chunk_ko_path.read_text()) if chunk_ko_path.exists() else []
            if not cached:
                result = _translate_chunks(words)
                if result:  # 성공한 경우만 저장
                    chunk_ko_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
                    cached = result
        else:
            cached = []
        ko_chunks = cached

        scene_headline = common_title

        # AI 이미지 생성 (캐시 있으면 재사용)
        ai_image_path = str(images_dir / f"scene_{sid}.jpg")
        if not Path(ai_image_path).exists():
            narration_text = _extract_narration(script_md, sid)
            generate_scene_image(scene_headline, narration_text, ai_image_path)

        # 이미지 경로 결정: AI 생성 > 기사 썸네일 > None
        final_image_path = ai_image_path if Path(ai_image_path).exists() else None

        create_styled_video(
            output_path=video_path,
            headline=scene_headline,
            source=_extract_source(article_dir),
            image_url=image_url or None,
            words=words,
            ko_chunks=ko_chunks,
            total_duration=dur,
            image_path=final_image_path,
        )

    # article.json에 URL 저장
    article_json_path = article_dir / "article.json"
    if article_json_path.exists():
        data = json.loads(article_json_path.read_text())
        data["sourceUrl"] = article_url
        article_json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    # CapCut 프로젝트 직접 생성
    # 텍스트가 비디오 프레임에 이미 렌더링되어 있으므로 CapCut 텍스트 트랙 생략
    capcut_path = _build_capcut(article_dir, slug, skip_text_track=True)
    return capcut_path
