"""
article_dir 안의 파일로 CapCut 네이티브 프로젝트를 직접 생성한다.
VideoMaker 서버 불필요. 결과물은 CapCut 프로젝트 폴더에만 기록된다.
"""
import json
import os
import re
import shutil
import subprocess
import time
import uuid as _uuid_mod
from pathlib import Path

CAPCUT_ROOT = Path("/Users/hongss/Movies/CapCut/User Data/Projects/com.lveditor.draft")
FONT_PATH = "/Applications/CapCut.app/Contents/Resources/Font/SystemFont/en.ttf"
W, H = 1080, 1920


# ── 유틸 ─────────────────────────────────────────────────────────

def _uuid() -> str:
    return str(_uuid_mod.uuid4()).upper()


def _ffprobe_duration(path: str) -> int:
    """파일 길이를 마이크로초로 반환."""
    try:
        out = subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", path], text=True
        ).strip()
        return round(float(out) * 1_000_000)
    except Exception:
        return 5_000_000


def _ffprobe_size(path: str) -> tuple[int, int]:
    try:
        out = subprocess.check_output(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0", path],
            text=True
        ).strip()
        w, h = out.split(",")
        return int(w), int(h)
    except Exception:
        return 1280, 720


def _extract_last_frame(video_path: str, out_path: str) -> bool:
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-sseof", "-0.1", "-i", video_path,
             "-frames:v", "1", "-q:v", "2", out_path],
            check=True, capture_output=True
        )
        return Path(out_path).exists()
    except Exception:
        return False


def _parse_srt(text: str) -> list[dict]:
    entries = []
    for block in text.strip().split("\n\n"):
        lines = block.strip().splitlines()
        if len(lines) < 3:
            continue
        m = re.match(
            r"(\d{2}):(\d{2}):(\d{2}),(\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2}),(\d{3})",
            lines[1]
        )
        if not m:
            continue
        def to_us(h, mi, s, ms):
            return (int(h)*3600 + int(mi)*60 + int(s)) * 1_000_000 + int(ms)*1_000
        entries.append({
            "start": to_us(*m.group(1,2,3,4)),
            "end":   to_us(*m.group(5,6,7,8)),
            "text":  "\n".join(lines[2:]),
        })
    return entries


# ── CapCut JSON 빌더 ─────────────────────────────────────────────

def _style(color: list, range_: list) -> dict:
    return {
        "fill": {"content": {"solid": {"color": color}, "render_type": "solid"}},
        "range": range_,
        "size": 10,
        "font": {"path": FONT_PATH, "id": ""},
    }


def _text_content(text: str) -> str:
    return json.dumps({"styles": [_style([1,1,1], [0, len(text)])], "text": text})


def _karaoke_content(line: str, active_start: int, active_end: int) -> str:
    styles = []
    if active_start > 0:
        styles.append(_style([1,1,1], [0, active_start]))
    styles.append(_style([1, 0.9, 0], [active_start, active_end]))
    if active_end < len(line):
        styles.append(_style([1,1,1], [active_end, len(line)]))
    return json.dumps({"styles": styles, "text": line})


def _group_words(words: list[dict]) -> list[dict]:
    """단어 목록을 4단어/3초 그룹으로 묶는다."""
    groups, i = [], 0
    while i < len(words):
        seg_start = words[i]["start"]
        group = []
        j = i
        while j < len(words) and len(group) < 4 and words[j]["end"] - seg_start < 3.0:
            group.append(words[j])
            j += 1
        if j == i:
            j += 1
        groups.append({"line": " ".join(w["text"] for w in group), "words": group})
        i = j
    return groups


def _video_material(mat_id: str, path: str, duration: int, is_photo=False) -> dict:
    w, h = (W, H) if is_photo else _ffprobe_size(path)
    return {
        "id": mat_id, "unique_id": "", "type": "photo" if is_photo else "video",
        "duration": duration, "path": path, "media_path": "", "local_id": "",
        "has_audio": not is_photo, "reverse_path": "", "intensifies_path": "",
        "reverse_intensifies_path": "", "intensifies_audio_path": "", "cartoon_path": "",
        "width": w, "height": h, "category_id": "", "category_name": "local",
        "material_id": "", "material_name": Path(path).name, "material_url": "",
        "crop": {"upper_left_x": 0.0, "upper_left_y": 0.0, "upper_right_x": 1.0,
                 "upper_right_y": 0.0, "lower_left_x": 0.0, "lower_left_y": 1.0,
                 "lower_right_x": 1.0, "lower_right_y": 1.0},
        "crop_ratio": "free", "audio_fade": None, "crop_scale": 1.0,
        "extra_type_option": 0,
        "stable": {"stable_level": 0, "matrix_path": "", "time_range": {"start": 0, "duration": 0}},
        "matting": {"flag": 0, "path": "", "interactiveTime": [], "has_use_quick_brush": False,
                    "strokes": [], "has_use_quick_eraser": False, "expansion": 0, "feather": 0,
                    "reverse": False, "custom_matting_id": "", "enable_matting_stroke": False},
        "source": 0, "source_platform": 0, "formula_id": "", "check_flag": 62978047,
        "video_algorithm": {"algorithms": [], "time_range": None, "path": "",
                            "gameplay_configs": [], "ai_in_painting_config": [],
                            "complement_frame_config": None, "motion_blur_config": None,
                            "deflicker": None, "noise_reduction": None,
                            "quality_enhance": None, "super_resolution": None,
                            "ai_background_configs": [], "smart_complement_frame": None,
                            "aigc_generate": None, "aigc_generate_list": [],
                            "mouth_shape_driver": None, "ai_expression_driven": None,
                            "ai_motion_driven": None, "image_interpretation": None,
                            "story_video_modify_video_config": {
                                "task_id": "", "is_overwrite_last_video": False, "tracker_task_id": ""},
                            "skip_algorithm_index": []},
        "is_unified_beauty_mode": False, "object_locked": None, "smart_motion": None,
        "multi_camera_info": None, "freeze": None, "picture_from": "none",
        "picture_set_category_id": "", "picture_set_category_name": "",
        "team_id": "", "local_material_id": _uuid(), "origin_material_id": "",
        "request_id": "", "has_sound_separated": False, "is_text_edit_overdub": False,
        "is_ai_generate_content": False, "aigc_type": "none", "is_copyright": True,
        "aigc_history_id": "", "aigc_item_id": "", "local_material_from": "",
        "smart_match_info": None, "beauty_face_preset_infos": [], "beauty_body_preset_id": "",
        "beauty_face_auto_preset": {"preset_id": "", "name": "", "rate_map": "", "scene": ""},
        "beauty_face_auto_preset_infos": [], "beauty_body_auto_preset": None,
        "live_photo_timestamp": -1, "live_photo_cover_path": "", "content_feature_info": None,
        "corner_pin": None, "surface_trackings": [],
        "video_mask_stroke": {"resource_id": "", "path": "", "type": "", "color": "",
                              "size": 0.0, "alpha": 0.0, "distance": 0.0, "texture": 0.0,
                              "horizontal_shift": 0.0, "vertical_shift": 0.0},
        "video_mask_shadow": {"resource_id": "", "path": "", "color": "", "alpha": 0.0,
                              "blur": 0.0, "distance": 0.0, "angle": 0.0},
    }


def _audio_material(mat_id: str, path: str, duration: int) -> dict:
    return {
        "id": mat_id, "unique_id": "", "type": "extract_music",
        "name": Path(path).name, "duration": duration, "path": path,
        "category_name": "local", "wave_points": [],
        "music_id": str(_uuid_mod.uuid4()), "app_id": 0, "text_id": "",
        "tone_type": "", "source_platform": 0, "video_id": "", "effect_id": "",
        "resource_id": "", "third_resource_id": "", "category_id": "",
        "intensifies_path": "", "formula_id": "", "check_flag": 1, "team_id": "",
        "local_material_id": str(_uuid_mod.uuid4()), "tone_speaker": "",
        "mock_tone_speaker": "", "tone_effect_id": "", "tone_effect_name": "",
        "tone_platform": "", "cloned_model_type": "", "tone_category_id": "",
        "tone_category_name": "", "tone_second_category_id": "",
        "tone_second_category_name": "", "tone_emotion_name_key": "",
        "tone_emotion_style": "", "tone_emotion_role": "", "tone_emotion_selection": "",
        "tone_emotion_scale": 0.0, "moyin_emotion": "", "request_id": "",
        "query": "", "search_id": "", "sound_separate_type": "",
        "is_text_edit_overdub": False, "is_ugc": False, "is_ai_clone_tone": False,
        "is_ai_clone_tone_post": False, "source_from": "", "copyright_limit_type": "none",
        "aigc_history_id": "", "aigc_item_id": "", "music_source": "", "pgc_id": "",
        "pgc_name": "", "similiar_music_info": {"original_song_id": "", "original_song_name": ""},
        "ai_music_type": 0, "ai_music_enter_from": "", "lyric_type": 0,
        "tts_task_id": "", "tts_generate_scene": "", "ai_music_generate_scene": 0,
        "tts_benefit_info": {"benefit_type": "none", "benefit_log_id": "",
                             "benefit_log_extra": "", "benefit_amount": -1},
    }


def _text_material(mat_id: str, text: str, content_override: str | None = None) -> dict:
    group_ts = int(time.time() * 1000)
    return {
        "recognize_task_id": "", "id": mat_id, "name": "", "recognize_text": "",
        "recognize_model": "", "punc_model": "", "type": "subtitle",
        "content": content_override if content_override is not None else _text_content(text),
        "base_content": "",
        "words": {"start_time": [], "end_time": [], "text": []},
        "current_words": {"start_time": [], "end_time": [], "text": []},
        "global_alpha": 1.0, "combo_info": {"text_templates": []},
        "caption_template_info": {"resource_id": "", "third_resource_id": "",
                                  "resource_name": "", "category_id": "", "category_name": "",
                                  "effect_id": "", "request_id": "", "path": "",
                                  "is_new": False, "source_platform": 0},
        "layer_weight": 1, "letter_spacing": 0.0, "text_curve": None,
        "text_loop_on_path": False, "offset_on_path": 0.0,
        "enable_path_typesetting": False, "text_exceeds_path_process_type": 0,
        "text_typesetting_paths": None, "text_typesetting_paths_file": "",
        "text_typesetting_path_index": 0, "line_spacing": 0.02,
        "has_shadow": False, "shadow_color": "", "shadow_alpha": 0.9,
        "shadow_smoothing": 0.45, "shadow_distance": 5.0,
        "shadow_point": {"x": 0.6363961030678928, "y": -0.6363961030678927},
        "shadow_angle": -45.0, "shadow_thickness_projection_enable": False,
        "shadow_thickness_projection_angle": 0.0, "shadow_thickness_projection_distance": 0.0,
        "border_alpha": 1.0, "border_color": "", "border_width": 0.08, "border_mode": 0,
        "style_name": "", "text_color": "#FFFFFF", "text_alpha": 1.0, "font_name": "",
        "font_title": "none", "font_size": 8.0, "font_path": FONT_PATH, "font_id": "",
        "font_resource_id": "", "initial_scale": 1.0, "font_url": "", "typesetting": 0,
        "alignment": 1, "line_feed": 1, "use_effect_default_color": True,
        "is_rich_text": False, "shape_clip_x": False, "shape_clip_y": False,
        "ktv_color": "", "text_to_audio_ids": [], "bold_width": 0.0, "italic_degree": 0,
        "underline": False, "underline_width": 0.05, "underline_offset": 0.22,
        "sub_type": 0, "check_flag": 7, "text_size": 48, "font_category_name": "",
        "font_source_platform": 0, "font_third_resource_id": "", "font_category_id": "",
        "add_type": 2, "operation_type": 0, "recognize_type": 0, "fonts": [],
        "background_color": "", "background_alpha": 1.0, "background_style": 0,
        "background_round_radius": 0.0, "background_width": 0.14, "background_height": 0.14,
        "background_vertical_offset": 0.0, "background_horizontal_offset": 0.0,
        "background_fill": "", "single_char_bg_enable": False, "single_char_bg_color": "",
        "single_char_bg_alpha": 1.0, "single_char_bg_round_radius": 0.3,
        "single_char_bg_width": 0.0, "single_char_bg_height": 0.0,
        "single_char_bg_vertical_offset": 0.0, "single_char_bg_horizontal_offset": 0.0,
        "font_team_id": "", "tts_auto_update": False, "text_preset_resource_id": "",
        "group_id": f"import_GROUP_{group_ts}", "preset_id": "", "preset_name": "",
        "preset_category": "", "preset_category_id": "", "preset_index": 0,
        "preset_has_set_alignment": False, "force_apply_line_max_width": False,
        "language": "", "relevance_segment": [], "original_size": [],
        "fixed_width": -1.0, "fixed_height": -1.0, "line_max_width": 0.78,
        "oneline_cutoff": False, "cutoff_postfix": "", "subtitle_template_original_fontsize": 0.0,
        "subtitle_keywords": None, "inner_padding": -1.0, "multi_language_current": "none",
        "source_from": "", "is_lyric_effect": False, "lyric_group_id": "",
        "lyrics_template": {"resource_id": "", "resource_name": "", "panel": "",
                            "effect_id": "", "path": "", "category_id": "",
                            "category_name": "", "request_id": ""},
        "is_batch_replace": False, "is_words_linear": False, "ssml_content": "",
        "subtitle_keywords_config": None, "sub_template_id": -1,
        "translate_original_text": "",
    }


def _seg_base(seg_id, mat_id, t_start, t_dur, track_idx) -> dict:
    return {
        "id": seg_id, "render_timerange": {"start": 0, "duration": 0},
        "desc": "", "state": 0, "speed": 1.0, "is_loop": False,
        "is_tone_modify": False, "reverse": False, "intensifies_audio": False,
        "cartoon": False, "volume": 1.0, "last_nonzero_volume": 1.0,
        "material_id": mat_id, "extra_material_refs": [], "render_index": 0,
        "keyframe_refs": [], "enable_lut": False, "enable_adjust": False,
        "enable_hsl": False, "visible": True, "group_id": "",
        "enable_color_curves": True, "enable_hsl_curves": True,
        "hdr_settings": None, "enable_color_wheels": True,
        "track_attribute": 0, "is_placeholder": False, "template_id": "",
        "enable_smart_color_adjust": False, "template_scene": "default",
        "common_keyframes": [], "caption_info": None,
        "responsive_layout": {"enable": False, "target_follow": "",
                              "size_layout": 0, "horizontal_pos_layout": 0,
                              "vertical_pos_layout": 0},
        "enable_color_match_adjust": False, "enable_color_correct_adjust": False,
        "enable_adjust_mask": False, "raw_segment_id": "", "lyric_keyframes": None,
        "enable_video_mask": True, "digital_human_template_group_id": "",
        "color_correct_alg_result": "", "source": "segmentsourcenormal",
        "enable_mask_stroke": False, "enable_mask_shadow": False,
        "enable_color_adjust_pro": False,
        "target_timerange": {"start": t_start, "duration": t_dur},
        "track_render_index": track_idx,
    }


def _video_seg(seg_id, mat_id, t_start, t_dur, s_start, s_dur, track_idx) -> dict:
    s = _seg_base(seg_id, mat_id, t_start, t_dur, track_idx)
    s.update({
        "source_timerange": {"start": s_start, "duration": s_dur},
        "clip": {"scale": {"x": 1.0, "y": 1.0}, "rotation": 0.0,
                 "transform": {"x": 0.0, "y": 0.0},
                 "flip": {"vertical": False, "horizontal": False}, "alpha": 1.0},
        "uniform_scale": {"on": True, "value": 1.0},
        "enable_lut": True,
        "hdr_settings": {"mode": 1, "intensity": 1.0, "nits": 1000},
    })
    return s


def _audio_seg(seg_id, mat_id, t_start, t_dur, track_idx) -> dict:
    s = _seg_base(seg_id, mat_id, t_start, t_dur, track_idx)
    s.update({
        "source_timerange": {"start": 0, "duration": t_dur},
        "clip": None, "uniform_scale": None, "hdr_settings": None,
    })
    return s


def _text_seg(seg_id, mat_id, t_start, t_dur, track_idx) -> dict:
    s = _seg_base(seg_id, mat_id, t_start, t_dur, track_idx)
    s.update({
        "source_timerange": None,
        "clip": {"scale": {"x": 1.0, "y": 1.0}, "rotation": 0.0,
                 "transform": {"x": 0.0, "y": -0.70},
                 "flip": {"vertical": False, "horizontal": False}, "alpha": 1.0},
        "uniform_scale": {"on": True, "value": 1.0},
        "hdr_settings": None,
    })
    return s


def _empty_materials(videos, audios, texts) -> dict:
    empty = lambda: []
    return {
        "ai_translates": empty(), "audio_balances": empty(), "audio_effects": empty(),
        "audio_fades": empty(), "audio_pannings": empty(), "audio_pitch_shifts": empty(),
        "audio_track_indexes": empty(), "audios": audios, "beats": empty(),
        "canvases": empty(), "chromas": empty(), "color_curves": empty(),
        "common_mask": empty(), "digital_human_model_dressing": empty(),
        "digital_humans": empty(), "drafts": empty(), "effects": empty(),
        "flowers": empty(), "green_screens": empty(), "handwrites": empty(),
        "hsl": empty(), "hsl_curves": empty(), "images": empty(),
        "log_color_wheels": empty(), "loudnesses": empty(), "manual_beautys": empty(),
        "manual_deformations": empty(), "material_animations": empty(),
        "material_colors": empty(), "multi_language_refs": empty(),
        "placeholder_infos": empty(), "placeholders": empty(), "plugin_effects": empty(),
        "primary_color_wheels": empty(), "realtime_denoises": empty(), "shapes": empty(),
        "smart_crops": empty(), "smart_relights": empty(), "sound_channel_mappings": empty(),
        "speeds": empty(), "stickers": empty(), "tail_leaders": empty(),
        "text_templates": empty(), "texts": texts, "time_marks": empty(),
        "transitions": empty(), "video_effects": empty(), "video_radius": empty(),
        "video_shadows": empty(), "video_strokes": empty(), "video_trackings": empty(),
        "videos": videos, "vocal_beautifys": empty(), "vocal_separations": empty(),
    }


# ── 메인 빌더 ────────────────────────────────────────────────────

def build(
    article_dir: Path,
    slug: str,
    draft_id: str | None = None,
    timeline_id: str | None = None,
    skip_text_track: bool = False,
    videos_subdir: str | None = None,
) -> str:
    """
    article_dir 안의 파일로 CapCut 프로젝트를 생성하고 경로를 반환한다.

    skip_text_track=True: 비디오에 텍스트가 이미 렌더링된 경우 CapCut 텍스트 트랙 생략.
    """
    draft_id    = draft_id    or _uuid()
    timeline_id = timeline_id or _uuid()
    draft_name  = f"NewsPipeline_{slug}"[:80]
    capcut_dir  = CAPCUT_ROOT / draft_name
    capcut_dir.mkdir(parents=True, exist_ok=True)

    # Resources 하위 디렉토리
    res_dir    = capcut_dir / "Resources"
    vid_res    = res_dir / "videos"
    aud_res    = res_dir / "audio"
    subs_res   = res_dir / "subtitles"
    for d in [vid_res, aud_res, subs_res]:
        d.mkdir(parents=True, exist_ok=True)

    # 씬 ID 수집
    audio_dir = article_dir / "audio"
    scene_ids = sorted(
        re.match(r"scene_(\d+)\.mp3", f).group(1)
        for f in os.listdir(audio_dir) if re.match(r"scene_\d+\.mp3", f)
    ) if audio_dir.exists() else []

    video_mats, video_segs = [], []
    audio_mats, audio_segs = [], []
    text_mats,  text_segs  = [], []
    timeline_offset = 0

    for sid in scene_ids:
        # 파일 복사
        src_audio = article_dir / "audio" / f"scene_{sid}.mp3"
        dst_audio = aud_res / f"scene_{sid}.mp3"
        if src_audio.exists():
            shutil.copy2(src_audio, dst_audio)

        src_srt = article_dir / "subtitles" / f"scene_{sid}.srt"
        dst_srt = subs_res / f"scene_{sid}.srt"
        if src_srt.exists():
            shutil.copy2(src_srt, dst_srt)

        src_words = article_dir / "subtitles" / f"scene_{sid}_words.json"
        dst_words = subs_res / f"scene_{sid}_words.json"
        if src_words.exists():
            shutil.copy2(src_words, dst_words)

        _vdir = article_dir / "videos" / videos_subdir if videos_subdir else article_dir / "videos"
        vid_src = _vdir / f"scene_{sid}-A.mp4"
        dst_vid = vid_res / f"scene_{sid}-A.mp4"
        if vid_src.exists():
            shutil.copy2(vid_src, dst_vid)

        # 오디오 길이 = 씬 총 길이
        scene_dur = _ffprobe_duration(str(dst_audio)) if dst_audio.exists() else 5_000_000
        scene_start = timeline_offset

        # ── 비디오 세그먼트 ────────────────────────────────────────
        if dst_vid.exists():
            raw_dur = _ffprobe_duration(str(dst_vid))
            mat_id = _uuid()
            video_mats.append(_video_material(mat_id, str(dst_vid), raw_dur))

            if raw_dur >= scene_dur:
                video_segs.append(_video_seg(_uuid(), mat_id,
                    scene_start, scene_dur, 0, scene_dur, 0))
            else:
                # 비디오보다 오디오가 길면 마지막 프레임 freeze
                video_segs.append(_video_seg(_uuid(), mat_id,
                    scene_start, raw_dur, 0, raw_dur, 0))
                freeze_path = str(res_dir / f"scene_{sid}-A_freeze.jpg")
                freeze_dur = scene_dur - raw_dur
                if freeze_dur > 0 and _extract_last_frame(str(dst_vid), freeze_path):
                    fid = _uuid()
                    video_mats.append(_video_material(fid, freeze_path, freeze_dur, is_photo=True))
                    video_segs.append(_video_seg(_uuid(), fid,
                        scene_start + raw_dur, freeze_dur, 0, freeze_dur, 0))

        # ── 오디오 세그먼트 ────────────────────────────────────────
        if dst_audio.exists():
            amid = _uuid()
            audio_mats.append(_audio_material(amid, str(dst_audio), scene_dur))
            audio_segs.append(_audio_seg(_uuid(), amid, scene_start, scene_dur, 2))

        # ── 텍스트(자막) 세그먼트 ─────────────────────────────────
        # skip_text_track=True: 스타일드 비디오에 텍스트가 이미 구워져 있으므로 생략
        if skip_text_track:
            pass
        elif dst_words.exists():
            # 카라오케 모드
            words = json.loads(dst_words.read_text())
            groups = _group_words(words)
            for grp in groups:
                line = grp["line"]
                line_words = grp["words"]
                for wi, w in enumerate(line_words):
                    t_start_us = round(w["start"] * 1_000_000)
                    next_start = line_words[wi+1]["start"] if wi+1 < len(line_words) else w["end"]
                    t_end_us   = round((next_start if wi+1 < len(line_words) else w["end"]) * 1_000_000)
                    dur_us     = max(t_end_us - t_start_us, 33_333)

                    char_start = line.find(w["text"])
                    char_end   = char_start + len(w["text"])

                    tmid = _uuid()
                    text_mats.append(_text_material(
                        tmid, line,
                        content_override=_karaoke_content(line, char_start, char_end)
                    ))
                    text_segs.append(_text_seg(_uuid(), tmid,
                        scene_start + t_start_us, dur_us, 1))
        elif dst_srt.exists():
            # 일반 자막 모드
            for entry in _parse_srt(dst_srt.read_text()):
                dur = entry["end"] - entry["start"]
                tmid = _uuid()
                text_mats.append(_text_material(tmid, entry["text"]))
                text_segs.append(_text_seg(_uuid(), tmid,
                    scene_start + entry["start"], dur, 1))

        timeline_offset += scene_dur

    total_dur = timeline_offset
    now_us  = int(time.time() * 1_000_000)
    now_sec = int(time.time())

    # ── draft_info.json (타임라인 메인) ───────────────────────────
    tracks = [{"id": _uuid(), "type": "video", "flag": 0, "attribute": 0,
               "name": "", "is_default_name": True, "segments": video_segs}]
    if text_segs:
        tracks.append({"id": _uuid(), "type": "text", "flag": 1, "attribute": 0,
                       "name": "", "is_default_name": True, "segments": text_segs})
    if audio_segs:
        tracks.append({"id": _uuid(), "type": "audio", "flag": 0, "attribute": 0,
                       "name": "", "is_default_name": True, "segments": audio_segs})

    timeline = {
        "id": timeline_id, "version": 360000, "new_version": "167.0.0",
        "name": draft_name, "duration": total_dur,
        "create_time": now_sec, "update_time": now_sec, "fps": 30.0,
        "is_drop_frame_timecode": False, "color_space": -1,
        "config": {
            "video_mute": False, "record_audio_last_index": 1,
            "extract_audio_last_index": 1, "original_sound_last_index": 1,
            "subtitle_recognition_id": "", "subtitle_taskinfo": [],
            "lyrics_recognition_id": "", "lyrics_taskinfo": [],
            "subtitle_sync": True, "lyrics_sync": True, "voice_change_sync": False,
            "sticker_max_index": 1, "adjust_max_index": 1, "material_save_mode": 0,
            "export_range": None, "maintrack_adsorb": True, "combination_max_index": 1,
            "attachment_info": [], "zoom_info_params": None, "system_font_list": [],
            "multi_language_mode": "none", "multi_language_main": "none",
            "multi_language_current": "none", "multi_language_list": [],
            "subtitle_keywords_config": None, "use_float_render": False,
        },
        "canvas_config": {"ratio": "original", "width": W, "height": H, "background": None},
        "tracks": tracks, "group_container": None,
        "materials": _empty_materials(video_mats, audio_mats, text_mats),
        "keyframes": {"videos": [], "audios": [], "texts": [], "stickers": [],
                      "filters": [], "adjusts": [], "handwrites": [], "effects": []},
        "keyframe_graph_list": [],
        "platform": {"os": "mac", "os_version": "15.7.3", "app_id": 359289,
                     "app_version": "8.5.0", "app_source": "cc",
                     "device_id": "dcc1089857e61cf134c7fa4d4c141402",
                     "hard_disk_id": "3e51f875d224354772abca5898e08446",
                     "mac_address": "effe792c62cfad28084acd4722cc7c23"},
        "last_modified_platform": {"os": "mac", "os_version": "15.7.3", "app_id": 359289,
                     "app_version": "8.5.0", "app_source": "cc",
                     "device_id": "dcc1089857e61cf134c7fa4d4c141402",
                     "hard_disk_id": "3e51f875d224354772abca5898e08446",
                     "mac_address": "effe792c62cfad28084acd4722cc7c23"},
        "mutable_config": None, "cover": None, "retouch_cover": None,
        "extra_info": None, "relationships": [],
        "render_index_track_mode_on": True, "free_render_index_mode_on": False,
        "static_cover_image_path": "", "source": "default", "time_marks": None,
        "path": "", "lyrics_effects": [],
        "uneven_animation_template_info": {"composition": "", "content": "",
                                           "order": "", "sub_template_info_list": []},
        "draft_type": "video",
        "smart_ads_info": {"page_from": "", "routine": "", "draft_url": ""},
        "function_assistant_info": {
            "smart_rec_applied": False, "fixed_rec_applied": False, "auto_adjust": False,
            "auto_adjust_segid_list": [], "color_correction": False,
            "color_correction_segid_list": [], "enhance_quality": False,
            "smooth_slow_motion": False, "deflicker_segid_list": [],
            "video_noise_segid_list": [], "enhance_quality_segid_list": [],
            "smart_segid_list": [], "retouch": False, "retouch_segid_list": [],
            "enhande_voice": False, "enhance_voice_segid_list": [],
            "audio_noise_segid_list": [], "auto_caption": False,
            "auto_caption_segid_list": [], "auto_caption_template_id": "",
            "caption_opt": False, "caption_opt_segid_list": [],
            "eye_correction": False, "eye_correction_segid_list": [],
            "normalize_loudness": False, "normalize_loudness_segid_list": [],
            "normalize_loudness_audio_denoise_segid_list": [],
            "auto_adjust_fixed": False, "auto_adjust_fixed_value": 50.0,
            "color_correction_fixed": False, "color_correction_fixed_value": 50.0,
            "normalize_loudness_fixed": False, "enhande_voice_fixed": False,
            "retouch_fixed": False, "enhance_quality_fixed": False,
            "smooth_slow_motion_fixed": False, "fps": {"num": 0, "den": 1},
        },
    }

    # ── 보일러플레이트 파일들 ──────────────────────────────────────
    att_editing = json.dumps({"editing_draft": {
        "ai_remove_filter_words": {"enter_source": "", "right_id": ""},
        "ai_shorts_info": {"report_params": "", "type": 0},
        "cover_extra_info": {"draft_id": "", "position": 0, "select_segment_id": "",
                             "select_segment_source_start": 0,
                             "select_segment_target_start": 0, "type": 1},
        "crop_info_extra": {"crop_mirror_type": 0, "crop_rotate": 0.0, "crop_rotate_total": 0.0},
        "draft_used_recommend_function": "", "edit_type": 0,
        "version": "1.0.0", "paste_segment_list": [],
    }})
    att_pc = json.dumps({"ai_packaging_infos": [], "pc_feature_flag": 0,
                         "recognize_tasks": [], "safe_area_type": 0,
                         "template_item_infos": [], "unlock_template_ids": []})
    common_files = {
        "attachment_action_scene.json": json.dumps({"action_scene": {"removed_segments": [], "segment_infos": []}}),
        "attachment_gen_ai_info.json": json.dumps({"gen_ai": {"id": "", "scene": "", "version": "1.0.0"}}),
        "attachment_pc_timeline.json": json.dumps({"safe_area_type": 0}),
        "attachment_plugin_draft.json": json.dumps({"plugin_draft": {"plugin_segments": [], "version": "1.0.0"}}),
        "attachment_script_video.json": json.dumps({"script_video": {"attachment_valid": False, "version": "1.0.0"}}),
    }

    def write(path, content):
        Path(path).write_text(content if isinstance(content, str) else json.dumps(content, ensure_ascii=False))

    write(capcut_dir / "draft_info.json",       json.dumps(timeline, ensure_ascii=False))
    write(capcut_dir / "draft_agency_config.json",
          {"is_auto_agency_enabled": False, "use_converter": False, "video_resolution": 720})
    write(capcut_dir / "draft_biz_config.json", "")
    write(capcut_dir / "draft_virtual_store.json", {"draft_materials": [], "draft_virtual_store": []})
    write(capcut_dir / "key_value.json", {})
    write(capcut_dir / "performance_opt_info.json",
          {"manual_cancle_precombine_segs": None, "need_auto_precombine_segs": None})
    write(capcut_dir / "attachment_editing.json", att_editing)
    write(capcut_dir / "attachment_pc_common.json", att_pc)
    write(capcut_dir / "timeline_layout.json",
          {"dockItems": [{"dockIndex": 0, "ratio": 1, "timelineIds": [timeline_id],
                          "timelineNames": ["타임라인 01"]}], "layoutOrientation": 1})

    (capcut_dir / "common_attachment").mkdir(exist_ok=True)
    for name, content in common_files.items():
        write(capcut_dir / "common_attachment" / name, content)

    for empty_dir in ["adjust_mask", "smart_crop", "matting", "qr_upload", "subdraft", "draft_settings"]:
        (capcut_dir / empty_dir).mkdir(exist_ok=True)

    timelines_dir = capcut_dir / "Timelines"
    timelines_dir.mkdir(exist_ok=True)
    write(timelines_dir / "project.json", {
        "config": {"color_space": -1, "render_index_track_mode_on": False, "use_float_render": False},
        "create_time": now_us, "id": _uuid(), "main_timeline_id": timeline_id,
        "timelines": [{"create_time": now_us, "id": timeline_id, "is_marked_delete": False,
                       "name": "타임라인 01", "update_time": now_us}],
        "update_time": now_us, "version": 0,
    })
    tl_sub = timelines_dir / timeline_id
    tl_sub.mkdir(exist_ok=True)
    write(tl_sub / "draft_info.json",       json.dumps(timeline, ensure_ascii=False))
    write(tl_sub / "attachment_editing.json", att_editing)
    write(tl_sub / "attachment_pc_common.json", att_pc)
    (tl_sub / "common_attachment").mkdir(exist_ok=True)
    for name, content in common_files.items():
        write(tl_sub / "common_attachment" / name, content)

    # ── draft_meta_info.json ──────────────────────────────────────
    meta = {
        "cloud_draft_cover": False, "cloud_draft_sync": False,
        "draft_cover": "draft_cover.jpg", "draft_deeplink_url": "",
        "draft_enterprise_info": {"draft_enterprise_extra": "", "draft_enterprise_id": "",
                                  "draft_enterprise_name": "", "enterprise_material": []},
        "draft_fold_path": str(capcut_dir), "draft_id": draft_id,
        "draft_is_ae_produce": False, "draft_is_ai_packaging_used": False,
        "draft_is_ai_shorts": False, "draft_is_ai_translate": False,
        "draft_is_article_video_draft": False, "draft_is_cloud_temp_draft": False,
        "draft_is_from_deeplink": "false", "draft_is_invisible": False,
        "draft_is_web_article_video": False,
        "draft_materials": [{"type": t, "value": []} for t in [0,1,2,3,6,7,8]],
        "draft_materials_copied_info": [], "draft_name": draft_name,
        "draft_need_rename_folder": False, "draft_new_version": "",
        "draft_removable_storage_device": "", "draft_root_path": str(CAPCUT_ROOT),
        "draft_segment_extra_info": [], "draft_timeline_materials_size_": 0,
        "draft_type": "", "draft_web_article_video_enter_from": "",
        "tm_draft_cloud_completed": "", "tm_draft_cloud_entry_id": -1,
        "tm_draft_cloud_modified": 0, "tm_draft_cloud_parent_entry_id": -1,
        "tm_draft_cloud_space_id": -1, "tm_draft_cloud_user_id": -1,
        "tm_draft_create": now_us, "tm_draft_modified": now_us,
        "tm_draft_removed": 0, "tm_duration": total_dur,
    }
    write(capcut_dir / "draft_meta_info.json", json.dumps(meta, ensure_ascii=False))

    # ── root_meta_info.json 등록 ──────────────────────────────────
    root_meta_path = CAPCUT_ROOT / "root_meta_info.json"
    try:
        root_meta = json.loads(root_meta_path.read_text())
    except Exception:
        root_meta = {"all_draft_store": [], "draft_ids": 1, "root_path": str(CAPCUT_ROOT)}

    entries = root_meta.setdefault("all_draft_store", [])
    entry = {
        "draft_cover": "draft_cover.jpg", "draft_fold_path": str(capcut_dir),
        "draft_id": draft_id, "draft_is_ai_shorts": False, "draft_is_invisible": False,
        "draft_json_file": str(capcut_dir / "draft_info.json"),
        "draft_name": draft_name, "draft_new_version": "",
        "draft_removable_storage_device": "", "draft_root_path": str(CAPCUT_ROOT),
        "draft_timeline_materials_size": 0, "draft_type": "",
        "streaming_edit_draft_ready": False, "tm_draft_cloud_entry_id": -1,
        "tm_draft_cloud_modified": 0, "tm_draft_cloud_parent_entry_id": -1,
        "tm_draft_cloud_space_id": -1, "tm_draft_cloud_user_id": -1,
        "tm_draft_create": now_us, "tm_draft_modified": now_us,
        "tm_draft_removed": 0, "tm_duration": total_dur,
    }
    idx = next((i for i, e in enumerate(entries) if e.get("draft_id") == draft_id), -1)
    if idx >= 0:
        entries[idx] = entry
    else:
        entries.insert(0, entry)
        root_meta["draft_ids"] = root_meta.get("draft_ids", 1) + 1

    root_meta_path.write_text(json.dumps(root_meta, ensure_ascii=False, indent=2))

    return str(capcut_dir)
