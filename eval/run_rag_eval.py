"""RAG 평가 (2026-11-15): eval/questions.csv → (a) 문서 없이 LLM만 (b) RAG 두 방식으로 답을 만들어 CSV로 저장.

- 검색 Recall@5는 자동 계산: 「근거 하나 이상」(정답 근거 청크 중 하나라도 top-5) · 「근거 전부」(모두 top-5). 정답 근거가 없는(정보 없음) 질문은 빈칸.
  검색은 서비스 엔드포인트(/api/rag/answer)와 같게: 질문에서 정책을 찾으면 그 정책 청크 안에서, 못 찾으면 전체에서.
- 채점 칸(정답 여부, 인용 정확, 기준일 표시, 정보 없음 처리, 채점 메모)은 비워 둠 — 사람이 채점.
- Claude API를 부르므로 돈이 듦. 실행 전에 예상 비용을 보여 주고 확인을 받음(--yes면 생략). --dry-run은 API 없이 검색·Recall@5만.

    python eval/run_rag_eval.py --dry-run            # 검색 Recall@5만 (무료)
    python eval/run_rag_eval.py                       # 두 방식 모두 (확인 후)
    python eval/run_rag_eval.py --modes rag --limit 5 # 일부만
"""
import argparse, csv, json, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend/services")]
import rag  # noqa: E402

PRICE_IN, PRICE_OUT = 4.0, 20.0   # claude-opus-5-5, 1M 토큰당 달러
GRADE = ["채점_정답 여부", "채점_인용 정확", "채점_기준일 표시", "채점_정보 없음 처리", "채점 메모"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--questions", default=str(ROOT / "eval/questions.csv"))
    ap.add_argument("--modes", default="llm_only,rag")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--yes", action="store_true")
    a = ap.parse_args()
    from dotenv import load_dotenv
    load_dotenv(ROOT / "backend/.env")
    from welfare_service import match_policy
    qs = list(csv.DictReader(open(a.questions, encoding="utf-8-sig")))
    if a.limit:
        qs = qs[:a.limit]
    modes = [m.strip() for m in a.modes.split(",") if m.strip()]
    ix = rag.RagIndex()
    pols = {c["policy_id"] for c in ix.chunks}
    prep = []
    for q in qs:
        pid = match_policy(q["질문"]); pid = pid if pid in pols else None
        hits = ix.search(q["질문"], 5, pid)
        top = [h["chunk_id"] for h in hits]
        gold = [g for g in q["정답 근거"].split(";") if g]
        r_any = (int(any(g in top for g in gold)) if gold else "")
        r_all = (int(all(g in top for g in gold)) if gold else "")
        prep.append((q, pid, hits, top, r_any, r_all))
    graded = [p for p in prep if p[4] != ""]
    print(f"질문 {len(qs)}개 · 검색 Recall@5(근거 하나 이상) {sum(p[4] for p in graded)}/{len(graded)} · (근거 전부) {sum(p[5] for p in graded)}/{len(graded)}")
    for q, pid, hits, top, r1, r2 in prep:
        if r1 == 0:
            print(f"  놓침 {q['id']} {q['질문']} | 정답 {q['정답 근거']} | top5 {top}")
    stamp = time.strftime("%Y%m%d_%H%M")
    out = ROOT / f"eval/results/rag_eval_{stamp}{'_dryrun' if a.dry_run else ''}.csv"
    if not a.dry_run:
        if not rag.has_key():
            sys.exit("ANTHROPIC_API_KEY가 backend/.env에 없어요. --dry-run으로 검색만 볼 수 있어요.")
        est_in = sum((1400 + sum(len(h["text"]) for h in p[2]) if m == "rag" else 400) for p in prep for m in modes)   # 한글 1자 ≈ 1토큰으로 넉넉히
        est_out = 600 * len(prep) * len(modes)
        cost = est_in / 1e6 * PRICE_IN + est_out / 1e6 * PRICE_OUT
        print(f"Claude API 호출 {len(prep) * len(modes)}번 · 예상 입력 {est_in:,} / 출력 {est_out:,} 토큰 · 약 ${cost:.2f} (claude-opus-5-5, 넉넉한 추정)")
        if not a.yes and input("진행할까요? [y/N] ").strip().lower() != "y":
            sys.exit("취소했어요.")
    cols = ["id", "정책", "유형", "질문", "정답", "정답 근거", "방식", "답변", "문장별 근거", "근거 없어 뺀 문장 수", "출처 URL·기준일",
            "검색 정책", "검색 top5", "검색 Recall@5(근거 하나 이상)", "검색 Recall@5(근거 전부)", "모델", "입력 토큰", "출력 토큰", "응답 초", "오류"] + GRADE
    tot_in = tot_out = 0
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader()
        for i, (q, pid, hits, top, r1, r2) in enumerate(prep, 1):
            for m in (["rag"] if a.dry_run else modes):
                row = {k: q.get(k, "") for k in ["id", "정책", "유형", "질문", "정답", "정답 근거"]} | {
                    "방식": "RAG" if m == "rag" else "LLM만(문서 없음)", "검색 정책": pid or "(전체)",
                    "검색 top5": ";".join(top) if m == "rag" else "", "검색 Recall@5(근거 하나 이상)": r1 if m == "rag" else "",
                    "검색 Recall@5(근거 전부)": r2 if m == "rag" else ""} | {g: "" for g in GRADE}
                if not a.dry_run:
                    res = rag.generate(q["질문"], hits if m == "rag" else None, None, m)
                    u = res.get("usage", {}); tot_in += u.get("input_tokens", 0); tot_out += u.get("output_tokens", 0)
                    row |= {"답변": res.get("answer", ""), "문장별 근거": json.dumps([[s["text"], s["chunk_ids"]] for s in res.get("sentences", [])], ensure_ascii=False),
                            "근거 없어 뺀 문장 수": len(res.get("debug", {}).get("dropped", [])), "출처 URL·기준일": res.get("footer", ""),
                            "모델": u.get("model", ""), "입력 토큰": u.get("input_tokens", ""), "출력 토큰": u.get("output_tokens", ""),
                            "응답 초": u.get("sec", ""), "오류": res.get("error", "")}
                    print(f"  [{i}/{len(prep)}] {q['id']} {m} {'오류 ' + res['error'] if res.get('error') else 'ok'}", flush=True)
                w.writerow(row)
    if not a.dry_run:
        print(f"실제 사용: 입력 {tot_in:,} / 출력 {tot_out:,} 토큰 · ${tot_in / 1e6 * PRICE_IN + tot_out / 1e6 * PRICE_OUT:.2f}")
    print("→", out)


if __name__ == "__main__":
    main()
