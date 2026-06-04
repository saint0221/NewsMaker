"""AI 생성 대본의 팩트를 원문 기사와 대조 검증하고 수정한다."""
import subprocess
import re

_PROMPT = """\
You are a strict fact-checker for AI-generated news scripts.

ORIGINAL SOURCE MATERIAL:
{sources}

AI-GENERATED SCRIPT TO CHECK:
{script}

Your task:
1. Read each narration sentence in the script carefully.
2. Check every specific factual claim (names, numbers, dates, quotes, events) against the sources.
3. Rewrite ONLY sentences that contain facts NOT supported by or contradicting the sources.
4. Keep the script structure, scene labels, tone, and approximate length the same.
5. Reasonable inferences and analysis that don't contradict sources are acceptable — keep them.
6. Do NOT add new facts not in the sources.

Return the complete corrected script in the same markdown format, then append:

---FACT_CHECK_REPORT---
Issues found: [number]
[one line per fix: "Scene XX: Original claim → Corrected to"]
"""


def fact_check(script_md: str, source_texts: list[str]) -> tuple[str, list[str]]:
    """
    대본을 원문 기사와 대조 팩트 체크한 뒤 수정본을 반환한다.

    Returns:
        (corrected_script, issues)  — issues는 수정 내역 목록
    """
    if not source_texts or not any(source_texts):
        return script_md, []

    sources = "\n\n---\n\n".join(
        f"[SOURCE {i+1}]\n{t[:3000]}"
        for i, t in enumerate(source_texts)
        if t and t.strip()
    )

    prompt = _PROMPT.format(sources=sources, script=script_md)

    try:
        result = subprocess.run(
            ["claude", "--print", "--dangerously-skip-permissions",
             "--model", "claude-sonnet-4-6"],   # Sonnet: 추론 정확도 중요
            input=prompt, capture_output=True, text=True, timeout=180,
        )
        if result.returncode != 0:
            return script_md, []

        output = result.stdout.strip()

        if "---FACT_CHECK_REPORT---" not in output:
            # 리포트 없이 전체가 수정 대본인 경우
            return output if output else script_md, []

        parts = output.split("---FACT_CHECK_REPORT---", 1)
        corrected = parts[0].strip()
        report = parts[1].strip() if len(parts) > 1 else ""

        # 스크립트 앞에 분석 텍스트가 섞여 있으면 제거
        # "# News Script:" 또는 "## [SCENE" 이전의 모든 텍스트 제거
        import re as _re
        script_start = _re.search(r'^(# News Script:|## \[SCENE)', corrected, _re.MULTILINE)
        if script_start:
            corrected = corrected[script_start.start():].strip()

        issues: list[str] = []
        for line in report.splitlines():
            line = line.strip()
            if line and not line.startswith("Issues found:") and ("→" in line or "->" in line):
                issues.append(line)

        return corrected if corrected else script_md, issues

    except Exception:
        return script_md, []
