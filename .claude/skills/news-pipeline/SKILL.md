---
name: news-pipeline
description: |
  뉴스 숏폼 영상 자동화 파이프라인 오케스트레이터.
  주제 입력부터 CapCut 프로젝트 생성까지 전체 워크플로우를 조율한다.
  다음 상황에서 반드시 이 스킬을 사용하라:
  - "뉴스 영상 만들어줘", "영상 생성", "주제로 영상"
  - "AI 반도체 뉴스 영상", "한국 경제 숏폼", 특정 주제를 언급하며 영상 요청
  - "다시 실행", "재생성", "씬 다시", "번역 다시", "영상 업데이트"
  - "파이프라인 실행", "뉴스 캡컷 만들어", "CapCut으로 뉴스"
---

# News Pipeline Orchestrator

주제 검색 → 전문 크롤링 → 대본+팩트체크 → AI 이미지+TTS+번역 → 프레임 렌더링 → CapCut 조립

**실행 모드:** 하이브리드
- Phase 1 (검색·크롤링·대본): 순차 파이프라인
- Phase 2 (이미지·TTS·번역): 서브 에이전트 병렬 팬아웃
- Phase 3 (렌더링·CapCut): 서브 에이전트 팬아웃 → 팬인

**서버 실행:** `python3.12 -m uvicorn web.app:app --port 8899`

---

## Phase 0: 컨텍스트 확인

```python
article_dir = Path("output") / datetime.now().strftime("%Y%m%d_%H%M%S") / "article_01"
# 기존 output/ 확인 → 재실행 요청이면 최근 article_dir 재사용
```

---

## Phase 1: 검색 + 크롤링 + 대본 (순차)

### 1-1. 뉴스 검색 (researcher)

```python
from src.fetcher import search_by_topic, fetch_full_content

# 한국어 주제: Naver API → RSS 폴백
# 영어 주제: NewsAPI → RSS 폴백
articles = search_by_topic(topic, count=5)
if selected_indices:
    articles = [a for i, a in enumerate(articles) if i in selected_indices]

primary = articles[0]
full_body = fetch_full_content(primary.url) or primary.description

related_bodies = []
for r in articles[1:4]:  # 최대 3개 관련 기사
    body = fetch_full_content(r.url)
    if body: related_bodies.append((r.title, body))

# 출처 기록 (반드시)
_save_sources_html(article_dir, primary, full_body, related_arts)
```

### 1-2. 대본 생성 (scriptwriter)

```python
# SCRIPT_PROMPT 사용 — 고등학생 눈높이, 6씬, 2~3분, 소스명 제거
script_md = _run_claude(prompt)
narrations = _extract_narrations(script_md)  # dict[sid, text]
```

### 1-3. 팩트체크 (scriptwriter)

```python
from src.fact_checker import fact_check
corrected, issues = fact_check(script_md, all_sources)
# Claude Sonnet으로 원문 대조, 오류 자동 수정
```

### 1-4. 공통 타이틀 생성

```python
from src.videomaker_export import _make_common_title
common_title = _make_common_title(script_md, topic)
# 5~8단어 영어 타이틀, 전 씬 동일 사용
```

---

## Phase 2: 미디어 생성 (서브 에이전트 병렬)

### 2-1. AI 이미지 생성 (image-generator, 백그라운드)

```python
from src.image_generator import generate_scene_image
article_img = str(images_dir / "article.jpg")
generate_scene_image(common_title, first_narration, article_img)
# fal.ai Flux-2, 1000×560, 기사당 1장
```

### 2-2. TTS 생성 (media-producer, 씬별 병렬)

```python
from src.tts import TTSGenerator
result = tts.generate(text, audio_path)
# ElevenLabs with-timestamps API
# words.json, srt, sentences.srt 저장
```

### 2-3. 한국어 번역 (media-producer)

```python
from src.chunker import chunk_words  # 단일 정규 함수, 직접 루프 금지
from src.translator import translate_to_korean

chunks = chunk_words(words)   # 6단어 청크
ko = translate_to_korean(chunks)  # Claude Sonnet, 3회 재시도
# 청크 수 불일치 → 자동 재번역
```

---

## Phase 3: 비디오 렌더링 + CapCut (서브 에이전트)

### 3-1. 씬별 비디오 렌더링 (video-assembler)

```python
from src.frame_renderer import create_styled_video

create_styled_video(
    output_path=video_path,
    headline=common_title,  # 전 씬 동일
    source='',              # 소스명 표시 안 함
    words=words,
    ko_chunks=ko_chunks,
    total_duration=audio_dur,
    image_path=shared_image,  # 기사당 1장 공유
    scene_index=int(sid)-1,   # Ken Burns 프리셋 (0~5)
)
# 양피지 레이아웃, Ken Burns 8% 줌, 6단어 카라오케 자막
```

### 3-2. CapCut 프로젝트 생성 (video-assembler)

```python
from src.capcut_builder import build

capcut_path = build(article_dir, slug, skip_text_track=True)
# 텍스트가 비디오에 내장 → CapCut 텍스트 트랙 생략
# 저장: /Movies/CapCut/User Data/Projects/NewsPipeline_{slug}/
```

---

## 데이터 흐름

```
topic → article.json + sources.html
     → script-final.md + fact-check.md
     → common_title
     → audio/scene_XX.mp3 + subtitles/*.json + images/article.jpg
     → videos/scene_XX-A.mp4
     → CapCut 프로젝트
```

## 핵심 불변식

- `chunk_words()` 호출은 반드시 `src/chunker.py`에서만 — 중복 구현 금지
- `ko_chunks` 길이 == `chunk_words(words)` 길이 — 불일치 시 RuntimeError
- `sources.html` 반드시 생성 — 크롤링 성공/실패 무관
- 비디오 픽셀 포맷: `yuv420p`, color_range: `tv` (CapCut 호환)

## 에러 핸들링

| 단계 | 에러 | 처리 |
|---|---|---|
| 검색 | 결과 0개 | 다른 소스 폴백, 모두 실패 시 중단 보고 |
| 크롤링 | 실패 | description 폴백, sources.html에 기록 |
| 대본 | Claude 실패 | 3회 재시도, 실패 시 중단 |
| 팩트체크 | 실패 | 원본 대본 유지, 계속 진행 |
| TTS | 씬 실패 | 해당 씬 건너뜀, 나머지 계속 |
| 번역 | 실패 | 3회 재시도, 빈 ko_chunks로 진행 |
| 이미지 | 실패 | 검은 배경 폴백 (article.image_url 사용 금지) |
| 렌더링 | 씬 실패 | 재시도 1회, 검은 배경 폴백 |

## 테스트 시나리오

**정상 흐름:**
"AI 반도체 뉴스로 영상 만들어줘" → Naver 검색 → 5개 기사 → 전문 크롤링 → 6씬 대본 → 팩트체크 → TTS+번역+이미지 → CapCut 생성

**에러 흐름:**
"YTN 뉴스 최신" → RSS 없음 → Naver API → 다른 소스로 자동 폴백 확인
번역 1개 씬 실패 → 3회 재시도 → 성공 후 계속 진행 확인
