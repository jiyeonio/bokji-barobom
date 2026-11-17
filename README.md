# 복지바로봄

궁금한 복지 내용을 말하듯 검색하면, 공식 복지 안내 영상에서 그 내용이 나오는 **장면부터 바로 재생**하고 옆에 **공식 정책 정보**(지원대상·선정기준·구비서류·신청방법·문의처·출처·기준일)를 함께 보여 주는 AI 복지 안내 서비스입니다.

- 저장소: https://github.com/jiyeonio/bokji-barobom
- 시연 영상: https://www.youtube.com/watch?v=nqQNDIDiAKc

자연어 영상 구간 검색 서비스 **SceneFinder**(MiniLM·Moment-DETR 기반)를 복지 분야로 넓히고, 화면 검색을 VLM(Qwen3-VL 계열)으로 바꾼 버전입니다.

## 주요 기능

- **장면 검색**: 「기초연금 신청할 때 뭐 챙겨가야 돼요?」처럼 물으면 영상 속 해당 장면부터 재생. 상위 3개 장면을 카드로 보여 줌
- **화면 확인 표시**: AI가 찾은 장면이 실제로 **화면에서 확인됐는지 / 자막에서만 확인됐는지** 배지로 표시(기본 결과를 먼저 보여 주고 뒤에서 확인한 뒤 갱신)
- **공식 정책 정보 패널**: 사회보장 공공데이터(한국사회보장정보원 복지서비스정보, 행정안전부 공공서비스(혜택) 정보)의 정책 정보를 영상 옆에 표시. 금액은 공식 원문에 있는 값만
- **신청 기간 질문은 공식 정보로**: 「아직 신청 되나요?」 같은 질문에는 영상 대신 공식 신청 기간·기준일로 답하고 「영상에는 해당 내용이 없어요」 안내
- **영상 정보 최신성 경고**: 영상 속 금액이 공공데이터 현재 값과 다르면 「영상 속 정보는 2018년 기준이에요. 현재는 …이에요」 표시(확실한 경우만, [규칙](docs/service/freshness_rules.md))
- **장면 목록·신청 단계 카드**: 영상을 장면별로 나누고, 신청 단계(자격 확인·서류 준비·신청서 작성·결과 확인)에 해당하는 장면은 단계 카드로. 누르면 그 장면으로 이동, 큰 자막·구간 반복
- **신청서 따라하기**: 공식 빈 서식(국가법령정보센터) 위 칸을 누르면 그 칸 설명 장면 재생 + 이 칸에 쓸 것(공식 작성 방법 → 영상 자막), 「내 신청서 비추기」로 종이 신청서 사진에 칸 표시(사진 저장 안 함), 항목 목록·「내 신청 준비 체크리스트」(개인정보 입력 없음)
- **가족에게 장면 보내기**: 장면 시작 시간이 들어간 링크와 준비 서류 목록을 카카오톡에 붙여넣기 좋은 글로 복사
- **쉬운 말로 보기**: 지원대상·선정기준을 로컬 LLM이 쉬운 말로(숫자가 원문과 다르면 숨김, 원문은 항상 함께)
- **정책 찾기(통합 정책 DB)**: 행정안전부 공공서비스(혜택) 개인·가구 대상 9,934개 + 한국사회보장정보원 지자체복지서비스(교차 확인 1,130개, 지자체에만 있는 3,698개)를 낱말·대상(어르신·청년·아이 키우는 가정·장애인)·지역으로. 영상이 없는 정책은 공식 정보 + 「영상 준비 중」
- **추천 질문 칩·단계 카드 버튼**: 검색창 아래·정책 화면 추천 질문, 결과가 애매하면 그 정책의 신청 단계 장면 버튼
- **AI 답변(RAG)**: 공공데이터 정책 정보 청크로만 답하고(Claude API) 문장마다 근거 항목·공식 출처·기준일 표시. 문서에 없으면 「공식 정보에서 확인되지 않아요」, 영상 금액이 다르면 최신 공식 정보 기준으로 안내. 누를 때만 질문 전송
- **기관용 안내 공백 리포트**(`#/agency`): 영상·공공데이터 모두 답 없던 질문, 영상이 필요한 정책, 오래된 정보 영상, 단계 장면 없는 영상, 영상 설명이 없는 서식 칸
- **접근성**: 큰 자막(영상 아래 칸), 구간 반복, 재생 속도, 글자 크기 3단계·고대비, 화면 읽어주기(브라우저 음성)

## 구조

```
질문 ─┬─ 정책 찾기(키워드) ──→ 공공데이터 정책 정보 ──→ 공식 답변·정책 패널
      └─ 장면 검색 (그 정책에 연결된 영상, 없으면 전체)
           ├─ 자막 검색: 파인튜닝 MiniLM (Whisper large-v3-turbo 자막)
           ├─ 화면 검색: Qwen3-VL-Embedding-2B + LoRA (2초마다 프레임 임베딩)
           └─ 결합(N3): z(자막) + 0.25·z(화면), 화면 구간은 4초 앞당김
                → 기본 결과 즉시 표시 (p95 0.27초)
                → VLM 재확인: Qwen3-VL-4B가 상위 5개 장면의 프레임·자막을 보고 순서·배지 갱신 (비동기)
```

| 부분 | 기술 |
|---|---|
| 백엔드 | FastAPI (`backend/welfare_app.py`, `backend/services/`) |
| 프론트엔드 | React 18 + TypeScript + Vite (`frontend/`), YouTube IFrame 플레이어 |
| 모델 | 파인튜닝 MiniLM, Qwen3-VL-Embedding-2B(+LoRA), Qwen3-VL-4B-Instruct, Whisper large-v3-turbo, (AI 답변) Claude API |
| 데이터 | 사회보장 공공데이터 Open API 3종, 공식 기관 YouTube 안내 영상(시연 54개), 국가법령정보센터 공식 서식 |

## 결과 (test, 사람이 검수한 복지 안내 영상 8개 · 질의 81개, 1회 실행)

설정은 test 전에 고정했고 test는 한 번만 돌렸습니다([최종 결과](docs/experiments/vlm_model_results.md), [계획·판정 기준](docs/experiments/vlm_model_plan.md), [test 보고서](ai/experiments/vlm_model/results/test_final/report.md)).

| | 기존 방식(B3) | **N3** (자막 + VLM 화면 검색) | **N3 + VLM 재확인** |
|---|---|---|---|
| 1위 장면 정답률 (IoU ≥ 0.3) | 31% | 38% | **43%** |
| 상위 3개 안 정답 | 52% | 60% | **63%** |
| 화면 글자로 찾는 질의 — 1위 | 38% | 50% | **56%** |
| 화면 글자로 찾는 질의 — 상위 3개 | 56% | 71% | **74%** |
| 응답 시간 (p95) | 0.21초 | 0.27초 | 기본 결과 0.27초 · 확인 완료 1.7초 |

- 채택 판정은 사전에 정한 최종 후보 N3로 했습니다(1위 정답 +6개, 기준 통과). N3 + VLM 재확인은 같은 test에서 함께 돌린 사전 고정 설정이며, 정확도 향상 기법이 아니라 **화면/자막 확인 표시** 기능으로 소개합니다.
- **한계**: 일상 말투 사용자 질문(19개)은 아직 무작위 수준이고, 질문이 영상에 답이 없는 경우를 걸러 내지 못합니다(상위 3개 장면 + 공식 정책 정보로 보완).
- 그 밖의 실험: 신청서 칸 찾기([form_grounding.md](docs/experiments/form_grounding.md) — VLM grounding vs OpenCV 서식 맞추기), AI 답변 평가([eval/](eval/README.md) — 문서 없이 LLM만 vs RAG, 검색 Recall@5).

## 실행 방법

### 준비물

- Python 3.11, Node.js 22, ffmpeg, GPU(약 15GB — Qwen3-VL-Embedding-2B·Qwen3-VL-4B·MiniLM을 함께 올림)
- Git LFS (`models/minilm`, `models/moment_detr` 가중치): `git lfs install && git lfs pull`
- 모델: Hugging Face의 `Qwen/Qwen3-VL-Embedding-2B`·`Qwen/Qwen3-VL-4B-Instruct`(처음 실행 때 내려받음), 화면 검색 LoRA 어댑터(`<WELFARE_DATA_DIR>/lora_runs/welfare/ep1`)
- 시연 영상 색인(자막·화면 특징·프레임)·장면 정보 DB·정책 DB는 `WELFARE_DATA_DIR`(저장소 밖)에 만듦 — 아래 「데이터 만들기」. 영상 파일은 저장소에 없음

### 설치

```bash
python -m venv .venv && . .venv/bin/activate
pip install torch==2.11.0 torchvision==0.26.0 --index-url https://download.pytorch.org/whl/cu128
pip install -r backend/requirements.txt
pip install anthropic==2.8.0      # 선택: AI 답변(RAG)
cp backend/.env.example backend/.env   # 값 채우기
cd frontend && npm ci
```

### 환경변수 (`backend/.env`, 저장소에 올리지 않음)

| 이름 | 내용 |
|---|---|
| `DATA_GO_KR_KEY` | 공공데이터포털 인증키 (복지서비스정보·지자체복지서비스·공공서비스(혜택)) |
| `YOUTUBE_API_KEY` | YouTube Data API 키 (영상 메타데이터) |
| `ANTHROPIC_API_KEY` | 선택: AI 답변(RAG)용 Claude API 키 |
| `SCENEFINDER_MINILM_MODEL_PATH` | 파인튜닝 MiniLM 폴더 경로 (`models/minilm`) |
| `WELFARE_DATA_DIR` | 시연 색인·LoRA 어댑터·정책 DB가 있는 폴더 (기본 `/nfs/team/data/scenefinder_vlm`) |

### 데이터 만들기

```bash
python backend/scripts/build_policies.py      # 공공데이터 → backend/data/policies.json (시연 정책 15개)
python backend/scripts/index_demo.py          # 시연 영상 색인 (영상 목록: docs/service/demo_new_videos*.tsv)
python backend/scripts/make_chapters.py       # 장면 나누기·단계 카드
python backend/scripts/build_scene_info.py    # 장면 정보 DB(화면 종류·화면 글자·설명)
python backend/scripts/fetch_policy_db.py     # 통합 정책 DB 원본(공공데이터 API) → <WELFARE_DATA_DIR>/policy_raw
python backend/scripts/build_policy_db.py     # → <WELFARE_DATA_DIR>/policy_db.sqlite
python backend/scripts/build_rag_docs.py      # AI 답변용 정책 청크 → backend/data/rag/chunks.jsonl
python backend/scripts/build_form_map.py      # 신청서 지도 (pymupdf 필요, 서식 PDF는 국가법령정보센터)
python backend/scripts/precompute_cache.py    # 시연·추천 질문 결과 캐시
```

### 서버

```bash
# 백엔드 (모델을 올리는 데 약 1분)
set -a && . backend/.env && set +a
SEARCH_MODEL=n3_vlm QUERY_CACHE=on .venv/bin/uvicorn backend.welfare_app:app --host 127.0.0.1 --port 8000

# 프론트엔드 (/api는 8000으로 넘김, frontend/.env.local에 VITE_API_BASE_URL=http://127.0.0.1:5173)
cd frontend && npx vite --port 5173
```

`SEARCH_MODEL=n3`로 두면 VLM 재확인 없이 동작합니다. `QUERY_CACHE=on`은 시연·추천 질문을 캐시에서 바로 답합니다(배지 변화를 보여 주려면 `off`).

## 저장소 구성

| 위치 | 내용 |
|---|---|
| `backend/welfare_app.py`, `backend/services/` | 복지바로봄 API (검색·영상·정책 찾기·신청서 지도·AI 답변·기관 리포트) |
| `ai/features/welfare_search.py` | 장면 검색 엔진(N3, VLM 재확인) |
| `backend/data/` | 정책 정보, 시연 영상 목록, 장면·단계 카드, 신청서 지도, AI 답변 청크, 질문 규칙 |
| `backend/scripts/` | 데이터 만들기(색인·장면·정책 DB·신청서 지도·캐시) |
| `frontend/` | 화면 (공식 서식 이미지 `public/forms`) |
| `models/` | 파인튜닝 MiniLM, Moment-DETR 체크포인트(기존 방식 B3 비교용) — Git LFS |
| `ai/experiments/vlm_model/` | 모델 실험(평가셋, 화면 검색 LoRA, 결합 규칙, VLM 재확인, test) |
| `ai/experiments/form_map/` | 신청서 칸 찾기 실험 |
| `eval/` | AI 답변(RAG) 평가 |
| `docs/experiments/`, `docs/service/` | 실험 계획·결과, 서비스 쪽 자료(영상 목록·정책 연결·최신성 규칙·시연 질문) |
| `tools/labeler/` | 평가셋 검수 도구 |
| `ai/vendor/moment_detr/` | Moment-DETR 원본 코드(MIT) |

## 출처·라이선스

- 정책 정보: 공공데이터포털 — 한국사회보장정보원 「중앙부처복지서비스」·「지자체복지서비스」, 행정안전부 「대한민국 공공서비스(혜택) 정보」. 화면에 출처·기준일을 함께 표시합니다.
- 서식: 국가법령정보센터 「사회보장급여 관련 공통서식에 관한 고시」 [별지 제1호서식] 사회보장급여 신청(변경)서.
- 영상: 공식 기관 YouTube 채널 영상을 IFrame으로 재생하며, 영상 파일은 저장소에 포함하지 않습니다.
- 모델·코드: Qwen3-VL(Apache-2.0), Moment-DETR(`ai/vendor/moment_detr`, MIT), MiniLM, Whisper — 각 원저작물의 라이선스를 따릅니다.
