"""빠른 배지 규칙 맞추기(서비스 속도 개선): dev 질의(정답 있음·없음 전부)에서 지금 실시간 VLM 배지를 기준 답으로,
장면 정보 점수(s_scr, s_sub)로 「화면에서 확인됨 / 확인 안 됨」을 바로 정할 문턱을 고름 → backend/data/badge_rules.json

고르는 기준(결과 전 고정): 바로 정한 배지가 VLM 배지와 95% 이상 같으면서, 바로 정하는 비율(질의 단위로 상위 3개 모두)이 가장 큰 문턱.
dev만 씀(시연 질문·새 평가 질문·test는 쓰지 않음).

    python backend/scripts/calibrate_badges.py   (GPU — API 서버를 내린 뒤)
"""
import itertools, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "backend/services")]
from welfare_service import Searcher, span_iou
from ai.features.welfare_search import SceneInfo


def main():
    s = Searcher("n3_vlm"); si = SceneInfo(s.ws.minilm)
    labels = json.loads((ROOT / "ai/experiments/vlm_model/labels/review.json").read_text())
    dev = {k: v for k, v in labels["videos"].items() if v["split"] == "dev"}
    qs = [q for q in labels["queries"] + labels.get("negative_queries", []) if q["video"] in dev]
    items = []
    for q in qs:
        y = dev[q["video"]]["youtube_id"]
        with s.ws.lock:
            mq, qv = s.ws.encode(q["query"])
            base = s.ws.n3(y, mq, qv)["top"]
            rj = s.ws.rejudge(y, q["query"], base)
        for sp, ver in zip(rj["top"][:3], rj["verification"]):
            sc, ss = si.scores(mq, y, sp, s.ws.subtitle_text(y, sp))
            items.append({"q": q["num"], "ver": ver, "s_scr": sc, "s_sub": ss, "base_rank": next(i for i, b in enumerate(base) if span_iou(b, sp) > 0.99)})
        items[-1]["top1_moved"] = span_iou(base[0], rj["top"][0]) < 0.99
    (ROOT / "docs/service/badge_calibration_items.json").write_text(json.dumps(items, ensure_ascii=False))
    best = None
    grid = [x / 100 for x in range(20, 96, 2)] + [9.0]   # 9.0 = 그 규칙을 쓰지 않음(예: 「화면에서 확인됨」은 늘 VLM)
    for a, b, c in itertools.product(grid, grid, grid):
        if b >= a and a < 9 or b > 1.5:
            continue
        dec = [(("screen" if it["s_scr"] >= a else "none" if (it["s_scr"] < b and it["s_sub"] < c) else None), it["ver"]) for it in items]
        d = [(x, v) for x, v in dec if x]
        if not d:
            continue
        agree = sum(x == v for x, v in d) / len(d)
        byq = {}
        for it, (x, _) in zip(items, dec):
            byq.setdefault(it["q"], []).append(x is not None)
        cover = sum(all(v) for v in byq.values()) / len(byq)
        if agree >= 0.95 and (best is None or cover > best[0]):
            best = (cover, agree, a, b, c, len(d))
    out = {"note": "서비스 속도 개선(2026-11-15). dev 질의의 실시간 VLM 배지를 기준으로 맞춤. 정하지 못하면 실시간 VLM.",
           "screen_min": best[2], "none_scr_max": best[3], "none_sub_max": best[4],
           "dev_agreement": round(best[1], 3), "dev_query_coverage": round(best[0], 3), "dev_items_decided": best[5], "dev_items": len(items),
           "dev_top1_moved_by_vlm": sum(1 for it in items if it.get("top1_moved")), "dev_queries": len(qs)} if best else {"note": "95% 맞는 문턱 없음"}
    (ROOT / "backend/data/badge_rules.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
