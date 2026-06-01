"""
뉴스 숏폼 비디오 프레임 렌더러.
이미지 레이아웃: 양피지 배경 + 상단 제목카드 + 기사 이미지 + 자막(카라오케)
"""
import io
import math
import os
import re
import subprocess
import tempfile
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1080, 1920

# ── 색상 팔레트 ────────────────────────────────────────────────
PARCHMENT    = (242, 232, 208)
PARCHMENT_DK = (228, 213, 182)
CARD_BG      = (255, 251, 242)
TITLE_TEXT   = (62,  44,  22)
SOURCE_TEXT  = (130, 100, 60)
BODY_TEXT    = (40,  30,  15)
BODY_FADED   = (160, 145, 120)
HIGHLIGHT_BG = (180, 70,  60)   # 진한 coral/red
HIGHLIGHT_FG = (255, 255, 255)
KO_TEXT      = (198, 88,  82)   # 한글 번역 산호색
KO_FADED     = (200, 160, 155)
BADGE_BG     = (80,  95,  55)   # 올리브
BADGE_FG     = (230, 220, 190)
SEPARATOR    = (200, 185, 155)
SHADOW       = (0,   0,   0,  40)

# ── 레이아웃 Y좌표 ─────────────────────────────────────────────
CARD_TOP    = 60
CARD_H      = 270
IMG_TOP     = CARD_TOP + CARD_H + 20
IMG_H       = 560
BADGE_TOP   = IMG_TOP + IMG_H + 18
BADGE_H     = 52
TEXT_TOP    = BADGE_TOP + BADGE_H + 36
TEXT_PAD_X  = 64


# ── 폰트 로더 ──────────────────────────────────────────────────
def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = []
    if bold:
        candidates = [
            "/System/Library/Fonts/AppleSDGothicNeo.ttc",
            "/System/Library/Fonts/Supplemental/Georgia Bold.ttf",
        ]
    else:
        candidates = [
            "/System/Library/Fonts/AppleSDGothicNeo.ttc",
            "/System/Library/Fonts/Supplemental/Georgia.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
        ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


# ── 텍스처 배경 ────────────────────────────────────────────────
def _parchment_bg() -> Image.Image:
    img = Image.new("RGB", (W, H), PARCHMENT)
    draw = ImageDraw.Draw(img)

    # 미묘한 그라디언트 (상단 약간 밝게)
    for y in range(H):
        t = y / H
        r = int(PARCHMENT[0] - 12 * t)
        g = int(PARCHMENT[1] - 10 * t)
        b = int(PARCHMENT[2] -  8 * t)
        draw.line([(0, y), (W, y)], fill=(r, g, b))

    # 거미줄 — 4개 코너

    return img


def _draw_spiderweb(draw: ImageDraw.Draw, cx: int, cy: int,
                    radius: int, open_right: bool, open_bottom: bool):
    color = (160, 140, 100, 60)
    spokes = 7
    rings = 5

    dx = 1 if open_right else -1
    dy = 1 if open_bottom else -1
    angle_start = 0 if (open_right and open_bottom) else \
                  90 if (not open_right and open_bottom) else \
                  270 if (open_right and not open_bottom) else 180

    spoke_angles = [math.radians(angle_start + i * 90 / (spokes - 1)) for i in range(spokes)]

    # 방사선
    for angle in spoke_angles:
        x2 = cx + int(radius * math.cos(angle)) * dx
        y2 = cy + int(radius * math.sin(angle)) * dy
        draw.line([(cx, cy), (x2, y2)], fill=color[:3], width=1)

    # 동심원 호
    for ring in range(1, rings + 1):
        r = radius * ring / rings
        for i, angle in enumerate(spoke_angles[:-1]):
            a1, a2 = angle, spoke_angles[i + 1]
            x1 = cx + int(r * math.cos(a1)) * dx
            y1 = cy + int(r * math.sin(a1)) * dy
            x2 = cx + int(r * math.cos(a2)) * dx
            y2 = cy + int(r * math.sin(a2)) * dy
            draw.line([(x1, y1), (x2, y2)], fill=color[:3], width=1)


# ── 둥근 사각형 ────────────────────────────────────────────────
def _rounded_rect(draw: ImageDraw.Draw, xy: tuple, radius: int,
                  fill=None, outline=None, width: int = 1):
    x0, y0, x1, y1 = xy
    draw.rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=fill,
                           outline=outline, width=width)


# ── 이미지 다운로드 & 크롭 ─────────────────────────────────────
def _load_image(url: str | None, target_w: int, target_h: int) -> Image.Image:
    if url:
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            img = Image.open(io.BytesIO(resp.content)).convert("RGB")
            ratio = max(target_w / img.width, target_h / img.height)
            nw = int(img.width * ratio)
            nh = int(img.height * ratio)
            img = img.resize((nw, nh), Image.LANCZOS)
            left = (nw - target_w) // 2
            top  = (nh - target_h) // 2
            return img.crop((left, top, left + target_w, top + target_h))
        except Exception:
            pass
    # 폴백: 어두운 그라디언트
    fallback = Image.new("RGB", (target_w, target_h), (30, 25, 20))
    draw = ImageDraw.Draw(fallback)
    for y in range(target_h):
        t = y / target_h
        c = int(30 + 20 * t)
        draw.line([(0, y), (target_w, y)], fill=(c, c-5, c-10))
    return fallback


def _darken(img: Image.Image, factor: float = 0.55) -> Image.Image:
    return img.point(lambda p: int(p * factor))


# ── 텍스트 줄 래핑 ─────────────────────────────────────────────
def _wrap(text: str, font: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    dummy = Image.new("RGB", (1, 1))
    d = ImageDraw.Draw(dummy)
    words = text.split()
    lines, cur = [], ""
    for w in words:
        test = (cur + " " + w).strip()
        bbox = d.textbbox((0, 0), test, font=font)
        if bbox[2] > max_w and cur:
            lines.append(cur)
            cur = w
        else:
            cur = test
    if cur:
        lines.append(cur)
    return lines


# ── 메인 프레임 렌더 ───────────────────────────────────────────
def render_frame(
    headline: str,
    source: str,
    image_url: str | None,
    lines: list[str],
    ko_lines: list[str],
    active_line: int,
    active_word: str,
    active_char_start: int = -1,   # 정확한 강조 위치 (-1이면 find() fallback)
    active_char_end: int = -1,
    image_cache: dict | None = None,
) -> Image.Image:

    bg = _parchment_bg()
    draw = ImageDraw.Draw(bg, "RGBA")

    # ── 제목 카드 ────────────────────────────────────────────
    card_x0, card_x1 = 40, W - 40
    card_y0, card_y1 = CARD_TOP, CARD_TOP + CARD_H

    # 카드 그림자
    shadow_img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow_img)
    sd.rounded_rectangle([card_x0+6, card_y0+6, card_x1+6, card_y1+6],
                          radius=24, fill=(0, 0, 0, 35))
    shadow_blur = shadow_img.filter(ImageFilter.GaussianBlur(12))
    bg.paste(Image.alpha_composite(
        Image.new("RGBA", bg.size, (0,0,0,0)),
        shadow_blur
    ).convert("RGB"), mask=shadow_blur.split()[3])

    _rounded_rect(draw, (card_x0, card_y0, card_x1, card_y1),
                  radius=24, fill=CARD_BG)

    # 제목 텍스트
    f_title = _font(52, bold=True)
    f_source = _font(30)
    text_x = card_x0 + 36
    max_w = card_x1 - card_x0 - 72
    title_lines = _wrap(headline, f_title, max_w)[:2]
    ty = card_y0 + 36
    for tl in title_lines:
        draw.text((text_x, ty), tl, font=f_title, fill=TITLE_TEXT)
        bbox = draw.textbbox((0, 0), tl, font=f_title)
        ty += bbox[3] - bbox[1] + 8

    # 소스 뱃지
    badge_text = f"● {source}"
    draw.text((text_x, ty + 10), badge_text, font=f_source, fill=SOURCE_TEXT)

    # ── 기사 이미지 ──────────────────────────────────────────
    img_x0, img_x1 = 40, W - 40
    img_w = img_x1 - img_x0
    cache_key = image_url or "__none__"
    if image_cache is not None and cache_key in image_cache:
        hero = image_cache[cache_key]
    else:
        hero = _darken(_load_image(image_url, img_w, IMG_H))
        if image_cache is not None:
            image_cache[cache_key] = hero

    # 둥근 마스크로 이미지 붙이기
    mask = Image.new("L", (img_w, IMG_H), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle([0, 0, img_w, IMG_H], radius=20, fill=255)
    bg.paste(hero, (img_x0, IMG_TOP), mask)

    # ── 소스 뱃지 바 ─────────────────────────────────────────
    badge_x0, badge_x1 = 40, W - 40
    badge_y0, badge_y1 = BADGE_TOP, BADGE_TOP + BADGE_H
    _rounded_rect(draw, (badge_x0, badge_y0, badge_x1, badge_y1),
                  radius=BADGE_H // 2, fill=BADGE_BG)
    f_badge = _font(28, bold=True)
    bl = f"📰  {source}  ·  뉴스 숏폼"
    bw = draw.textbbox((0, 0), bl, font=f_badge)[2]
    draw.text(((W - bw) // 2, badge_y0 + 12), bl, font=f_badge, fill=BADGE_FG)

    # ── 자막 텍스트 구역 — 단일 라인씩, 5 엔트리 ─────────────────
    f_ko        = _font(32)
    f_body      = _font(40)
    f_body_bold = _font(40, bold=True)
    KO_H        = 44   # 한글 줄 높이
    KO_GAP      = 6    # 한글↔영어 간격
    EN_H        = 54   # 영어 줄 높이
    ENTRY_GAP   = 18   # 엔트리 간격
    max_text_w  = W - TEXT_PAD_X * 2
    ty = TEXT_TOP

    for li, line in enumerate(lines):
        is_active = (li == active_line)
        ko = ko_lines[li] if li < len(ko_lines) else ""
        ko_color = KO_TEXT   if is_active else KO_FADED
        en_color = BODY_TEXT if is_active else BODY_FADED

        # ── 한글 — 한 줄만 (넘치면 말줄임) ──────────────────
        if ko:
            ko_lines_wrap = _wrap(ko, f_ko, max_text_w)
            ko_display = ko_lines_wrap[0] if ko_lines_wrap else ko
            draw.text((TEXT_PAD_X, ty), ko_display, font=f_ko, fill=ko_color)
        ty += KO_H + KO_GAP

        # ── 영어 — 한 줄 (강조 단어) ─────────────────────────
        # 정확한 문자 위치 우선 사용 → 같은 단어 중복 강조 방지
        if is_active and active_word:
            idx = active_char_start if active_char_start >= 0 else line.lower().find(active_word.lower())
        else:
            idx = -1
        if idx >= 0:
            # active_char_end로 정확한 끝 위치 사용
            end_idx = active_char_end if (active_char_end > idx) else idx + len(active_word)
            before = line[:idx]
            word   = line[idx:end_idx]
            after  = line[end_idx:]
            x = TEXT_PAD_X
            if before:
                draw.text((x, ty), before, font=f_body, fill=en_color)
                x += draw.textbbox((0, 0), before, font=f_body)[2]
            wb = draw.textbbox((0, 0), word, font=f_body_bold)
            ww, wh = wb[2], wb[3] - wb[1]
            pad = 6
            _rounded_rect(draw,
                (x - pad, ty - pad//2, x + ww + pad, ty + wh + pad//2),
                radius=8, fill=HIGHLIGHT_BG)
            draw.text((x, ty), word, font=f_body_bold, fill=HIGHLIGHT_FG)
            x += ww + 2
            if after:
                draw.text((x, ty), after, font=f_body, fill=en_color)
        else:
            draw.text((TEXT_PAD_X, ty), line, font=f_body, fill=en_color)

        ty += EN_H

        # 구분선 (활성 엔트리 아래)
        if is_active and li < len(lines) - 1:
            draw.line([(TEXT_PAD_X, ty + 6), (W - TEXT_PAD_X, ty + 6)],
                      fill=SEPARATOR, width=1)
            ty += 16

        ty += ENTRY_GAP

    return bg


# ── 씬 비디오 생성 ─────────────────────────────────────────────
def create_styled_video(
    output_path: str,
    headline: str,
    source: str,
    image_url: str | None,
    words: list[dict],
    total_duration: float,
    ko_sentences: list[dict] | None = None,   # 레거시 (사용 안 함)
    ko_chunks: list[str] | None = None,        # 청크별 한국어 번역 (groups와 1:1)
):
    """
    words 타이밍에 맞춰 스타일드 프레임을 생성하고 비디오로 조립한다.
    words가 없으면 정적 배경 프레임 1장으로 대체.
    """
    from src.videomaker_export import _create_black_video

    # ko_chunks[i] → groups[i]에 직접 대응 (1:1 청크 번역)
    ko_chunks = ko_chunks or []

    if not words:
        # 정적 프레임 한 장
        img = render_frame(headline, source, image_url, [], [], 0, "")
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            img.save(f.name, quality=92)
            frame_path = f.name
        subprocess.run([
            "ffmpeg", "-y", "-loop", "1", "-i", frame_path,
            "-t", str(total_duration),
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-an", output_path,
        ], check=True, capture_output=True)
        Path(frame_path).unlink(missing_ok=True)
        return

    # 8단어 청크 그룹화 — ko_chunks[gi]가 각 그룹의 한국어 번역
    groups: list[dict] = []
    i = 0
    while i < len(words):
        seg_start = words[i]["start"]
        group_words = []
        j = i
        while j < len(words) and len(group_words) < 8 and words[j]["end"] - seg_start < 3.5:
            group_words.append(words[j])
            j += 1
        if j == i:
            j += 1
        gi = len(groups)
        ko = ko_chunks[gi] if gi < len(ko_chunks) else ""
        groups.append({
            "line":  " ".join(w["text"] for w in group_words),
            "ko":    ko,
            "words": group_words,
            "start": group_words[0]["start"],
            "end":   group_words[-1]["end"],
        })
        i = j

    # [-2, -1, 0, +1, +2] = 5개 엔트리 표시
    events: list[dict] = []
    for gi, grp in enumerate(groups):
        ctx_lines = []
        for delta in [-2, -1, 0, 1, 2]:
            idx = gi + delta
            if 0 <= idx < len(groups):
                ctx_lines.append((delta, groups[idx]["line"], groups[idx].get("ko", "")))

        visible    = [l  for _, l, _  in ctx_lines]
        visible_ko = [ko for _, _, ko in ctx_lines]
        active_li  = next(i for i, (d, _, _) in enumerate(ctx_lines) if d == 0)

        next_grp_start = groups[gi + 1]["words"][0]["start"] if gi + 1 < len(groups) else None

        for wi, w in enumerate(grp["words"]):
            t_start = w["start"]
            if wi + 1 < len(grp["words"]):
                # 그룹 내: 다음 단어 시작까지 (갭 포함)
                t_end = grp["words"][wi + 1]["start"]
            elif next_grp_start is not None:
                # 그룹 마지막: 다음 그룹 첫 단어 시작까지 (갭 포함)
                t_end = next_grp_start
            else:
                # 전체 마지막 단어: total_duration까지
                t_end = total_duration
            # 그룹 내 해당 단어의 정확한 문자 위치 계산 (같은 단어 중복 방지)
            prefix = " ".join(pw["text"] for pw in grp["words"][:wi])
            char_start = len(prefix) + (1 if wi > 0 else 0)
            char_end = char_start + len(w["text"])

            events.append({
                    "t_start":         t_start,
                    "t_end":           t_end,
                    "lines":           visible,
                    "ko_lines":        visible_ko,
                    "active_li":       active_li,
                    "active_word":     w["text"],
                    "active_char_start": char_start,
                    "active_char_end":   char_end,
                })

    # 30fps 그리드 기준으로 각 프레임 시간 t에 해당하는 이벤트를 찾아 렌더링
    fps = 30
    total_frames = round(total_duration * fps)
    image_cache: dict = {}

    # events를 t_start 기준으로 이진 탐색할 수 있도록 정렬
    events.sort(key=lambda e: e["t_start"])
    ev_starts = [e["t_start"] for e in events]

    import bisect

    def find_event(t: float) -> dict | None:
        """시간 t에 해당하는 이벤트 반환."""
        idx = bisect.bisect_right(ev_starts, t) - 1
        if idx < 0:
            return None
        ev = events[idx]
        return ev if t < ev["t_end"] else None

    # 렌더링 캐시: (active_li, active_word) → frame jpg path
    frame_cache: dict[tuple, str] = []
    frame_paths: list[str] = []
    numbered_dir = tempfile.mkdtemp()

    try:
        rendered_cache: dict[tuple, Image.Image] = {}

        for fn in range(total_frames):
            t = fn / fps
            ev = find_event(t)

            if ev:
                key = (ev["active_li"], ev["active_word"],
                       ev.get("active_char_start", -1),
                       tuple(ev["lines"]), tuple(ev.get("ko_lines", [])))
            else:
                key = ("blank", "", ())

            if key not in rendered_cache:
                if ev:
                    img = render_frame(
                        headline, source, image_url,
                        ev["lines"], ev.get("ko_lines", []),
                        ev["active_li"], ev["active_word"],
                        ev.get("active_char_start", -1),
                        ev.get("active_char_end", -1),
                        image_cache,
                    )
                else:
                    img = render_frame(headline, source, image_url, [], [], 0, "", -1, -1, image_cache)
                rendered_cache[key] = img

            fp = Path(numbered_dir) / f"frame_{fn:06d}.png"
            rendered_cache[key].save(str(fp))
            frame_paths.append(str(fp))

        subprocess.run([
            "ffmpeg", "-y",
            "-framerate", str(fps),
            "-i", str(Path(numbered_dir) / "frame_%06d.png"),
            "-vf", "format=yuv420p",          # yuvj420p(JPEG풀레인지) → yuv420p
            "-c:v", "libx264", "-preset", "fast",
            "-profile:v", "high", "-level", "4.1",
            "-pix_fmt", "yuv420p",
            "-an", output_path,
        ], check=True, capture_output=True)

    finally:
        import shutil as _shutil
        _shutil.rmtree(numbered_dir, ignore_errors=True)
