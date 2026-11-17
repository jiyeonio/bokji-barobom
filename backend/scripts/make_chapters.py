"""시연 영상 장면(챕터) 자동 나누기 + 확신 높은 신청 단계만 단계 카드로 → backend/data/chapters/<id>.json, (검수 안 된 영상) backend/data/steps/<id>.json

나누기: 자막이 있으면 자막 덩어리(10~16초)를 MiniLM으로 임베딩해 이웃 덩어리 유사도가 낮은 곳에서 끊음,
        자막이 없으면 LoRA 화면 특징의 이웃 칸 변화가 큰 곳에서 끊음. 장면 수 = 영상 길이/60초(3~15개), 장면은 최소 20초.
제목·단계: 로컬 Qwen3-VL-4B가 장면 프레임 3장 + 자막을 보고 짧은 제목과 신청 단계(1 자격 확인·2 서류 준비·3 신청서 작성·4 결과 확인·0 없음)를 고름.
단계 카드는 아래를 모두 만족할 때만(사람 검수 없이 화면에 보이므로): VLM 재확인 P(예) ≥ 0.7, 자막에 그 단계 낱말, 영상 시작 10초 이후.
사람이 검수한(status reviewed) 단계 카드 파일은 건드리지 않음.

    python backend/scripts/make_chapters.py [--only <id,...>]   (GPU — API 서버를 내린 뒤)
"""
import argparse, json, math, re, sys, time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "backend/services"), str(ROOT / "ai/experiments/vlm_model"), str(ROOT / "backend/scripts")]
from lora_make_data import Gen, chunks_of, parse_json
from draft_steps import STEP_WORDS, MIN_P, MIN_START

IDX = Path("/nfs/team/data/scenefinder_vlm/demo/index")
OUT = ROOT / "backend/data/chapters"
STEPS = ROOT / "backend/data/steps"
MIN_LEN = 20.0
MAX_LEN, SPLIT_TO = 360.0, 180.0   # 6분 넘는 장면은 3분 안팎으로 더 나눔
# 단계 재확인 질문: 추상적인 「~ 단계입니까」 대신 화면·자막에 보이는 것을 묻는 구체적인 질문(2026-11-15 시험에서 추상 질문은 서식 화면도 「아니오」)
STEP_DESC = {1: "화면이나 자막에 지원 대상·자격 조건(나이, 소득 기준 등)이 나옵니까?",
             2: "화면이나 자막에 신청할 때 준비하거나 제출해야 할 서류 이름이 나옵니까?",
             3: "이 화면은 신청서나 서식(또는 신청 화면)을 작성하는 방법을 보여 줍니까?",
             4: "화면이나 자막에 신청 결과·신청 완료·심사 결과 안내가 나옵니까?"}
TITLE_PROMPT = """복지 안내 영상의 한 장면입니다(이미지 3장: 앞·가운데·뒤). 자막: {sub}

1) 이 장면을 15자 이내의 짧은 한국어 제목으로 쓰세요(예: 「로그인하기」, 「소득 정보 입력」). 화면과 자막에 있는 내용만.
2) 이 장면이 복지 신청 단계 중 어디에 해당하는지 번호 하나: 1 자격 확인, 2 서류 준비, 3 신청서 작성, 4 결과 확인, 0 해당 없음.
JSON 하나만: {{"title": "...", "step": 0}}"""
CHECK_PROMPT = "이 이미지는 영상의 한 장면이고, 그 장면의 자막은 「{sub}」입니다. {desc} 예 또는 아니오로만 답하세요."
CHECK_PROMPT_FRAME = "{desc} 예 또는 아니오로만 답하세요."   # 3단계(서식 작성)는 화면만 보고 판단 — 프레임 한 장씩, 가장 높은 값


def cuts_from_scores(times, score, n_cut, min_len, start, end):
    """score가 높은 경계부터 n_cut개, 장면이 min_len보다 짧아지지 않게."""
    order = np.argsort(-np.asarray(score))
    chosen = []
    for i in order:
        t = times[i]
        if t - start < min_len or end - t < min_len or any(abs(t - c) < min_len for c in chosen):
            continue
        chosen.append(t)
        if len(chosen) >= n_cut:
            break
    return sorted(chosen)


def segment(v, minilm):
    d = IDX / v["youtube_id"]; dur = float(v["duration_sec"])
    subs = json.loads((d / "subs.json").read_text())["segments"]
    n = int(np.clip(round(dur / 60), 3, 15))
    if subs:
        chs = chunks_of(subs, dur)
        if len(chs) < 2:
            return [(0.0, dur)]
        e = minilm.encode([c["text"] or "." for c in chs], convert_to_tensor=True)
        sim = F.cosine_similarity(e[:-1], e[1:]).cpu().numpy()
        times = [chs[i + 1]["start"] for i in range(len(chs) - 1)]
        cuts = cuts_from_scores(times, -sim, n - 1, MIN_LEN, 0.0, dur)
    else:
        f = F.normalize(torch.load(d / "lora_640.pt").float(), dim=-1)
        ch = (1 - (f[:-1] * f[1:]).sum(-1)).numpy()
        ch = np.convolve(ch, np.ones(3) / 3, mode="same")
        times = [(i + 1) * 2.0 for i in range(len(ch))]
        cuts = cuts_from_scores(times, ch, n - 1, MIN_LEN, 0.0, dur)
        sim = -ch
    bounds = [0.0] + cuts + [dur]
    # 2026-11-15: 장면 수 상한(15) 때문에 너무 긴 장면(MAX_LEN 초과)은 그 안에서 경계 점수가 높은 곳을 골라 SPLIT_TO 안팎으로 더 나눔
    out = []
    for s, e in zip(bounds[:-1], bounds[1:]):
        if e - s > MAX_LEN:
            idx = [i for i, t in enumerate(times) if s < t < e]
            extra = cuts_from_scores([times[i] for i in idx], [-sim[i] for i in idx], math.ceil((e - s) / SPLIT_TO) - 1, MIN_LEN, s, e)
            b2 = [s] + extra + [e]; out += list(zip(b2[:-1], b2[1:]))
        else:
            out.append((s, e))
    return out


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--only", default="")
    a = ap.parse_args()
    import os
    from sentence_transformers import SentenceTransformer
    minilm = SentenceTransformer(os.environ["SCENEFINDER_MINILM_MODEL_PATH"])
    g = Gen(); tok = g.proc.tokenizer
    yes, no = tok.encode("예", add_special_tokens=False)[0], tok.encode("아니오", add_special_tokens=False)[0]

    @torch.no_grad()
    def p_yes(msgs):
        from PIL import Image
        text = g.proc.apply_chat_template(msgs, add_generation_prompt=True, tokenize=False)
        imgs = [Image.fromarray(c["image"]) for m in msgs for c in m[0]["content"] if c["type"] == "image"]
        x = g.proc(text=text, images=imgs, padding=True, return_tensors="pt").to("cuda")
        lg = g.model(**x).logits[:, -1, :].float()
        return torch.softmax(torch.stack([lg[:, yes], lg[:, no]], 1), 1)[:, 0].tolist()

    cat = json.loads((ROOT / "backend/data/demo_videos.json").read_text())
    only = set(filter(None, a.only.split(",")))
    OUT.mkdir(parents=True, exist_ok=True)
    for v in cat:
        y = v["youtube_id"]
        if only and y not in only:
            continue
        d = IDX / y; t0 = time.time()
        subs = json.loads((d / "subs.json").read_text())["segments"]
        frames = np.load(d / "frames.npy", mmap_mode="r")
        spans = segment(v, minilm)

        def sub_of(s, e):
            return " ".join(x["text"].strip() for x in subs if x["end_time"] > s and x["start_time"] < e)

        def imgs(s, e):
            return [np.asarray(frames[min(len(frames) - 1, int(t // 2))]) for t in (s + (e - s) * 0.2, (s + e) / 2, s + (e - s) * 0.8)]

        msgs = [[{"role": "user", "content": [{"type": "image", "image": im} for im in imgs(s, e)] +
                  [{"type": "text", "text": TITLE_PROMPT.format(sub=(sub_of(s, e) or "(없음)")[:300])}]}] for s, e in spans]
        outs = []
        for i in range(0, len(msgs), 6):
            outs += g(msgs[i:i + 6], max_new=60)
        chs = []
        for (s, e), o in zip(spans, outs):
            j = parse_json(o, "obj") or {}
            title = str(j.get("title") or "").strip()[:20] or (sub_of(s, e)[:18] or "장면")
            step = j.get("step") if j.get("step") in (1, 2, 3, 4) else None
            chs.append({"start": round(s, 1), "end": round(e, 1), "title": title, "step": step, "stepConfident": False, "why": ""})
        cand = [c for c in chs if c["step"]]
        if cand:
            msgs2 = []
            for c in cand:
                txt = (CHECK_PROMPT_FRAME.format(desc=STEP_DESC[3]) if c["step"] == 3 else
                       CHECK_PROMPT.format(sub=(sub_of(c["start"], c["end"]) or "없음")[:200], desc=STEP_DESC[c["step"]]))
                msgs2 += [[{"role": "user", "content": [{"type": "image", "image": im}, {"type": "text", "text": txt}]}] for im in imgs(c["start"], c["end"])]
            flat = []
            for i in range(0, len(msgs2), 9):
                flat += p_yes(msgs2[i:i + 9])
            ps = [max(flat[3 * k:3 * k + 3]) for k in range(len(cand))]   # 장면당 프레임 3장 중 최댓값
            for c, p in zip(cand, ps):
                sub = sub_of(c["start"], c["end"])
                miss = [x for x, ok in [(f"P(예)≥{MIN_P}", p >= MIN_P), ("자막에 단계 낱말", bool(re.search(STEP_WORDS[c["step"]], sub))),
                                        (f"{MIN_START:.0f}초 이후", c["start"] >= MIN_START)] if not ok]
                c["stepConfident"] = not miss; c["pYes"] = round(p, 3); c["why"] = "통과" if not miss else "미달: " + ", ".join(miss)
        (OUT / f"{y}.json").write_text(json.dumps({"youtubeId": y, "generatedAt": time.strftime("%Y-%m-%d %H:%M"), "method": "auto",
                                                   "chapters": chs}, ensure_ascii=False, indent=1), encoding="utf-8")
        sf = STEPS / f"{y}.json"
        if not (sf.exists() and json.loads(sf.read_text()).get("status") == "reviewed"):
            steps = [{"id": f"s{c['step']}_{i}", "start": c["start"], "end": c["end"], "title": c["title"], "short": c["title"][:8],
                      "step": c["step"], "stepLabel": "", "verification": "none", "subtitle": sub_of(c["start"], c["end"])[:120],
                      "screenTitle": "", "relatedDocs": [], "confident": True, "confidence": c["why"], "pYes": c.get("pYes")}
                     for i, c in enumerate(chs) if c["stepConfident"]]
            sf.write_text(json.dumps({"youtubeId": y, "status": "auto", "source": "make_chapters", "chapters": steps,
                                      "generatedAt": time.strftime("%Y-%m-%d %H:%M")}, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{y} 장면 {len(chs)}, 단계 후보 {len(cand)}, 단계 카드 {sum(c['stepConfident'] for c in chs)} ({time.time() - t0:.0f}초)", flush=True)


if __name__ == "__main__":
    main()
