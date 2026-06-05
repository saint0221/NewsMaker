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


_LANG_FONT_MAP: dict[str, str] = {
    "ja": "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "zh": "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "es": "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
}


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
    active_char_start: int = -1,
    active_char_end: int = -1,
    image_cache: dict | None = None,
    transparent_hero: bool = False,   # True → 히어로 영역을 투명으로 (Ken Burns용)
    subtitle_lang: str = "ko",
) -> Image.Image:

    mode = "RGBA" if transparent_hero else "RGB"
    bg = _parchment_bg().convert(mode)
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

    # ── 기사 이미지 ──────────────────────────────────────────
    img_x0, img_x1 = 40, W - 40
    img_w = img_x1 - img_x0

    if transparent_hero:
        # Ken Burns 모드: 히어로 영역을 투명으로 남김
        if mode == "RGBA":
            transparent_region = Image.new("RGBA", (img_w, IMG_H), (0, 0, 0, 0))
            bg.paste(transparent_region, (img_x0, IMG_TOP))
    else:
        cache_key = image_url or "__none__"
        if image_cache is not None and cache_key in image_cache:
            hero = image_cache[cache_key]
        else:
            hero = _darken(_load_image(image_url, img_w, IMG_H))
            if image_cache is not None:
                image_cache[cache_key] = hero

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
    bl = "뉴스 숏폼"
    bw = draw.textbbox((0, 0), bl, font=f_badge)[2]
    draw.text(((W - bw) // 2, badge_y0 + 12), bl, font=f_badge, fill=BADGE_FG)

    # ── 자막 텍스트 구역 — 단일 라인씩, 5 엔트리 ─────────────────
    _lf_path = _LANG_FONT_MAP.get(subtitle_lang)
    f_ko = (ImageFont.truetype(_lf_path, 42)
            if _lf_path and os.path.exists(_lf_path)
            else _font(42))
    f_body      = _font(54)
    f_body_bold = _font(54, bold=True)
    KO_H        = 56   # 한글 줄 높이
    KO_GAP      = 6    # 한글↔영어 간격
    EN_H        = 70   # 영어 줄 높이
    ENTRY_GAP   = 14   # 엔트리 간격
    max_text_w  = W - TEXT_PAD_X * 2
    ty = TEXT_TOP

    for li, line in enumerate(lines):
        is_active = (li == active_line)
        ko = ko_lines[li] if li < len(ko_lines) else ""
        ko_color = KO_TEXT   if is_active else KO_FADED
        en_color = BODY_TEXT if is_active else BODY_FADED

        # ── 영어 — 래핑 허용 (오버플로 없이 전부 표시) ──────────
        en_wrapped = _wrap(line, f_body, max_text_w)

        if is_active and active_word:
            idx = active_char_start if active_char_start >= 0 else line.lower().find(active_word.lower())
        else:
            idx = -1

        char_offset = 0
        for wrap_line in en_wrapped:
            line_start = char_offset
            line_end   = char_offset + len(wrap_line)
            active_in  = (idx >= 0 and line_start <= idx < line_end)

            if active_in:
                local_idx = idx - line_start
                end_idx   = min((active_char_end - line_start) if active_char_end > idx
                                else local_idx + len(active_word),
                                len(wrap_line))
                before = wrap_line[:local_idx]
                word   = wrap_line[local_idx:end_idx]
                after  = wrap_line[end_idx:]
                x = TEXT_PAD_X
                if before:
                    draw.text((x, ty), before, font=f_body, fill=en_color)
                    x += draw.textbbox((0, 0), before, font=f_body)[2]
                wb = draw.textbbox((0, 0), word, font=f_body_bold)
                ww, wh = wb[2], wb[3] - wb[1]
                # 실제 렌더링 영역(baseline 포함)으로 박스 계산
                bb = draw.textbbox((x, ty), word, font=f_body_bold)
                pad_x, pad_y = 8, 6
                _rounded_rect(draw,
                    (bb[0] - pad_x, bb[1] - pad_y,
                     bb[2] + pad_x, bb[3] + pad_y),
                    radius=8, fill=HIGHLIGHT_BG)
                draw.text((x, ty), word, font=f_body_bold, fill=HIGHLIGHT_FG)
                x += ww + 2
                if after:
                    draw.text((x, ty), after, font=f_body, fill=en_color)
            else:
                draw.text((TEXT_PAD_X, ty), wrap_line, font=f_body, fill=en_color)

            ty += EN_H
            char_offset = line_end + 1

        ty -= EN_H
        ty += EN_H

        # ── 한글 — 영어 아래 ────────────────────────────────
        if ko:
            ko_lines_wrap = _wrap(ko, f_ko, max_text_w)
            ko_display = ko_lines_wrap[0] if ko_lines_wrap else ko
            draw.text((TEXT_PAD_X, ty), ko_display, font=f_ko, fill=ko_color)
        ty += KO_H + KO_GAP

        # 구분선 (활성 엔트리 아래)
        if is_active and li < len(lines) - 1:
            draw.line([(TEXT_PAD_X, ty + 6), (W - TEXT_PAD_X, ty + 6)],
                      fill=SEPARATOR, width=1)
            ty += 16

        ty += ENTRY_GAP

    return bg


# ── 씬 비디오 생성 ─────────────────────────────────────────────
IMG_W = W - 80  # 썸네일 영역 너비 (1000px)


def _create_ken_burns_video(
    image_path: str,
    output_path: str,
    total_duration: float,
    total_frames: int,
    zoom_direction: str = "in",
) -> bool:
    """ffmpeg zoompan 필터로 Ken Burns 효과 배경 영상 생성 (1000×560)."""
    try:
        fps = 30
        zoom_expr = f"1+0.08*on/{total_frames}" if zoom_direction == "in" \
                    else f"1.08-0.08*on/{total_frames}"

        subprocess.run([
            "ffmpeg", "-y",
            "-loop", "1", "-i", image_path,
            "-vf", (
                f"scale=8000:-1,"
                f"zoompan=z='{zoom_expr}':"
                f"x='iw/2-(iw/zoom/2)':"
                f"y='ih/2-(ih/zoom/2)':"
                f"d={total_frames}:s={IMG_W}x{IMG_H},"
                "format=yuv420p"
            ),
            "-t", str(total_duration),
            "-r", str(fps),
            "-c:v", "libx264", "-preset", "fast",
            "-an", output_path,
        ], check=True, capture_output=True)
        return True
    except Exception:
        return False


# 씬별 Ken Burns 애니메이션 프리셋 (6가지 변형)
# 각 항목: (zoom_dir, pan_x_ratio, pan_y_ratio)
# zoom_dir: "in"=줌인, "out"=줌아웃
# pan_x_ratio: 수평 이동량 (양수=오른쪽, 음수=왼쪽), 이미지 너비 대비 비율
# pan_y_ratio: 수직 이동량 (양수=아래, 음수=위), 이미지 높이 대비 비율
_KB_PRESETS = [
    ("in",  0.0,   0.0),   # 씬01: 중앙 줌인 (기본)
    ("out", 0.08,  0.0),   # 씬02: 줌아웃 + 좌로 패닝
    ("in", -0.08,  0.0),   # 씬03: 줌인 + 우로 패닝
    ("out", 0.0,   0.06),  # 씬04: 줌아웃 + 위로 패닝
    ("in",  0.0,  -0.06),  # 씬05: 줌인 + 아래로 패닝
    ("out",-0.06,  0.06),  # 씬06: 줌아웃 + 대각선 패닝
]


def create_styled_video(
    output_path: str,
    headline: str,
    source: str,
    image_url: str | None,
    words: list[dict],
    total_duration: float,
    ko_sentences: list[dict] | None = None,
    ko_chunks: list[str] | None = None,
    image_path: str | None = None,
    scene_index: int = 0,   # 0~5: Ken Burns 프리셋 선택
    subtitle_lang: str = "ko",
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
        img = render_frame(headline, source, image_url, [], [], 0, "", subtitle_lang=subtitle_lang)
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            img.save(f.name, quality=88, optimize=True)
            frame_path = f.name
        subprocess.run([
            "ffmpeg", "-y", "-loop", "1", "-i", frame_path,
            "-t", str(total_duration),
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-an", output_path,
        ], check=True, capture_output=True)
        Path(frame_path).unlink(missing_ok=True)
        return

    # 그룹화 — 단일 정규 함수(src/chunker.py) 사용
    from src.chunker import chunk_words_with_data
    raw_groups = chunk_words_with_data(words)
    groups: list[dict] = []
    for gi, group_words in enumerate(raw_groups):
        ko = ko_chunks[gi] if gi < len(ko_chunks) else ""
        groups.append({
            "line":  " ".join(w["text"] for w in group_words),
            "ko":    ko,
            "words": group_words,
            "start": group_words[0]["start"],
            "end":   group_words[-1]["end"],
        })

    # [-1, 0, +1, +2] = 4개 엔트리 표시 (글자 크기 확대로 조정)
    events: list[dict] = []
    for gi, grp in enumerate(groups):
        ctx_lines = []
        for delta in [-1, 0, 1, 2]:
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

    frame_paths: list[str] = []
    numbered_dir = tempfile.mkdtemp()

    # Ken Burns용 히어로 이미지 로드 (10% 여유분 확보)
    hero_raw: Image.Image | None = None
    if image_path and Path(image_path).exists():
        try:
            src = Image.open(image_path).convert("RGB")
            # 줌 영역 확보를 위해 15% 크게 스케일
            scale = max((IMG_W * 1.15) / src.width, (IMG_H * 1.15) / src.height)
            hero_raw = src.resize((int(src.width * scale), int(src.height * scale)), Image.LANCZOS)
        except Exception:
            hero_raw = None

    # 히어로 마스크 (둥근 모서리) — 재사용
    _hero_mask = Image.new("L", (IMG_W, IMG_H), 0)
    _md = ImageDraw.Draw(_hero_mask)
    _md.rounded_rectangle([0, 0, IMG_W, IMG_H], radius=20, fill=255)

    try:
        # 텍스트 레이어 캐시: key → RGBA (히어로 영역 투명)
        text_layer_cache: dict[tuple, Image.Image] = {}

        for fn in range(total_frames):
            t = fn / fps
            ev = find_event(t)

            if ev:
                key = (ev["active_li"], ev["active_word"],
                       ev.get("active_char_start", -1),
                       tuple(ev["lines"]), tuple(ev.get("ko_lines", [])))
            else:
                key = ("blank", "", ())

            # 텍스트 레이어 캐시 (Ken Burns 유무와 무관하게 transparent_hero)
            if key not in text_layer_cache:
                render_kwargs = dict(
                    transparent_hero=bool(hero_raw),
                    image_cache=image_cache,
                    subtitle_lang=subtitle_lang,
                )
                if ev:
                    layer = render_frame(
                        headline, source, image_url,
                        ev["lines"], ev.get("ko_lines", []),
                        ev["active_li"], ev["active_word"],
                        ev.get("active_char_start", -1),
                        ev.get("active_char_end", -1),
                        **render_kwargs,
                    )
                else:
                    layer = render_frame(
                        headline, source, image_url,
                        [], [], 0, "", -1, -1,
                        **render_kwargs,
                    )
                text_layer_cache[key] = layer.convert("RGBA")

            text_layer = text_layer_cache[key]

            if hero_raw is not None:
                # Ken Burns: 씬별 프리셋 적용
                preset = _KB_PRESETS[scene_index % len(_KB_PRESETS)]
                zoom_dir, pan_x_ratio, pan_y_ratio = preset
                progress = fn / max(total_frames - 1, 1)

                # 줌 방향 (in: 1.0→1.08, out: 1.08→1.0)
                if zoom_dir == "in":
                    zoom = 1.0 + 0.08 * progress
                else:
                    zoom = 1.08 - 0.08 * progress

                crop_w = int(IMG_W / zoom)
                crop_h = int(IMG_H / zoom)

                # 패닝: 시작→끝 선형 이동
                max_pan_x = int(hero_raw.width  * abs(pan_x_ratio))
                max_pan_y = int(hero_raw.height * abs(pan_y_ratio))
                pan_x = int(max_pan_x * progress * (1 if pan_x_ratio >= 0 else -1))
                pan_y = int(max_pan_y * progress * (1 if pan_y_ratio >= 0 else -1))

                # 중앙 기준 + 패닝 오프셋
                cx = (hero_raw.width  - crop_w) // 2 + pan_x
                cy = (hero_raw.height - crop_h) // 2 + pan_y

                # 경계 클램프
                cx = max(0, min(cx, hero_raw.width  - crop_w))
                cy = max(0, min(cy, hero_raw.height - crop_h))

                kb = hero_raw.crop((cx, cy, cx + crop_w, cy + crop_h))
                kb = kb.resize((IMG_W, IMG_H), Image.LANCZOS)
                kb = kb.point(lambda p: int(p * 0.55))  # 다크닝

                frame = text_layer.copy()
                frame.paste(kb, (40, IMG_TOP), _hero_mask)  # 투명 영역에 KB 삽입
                frame = frame.convert("RGB")
            else:
                frame = text_layer.convert("RGB")

            fp = Path(numbered_dir) / f"frame_{fn:06d}.jpg"
            frame.save(str(fp), quality=88, optimize=True)

        subprocess.run([
            "ffmpeg", "-y",
            "-framerate", str(fps),
            "-i", str(Path(numbered_dir) / "frame_%06d.jpg"),
            # 오디오와 정확히 같은 길이로 고정 → freeze 프레임 불필요
            "-t", str(total_duration),
            # JPG 풀레인지(yuvj420p) → TV 리미티드(yuv420p) 강제 변환
            "-vf", "scale=in_range=full:out_range=tv,format=yuv420p",
            "-c:v", "libx264", "-preset", "fast",
            "-profile:v", "high", "-level", "4.1",
            "-pix_fmt", "yuv420p",
            "-color_range", "1",
            "-an", output_path,
            ], check=True, capture_output=True)

    finally:
        import shutil as _shutil
        _shutil.rmtree(numbered_dir, ignore_errors=True)
