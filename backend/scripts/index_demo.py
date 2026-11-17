"""시연용 영상 미리 분석 → /nfs/team/data/scenefinder_vlm/demo/index/<유튜브ID>/ + backend/data/demo_videos.json(목록)

영상마다:
  subs.json     자막 (서비스와 같은 Whisper large-v3-turbo, 말이 거의 없으면 빈 목록)
  lora_640.pt   화면 검색 특징: Qwen3-VL-Embedding-2B + 고른 LoRA(welfare ep1), 2초 칸, 640×360 (평가와 같은 디코딩)
  frames.npy    2초 칸 프레임 640×360 (VLM 재판별용, 질의 때 디코딩하지 않게)
  clip.pt       CLIP 특징 (main 방식용, 서비스 build_feature)
dev·test 영상은 평가 때 만든 같은 파일을 복사한다(같은 설정). test 영상은 test 실행(results/test_final) 뒤에만 들어간다.
LoRA 학습 영상 20개도 검색 대상에 넣는다(2026-11-15 사용자 결정; 화면 검색 LoRA가 학습한 영상이라 이 영상들의 검색은 실제보다 좋게 나올 수 있음).
정책 연결은 POLICY_OVERRIDE로 영상마다 명시(원래 정책 표기가 거칠어 엉뚱하게 연결되지 않게).

    python backend/scripts/index_demo.py
"""
import argparse, csv, json, math, os, shutil, sys, time
from pathlib import Path

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "backend/services"), str(ROOT / "ai/experiments/vlm_model")]
os.environ.setdefault("WHISPER_MODEL_SIZE", "large-v3-turbo")
D = Path("/nfs/team/data/scenefinder_vlm")
IDX = D / "demo/index"
NEW_VIDEOS = D / "demo/videos"
LORA = D / "lora_runs/welfare/ep1"
CATALOG = ROOT / "backend/data/demo_videos.json"
LORA_VIDEOS = D / "lora_videos"
LORA_SUBS = D / "lora_data/subs"
# 영상별 정책 연결(policy_hint) 지정 — welfare_service.POLICY_OF_HINT의 키 또는 정책 ID (사람이 확인한 연결)
POLICY_OVERRIDE = {"1yYTX1-p-NI": "에너지바우처", "KK54HbOOCJ8": "에너지바우처", "1NFNR-HUtxs": "아이돌봄", "ZVcj7R_bOCQ": "노인일자리",
                   # 2026-11-15: 정책명·소관기관·영상 제목이 모두 맞는 것만 (애매한 영상은 docs/service/video_policy_links.md)
                   "KRQgoAmtHGY": "job-seeking-benefit", "9IqJJbTEuPE": "employment-support", "1tEk_OytD7Y": "happy-housing",
                   "CgI_zM3DJiM": "naeil-card", "BIbOi1uOWJY": "didimdol-loan", "qCoHO1-5eSU": "disability-personal-budget",
                   # test 영상(test 실행 뒤 추가): LH 행복주택 → 행복주택, 국민건강보험 장기요양 인정신청 → 장기요양인정,
                   # 서울시 청년월세(서울시 사업, 국토부 청년월세 지원과 다름)는 연결하지 않음
                   "2DoWXzsKxSw": "happy-housing", "C4rra31STNk": "long-term-care", "xRSg7tyyOFU": "기타:서울시 청년월세",
                   # 2026-11-15 사용자 결정: 서울시 청년월세 영상은 국가 청년월세 지원과 조건이 달라 연결 풀기
                   "H-oqT3Sthl4": "기타:서울시 청년월세"}
POLICIES_JSON = ROOT / "backend/data/policies.json"
# 장면 검색 후보에서 빼는 영상(영상 화면·정책 패널·단계 카드는 그대로). 2026-11-15: 복지로 「기초연금 모바일 신청 방법」은 사용자 결정으로 검색에 넣음
# (시연 질문 「이거 아직 신청 되는 거예요?」 1위가 KBBwdz4sidM 0:44 → 이 영상으로 바뀌는 것은 괜찮다고 함 — 안내·공식 신청 기간 답은 그대로)
SEARCH_EXCLUDE = set()


def auto_policy(title):
    """새 영상 자동 연결: 제목에 정책 키워드가 있는 정책이 정확히 하나일 때만 (둘 이상·없음이면 연결하지 않음)."""
    pols = json.loads(POLICIES_JSON.read_text())
    hit = {p["policyId"] for p in pols if any(k in title for k in p["keywords"]) or p["name"] in title}
    return hit.pop() if len(hit) == 1 else None
CLIP_LEN = 2


def rows():
    out = []
    lora_ids = {r["youtube_id"] for r in csv.DictReader(open(ROOT / "docs/experiments/vlm_lora_train_videos.tsv"), delimiter="\t")}
    cand = {r["youtube_id"]: r for f in ("vlm_eval_candidates.tsv", "vlm_lora_candidates.tsv")
            for r in csv.DictReader(open(ROOT / "docs/experiments" / f), delimiter="\t")}
    for r in csv.DictReader(open(ROOT / "docs/experiments/vlm_eval_split.tsv"), delimiter="\t"):
        if r["split"] != "dev":
            continue
        out.append({"youtube_id": r["youtube_id"], "title": r["title"], "channel": r["channel"], "policy_hint": r["policy"],
                    "published": cand.get(r["youtube_id"], {}).get("published", ""), "duration_sec": int(float(r["duration_sec"])),
                    "origin": "eval_dev", "video_path": str(D / "eval_videos" / f"{r['youtube_id']}.mp4")})
    for f in ("demo_new_videos.tsv", "demo_new_videos2.tsv"):
        for r in csv.DictReader(open(ROOT / "docs/service" / f), delimiter="\t"):
            out.append({"youtube_id": r["youtube_id"], "title": r["title"], "channel": r["channel"], "policy_hint": r["policy"],
                        "published": r["published"], "duration_sec": int(r["duration_sec"]), "origin": "demo_new",
                        "video_path": str(NEW_VIDEOS / f"{r['youtube_id']}.mp4")})
    for r in csv.DictReader(open(ROOT / "docs/experiments/vlm_lora_train_videos.tsv"), delimiter="\t"):
        out.append({"youtube_id": r["youtube_id"], "title": r["title"], "channel": r["channel"], "policy_hint": "기타:" + r["policy"],
                    "published": r["published"], "duration_sec": int(r["duration_sec"]), "origin": "lora_train",
                    "video_path": str(LORA_VIDEOS / f"{r['youtube_id']}.mp4")})
    # test 영상: test 1회 실행(2026-11-15, results/test_final) 뒤에 시연 목록에 추가 — test 결과 파일이 있어야만 넣음
    if (ROOT / "ai/experiments/vlm_model/results/test_final/rows.json").exists():
        for r in csv.DictReader(open(ROOT / "docs/experiments/vlm_eval_split.tsv"), delimiter="\t"):
            if r["split"] == "test":
                out.insert(len([x for x in out if x["origin"] == "eval_dev"]), {
                    "youtube_id": r["youtube_id"], "title": r["title"], "channel": r["channel"], "policy_hint": r["policy"],
                    "published": cand.get(r["youtube_id"], {}).get("published", ""), "duration_sec": int(float(r["duration_sec"])),
                    "origin": "eval_test", "video_path": str(D / "eval_videos" / f"{r['youtube_id']}.mp4")})
    sys.path.insert(0, str(ROOT / "backend/services"))
    from welfare_service import policy_of
    for r in out:
        if r["youtube_id"] in POLICY_OVERRIDE:
            r["policy_hint"], r["policy_link"] = POLICY_OVERRIDE[r["youtube_id"]], "manual"
        elif policy_of(r["policy_hint"]):
            r["policy_link"] = "list"          # 시연 영상 목록(tsv)의 정책 열
        else:
            pid = auto_policy(r["title"])
            r["policy_hint"], r["policy_link"] = (pid, "auto") if pid else (r["policy_hint"], "none")
    return out


def main():
    ap = argparse.ArgumentParser(); ap.parse_args()
    items = [r for r in rows() if Path(r["video_path"]).exists()]
    print(f"시연 영상 {len(items)}개 (받은 것만)", flush=True)
    for r in items:
        (IDX / r["youtube_id"]).mkdir(parents=True, exist_ok=True)
    # 1) dev: 평가 때 만든 파일 복사 (같은 설정)
    for r in items:
        if r["origin"] not in ("eval_dev", "eval_test"):
            continue
        y, d = r["youtube_id"], IDX / r["youtube_id"]
        lora_feat = (LORA / "dev_qwen_640" / f"{y}.pt") if r["origin"] == "eval_dev" else (D / "eval_features/qwen_640_lora_welfare_ep1" / f"{y}.pt")
        for src, dst in [(D / "eval_subtitles" / f"{y}.json", d / "subs.json"), (lora_feat, d / "lora_640.pt"),
                         (D / "eval_frames_640" / f"{y}.npy", d / "frames.npy"), (D / "eval_features/clip" / f"{y}_clip_features.pt", d / "clip.pt")]:
            if not dst.exists():
                shutil.copy(src, dst)
    # LoRA 학습 영상: 학습 데이터를 만들 때 만든 Whisper 자막(같은 설정) 재사용
    for r in items:
        if r["origin"] == "lora_train" and not (IDX / r["youtube_id"] / "subs.json").exists() and (LORA_SUBS / f"{r['youtube_id']}.json").exists():
            shutil.copy(LORA_SUBS / f"{r['youtube_id']}.json", IDX / r["youtube_id"] / "subs.json")
    new = [r for r in items if r["origin"] in ("demo_new", "lora_train")]
    # 2) 새 영상 자막
    todo = [r for r in new if not (IDX / r["youtube_id"] / "subs.json").exists()]
    if todo:
        from subtitles import _transcribe, MIN_SUBTITLE_SEGMENTS, MIN_SUBTITLE_CHARS
        for r in todo:
            items_, lang, prob = _transcribe(r["video_path"])
            if len(items_) < MIN_SUBTITLE_SEGMENTS or sum(len(i["text"]) for i in items_) < MIN_SUBTITLE_CHARS:
                items_ = []
            (IDX / r["youtube_id"] / "subs.json").write_text(json.dumps({"source": "whisper_large-v3-turbo", "language": lang,
                                                                        "segments": items_}, ensure_ascii=False, indent=1))
            print("자막", r["youtube_id"], len(items_), flush=True)
        del _transcribe; torch.cuda.empty_cache()
    # 3) CLIP 특징 (main 방식) — 칸 수 기준
    from ai.features.moment_detr_features import build_feature
    for r in new:
        d = IDX / r["youtube_id"]
        if not (d / "clip.pt").exists():
            build_feature(video_path=r["video_path"], video_id=r["youtube_id"], output_dir=str(d), overwrite=True)
            (d / f"{r['youtube_id']}_clip_features.pt").rename(d / "clip.pt")
    # 4) 프레임 + LoRA 화면 특징 (칸 수는 CLIP과 맞춤, 평가와 같음)
    import speed_opt
    from lora import load_lora
    emb = None
    for r in new:
        d = IDX / r["youtube_id"]
        if (d / "lora_640.pt").exists() and (d / "frames.npy").exists():
            continue
        if emb is None:
            emb = speed_opt.Embedder(); load_lora(emb.m, LORA / "adapter.pt")
        n = len(torch.load(d / "clip.pt")); t0 = time.time()
        frames = speed_opt.decode(Path(r["video_path"]), n, "cpu")
        np.save(d / "frames.npy", frames)
        e, _, _ = emb(frames, "torchvision", "cuda", 16)
        torch.save(e.half().cpu(), d / "lora_640.pt")
        print("특징", r["youtube_id"], n, f"{(time.time() - t0) / (r['duration_sec'] / 60):.2f}초/영상 1분", flush=True)
    cat = [{k: v for k, v in r.items() if k != "video_path"} | {"bins": len(torch.load(IDX / r["youtube_id"] / "clip.pt"))}
           | ({"in_search": False} if r["youtube_id"] in SEARCH_EXCLUDE else {}) for r in items]
    CATALOG.write_text(json.dumps(cat, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"→ {CATALOG} ({len(cat)}개)")


if __name__ == "__main__":
    main()
