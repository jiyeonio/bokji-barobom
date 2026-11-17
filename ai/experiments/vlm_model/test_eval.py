"""test 1회 평가 — 고정 설정(docs/experiments/vlm_frozen_config.md)으로만, 사용자 지시로만 실행.

방식: B1 자막 검색, B2 구간 검색 CLIP 버전, B3 main 서비스 결합, N3(최종 후보), N3+VLM 재판별(참고).
모든 계산은 dev에서 쓴 함수를 그대로 부른다(prelim_eval.Methods, combo_dev.rank_query, vlm_rejudge.Judge·rerank).

    python ai/experiments/vlm_model/test_eval.py prep --i-confirm-test   # test 특징·프레임 (LoRA 화면 특징, CLIP, 2초 칸 프레임)
    python ai/experiments/vlm_model/test_eval.py run  --i-confirm-test   # 평가 1회 → results/test_final/
    python ai/experiments/vlm_model/test_eval.py report                  # 표 (results/test_final/report.md)
"""
import argparse, csv, json, random, statistics, subprocess, sys, time
from pathlib import Path

import numpy as np
import torch

HERE = Path(__file__).parent
ROOT = HERE.parents[2]
sys.path[:0] = [str(ROOT), str(HERE), str(ROOT / "ai/experiments/translation_compare")]
D = Path("/nfs/team/data/scenefinder_vlm")
OUT = HERE / "results/test_final"
FROZEN = json.loads((ROOT / "docs/experiments/vlm_frozen_config.json").read_text())
LORA_FEATS = D / FROZEN["n3"]["lora_test_features_dir"]
METHODS = ["B1", "B2", "B3", "N3", "N3VLM"]


def test_rows():
    rows = [r for r in csv.DictReader(open(ROOT / "docs/experiments/vlm_eval_split.tsv"), delimiter="\t") if r["split"] == "test"]
    assert len(rows) == 8 and all(r["split"] == "test" for r in rows)
    return rows


def load_test():
    labels = json.loads((HERE / "labels/review.json").read_text())
    vids = {k: v for k, v in labels["videos"].items() if v["split"] == "test"}
    pos = [q for q in labels["queries"] if q["video"] in vids]
    neg = [q for q in labels.get("negative_queries", []) if q["video"] in vids]
    assert all(q.get("source") == "human_reviewed" for q in pos + neg), "검수 안 된 test 질의가 있음"
    for q in pos:
        q["partial"] = str(q.get("note", "")).startswith("부분")
    return vids, pos, neg


def cmd_prep(a):
    import speed_opt
    from lora import load_lora
    rows = test_rows()
    # CLIP (서비스와 같은 Moment-DETR 특징, B2·B3) — 평가 특징 추출 스크립트 그대로
    subprocess.run([sys.executable, str(HERE / "extract_eval_features.py"), "--subset", "test", "--kinds", "clip"], check=True)
    emb = speed_opt.Embedder(); load_lora(emb.m, D / FROZEN["n3"]["lora_adapter"])
    LORA_FEATS.mkdir(parents=True, exist_ok=True); (D / "eval_frames_640").mkdir(exist_ok=True)
    timing = {}
    for r in rows:
        y = r["youtube_id"]
        n = len(torch.load(D / "eval_features/clip" / f"{y}_clip_features.pt"))
        torch.cuda.synchronize(); t0 = time.time()
        frames = speed_opt.decode(D / "eval_videos" / f"{y}.mp4", n, "cpu")
        e, _, _ = emb(frames, "torchvision", "cuda", 16)
        torch.cuda.synchronize(); sec = time.time() - t0
        torch.save(e.half().cpu(), LORA_FEATS / f"{y}.pt")
        np.save(D / "eval_frames_640" / f"{y}.npy", frames)
        timing[r["key"]] = {"sec": round(sec, 2), "video_sec": float(r["duration_sec"]), "n": n}
        print(r["key"], timing[r["key"]], flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    tot = sum(t["sec"] for t in timing.values()) / sum(t["video_sec"] for t in timing.values()) * 60
    (OUT / "extract_timing.json").write_text(json.dumps({"per_video": timing, "sec_per_video_min": round(tot, 3),
                                                         "note": "디코딩+LoRA 임베딩을 겹치지 않고 차례로 (추출 1회 기준)"}, ensure_ascii=False, indent=1))


def cmd_run(a):
    import prelim_eval as pe, summary
    from combo_dev import rank_query
    from vlm_rejudge import Judge, rerank, PROMPTS
    vids, pos, neg = load_test()
    pe.LORA["adapter"] = str(D / FROZEN["n3"]["lora_adapter"]); pe.LORA["feats"] = str(LORA_FEATS)
    m = pe.Methods(vids); j = Judge()
    n3, vl = FROZEN["n3"]["combo"], FROZEN["n3_vlm"]
    lat = {k: [] for k in METHODS}
    rows, negs = [], []

    def n3_rank(k, q):
        qv = m._qwen_text([q], pe.QWEN_Q_INSTR)[0]
        fs = m.smooth(m._feat(k, "qwen_640") @ qv)
        spans_f, _ = m._frame_rank(k, qv, "qwen_640")
        sig = {"sub": m._sub_ranked(k, q), "frame_bins": fs.tolist(), "frame_spans": spans_f[:4], "mr_top5": []}
        return rank_query(sig, n3["rule"], n3["K"], n3["w_frame"], n3["w_mr"], pe.widen, n3["shift"])

    for q in pos + neg:   # 예열 없이 바로 재면 첫 질의가 느려서 한 번 돌려 둠
        n3_rank(q["video"], q["query"]); break
    for q in pos + neg:
        k, yid = q["video"], vids[q["video"]]["youtube_id"]
        res = {}
        for name in ("B1", "B2", "B3"):
            torch.cuda.synchronize(); t0 = time.time()
            r = m.run(name, k, q["query"]); torch.cuda.synchronize(); lat[name].append(time.time() - t0)
            res[name] = {"top5": summary.nms_top(r, k=5) if r else [], "score": None}
        torch.cuda.synchronize(); t0 = time.time()
        top, sc = n3_rank(k, q["query"]); torch.cuda.synchronize(); tb = time.time() - t0; lat["N3"].append(tb)
        res["N3"] = {"top5": [tuple(x) for x in top[:5]], "score": sc}
        t1 = time.time()
        spans = [tuple(x) for x in top[:vl["K"]]]
        py = j.p_yes(q["query"], yid, spans, vl["prompt"])
        torch.cuda.synchronize(); lat["N3VLM"].append(tb + time.time() - t1)
        res["N3VLM"] = {"top5": rerank(spans, py, vl["K"], vl["comb"])[:5] + [tuple(x) for x in top[vl["K"]:5]], "score": max(py) if py else None}
        if "gt" in q and q["gt"]:
            row = {kk: q.get(kk) for kk in ("num", "video", "type", "query", "gt", "origin", "partial")} | {"overlay_text": bool(q.get("overlay_text"))}
            for name in METHODS:
                t5 = res[name]["top5"]
                row[name] = {"top5": t5, "iou": summary.best_iou(t5[0], q["gt"]) if t5 else 0.0, "score": res[name]["score"]}
            rows.append(row)
        else:
            negs.append({"num": q["num"], "video": k, "query": q["query"], "origin": q.get("origin"),
                         **{name: res[name]["score"] for name in ("N3", "N3VLM")}})
    rng = random.Random(0)   # 무작위 기준선 (예비 실험과 같은 방식)
    for r in rows:
        dur = vids[r["video"]]["duration"]; L = statistics.mean(e - s for s, e in r["gt"])
        sims = [summary.best_iou((s, s + L), r["gt"]) for s in (rng.uniform(0, max(0.0, dur - L)) for _ in range(100))]
        r["random"] = {"p03": sum(x >= 0.3 for x in sims) / len(sims)}
    pct = lambda v, p: sorted(v)[int(p * (len(v) - 1))]  # noqa: E731
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "rows.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    (OUT / "negatives.json").write_text(json.dumps(negs, ensure_ascii=False, indent=1))
    (OUT / "meta.json").write_text(json.dumps({
        "run_at": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()), "frozen_commit": FROZEN.get("frozen_commit"),
        "n_pos": len(rows), "n_neg": len(negs),
        "latency_sec": {k: {"p50": round(statistics.median(v), 3), "p95": round(pct(v, 0.95), 3)} for k, v in lat.items()},
        "gpu_peak_gib": round(torch.cuda.max_memory_allocated() / 2**30, 2)}, ensure_ascii=False, indent=1))
    print(f"→ {OUT} (정답 있음 {len(rows)}, 정답 없음 {len(negs)})")


def cmd_report(a):
    import summary
    rows = json.loads((OUT / "rows.json").read_text()); meta = json.loads((OUT / "meta.json").read_text())
    ext = json.loads((OUT / "extract_timing.json").read_text()) if (OUT / "extract_timing.json").exists() else {}

    def st(rs, m):
        n = len(rs)
        r1 = sum(r[m]["iou"] >= 0.3 for r in rs); r15 = sum(r[m]["iou"] >= 0.5 for r in rs)
        r3 = sum(any(summary.best_iou(c, r["gt"]) >= 0.3 for c in r[m]["top5"][:3]) for r in rs)
        r5 = sum(any(summary.best_iou(c, r["gt"]) >= 0.3 for c in r[m]["top5"][:5]) for r in rs)
        s5 = sum(summary.start_ok(r[m]["top5"][0], r["gt"]) for r in rs if r[m]["top5"])
        early = sum(0 <= min((g[0] - r[m]["top5"][0][0] for g in r["gt"]), key=abs) <= 5 for r in rs if r[m]["top5"])
        return dict(n=n, r1=r1, r15=r15, r3=r3, r5=r5, s5=s5, early=early)

    G = [("전체", lambda r: True), ("S 말", lambda r: r["type"] == "S"), ("V 화면", lambda r: r["type"] == "V"),
         ("V 화면 글자", lambda r: r["type"] == "V" and r["overlay_text"]), ("사용자 질문", lambda r: r["origin"] == "simulated_user")]
    NAME = {"B1": "B1 자막 검색(MiniLM)", "B2": "B2 구간 검색 CLIP 버전", "B3": "B3 main 서비스", "N3": "**N3 (최종 후보)**", "N3VLM": "N3+VLM 재판별(참고)"}
    L = [f"# test 결과 (1회, {meta['run_at']}, 고정 커밋 {meta.get('frozen_commit')})", ""]
    for g, f in G:
        rs = [r for r in rows if f(r)]
        if not rs:
            continue
        b3 = st(rs, "B3")
        L += [f"## {g} (질의 {len(rs)})", "", "| 방식 | R@1 IoU≥0.3 | R@1 IoU≥0.5 | R@3 | R@5 | 시작 ±5초 | 앞 0~5초 | R@1 B3 대비 |", "|---|---|---|---|---|---|---|---|"]
        for mth in METHODS:
            x = st(rs, mth)
            p = lambda v: f"{v} ({v / x['n'] * 100:.0f}%)"  # noqa: E731
            diff = "–" if mth == "B3" else f"{x['r1'] - b3['r1']:+d}"
            L.append(f"| {NAME[mth]} | {p(x['r1'])} | {p(x['r15'])} | {p(x['r3'])} | {p(x['r5'])} | {p(x['s5'])} | {p(x['early'])} | {diff} |")
        rnd = sum(r["random"]["p03"] for r in rs)
        L += [f"| 무작위(기댓값) | {rnd:.1f} | | | | | | |", ""]
    a_ = st(rows, "N3"); b_ = st(rows, "B3"); v_ = st(rows, "N3VLM")
    lat = meta["latency_sec"]
    ok1 = a_["r1"] - b_["r1"] >= 6; ok2 = a_["r3"] >= b_["r3"] - 3; ok3 = a_["s5"] >= b_["s5"] - 3
    ok4 = lat["N3"]["p95"] <= 1.0; ok5 = ext.get("sec_per_video_min", 99) <= 1.5
    L += ["## 판정 (vlm_model_plan.md 5장, 최종 후보 N3)", "",
          "| 조건 | N3 | B3 | 결과 |", "|---|---|---|---|",
          f"| R@1 IoU≥0.3이 B3보다 +6개 이상 | {a_['r1']} | {b_['r1']} | {'통과' if ok1 else '미달'} ({a_['r1'] - b_['r1']:+d}) |",
          f"| R@3이 3개 넘게 나빠지지 않음 | {a_['r3']} | {b_['r3']} | {'통과' if ok2 else '미달'} ({a_['r3'] - b_['r3']:+d}) |",
          f"| 시작 ±5초가 3개 넘게 나빠지지 않음 | {a_['s5']} | {b_['s5']} | {'통과' if ok3 else '미달'} ({a_['s5'] - b_['s5']:+d}) |",
          f"| 질의당 응답 p95 ≤ 1초 | {lat['N3']['p95']}초 | {lat['B3']['p95']}초 | {'통과' if ok4 else '미달'} |",
          f"| 특징 추출 ≤ 영상 1분당 1.5초 | {ext.get('sec_per_video_min', '–')}초 | | {'통과' if ok5 else '미달'} |",
          "", f"**종합: {'채택(시연에 VLM 버전 사용)' if all([ok1, ok2, ok3, ok4, ok5]) else '채택 조건 미달'}**", "",
          f"- 참고 N3+VLM 재판별: R@1 {v_['r1']} (B3 대비 {v_['r1'] - b_['r1']:+d}), 확인 완료까지 p95 {lat['N3VLM']['p95']}초", ""]
    neg = json.loads((OUT / "negatives.json").read_text())
    L += [f"- 정답 없음 질의 {len(neg)}개: 필터 미적용(한계). N3 1위 점수 중앙값 {statistics.median([x['N3'] for x in neg if x['N3'] is not None]):.2f}"]
    (OUT / "report.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("cmd", choices=["prep", "run", "report"]); ap.add_argument("--i-confirm-test", action="store_true")
    a = ap.parse_args()
    if a.cmd in ("prep", "run") and not a.i_confirm_test:
        sys.exit("test는 사용자 지시로만 실행합니다. --i-confirm-test 를 붙이세요.")
    {"prep": cmd_prep, "run": cmd_run, "report": cmd_report}[a.cmd](a)


if __name__ == "__main__":
    main()
