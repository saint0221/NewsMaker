---
name: news-pipeline
description: |
  뉴스 숏폼 영상 자동화 파이프라인 오케스트레이터. 뉴스 수집부터 CapCut 프로젝트 생성까지
  전체 워크플로우를 에이전트 팀으로 조율한다.
  다음 상황에서 반드시 이 스킬을 사용하라:
  - "뉴스 영상 만들어줘", "영상 생성", "news pipeline 실행"
  - "기사 선택하고 영상", "뉴스 캡컷 만들어"
  - "다시 실행", "재생성", "파이프라인 재시도"
  - "씬 재생성", "번역 다시", "영상 업데이트"
---

# News Pipeline Orchestrator

뉴스 수집 → 대본 → 미디어 생성 → 비디오 렌더링 → CapCut 조립을 에이전트 팀으로 조율한다.

**실행 모드:** 하이브리드
- Phase 1 (수집·대본): 파이프라인 (순차)
- Phase 2 (미디어): 팬아웃 (병렬, 에이전트 팀)
- Phase 3 (비디오·조립): 팬아웃 → 팬인 (에이전트 팀)

## Phase 0: 컨텍스트 확인

실행 전 기존 작업 상태를 확인한다:

1. `output/` 디렉토리 스캔 → 기존 article_dir 목록 확인
2. 분기:
   - **초기 실행**: output/ 없거나 비어있음 → Phase 1부터 전체 실행
   - **후속 요청**: article_dir 존재 + 부분 수정 요청 → 해당 에이전트만 재호출
   - **재실행**: 새 기사 선택 → 새 타임스탬프 article_dir 생성

## Phase 1: 뉴스 수집 + 대본 생성 (순차)

### 1-1. 뉴스 수집 (researcher)

```python
from src.fetcher import NewsFetcher, fetch_full_content
import random, json
from datetime import datetime
from pathlib import Path

category = "<사용자 입력 카테고리>"  # 기본값: technology
fetcher = NewsFetcher()
articles = fetcher.fetch(category=category, count=10)
random.shuffle(articles)
articles = articles[:3]

# 사용자에게 선택지 제시
for i, a in enumerate(articles):
    print(f"[{i}] {a.source}: {a.title[:70]}")

# 사용자 선택 후
selected = articles[<선택_인덱스>]
base_dir = Path("output") / datetime.now().strftime("%Y%m%d_%H%M%S")
article_dir = base_dir / "article_01"
article_dir.mkdir(parents=True, exist_ok=True)

# 전문 크롤링
full_body = fetch_full_content(selected.url) or selected.description or ""
related = fetcher.find_related(selected, category, count=2)
related_bodies = [(r.title, fetch_full_content(r.url)) for r in related]
```

article.json 저장 후 **scriptwriter에게 전달**.

### 1-2. 대본 생성 + 팩트체크 (scriptwriter)

`web/app.py`의 `SCRIPT_PROMPT`와 `_run_claude()` 활용:
- 6씬 영어 대본 생성
- Claude Sonnet으로 팩트체크
- 공통 타이틀 생성 (`_make_common_title()`)

완료 시 `common_title`과 `scene_ids`를 오케스트레이터에 반환.

## Phase 2: 미디어 생성 (팬아웃, 에이전트 팀)

researcher + scriptwriter 완료 후 **media-producer** 호출.

```python
# 씬별 병렬 처리
from src.tts import TTSGenerator
from src.translator import translate_to_korean
from src.videomaker_export import _make_chunks

tts = TTSGenerator()
for sid, text in narrations.items():
    # TTS + 자막 생성
    audio_path = str(article_dir / "audio" / f"scene_{sid}.mp3")
    result = tts.generate(text, audio_path)
    # words.json, srt 저장
    
    # 6단어 청크 번역
    words = json.loads((article_dir / f"subtitles/scene_{sid}_words.json").read_text())
    chunks = _make_chunks_6w(words)
    ko = translate_to_korean(chunks)
    # chunk_ko.json 저장 (청크 수 일치 확인)

# AI 이미지 (기사당 1장)
from src.image_generator import generate_scene_image
article_img = str(images_dir / "article.jpg")
generate_scene_image(common_title, first_narration, article_img)
```

## Phase 3: 비디오 렌더링 + CapCut 조립 (팬아웃 → 팬인)

**video-assembler** 호출. 씬별 병렬 렌더링 후 CapCut으로 조립.

```python
from src.frame_renderer import create_styled_video
from src.capcut_builder import build as build_capcut

# 씬별 비디오 생성 (공유 이미지 사용)
for sid in scene_ids:
    create_styled_video(
        output_path=str(videos_dir / f"scene_{sid}-A.mp4"),
        headline=common_title,
        source='',
        image_url=None,
        words=words,
        ko_chunks=ko_chunks,
        total_duration=audio_dur,
        image_path=shared_image,
    )

# CapCut 프로젝트 생성
slug = re.sub(r'[^\w가-힣-]', '-', title).strip('-')[:40]
capcut_path = build_capcut(article_dir, slug, skip_text_track=True)
```

## 에러 핸들링

| 에러 | 처리 |
|---|---|
| 크롤링 실패 | RSS description으로 폴백, 계속 진행 |
| 대본 생성 실패 | 3회 재시도, 실패 시 중단 보고 |
| TTS 씬 실패 | 해당 씬 건너뜀, 나머지 계속 |
| 번역 실패 | 재시도 3회, 빈 ko_chunks로 영상 생성 |
| 이미지 생성 실패 | 검은 배경으로 폴백 |
| 비디오 렌더링 실패 | 해당 씬 재시도 1회, 검은 배경 폴백 |

## 데이터 흐름

```
article.json ──→ script-final.md ──→ audio/, subtitles/, images/
                                 └──→ videos/ ──→ CapCut 프로젝트
```

파일 경로 컨벤션: `output/{YYYYMMDD_HHMMSS}/article_01/`

## 테스트 시나리오

**정상 흐름:**
1. "technology 뉴스로 영상 만들어줘" → 3개 기사 표시 → 선택 → 전체 파이프라인 실행

**에러 흐름:**
1. 크롤링 실패 → RSS description 폴백 로그 확인
2. TTS 1개 씬 실패 → 해당 씬 제외하고 CapCut 생성 확인

## 후속 작업 지원

- "마지막 결과물로 CapCut 재생성" → Phase 3만 재실행
- "씬 02 번역 다시" → media-producer의 해당 씬만 재실행
- "다른 카테고리로 다시" → Phase 0에서 새 실행 판별
