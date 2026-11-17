"""장면 정보 미리 만들기(서비스 속도 개선, 2026-11-15): 영상 등록(색인) 때 장면마다 VLM으로 화면 설명·화면 종류·화면 글자를 만들어 DB에 저장.
검색 때 이 정보로 「화면에서 확인됨 / 자막에서 확인됨」 배지를 바로 정하고, 애매할 때만 실시간 VLM(welfare_search.rejudge)을 씀.

- 장면 단위: 자막 덩어리(10~16초, lora_make_data.chunks_of와 같음). 자막이 없으면 12초씩.
- DB: <WELFARE_DATA_DIR>/demo/scene_info.sqlite, 표 scenes(youtube_id, start, end, screen_type, screen_text, description, subtitle, model, created_at)
- 이미 있는 영상은 건너뜀(--rebuild로 다시).

    python backend/scripts/build_scene_info.py [--only <id,...>] [--rebuild]   (GPU — API 서버를 내린 뒤)
"""
import argparse, json, os, sqlite3, sys, time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "ai/experiments/vlm_model")]
from lora_make_data import Gen, chunks_of, parse_json

D = Path(os.environ.get("WELFARE_DATA_DIR", "/nfs/team/data/scenefinder_vlm"))
IDX = D / "demo/index"
DB = D / "demo/scene_info.sqlite"
TYPES = ["신청서 작성", "서류 목록", "홈페이지·앱 화면", "안내 문구·표", "사람·대화", "기타"]
PROMPT = """복지 안내 영상의 한 장면입니다(이미지 2장: 앞부분, 뒷부분). 자막: {sub}

화면에 보이는 것만 보고 JSON 하나로 답하세요(자막 내용을 화면에 있다고 쓰지 마세요).
{{"screen_type": "{types} 중 하나",
 "screen_text": "화면에 쓰인 주요 글자(제목·버튼·칸 이름·서류 이름 등, 80자 이내, 없으면 빈 문자열)",
 "description": "화면이 어떤 모습인지 한 문장(40자 이내)"}}"""


def db():
    con = sqlite3.connect(DB)
    con.execute("""CREATE TABLE IF NOT EXISTS scenes (youtube_id TEXT, start REAL, end REAL, screen_type TEXT, screen_text TEXT,
                   description TEXT, subtitle TEXT, model TEXT, created_at TEXT)""")
    con.execute("CREATE INDEX IF NOT EXISTS scenes_vid ON scenes(youtube_id)")
    return con


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--only", default=""); ap.add_argument("--rebuild", action="store_true")
    a = ap.parse_args()
    con = db()
    done = {r[0] for r in con.execute("SELECT DISTINCT youtube_id FROM scenes")}
    cat = json.loads((ROOT / "backend/data/demo_videos.json").read_text())
    only = set(filter(None, a.only.split(",")))
    todo = [v for v in cat if (not only or v["youtube_id"] in only) and (a.rebuild or v["youtube_id"] not in done)]
    if not todo:
        print("할 영상 없음"); return
    g = Gen()
    for v in todo:
        y = v["youtube_id"]; t0 = time.time()
        subs = json.loads((IDX / y / "subs.json").read_text())["segments"]
        frames = np.load(IDX / y / "frames.npy", mmap_mode="r")
        chs = chunks_of(subs, float(v["duration_sec"]))
        msgs = []
        for c in chs:
            b = [min(len(frames) - 1, int((c["start"] + (c["end"] - c["start"]) * f) // 2)) for f in (1 / 3, 2 / 3)]
            msgs.append([{"role": "user", "content": [{"type": "image", "image": np.asarray(frames[i])} for i in b] +
                          [{"type": "text", "text": PROMPT.format(sub=(c["text"] or "(없음)")[:200], types=" / ".join(TYPES))}]}])
        outs = []
        for i in range(0, len(msgs), 8):
            outs += g(msgs[i:i + 8], max_new=120)
        con.execute("DELETE FROM scenes WHERE youtube_id=?", (y,))
        rows = []
        for c, o in zip(chs, outs):
            j = parse_json(o, "obj") or {}
            st = j.get("screen_type") if j.get("screen_type") in TYPES else "기타"
            rows.append((y, c["start"], c["end"], st, str(j.get("screen_text") or "")[:120], str(j.get("description") or "")[:80],
                         c["text"][:300], "Qwen/Qwen3-VL-4B-Instruct", time.strftime("%Y-%m-%d %H:%M")))
        con.executemany("INSERT INTO scenes VALUES (?,?,?,?,?,?,?,?,?)", rows); con.commit()
        print(f"{y} 장면 {len(rows)} ({time.time() - t0:.0f}초)", flush=True)
    print(f"→ {DB}")


if __name__ == "__main__":
    main()
