"""「장면 콕 집기」 후보 질문 만들기(시연용, 평가 아님): 주력 정책 영상의 장면마다 로컬 Qwen3-VL-4B가 프레임을 보고
화면에 실제로 보이는 것을 「…하는 장면 / …화면」 짧은 문장으로 씀(특징 없는 화면이면 SKIP). 정답 = 그 장면 구간.
→ docs/service/pinpoint_generated.json (pinpoint_candidates.py가 검색으로 확인)

    python backend/scripts/pinpoint_gen.py   (GPU 사용 — API 서버를 내린 뒤)
"""
import json, re, sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "backend/services"), str(ROOT / "ai/experiments/vlm_model")]
from welfare_service import policy_of
from lora_make_data import Gen, chunks_of

IDX = Path("/nfs/team/data/scenefinder_vlm/demo/index")
FOCUS = {"basic-pension", "child-care", "youth-rent", "long-term-care"}
PROMPT = """복지 안내 영상의 한 장면입니다(이미지 2장: 앞부분, 뒷부분). 자막: {sub}

이 장면의 화면에 실제로 보이는 것(신청서 칸, 버튼, 서류, 앱·홈페이지 화면, 표, 안내 문구 등)을 사람이 검색창에 칠 법한
짧은 한국어 문장 하나로 쓰세요. 「…하는 장면」 또는 「…화면」으로 끝내고, 화면에서 확인할 수 없는 내용은 쓰지 마세요.
사람 얼굴·말하는 모습만 있거나 화면에 특별한 것이 없으면 SKIP 이라고만 쓰세요.
예시(주제 무관): 「도서관 앱에서 대출 연장 버튼 누르는 화면」"""


def main():
    cat = json.loads((ROOT / "backend/data/demo_videos.json").read_text())
    g = Gen(); out = []
    for v in cat:
        if policy_of(v["policy_hint"]) not in FOCUS:
            continue
        y = v["youtube_id"]; d = IDX / y
        subs = json.loads((d / "subs.json").read_text())["segments"]; frames = np.load(d / "frames.npy", mmap_mode="r")
        chs = chunks_of(subs, float(v["duration_sec"]))
        pick = chs[:: max(1, len(chs) // 8)][:8]   # 영상마다 고르게 최대 8장면
        msgs = []
        for c in pick:
            b1 = min(len(frames) - 1, int((c["start"] + (c["end"] - c["start"]) / 3) // 2)); b2 = min(len(frames) - 1, int((c["start"] + 2 * (c["end"] - c["start"]) / 3) // 2))
            msgs.append([{"role": "user", "content": [{"type": "image", "image": np.asarray(frames[b1])}, {"type": "image", "image": np.asarray(frames[b2])},
                                                      {"type": "text", "text": PROMPT.format(sub=(c["text"] or "(없음)")[:200])}]}])
        for i in range(0, len(msgs), 8):
            for c, o in zip(pick[i:i + 8], g(msgs[i:i + 8], max_new=60)):
                o = o.strip().strip('"「」').splitlines()[0] if o.strip() else ""
                if o and "SKIP" not in o.upper() and re.search(r"(장면|화면)$", o):
                    out.append({"query": o, "yid": y, "gt": [[c["start"], c["end"]]], "from": "시연용 화면 묘사(생성)"})
        print(y, len([x for x in out if x["yid"] == y]), flush=True)
    (ROOT / "docs/service/pinpoint_generated.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"→ {len(out)}개")


if __name__ == "__main__":
    main()
