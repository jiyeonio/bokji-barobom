"""사용자 말투 질문 강화 비교 (docs/service/query_robustness_plan.md, 탐색적 — 모델 채택 판정과 무관).

  0) 정책 유사도 임계값: dev 질의(정답 있음·없음 전부)로만 정함 (새 평가 질문은 쓰지 않음)
  1) 설정별로 새 사용자 말투 질문(backend/data/userq_eval.json, AI 생성·교차 확인)을 서비스와 같은 검색(전체 시연 영상)으로,
     dev 사용자 질문 18개를 그 영상 안 검색으로 → N3(재판별 전)·N3+VLM(재판별 뒤) 지표
  고르기(결과 전 고정): 새 질문 시스템 단위 R@1(N3+VLM, 서비스 기본값) 최대 · dev R@1이 기준보다 3개 넘게 떨어지면 탈락 ·
  기본 결과 p95 1초 넘으면 탈락 · 같으면 바꾸는 것이 적은 설정.

    python backend/scripts/eval_userq.py   (GPU — API 서버를 내린 뒤)
"""
import json, statistics, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "backend/services"), str(ROOT / "ai/experiments/translation_compare")]
import summary
from welfare_service import POLICIES, RULES, Searcher, match_policy, policy_of, span_iou

OUT = ROOT / "docs/service/userq_results.json"
CONFIGS = {
    "기준(지금)": {"policy": "keyword", "rewrite": "none", "step_first": False},
    "+1 정책 우선": {"policy": "alias+sim", "rewrite": "none", "step_first": False},
    "+2A 바꿔쓰기(규칙)": {"policy": "keyword", "rewrite": "rules", "step_first": False},
    "+2B 바꿔쓰기(LLM)": {"policy": "keyword", "rewrite": "llm", "step_first": False},
    "+3 단계 카드 우선": {"policy": "keyword", "rewrite": "none", "step_first": True},
    "전부(1+2A+3)": {"policy": "alias+sim", "rewrite": "rules", "step_first": True},
    "전부(1+2B+3)": {"policy": "alias+sim", "rewrite": "llm", "step_first": True},
}


def main():
    s = Searcher("n3_vlm")
    cat = s.ws.catalog
    labels = json.loads((ROOT / "ai/experiments/vlm_model/labels/review.json").read_text())
    dev = {k: v for k, v in labels["videos"].items() if v["split"] == "dev"}
    devq = [q for q in labels["queries"] + labels.get("negative_queries", []) if q["video"] in dev]
    expect = lambda yid: policy_of(cat[yid]["policy_hint"]) if yid in cat else None  # noqa: E731

    # 0) 유사도 임계값 (dev만): 키워드·별칭으로 정책을 못 찾은 dev 질의에서, 맞힌 수 - 2×틀린 정책 수가 가장 큰 값
    rows0 = []
    for q in devq:
        y = dev[q["video"]]["youtube_id"]
        if match_policy(q["query"], None, "alias") is None:
            sc = s.policy_scores(q["query"]); rows0.append((sc[0][0], sc[0][1], sc[0][1] - sc[1][1], expect(y)))
    best = (None, -1e9)
    for t in [x / 100 for x in range(20, 96, 5)]:
        ok = sum(1 for p, v, m, e in rows0 if (v >= t and m >= RULES["policy_similarity"]["margin"] and p == e) or ((v < t or m < RULES["policy_similarity"]["margin"]) and e is None))
        wrong = sum(1 for p, v, m, e in rows0 if v >= t and m >= RULES["policy_similarity"]["margin"] and p != e)
        score = ok - 2 * wrong
        if score > best[1]:
            best = (t, score, ok, wrong)
    tau = best[0]
    print(f"유사도 임계값 {tau} (dev 질의 {len(rows0)}개 중 맞음 {best[2]}, 틀린 정책 {best[3]})", flush=True)

    newq = json.loads((ROOT / "backend/data/userq_eval.json").read_text())["queries"]
    devu = [q for q in labels["queries"] if q["video"] in dev and q.get("origin") == "simulated_user"]
    results = {"sim_threshold": tau, "n_new": len(newq), "n_new_pos": sum(1 for q in newq if q["gt"]), "n_dev_user": len(devu), "configs": {}}
    for name, o in CONFIGS.items():
        opts = dict(o, sim_threshold=tau)
        # 새 질문: 서비스와 같은 검색
        sysr = {"N3": [], "N3VLM": []}; pol_ok = 0; lat = []; neg = []
        for q in newq:
            out = s.start(q["query"], None, opts); lat.append(out["timing"]["base_sec"])
            pre = [dict(v) for v in out["videos"]]
            while out["status"] == "pending":
                time.sleep(0.3)
            pol_ok += out["policyId"] == expect(q["youtube_id"])
            if not q["gt"]:
                neg.append(bool(out["noAnswerInVideo"])); continue
            for key, vids in (("N3", pre), ("N3VLM", out["videos"])):
                found = [(v["youtubeId"], v["top"][0]) for v in vids[:3] if v["top"]]
                hit = lambda yv: yv[0] == q["youtube_id"] and summary.best_iou(yv[1], q["gt"]) >= 0.3  # noqa: E731
                sysr[key].append({"r1": bool(found) and hit(found[0]), "r3": any(hit(f) for f in found),
                                  "s5": bool(found) and found[0][0] == q["youtube_id"] and summary.start_ok(found[0][1], q["gt"]),
                                  "vid3": any(f[0] == q["youtube_id"] for f in found)})
        # dev 사용자 질문: 그 영상 안에서만
        devr = {"N3": [], "N3VLM": []}; dev01 = {"N3": [], "N3VLM": []}
        for q in devu:
            y = dev[q["video"]]["youtube_id"]
            with s.ws.lock:
                pid, variants, k = s.plan(q["query"], None, opts)
                encs = [s.ws.encode(v) for v, _ in variants]
                r = s.rank_video(y, variants, encs, s.step_span(y, k) if k else None)
                rj = s.ws.rejudge(y, q["query"], r["top"])
            top_v = rj["top"]
            if r["pinned"]:
                top_v = [r["pinned"]] + [t for t in top_v if span_iou(t, r["pinned"]) <= 0.99]
            for key, top in (("N3", r["top"]), ("N3VLM", top_v)):
                ok = summary.best_iou(top[0], q["gt"]) >= 0.3
                devr[key].append(ok)
                if y == "NYNnaDN9d8M":
                    dev01[key].append(ok)
        pct = lambda v, p: sorted(v)[int(p * (len(v) - 1))]  # noqa: E731
        res = {"opts": opts,
               "new": {k: {m: sum(x[m] for x in v) for m in ("r1", "r3", "s5", "vid3")} for k, v in sysr.items()},
               "new_policy_acc": f"{pol_ok}/{len(newq)}", "new_neg_notice": f"{sum(neg)}/{len(neg)}",
               "dev_user_r1": {k: sum(v) for k, v in devr.items()}, "dev01_r1": {k: f"{sum(v)}/{len(v)}" for k, v in dev01.items()},
               "base_latency": {"p50": round(statistics.median(lat), 3), "p95": round(pct(lat, 0.95), 3)}}
        results["configs"][name] = res
        print(name, json.dumps({k: res[k] for k in ("new", "new_policy_acc", "dev_user_r1", "base_latency")}, ensure_ascii=False), flush=True)

    base = results["configs"]["기준(지금)"]
    ok = {n: r for n, r in results["configs"].items()
          if r["dev_user_r1"]["N3VLM"] >= base["dev_user_r1"]["N3VLM"] - 3 and r["base_latency"]["p95"] <= 1.0}
    nchg = lambda n: sum(1 for k in ("policy", "rewrite", "step_first") if CONFIGS[n][k] != CONFIGS["기준(지금)"][k])  # noqa: E731
    pick = max(ok, key=lambda n: (ok[n]["new"]["N3VLM"]["r1"], ok[n]["new"]["N3VLM"]["r3"], -nchg(n)))
    results["selected"] = pick
    results["rule"] = "새 질문 시스템 단위 R@1(N3+VLM) 최대, dev 사용자 질문 R@1이 기준보다 3개 넘게 떨어지면 탈락, 기본 결과 p95 > 1초 탈락, 같으면 바꾸는 것이 적은 설정"
    OUT.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print("고름:", pick)


if __name__ == "__main__":
    main()
