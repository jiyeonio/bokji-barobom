"""시연 「장면 콕 집기」 후보 찾기: 정답 구간이 있는 화면 묘사 질문을 서비스와 같은 검색(전체 시연 영상, n3_vlm)으로 돌려
1위가 정답 영상·정답 구간(IoU ≥ 0.3)이고 「화면에서 확인됨」인 것만 고름 → docs/service/pinpoint_candidates.md

질문 출처: dev·test 검수 완료 V(화면) 질의(test는 test 실행 뒤), LoRA 학습 영상의 화면 글자 질의(b1_screen, 생성 데이터),
시연용 화면 묘사 질문(pinpoint_gen.py).
    python backend/scripts/pinpoint_candidates.py  (API 서버가 떠 있어야 함)
"""
import json, sys, time, urllib.parse, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "backend/services"), str(ROOT / "ai/experiments/translation_compare")]
import summary
from welfare_service import POLICIES, policy_of

API = "http://127.0.0.1:8000"
FOCUS = {"basic-pension", "child-care", "youth-rent", "long-term-care"}


def get(u):
    return json.load(urllib.request.urlopen(API + u))


def fmt(t):
    return f"{int(t) // 60}:{int(t) % 60:02d}"


def main():
    cat = {v["youtube_id"]: v for v in json.loads((ROOT / "backend/data/demo_videos.json").read_text())}
    labels = json.loads((ROOT / "ai/experiments/vlm_model/labels/review.json").read_text())
    test_done = (ROOT / "ai/experiments/vlm_model/results/test_final/rows.json").exists()
    cands = []
    for q in labels["queries"]:
        v = labels["videos"][q["video"]]
        if q.get("source") != "human_reviewed" or q["type"] != "V" or (v["split"] == "test" and not test_done):
            continue
        cands.append({"query": q["query"], "yid": v["youtube_id"], "gt": q["gt"], "from": f"{v['split']} 검수 질의"})
    for l in open(ROOT / "ai/experiments/vlm_model/labels/lora_train_pairs.jsonl"):
        p = json.loads(l)
        if p["kind"] == "b1_screen":
            cands.append({"query": p["query"], "yid": p["vid"], "gt": [[p["start"], p["end"]]], "from": "학습 영상 화면 질의(생성)"})
    gen = ROOT / "docs/service/pinpoint_generated.json"   # pinpoint_gen.py가 만든 시연용 화면 묘사 질문
    if gen.exists():
        cands += json.loads(gen.read_text())
    cands = [c for c in cands if c["yid"] in cat and policy_of(cat[c["yid"]]["policy_hint"]) in FOCUS]
    print(f"후보 질문 {len(cands)}개", flush=True)
    ok = []
    for c in cands:
        d = get("/api/welfare/search?q=" + urllib.parse.quote(c["query"])); t0 = time.time()
        while d["status"] == "pending" and time.time() - t0 < 40:
            time.sleep(0.6); d = get(f"/api/welfare/search/{d['jobId']}")
        if not d["scenes"]:
            continue
        s = d["scenes"][0]; f = s["found"]
        iou = summary.best_iou((f["start"], f["end"]), c["gt"]) if s["videoId"] == c["yid"] else 0.0
        if s["videoId"] == c["yid"] and iou >= 0.3 and f["verification"] == "screen":
            ok.append({**c, "start": f["start"], "end": f["end"], "iou": round(iou, 2), "label": f["label"],
                       "policy": POLICIES[policy_of(cat[c["yid"]]["policy_hint"])]["name"], "title": cat[c["yid"]]["title"],
                       "origin": cat[c["yid"]]["origin"]})
            print("통과", c["query"][:40], flush=True)
    L = ["# 「장면 콕 집기」 후보 (서비스와 같은 검색, n3_vlm, 전체 시연 영상)", "",
         f"자동 생성 {time.strftime('%Y-%m-%d %H:%M')} UTC. 조건: 1위가 정답 영상·정답 구간(IoU ≥ 0.3) + 「화면에서 확인됨」. 후보 질문 {len(cands)}개 중 {len(ok)}개 통과.", "",
         "| 질문 | 정책 | 영상 | 장면 | IoU | 썸네일 시점 | 출처 |", "|---|---|---|---|---|---|---|"]
    for o in ok:
        L.append(f"| {o['query']} | {o['policy']} | {o['title'][:30]} ({o['yid']}, {o['origin']}) | {fmt(o['start'])}~{fmt(o['end'])} | {o['iou']} | "
                 f"{fmt((o['start'] + o['end']) / 2)} | {o['from']} |")
    (ROOT / "docs/service/pinpoint_candidates.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    (ROOT / "docs/service/pinpoint_candidates.json").write_text(json.dumps(ok, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"→ 통과 {len(ok)}개")


if __name__ == "__main__":
    main()
