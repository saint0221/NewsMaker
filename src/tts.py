import os
import re
import math
import base64
import requests
from dataclasses import dataclass


@dataclass
class TTSResult:
    audio_path: str
    srt_word: str       # 단어 단위 (CapCut 자막용)
    srt_sentence: str   # 문장 단위 (슬롯 타이밍용)
    words: list         # [{"text": str, "start": float, "end": float}, ...]


def _fmt_srt_time(sec: float) -> str:
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    ms = int((sec % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _extract_words(characters, starts, ends) -> list[tuple[str, float, float]]:
    """문자 단위 정렬 데이터를 단어 단위로 변환."""
    words = []
    chars, w_start, w_end = [], 0.0, 0.0
    for i, ch in enumerate(characters):
        if ch in (' ', '\n', '\t'):
            if chars:
                words.append((''.join(chars), w_start, w_end))
                chars = []
        else:
            if not chars:
                w_start = starts[i]
            chars.append(ch)
            w_end = ends[i]
    if chars:
        words.append((''.join(chars), w_start, w_end))
    return words


def _alignment_to_srt_word(characters, starts, ends) -> str:
    words = _extract_words(characters, starts, ends)
    if not words:
        return ''

    # Group: up to 4 words or 3-second window per subtitle line
    segments, i = [], 0
    while i < len(words):
        seg_start = words[i][1]
        seg_words = []
        j = i
        while j < len(words) and len(seg_words) < 4 and words[j][2] - seg_start < 3.0:
            seg_words.append(words[j][0])
            j += 1
        if j == i:
            j += 1
        segments.append((' '.join(seg_words), seg_start, words[j - 1][2]))
        i = j

    lines = []
    for k, (text, start, end) in enumerate(segments, 1):
        lines.append(f"{k}\n{_fmt_srt_time(start)} --> {_fmt_srt_time(end)}\n{text}\n")
    return '\n'.join(lines)


def _to_words_json(characters, starts, ends) -> list:
    """단어별 타임스탬프 목록 반환 (카라오케 강조용)."""
    return [
        {"text": t, "start": round(s, 3), "end": round(e, 3)}
        for t, s, e in _extract_words(characters, starts, ends)
    ]


def _alignment_to_srt_sentence(characters, starts, ends) -> str:
    words = []
    chars, w_start, w_end = [], 0.0, 0.0
    for i, ch in enumerate(characters):
        if ch in (' ', '\n', '\t'):
            if chars:
                words.append((''.join(chars), w_start, w_end))
                chars = []
        else:
            if not chars:
                w_start = starts[i]
            chars.append(ch)
            w_end = ends[i]
    if chars:
        words.append((''.join(chars), w_start, w_end))

    if not words:
        return ''

    segments, sent_words, sent_start = [], [], 0.0
    for word, ws, we in words:
        if not sent_words:
            sent_start = ws
        sent_words.append(word)
        if re.search(r'[.!?。！？]$', word):
            segments.append((' '.join(sent_words), sent_start, we))
            sent_words = []
    if sent_words:
        segments.append((' '.join(sent_words), sent_start, words[-1][2]))

    lines = []
    for k, (text, start, end) in enumerate(segments, 1):
        lines.append(f"{k}\n{_fmt_srt_time(start)} --> {_fmt_srt_time(end)}\n{text}\n")
    return '\n'.join(lines)


class TTSGenerator:
    BASE_URL = "https://api.elevenlabs.io/v1/text-to-speech"
    MODEL_ID = "eleven_multilingual_v2"

    def __init__(self):
        self.api_key = os.environ["ELEVENLABS_API_KEY"]
        self.voice_id = os.environ.get("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")

    def generate(self, text: str, audio_path: str) -> TTSResult:
        url = f"{self.BASE_URL}/{self.voice_id}/with-timestamps"
        headers = {
            "xi-api-key": self.api_key,
            "Content-Type": "application/json",
        }
        payload = {
            "text": text,
            "model_id": self.MODEL_ID,
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
        }

        resp = requests.post(url, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()

        audio_bytes = base64.b64decode(data["audio_base64"])
        with open(audio_path, "wb") as f:
            f.write(audio_bytes)

        alignment = data["alignment"]
        characters = alignment["characters"]
        starts = alignment["character_start_times_seconds"]
        ends = alignment["character_end_times_seconds"]

        return TTSResult(
            audio_path=audio_path,
            srt_word=_alignment_to_srt_word(characters, starts, ends),
            srt_sentence=_alignment_to_srt_sentence(characters, starts, ends),
            words=_to_words_json(characters, starts, ends),
        )
