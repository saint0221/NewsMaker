"""영어 문장 목록을 Claude CLI로 한국어 번역한다."""
import json
import re
import subprocess


def translate_to_korean(sentences: list[str], max_retries: int = 3) -> list[str]:
    """영어 문장 리스트를 한국어로 번역. 최대 3회 재시도, 실패 시 빈 목록 반환."""
    if not sentences:
        return []

    numbered = "\n".join(f"{i+1}. {s}" for i, s in enumerate(sentences))
    prompt = (
        "Translate each English sentence to natural Korean. "
        "Return ONLY a JSON array of Korean strings in the same order.\n\n"
        f"{numbered}\n\n"
        'Format: ["번역1", "번역2", ...]'
    )

    for attempt in range(max_retries):
        try:
            result = subprocess.run(
                ["claude", "--print", "--dangerously-skip-permissions",
                 "--model", "claude-haiku-4-5-20251001"],
                input=prompt, capture_output=True, text=True, timeout=90,
            )
            text = result.stdout.strip()
            m = re.search(r'\[.*\]', text, re.DOTALL)
            if not m:
                continue
            parsed = json.loads(m.group())
            if len(parsed) != len(sentences):
                continue
            # 한글 포함 여부로 번역 성공 판단
            has_korean = any(any('가' <= c <= '힣' for c in p) for p in parsed)
            if not has_korean:
                continue
            return parsed
        except Exception:
            continue

    return []


def translate_srt_sentences(srt_path: str) -> list[dict]:
    """
    sentence SRT 파일을 읽고 한국어 번역을 추가한 목록을 반환한다.
    반환값: [{"en": str, "ko": str, "start": float, "end": float}, ...]
    """
    def _parse_srt(text: str):
        entries = []
        for block in text.strip().split("\n\n"):
            lines = block.strip().splitlines()
            if len(lines) < 3:
                continue
            m = re.match(
                r"(\d{2}):(\d{2}):(\d{2}),(\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2}),(\d{3})",
                lines[1],
            )
            if not m:
                continue
            def to_s(h, mi, s, ms):
                return int(h)*3600 + int(mi)*60 + int(s) + int(ms)/1000
            entries.append({
                "en": " ".join(lines[2:]),
                "start": to_s(*m.group(1,2,3,4)),
                "end":   to_s(*m.group(5,6,7,8)),
            })
        return entries

    from pathlib import Path
    content = Path(srt_path).read_text(encoding="utf-8")
    entries = _parse_srt(content)
    if not entries:
        return []

    translations = translate_to_korean([e["en"] for e in entries])
    for e, ko in zip(entries, translations):
        e["ko"] = ko
    return entries
