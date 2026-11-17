# RAG 평가

- `questions.csv` — **AI 작성, 사람 검수 필요.** 정책 3개(기초연금·청년월세·아이돌봄) × 10개 = 30개. 유형: 자격 / 금액 / 구비서류 / 신청방법 / 신청기간 / 모호한 질문 / 정보 없음 / 영상 금액 불일치.
  정답과 정답 근거(청크 ID, `;`로 구분)는 `backend/data/rag/chunks.jsonl` 원문으로 작성. 「영상 금액 불일치」 중 청년월세·아이돌봄의 영상 금액은 시험용으로 만든 가정(비고 칸 참고).
- `run_rag_eval.py` — (a) 문서 없이 LLM만 (b) RAG 두 방식 답 + 검색 Recall@5 자동 계산 → `results/rag_eval_<시각>.csv`. 채점 칸은 비어 있음.
  `--dry-run`은 API 없이 검색만(무료). 실제 실행은 Claude API(claude-opus-5-5) 비용이 들어 실행 전에 예상 비용을 보여 주고 묻습니다.
- 정책 청크를 다시 만들면(`backend/scripts/build_rag_docs.py`) 청크 ID가 바뀔 수 있으니 정답 근거를 다시 확인하세요.
