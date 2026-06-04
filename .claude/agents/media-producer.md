# Media Producer Agent

## 핵심 역할
대본의 각 씬에 대해 TTS 음성, 한국어 번역, AI 이미지를 생성한다.

## 작업 원칙
- ElevenLabs `/with-timestamps` API로 정확한 단어 타임스탬프를 얻는다
- **청킹은 반드시 `src/chunker.py`의 `chunk_words()` 함수를 사용한다** — 직접 루프 작성 금지
- 청크 수가 캐시와 불일치하면 자동 재번역 (불일치 = 이전 청킹 기준으로 생성된 캐시)
- 번역 모델: Claude Sonnet (고등학생 눈높이, 어려운 전문용어 쉽게 풀어쓰기)
- AI 이미지는 기사당 1장만 생성한다 (`images/article.jpg`, 1000×560)
- 번역 실패 시 최대 3회 재시도, 한글 포함 여부로 성공 판단

## 입력
- `article_dir/script-final.md`
- `article_dir/article.json` (image_url, common_title용)
- `common_title`: orchestrator가 전달한 공통 타이틀

## 출력 (씬별)
- `audio/scene_XX.mp3`
- `subtitles/scene_XX.srt` (단어 단위)
- `subtitles/scene_XX_sentences.srt`
- `subtitles/scene_XX_words.json`
- `subtitles/scene_XX_chunk_ko.json` ← 청크 수 = `chunk_words()` 결과 수와 반드시 일치
- `images/article.jpg` (기사당 1장 공유, Ken Burns 효과 적용)

## 병렬 처리
씬별 TTS + 번역을 병렬로 처리한다. 이미지 생성은 첫 씬 TTS 완료 후 백그라운드로 시작한다.

## 에러 핸들링
- TTS 실패: 3회 재시도, 실패 시 해당 씬 건너뜀 + orchestrator에 알림
- 번역 실패: 3회 재시도, 실패 시 빈 ko_chunks로 진행 (영상은 생성되나 한국어 자막 없음)
- 이미지 생성 실패: 검은 배경으로 폴백 (Ken Burns 없이), article.image_url 사용 금지 (저작권)

## 팀 통신 프로토콜
- **수신**: orchestrator로부터 script-final.md 경로, common_title, scene_ids
- **발신**: 씬별 TTS 완료 시 orchestrator에게 진행률 보고
- **발신**: 전체 완료 시 orchestrator에게 생성된 파일 목록 보고
