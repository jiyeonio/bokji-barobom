"""시연 질문·추천 질문 후보 결과를 미리 계산해 캐시(서비스 속도 개선, 2026-11-15). 지금 서비스 설정(n3_vlm, 실시간 VLM 배지)으로 계산.

질문: 시연 질문 8개(오프닝 4, 신청 기간, 장면 콕 집기 #1·#7·#9) + 장면 콕 집기 후보(docs/service/pinpoint_candidates.json) + 시연 정책 4개의 추천 질문 칩.
    python backend/scripts/precompute_cache.py   (GPU — API 서버를 내린 뒤, 캐시 DB: <WELFARE_DATA_DIR>/demo/scene_info.sqlite)
"""
import copy, json, os, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "backend/services")]
os.environ["BADGE_MODE"] = "vlm"; os.environ["QUERY_CACHE"] = "on"
from welfare_service import Searcher, policy_chips

DEMO = [("기초연금 신청할 때 뭐 챙겨가야 돼요?", None), ("기초연금 신청하는 법", None), ("월세 지원 받으려면 뭐 내야 돼요?", None),
        ("아이돌봄 어디서 신청해요?", None), ("이거 아직 신청 되는 거예요?", "basic-pension"),
        ("고유식별정보 민감정보 수집 이용 동의 체크하는 화면", None), ("아이돌봄서비스 홈페이지에 '정기이용신청' 버튼 클릭하는 장면", None),
        ("노인성 질병 종류와 질병코드 표", None)]
CHIP_POLICIES = ["basic-pension", "child-care", "youth-rent", "long-term-care"]   # 시연 정책
# 신청서 작성 질문(홈 검색 기본 질문 포함) — 신청서 지도가 있는 영상이 1위로 오는 규칙(welfare_service.FORM_INTENT)
FORM_QS = ["기초연금 신청서 어떻게 써요?", "기초연금 신청서 작성 방법", "기초연금 신청서 쓰는 법", "신청서 어떻게 작성해요"]


def main():
    s = Searcher("n3_vlm")
    qs = DEMO + [(c["query"], None) for c in json.loads((ROOT / "docs/service/pinpoint_candidates.json").read_text())]
    qs += [(c, pid) for pid in CHIP_POLICIES for c in policy_chips(pid)]
    qs += [(q, None) for q in FORM_QS]   # 정책 화면 추천 질문 칩(정책 맥락 함께)
    seen = set(); n = 0
    for q, ctx in qs:
        if (q, ctx) in seen:
            continue
        seen.add((q, ctx))
        out = s.base(q, ctx); out["jobId"] = "precompute"; s.jobs["precompute"] = out
        s._verify("precompute")
        res = copy.deepcopy(out); res.pop("jobId", None)
        s.cache.put(s.cache.key(q, ctx, s.opts, s.mode), q, ctx, res); n += 1
        v = res["videos"][0] if res["videos"] else None
        print(q[:30], "→", (v["youtubeId"], round(v["top"][0][0], 1), v["verification"][0]) if v else "-", flush=True)
    print(f"캐시 {n}개 (판 {s.cache.ver})")


if __name__ == "__main__":
    main()
