# 최종 설정 고정 (2026-11-15, test 실행 전)

test는 이 설정으로 **1회만** 실행합니다([test_eval.py](../../ai/experiments/vlm_model/test_eval.py), `--i-confirm-test` 필요). 값은 [vlm_frozen_config.json](vlm_frozen_config.json).

- **최종 후보 N3**: 자막 MiniLM(파인튜닝) 상위 5 + LoRA 화면 검색 상위 3(시작 4초 앞당김), 점수 = z(자막) + 0.25 × z(화면), N1 후보 없음. LoRA 어댑터 `lora_runs/welfare/ep1/adapter.pt` (sha256 `6ba156b5e919a1d9…`).
- **N3+VLM 재판별(참고)**: Qwen3-VL-4B-Instruct, 상위 5개, 프롬프트 A(답하는가), mix 결합. dev +2로 최종 후보 기준 미달 → 판정에 쓰지 않고 함께 보고.
- 비교: B1·B2·B3 (예비 실험과 같은 계산).
- 정답 없음 필터: 적용 안 함(한계).
- 판정 기준: vlm_model_plan.md 5장: 최종 후보 N3가 B3보다 R@1 IoU≥0.3 +6개 이상, R@3·시작 ±5초가 3개 넘게 나빠지지 않음, 질의 p95 ≤ 1초, 특징 추출 ≤ 1.5초/영상 1분.
- test 질의: 102개(정답 있음 81, 정답 없음 21), 모두 사람 검수 완료(수정 0).
