"""영어 문장 목록을 Claude CLI로 한국어 번역한다."""
import json
import re
import subprocess


_SYSTEM = """\
당신은 뉴스 숏폼 영상의 한국어 자막 번역가입니다.

규칙:
- 영어 나레이션 청크를 자연스럽고 구어체 한국어로 번역한다
- 고등학생도 쉽게 이해할 수 있는 쉬운 단어를 사용한다
- 어려운 전문 용어는 쉬운 말로 풀어쓴다 (예: "양적완화" → "돈을 더 풀어서")
- 청크가 문장 중간에서 잘린 경우에도 자연스럽게 번역한다
- 친근하고 대화하듯 말하는 톤 유지
- 고유명사(인명, 기업명, 제품명)는 음역하거나 원문 표기를 유지한다
- 직역 금지 — 한국어 화자가 실제로 말하는 방식으로 번역한다
- 각 청크는 독립적으로 번역하되, 전체 흐름이 자연스럽도록 한다"""

_USER_TEMPLATE = """\
다음 영어 청크들을 한국어로 번역하세요.
청크들은 뉴스 나레이션의 연속된 부분입니다.

{numbered}

JSON 배열로만 응답하세요: ["번역1", "번역2", ...]"""


def translate_to_korean(sentences: list[str], max_retries: int = 3) -> list[str]:
    """영어 나레이션 청크 리스트를 자연스러운 한국어로 번역."""
    if not sentences:
        return []

    numbered = "\n".join(f"{i+1}. {s}" for i, s in enumerate(sentences))
    prompt = _USER_TEMPLATE.format(numbered=numbered)

    for attempt in range(max_retries):
        try:
            result = subprocess.run(
                ["claude", "--print", "--dangerously-skip-permissions",
                 "--model", "claude-sonnet-4-6",   # Haiku → Sonnet (번역 품질 향상)
                 "--system-prompt", _SYSTEM],
                input=prompt, capture_output=True, text=True, timeout=120,
            )
            text = result.stdout.strip()
            m = re.search(r'\[.*\]', text, re.DOTALL)
            if not m:
                continue
            parsed = json.loads(m.group())
            if len(parsed) != len(sentences):
                continue
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
