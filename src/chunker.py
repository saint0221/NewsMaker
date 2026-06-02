"""
words.json → 6단어 청크 변환 — 단일 정규 함수.
frame_renderer, videomaker_export, web/app.py 모두 이 함수를 사용한다.
청크 크기를 변경할 때는 이 파일 한 곳만 수정하면 된다.
"""

CHUNK_MAX_WORDS = 6
CHUNK_MAX_SECS  = 3.0


def chunk_words(words: list[dict]) -> list[str]:
    """
    words.json 단어 목록을 6단어 청크(문자열)로 변환한다.

    Parameters
    ----------
    words : [{"text": str, "start": float, "end": float}, ...]

    Returns
    -------
    list[str] — 청크 텍스트 목록
    """
    chunks: list[str] = []
    i = 0
    while i < len(words):
        seg_start = words[i]["start"]
        group: list[str] = []
        j = i
        while (j < len(words)
               and len(group) < CHUNK_MAX_WORDS
               and words[j]["end"] - seg_start < CHUNK_MAX_SECS):
            group.append(words[j]["text"])
            j += 1
        if j == i:
            j += 1
        chunks.append(" ".join(group))
        i = j
    return chunks


def chunk_words_with_data(words: list[dict]) -> list[list[dict]]:
    """
    words.json 단어 목록을 6단어 청크(딕셔너리 리스트)로 변환한다.
    frame_renderer 내부 그룹화용.
    """
    groups: list[list[dict]] = []
    i = 0
    while i < len(words):
        seg_start = words[i]["start"]
        group: list[dict] = []
        j = i
        while (j < len(words)
               and len(group) < CHUNK_MAX_WORDS
               and words[j]["end"] - seg_start < CHUNK_MAX_SECS):
            group.append(words[j])
            j += 1
        if j == i:
            j += 1
        groups.append(group)
        i = j
    return groups
