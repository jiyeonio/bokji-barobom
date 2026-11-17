"""복지바로봄 API (frontend/src/data/types.ts 모양).

  GET /api/welfare/search?q=&policy=   → SearchResponse (기본 결과 바로, n3_vlm이면 status 'pending' + jobId)
  GET /api/welfare/search/{jobId}      → 같은 모양, VLM 확인 뒤 순서·verification 갱신 (프론트가 폴링)
  GET /api/videos/{videoId}?jobId=&t=  → VideoDetail (policy·docs·officialSteps·chapters·subtitles)
  GET /api/welfare/health              → 방식·영상 수

검색 방식은 환경변수 SEARCH_MODEL (n3_vlm 기본 / n3). main 방식은 기존 /api/search 라우터를 씀.
"""
import json, os, threading, time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

ROOT = Path(__file__).resolve().parents[2]
STEPS_DIR = ROOT / "backend/data/steps"
CHAPTERS_DIR = ROOT / "backend/data/chapters"
NOTICE = {
    "time_sensitive": "신청 기간·지금 신청 가능 여부는 영상에 나온 내용이 아니라 공식 정보로 확인해야 해요. 영상에는 해당 내용이 없어요, 공식 정보를 확인하세요.",
    "vlm_no_answer": "영상에는 해당 내용이 없어요, 공식 정보를 확인하세요.",
}
STEP_TITLES = {1: "지원 조건 확인", 2: "서류 준비", 3: "신청서 작성", 4: "결과 확인"}
STEP_SHORT = {1: "자격 확인", 2: "서류 준비", 3: "신청서 작성", 4: "결과 확인"}
CIRCLED = "①②③④⑤⑥⑦⑧"

_searcher = None
_lock = threading.Lock()


def searcher():
    global _searcher
    with _lock:
        if _searcher is None:
            from welfare_service import Searcher
            _searcher = Searcher(os.environ.get("SEARCH_MODEL", "n3_vlm"))
    return _searcher


def fmt(sec):
    sec = int(sec); return f"{sec // 60:02d}:{sec % 60:02d}"


_EASY = None


def easy_for(pid):
    """「쉬운 말로 보기」: 자동 검사(숫자·내용) 통과 + 검토 ok인 항목만 (backend/data/easy_text.json)."""
    global _EASY
    if _EASY is None:
        f = ROOT / "backend/data/easy_text.json"
        _EASY = json.loads(f.read_text())["policies"] if f.exists() else {}
    return {k: v["easy"] for k, v in _EASY.get(pid, {}).items() if v.get("ok") and v.get("review", {}).get("verdict") == "ok"}


def public_policy(p):
    keep = ["policyId", "name", "category", "target", "targetDetail", "criteria", "benefit", "applyMethod", "applyWhen", "contact",
            "agency", "applyUrl", "officialUrls", "amount", "source", "sourceIds", "baseYear", "updatedAt", "fetchedAt", "requiredDocsNotes"]
    return {k: p.get(k) for k in keep} | {"requiredDocs": [d["name"] for d in p.get("requiredDocs", [])], "easy": easy_for(p["policyId"])}


def first_sentence(t):
    """자막에서 첫 문장 한 줄 (화면에서 한 줄 말줄임)."""
    import re as _re
    t = (t or "").strip()
    m = _re.match(r"(.+?[.?!])(\s|$)", t)
    return (m.group(1) if m else t).strip()


def label_of(s, yid, span):
    t = s.ws.subtitle_text(yid, span, limit=60).strip()
    return t if t else "화면 장면"


_fresh_cache = {}


def video_warnings(s, yid):
    """영상 정보 최신성 경고 (영상이 연결된 정책 기준, 자막에서만). 영상마다 한 번 계산해 둠."""
    if yid not in _fresh_cache:
        from freshness import check_video
        from welfare_service import POLICIES, policy_of
        c = s.ws.catalog[yid]
        _fresh_cache[yid] = check_video(POLICIES.get(policy_of(c["policy_hint"])), s.ws.video(yid)["segs"], c["published"])
    return _fresh_cache[yid]


def scene_results(s, out):
    from freshness import overlapping
    cat = s.ws.catalog; res = []
    for v in out["videos"]:
        y = v["youtubeId"]; c = cat[y]; top = v["top"]; ver = v["verification"]
        res.append({
            "videoId": y, "youtubeVideoId": y, "title": c["title"], "publisher": c["channel"], "publishedAt": c["published"],
            "duration": fmt(c["duration_sec"]), "thumbnailUrl": f"https://i.ytimg.com/vi/{y}/hqdefault.jpg",
            "formStart": bool(v.get("formStart")), "formMap": (CHAPTERS_DIR.parent / "form_maps" / f"{y}.json").exists(),
            "found": {"start": top[0][0], "end": top[0][1], "label": label_of(s, y, top[0]), "verification": ver[0],
                      "warnings": overlapping(video_warnings(s, y), top[0][0], top[0][1])},
            "otherScenes": [{"start": sp[0], "end": sp[1], "label": label_of(s, y, sp), "verification": ver[i + 1] if i + 1 < len(ver) else "none",
                             "warnings": overlapping(video_warnings(s, y), sp[0], sp[1])}
                            for i, sp in enumerate(top[1:3])],
        })
    for v in out.get("related", []):   # 같은 정책의 관련 영상 (장면 확인 없음 → 화면에는 「관련 영상」으로)
        y = v["youtubeId"]; c = cat[y]; sp = v["top"][0]
        res.append({"videoId": y, "youtubeVideoId": y, "title": c["title"], "publisher": c["channel"], "publishedAt": c["published"],
                    "duration": fmt(c["duration_sec"]), "thumbnailUrl": f"https://i.ytimg.com/vi/{y}/hqdefault.jpg", "related": True,
                    "found": {"start": sp[0], "end": sp[1], "label": label_of(s, y, sp), "verification": "none"}, "otherScenes": []})
    return res


def step_cards(s, pid, yid=None):
    """정책의 단계 카드 버튼: 그 정책에 연결된 영상(검색 후보에서 뺀 영상 포함)의 단계마다 처음 나오는 카드.
    yid를 주면(검색 결과 1위 영상) 그 영상의 단계만 — 없으면 빈 목록(다른 영상 시간을 보여 주지 않음)."""
    from welfare_service import policy_of
    if not pid:
        return []
    out = {}
    for y, c in s.ws.catalog.items():
        if policy_of(c["policy_hint"]) != pid or (yid and y != yid):
            continue
        st = steps_file(y)
        for ch in sorted((st or {}).get("chapters", []), key=lambda x: x["start"]):
            k = ch.get("step")
            if k and k not in out and (st.get("status") == "reviewed" or ch.get("confident")):
                out[k] = {"step": k, "label": f"{CIRCLED[k - 1]} {STEP_SHORT[k]}", "videoId": y, "start": ch["start"], "end": ch["end"],
                          "title": ch.get("title", ""), "videoTitle": c["title"]}
    return [out[k] for k in sorted(out)]


def response(s, out):
    from welfare_service import POLICIES, policy_chips
    pol = [public_policy(POLICIES[out["policyId"]])] if out["policyId"] else ([out["dbPolicy"]] if out.get("dbPolicy") else [])
    return {"query": out["query"], "policies": pol, "scenes": scene_results(s, out), "jobId": out["jobId"], "status": out["status"],
            "official": out["official"], "notice": {"show": bool(out["noAnswerInVideo"]), "reason": out.get("noticeReason"),
                                                    "message": NOTICE.get(out.get("noticeReason") or "", "")},
            "noVideo": out.get("noVideo", False), "model": s.mode, "timing": out["timing"],
            "stepCards": step_cards(s, out["policyId"], out["videos"][0]["youtubeId"] if out["videos"] else None),
            "chips": policy_chips(out["policyId"]) if out["policyId"] else (policy_chips(name=out["dbPolicy"]["name"]) if out.get("dbPolicy") else [])}


def steps_file(yid):
    f = STEPS_DIR / f"{yid}.json"
    return json.loads(f.read_text()) if f.exists() else None


def fill_gaps(chs, dur):
    """장면 사이 빈 곳을 「그 밖의 부분」으로 채워 영상 전체를 덮음 (지금 위치 찾기용)."""
    chs = sorted(chs, key=lambda c: c["start"]); out = []; t = 0.0; g = 0
    for c in chs:
        if c["start"] > t + 1:
            g += 1; out.append({"id": f"gap{g}", "start": t, "end": c["start"], "title": "그 밖의 부분", "short": "", "step": None,
                                "stepLabel": "", "verification": "none", "subtitle": "", "screenTitle": "", "relatedDocs": [], "gap": True})
        out.append(c); t = max(t, c["end"])
    if t < dur - 1:
        out.append({"id": f"gap{g + 1}", "start": t, "end": dur, "title": "그 밖의 부분", "short": "", "step": None, "stepLabel": "",
                    "verification": "none", "subtitle": "", "screenTitle": "", "relatedDocs": [], "gap": True})
    return out


_rag = None


def rag_index(s):
    """RAG 청크 인덱스(서비스의 파인튜닝 MiniLM을 같이 씀, 처음 한 번)."""
    global _rag
    if _rag is None:
        import rag
        _rag = rag.RagIndex(s.ws.minilm)
    return _rag


def create_welfare_router() -> APIRouter:
    r = APIRouter()

    @r.get("/api/welfare/health")
    def health():
        s = searcher(); return {"model": s.mode, "videos": len(s.ws.catalog)}

    @r.get("/api/welfare/search")
    def search(q: str, policy: str | None = None):
        q = q.strip()
        if not q:
            raise HTTPException(400, "검색어가 비어 있어요")
        s = searcher(); out = s.start(q, policy)
        return response(s, out)

    @r.get("/api/welfare/search/{job_id}")
    def search_job(job_id: str):
        s = searcher(); out = s.job(job_id)
        if not out:
            raise HTTPException(404, "검색 결과가 만료됐어요. 다시 검색해 주세요")
        return response(s, out)

    @r.get("/api/videos/{video_id}")
    def video(video_id: str, jobId: str | None = None, t: float | None = None, e: float | None = None, policy: str | None = None):
        """찾은 장면 = 사용자가 누른 장면(t~e)이 항상 우선. 이 검색의 다른 장면, 단계 카드는 그와 겹치지 않을 때만 타임라인에 넣음
        (타임라인 장면이 서로 겹치지 않게). 오른쪽 공식 신청 단계는 단계 카드 파일에서 바로 만듦."""
        from welfare_service import POLICIES, policy_chips, policy_of
        s = searcher(); cat = s.ws.catalog
        if video_id not in cat:
            raise HTTPException(404, "시연 영상 목록에 없는 영상이에요")
        c = cat[video_id]; dur = float(c["duration_sec"])
        job = s.job(jobId) if jobId else None
        # 영상의 정책은 그 영상에 연결된 정책이 먼저 (검색 정책과 다를 수 있음)
        pid = policy_of(c["policy_hint"]) or (job or {}).get("policyId") or policy
        p = POLICIES.get(pid)
        st = steps_file(video_id)
        v = next((x for x in (job or {}).get("videos", []) if x["youtubeId"] == video_id), None)
        tops = [(tuple(sp), (v["verification"][i] if v and i < len(v["verification"]) else "none")) for i, sp in enumerate((v or {}).get("top", [])[:3])]

        def scene(cid, sp, short, label, ver):
            return {"id": cid, "start": sp[0], "end": sp[1], "title": first_sentence(s.ws.subtitle_text(video_id, sp, 200)) or "화면 장면",
                    "short": short, "step": None,
                    "stepLabel": label, "verification": ver, "subtitle": s.ws.subtitle_text(video_id, sp, 120), "screenTitle": "", "relatedDocs": []}

        cands = []   # 우선순위 순
        if t is not None:
            if e is None or e <= t:   # 끝을 모르면: 이 검색 결과 중 시작이 같은 장면, 없으면 그 시간의 자막 문장들
                hit = next((sp for sp, _ in tops if abs(sp[0] - t) < 0.6), None)
                if hit:
                    e = hit[1]
                else:
                    segs_ = s.ws.video(video_id)["segs"]
                    near = [x for x in segs_ if x["end_time"] > t and x["start_time"] < t + 12]
                    e = min(dur, max([x["end_time"] for x in near] + [t + 6]))
            ver = next((vv for sp, vv in tops if abs(sp[0] - t) < 0.6), "none")
            cands.append(scene("found1", (t, e), "찾은 장면" if job else "고른 장면", "찾은 장면" if job else "고른 장면", ver))
        for i, (sp, ver) in enumerate(tops):
            cands.append(scene(f"found{i + 1}" if t is None and i == 0 else f"other{i + 1}", sp,
                               "찾은 장면" if t is None and i == 0 else "다른 장면", "찾은 장면" if t is None and i == 0 else "다른 장면", ver))
        # 「확인 안 됨」인 다른 장면은 목록에서 뺌(찾은 장면은 누른 장면이라 남김)
        cands = [ch for ch in cands if ch["id"] == "found1" or ch["verification"] in ("screen", "subtitle")]
        if st:   # 단계 카드: 검수된 파일은 그대로, 검수 안 된 파일은 자동 확인 통과(confident) 단계만. 제목은 「① 자격 확인」처럼 단계 이름
            for ch in sorted(st["chapters"], key=lambda x: x["step"] or 9):
                if st.get("status") != "reviewed" and not ch.get("confident"):
                    continue
                k = ch.get("step")
                # 자동 장면 나누기에서 온 단계 카드는 같은 단계가 여러 장면일 수 있어 장면 제목을 붙임(예: ③ 신청서 작성 · 배우자 정보 입력)
                detail = f" · {ch['title']}" if st.get("source") == "make_chapters" and ch.get("title") else ""
                cands.append(dict(ch) | ({"title": f"{CIRCLED[k - 1]} {STEP_SHORT[k]}{detail}", "short": STEP_SHORT[k]} if k else {}))
        chf = CHAPTERS_DIR / f"{video_id}.json"   # 자동 장면 나누기(제목만, 가장 낮은 우선순위 — 위 장면과 겹치지 않는 곳만)
        if chf.exists():
            for i, ch in enumerate(json.loads(chf.read_text())["chapters"]):
                cands.append({"id": f"c{i}", "start": ch["start"], "end": ch["end"], "title": ch["title"], "short": ch["title"][:8],
                              "step": None, "stepLabel": "장면", "verification": "none", "subtitle": s.ws.subtitle_text(video_id, (ch["start"], ch["end"]), 120),
                              "screenTitle": "", "relatedDocs": []})
        chapters = []
        for ch in cands:   # 앞(우선) 장면과 겹치면 넣지 않음
            if all(min(ch["end"], k["end"]) - max(ch["start"], k["start"]) <= 0.5 for k in chapters):
                chapters.append(ch)
        chapters = fill_gaps(chapters, dur)
        matched = next((ch for ch in chapters if ch["id"] == "found1"), None) or next((ch for ch in chapters if not ch.get("gap")), chapters[0])
        steps_map = {}
        for ch in sorted((st or {}).get("chapters", []), key=lambda x: x["start"]):   # 같은 단계가 여러 장면이면 처음 나오는 장면
            if ch.get("step") and ch["step"] not in steps_map and ((st or {}).get("status") == "reviewed" or ch.get("confident")):
                steps_map[ch["step"]] = ch
        official_steps = [{"step": k, "title": STEP_TITLES[k],
                           "note": {1: (p or {}).get("target", ""), 2: f"구비서류 {len((p or {}).get('requiredDocs', []))}가지",
                                    3: (p or {}).get("applyMethod", "")[:80], 4: f"문의 {(p or {}).get('contact', '')}"}[k],
                           **({"videoAt": steps_map[k]["start"]} if k in steps_map else {}),
                           "verification": steps_map[k]["verification"] if k in steps_map else "none"} for k in (1, 2, 3, 4) if k in steps_map]
        segs = s.ws.video(video_id)["segs"]
        return {"videoId": video_id, "youtubeVideoId": video_id, "title": c["title"], "publisher": c["channel"], "publishedAt": c["published"],
                "durationSec": dur, "query": (job or {}).get("query", ""), "matchedChapterId": matched["id"], "chapters": chapters,
                "policy": public_policy(p) if p else None,
                "docs": [{"id": d["id"], "name": d["name"]} for d in (p or {}).get("requiredDocs", [])],
                "officialSteps": official_steps, "stepsStatus": (st or {}).get("status"),
                "subtitles": [{"start": x["start_time"], "end": x["end_time"], "text": x["text"].strip()} for x in segs],
                "freshness": video_warnings(s, video_id), "chips": policy_chips(pid) if p else [],
                "formMap": (ROOT / "backend/data/form_maps" / f"{video_id}.json").exists()}

    # ---------- AI 답변 (RAG, Claude API) ----------
    @r.post("/api/rag/answer")
    async def rag_answer(request: Request):
        """{question, policyId?, videoId?, t?} → 공공데이터 청크 top-5로만 답한 문장(문장마다 근거 청크 ID) + 공식 URL·기준일.
        질문은 Anthropic API로 전송됨(화면에 안내). 답변·질문을 따로 저장하지 않음."""
        import asyncio
        from welfare_service import match_policy
        body = await request.json()
        q = (body.get("question") or "").strip()
        if not q or len(q) > 300:
            raise HTTPException(400, "질문을 300자 안으로 입력해 주세요")
        s = searcher()
        ix = rag_index(s)
        rag_pols = {c["policy_id"] for c in ix.chunks}
        pid = body.get("policyId") if body.get("policyId") in rag_pols else None
        pid = pid or (lambda x: x if x in rag_pols else None)(match_policy(q))
        with s.ws.lock:
            hits = ix.search(q, 5, pid)
        video = None
        y = body.get("videoId")
        if y and y in s.ws.catalog:
            c = s.ws.catalog[y]; t = float(body.get("t") or 0)
            segs = [x["text"].strip() for x in s.ws.video(y)["segs"] if t - 45 <= x["start_time"] <= t + 45]
            warn = [f"(영상 {int(w['start'])//60}:{int(w['start'])%60:02d}) {w['claim']}" for w in video_warnings(s, y)]
            video = {"title": c["title"], "published": c["published"], "text": " ".join(segs)[:1500] + ("\n영상 속 금액: " + " / ".join(warn) if warn else "")}
        import rag
        out = await asyncio.to_thread(rag.generate, q, hits, video, "rag")
        return out | {"question": q, "policyId": pid, "retrieved": [{"chunkId": h["chunk_id"], "field": h["field"], "policyName": h["policy_name"],
                                                                     "score": h["score"], "text": h["text"][:200]} for h in hits]}

    @r.get("/api/suggest")
    def suggest():
        from welfare_service import SUGGEST_HOME
        return {"home": SUGGEST_HOME}

    # ---------- 통합 정책 검색 DB (행정안전부 공공서비스(혜택), 개인·가구 대상) ----------
    @r.get("/api/policies/meta")
    def policies_meta():
        from policy_db import db
        d = db()
        if not d.ok:
            raise HTTPException(503, "정책 DB가 아직 없어요 (backend/scripts/build_policy_db.py)")
        return {"meta": d.meta, "regions": d.regions, "audiences": d.meta.get("audienceLabels", {})}

    @r.get("/api/policies/search")
    def policies_search(q: str = "", audience: str | None = None, sido: str | None = None, sigungu: str | None = None,
                        nationwide: bool = True, page: int = 1, size: int = 20):
        from policy_db import db
        from welfare_service import policy_of
        d = db()
        if not d.ok:
            raise HTTPException(503, "정책 DB가 아직 없어요")
        res = d.search(q, audience or None, sido or None, sigungu or None, nationwide, max(1, page), min(max(1, size), 50))
        vids = {}
        for y, c in searcher().ws.catalog.items():
            pid = policy_of(c["policy_hint"])
            if pid:
                vids[pid] = vids.get(pid, 0) + 1
        for it in res["items"]:
            it["videos"] = vids.get(it["curated"], 0) if it["curated"] else 0
        return res | {"source": d.meta.get("source"), "fetchedAt": d.meta.get("fetchedAt")}

    @r.get("/api/policies/item/{sid}")
    def policy_item(sid: str):
        from policy_db import db
        from welfare_service import POLICIES, policy_chips, policy_of
        d = db(); p = d.as_policy(sid) if d.ok else None
        if not p:
            raise HTTPException(404, "정책을 찾지 못했어요")
        x = d.detail(sid); cur = x["curated"]
        s = searcher()
        videos = [{"videoId": y, "title": c["title"], "publisher": c["channel"], "publishedAt": c["published"], "duration": fmt(c["duration_sec"]),
                   "thumbnailUrl": f"https://i.ytimg.com/vi/{y}/hqdefault.jpg"} for y, c in s.ws.catalog.items() if cur and policy_of(c["policy_hint"]) == cur]
        return {"policy": p, "raw": {k: x["detail"].get(k) or x["list"].get(k) for k in
                                     ["서비스목적", "지원대상", "선정기준", "지원내용", "지원유형", "신청방법", "신청기한", "구비서류", "본인확인필요구비서류",
                                      "공무원확인구비서류", "접수기관명", "문의처", "전화문의", "법령"]},
                "curatedPolicyId": cur, "curatedName": POLICIES[cur]["name"] if cur in POLICIES else None, "videos": videos,
                "stepCards": step_cards(s, cur), "chips": policy_chips(cur) if cur else policy_chips(name=p["name"]),
                "chipCtx": cur or f"db:{sid}"}

    # ---------- 신청서 지도 · 내 신청서 비추기 ----------
    @r.get("/api/forms/map/{video_id}")
    def form_map_api(video_id: str):
        from form_align import form_map
        m = form_map(video_id)
        if not m:
            raise HTTPException(404, "이 영상의 신청서 지도가 없어요")
        return m

    @r.post("/api/forms/align")
    async def form_align_api(request: Request):
        """사진(본문 그대로, image/*)을 등록된 빈 서식에 겹쳐 칸 위치를 돌려줌. 사진은 메모리에서만 처리하고 저장·기록하지 않음."""
        from form_align import align
        data = await request.body()
        if not data or len(data) > 12 * 1024 * 1024:
            raise HTTPException(400, "사진이 없거나 너무 커요(12MB 이하)")
        try:
            return align(data)
        finally:
            del data

    @r.get("/api/agency/report")
    def agency_report():
        """기관용 안내 공백 리포트: ① 영상·공공데이터 모두 답 없던 질문(검색 기록 + 평가 사례) ② 오래된 정보 경고가 뜬 영상 ③ 장면 목록만 있고 단계 카드가 없는 영상."""
        import re
        from welfare_service import POLICIES, policy_of
        s = searcher(); cat = s.ws.catalog
        gaps = {}; need = []
        try:
            with s.log_lock:
                rows = s.log.execute("""SELECT query, policy_id, COUNT(*) FROM search_log
                                        WHERE (no_video=1 OR notice_reason='vlm_no_answer') AND official_items=0 AND policy_id NOT LIKE 'db:%'
                                        GROUP BY query, policy_id""").fetchall()
                # 통합 정책 DB에서 찾은 정책(영상 없음)을 물은 질문 → 「안내 영상이 필요한 정책」
                need = s.log.execute("""SELECT policy_id, COUNT(*), GROUP_CONCAT(DISTINCT query) FROM search_log
                                        WHERE policy_id LIKE 'db:%' GROUP BY policy_id ORDER BY COUNT(*) DESC LIMIT 30""").fetchall()
            for q, pid, n in rows:
                gaps[q] = {"query": q, "policy": POLICIES[pid]["name"] if pid in POLICIES else "", "count": n, "source": "검색 기록"}
        except Exception:
            pass
        need_video = []
        try:
            from policy_db import db
            d = db()
            for pid, n, qs in need:
                row = next((r for r in d.rows if r["id"] == pid[3:]), None)
                if row:
                    need_video.append({"policyId": pid[3:], "name": row["name"], "agency": row["agency"], "count": n, "queries": (qs or "").split(",")[:3]})
        except Exception:
            pass
        jf = ROOT / "ai/experiments/vlm_model/results/official_judgments_dev.json"
        if jf.exists():   # 평가에서 영상에 답이 없던 실제 사용자 질문 중 공공데이터로도 답하지 못한(없음·부분) 사례
            for j in json.loads(jf.read_text())["judgments"]:
                if j["combined_verdict"] in ("없음", "부분") and j["query"] not in gaps:
                    gaps[j["query"]] = {"query": j["query"], "policy": (j.get("services") or [{}])[0].get("name", ""), "count": None,
                                        "source": "평가 사례", "reason": j["reason"], "verdict": j["combined_verdict"]}
        theme = lambda q: "가족 대리 신청" if re.search(r"대신|대리|엄마|아빠|남편|아내|부모님|손주", q) else ("화면 위치" if re.search(r"화면|어디서 눌", q) else "기타")  # noqa: E731
        gap_list = sorted(({**g, "theme": theme(g["query"])} for g in gaps.values()), key=lambda g: (g["theme"] != "가족 대리 신청", g["query"]))
        stale = []
        for y, c in cat.items():
            for w in video_warnings(s, y):
                stale.append({"videoId": y, "title": c["title"], "channel": c["channel"], "published": c["published"], "at": w["start"],
                              "claim": w["claim"], "current": w["current"], "policy": w["policyName"], "updatedAt": w["updatedAt"]})
        nosteps = []
        for y, c in cat.items():
            st = steps_file(y)
            shown = [ch for ch in (st or {}).get("chapters", []) if (st or {}).get("status") == "reviewed" or ch.get("confident")]
            if not shown:
                pid = policy_of(c["policy_hint"])
                nosteps.append({"videoId": y, "title": c["title"], "channel": c["channel"], "policy": POLICIES[pid]["name"] if pid in POLICIES else "",
                                "durationSec": c["duration_sec"], "chapters": len(json.loads((CHAPTERS_DIR / f"{y}.json").read_text())["chapters"]) if (CHAPTERS_DIR / f"{y}.json").exists() else 0})
        nosteps.sort(key=lambda x: (x["policy"] == "", -x["durationSec"]))
        form_gaps = []
        for f in sorted((ROOT / "backend/data/form_maps").glob("*.json")):
            m = json.loads(f.read_text())
            for x in m["fields"]:
                if not x["videoExplained"]:
                    form_gaps.append({"form": m["form"]["title"], "videoId": m["video"], "videoTitle": cat.get(m["video"], {}).get("title", ""),
                                      "page": x["page"], "section": x["section"], "label": x["label"],
                                      "official": (x["write"] or {}).get("label") if (x["write"] or {}).get("source") == "official" else None,
                                      "sectionGuide": x.get("sectionGuide")})
        return {"generatedAt": time.strftime("%Y-%m-%d %H:%M"), "videos": len(cat), "formGaps": form_gaps,
                "summary": {"gaps": len(gap_list), "familyProxy": sum(g["theme"] == "가족 대리 신청" for g in gap_list), "stale": len(stale), "noSteps": len(nosteps), "needVideo": len(need_video), "formGaps": len(form_gaps)},
                "gaps": gap_list, "stale": stale, "noSteps": nosteps, "needVideo": need_video}

    return r
