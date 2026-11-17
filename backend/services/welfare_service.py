"""복지바로봄 검색 조립: 정책 찾기 → 연결된 영상에서 장면 검색(N3) → (n3_vlm) VLM 재판별로 순서·verification 갱신 → 공식 정보 답.

- 정책 찾기: 질의에 정책 키워드가 있으면 그 정책, 없으면 요청의 policy(앞 화면 맥락), 둘 다 없으면 정책 없이 전체 영상
- 영상: 정책과 연결된 시연 영상(backend/data/demo_videos.json의 policy_hint → POLICY_OF_HINT). 정책이 없으면 전체.
- 영상 간 순서(검증 안 된 규칙): 기본 결과는 영상별 N3 1위의 자막 원점수(MiniLM 코사인) + 화면 원점수 순,
  VLM 확인 뒤에는 1위 장면의 P(답함) 순. 상위 MAX_VIDEOS개 영상만 VLM 확인.
- 공식 정보 답: 질문 의도(서류·기간·장소/방법·대상·금액)를 낱말로 나눠 정책 항목을 골라 보여줌.
- 「영상에 답 없음」 안내 (noAnswerInVideo, noticeReason):
  · time_sensitive: 신청 기간·지금 신청 가능 여부를 묻는 질문(의도 when)은 영상 장면과 관계없이 항상 안내.
    영상의 기간 안내는 게시 당시 기준이라, 제안서 원칙(신청 자격·기간은 최신 공식 정보를 근거로)대로 공식 정보로 답함.
  · vlm_no_answer: VLM 확인 뒤 보이는 장면이 모두 「확인 안 됨」(검증 안 된 규칙, dev에서 맞추지 않음).
"""
import copy, hashlib, json, os, re, sqlite3, threading, time, uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
POLICIES = {p["policyId"]: p for p in json.loads((ROOT / "backend/data/policies.json").read_text())}
POLICY_OF_HINT = {"기초연금": "basic-pension", "아이돌봄": "child-care", "청년주거": "youth-rent", "주거급여": "housing-benefit",
                  "장기요양": "long-term-care", "노인일자리": "senior-jobs", "치매": "dementia-screening", "에너지바우처": "energy-voucher"}


def policy_of(hint):
    """시연 목록의 policy_hint → 정책 ID (예전 표기 키 또는 정책 ID 그대로)."""
    return POLICY_OF_HINT.get(hint) or (hint if hint in POLICIES else None)


MAX_VIDEOS = 3          # VLM으로 확인하는 영상 수
MAX_RELATED = 2         # 같은 정책의 영상을 「관련 영상」으로 더 보여 줌(확인 안 함)

INTENTS = [   # (의도, 정규식, 보여 줄 정책 항목)
    ("docs", r"서류|챙겨|준비물|가져가|내야|제출|필요한 거|뭐 내|뭘 내", ["requiredDocs"]),
    ("when", r"언제|기간|아직|마감|지금도|신청 되|신청돼|되는 거|접수", ["applyWhen", "updatedAt"]),
    ("where", r"어디|어떻게 신청|신청하는 법|신청 방법|신청방법|신청해요|신청하나요", ["applyMethod", "applyUrl"]),
    ("who", r"누가|대상|자격|받을 수|해당|조건", ["targetDetail", "criteria"]),
    ("amount", r"얼마|금액|받는 돈|지원금", ["amount", "benefit"]),
]


# 신청서 작성 의도(2026-11-15): 정책이 정해지고 그 정책 영상 중 신청서 지도(backend/data/form_maps)가 있으면 그 영상을 1위로,
# 장면은 신청서 설명 시작(form map videoRange[0])으로 고정 → 카드를 누르면 「내 신청서 비추기」 탭이 열림
FORM_INTENT = re.compile(r"신청서.{0,6}(작성|쓰|써|기입|적는|적어|채우)|(작성|쓰는|써|채우).{0,6}신청서|서식.{0,6}(작성|쓰|써)")
FORM_MAPS = ROOT / "backend/data/form_maps"


def form_start(y):
    f = FORM_MAPS / f"{y}.json"
    if not f.exists():
        return None
    m = json.loads(f.read_text()); s0 = float(m["videoRange"][0])
    nxt = sorted(x["scene"]["start"] for x in m["fields"] if x["scene"]["start"] > s0 + 5)
    return (s0, float(nxt[0]) if nxt else s0 + 20)


RULES = json.loads((ROOT / "backend/data/query_rules.json").read_text())
# 사용자 말투 질문 강화 설정 (docs/service/query_robustness_plan.md). 모두 끄면(기본) 지금까지와 같은 결과.
#   policy: keyword(정책 키워드만) | alias(+별칭) | alias+sim(+MiniLM 유사도, 임계값은 dev로 정함)
#   rewrite: none | rules(규칙 사전) | llm(Qwen3-VL-4B 바꿔쓰기)   step_first: 의도가 단계면 보여 줄 수 있는 단계 카드를 1순위로
DEFAULT_OPTS = {"policy": "keyword", "rewrite": "none", "step_first": False, "sim_threshold": None}


def match_policy(q, ctx=None, mode="keyword", sim=None):
    for pid, p in POLICIES.items():
        if any(k in q for k in p["keywords"]) or p["name"] in q:
            return pid
    if mode in ("alias", "alias+sim"):
        hits = {pid for pid, al in RULES["policy_aliases"].items() if pid in POLICIES and any(a in q for a in al)}
        if len(hits) == 1:
            return hits.pop()
    if mode == "alias+sim" and sim:
        pid = sim(q)
        if pid:
            return pid
    return ctx if ctx in POLICIES else None


def rule_rewrites(q, pid):
    out = []
    for r in RULES["rewrite_rules"]:
        if re.search(r["pattern"], q):
            for ph in r["phrases"]:
                c = f"{POLICIES[pid]['name']} {ph}" if pid else ph
                if c not in out and c != q:
                    out.append(c)
    return out[:RULES["rewrite_max"]]


def step_intent(q):
    for k, pat in RULES["step_first"]["intents"].items():
        if re.search(pat, q):
            return int(k)
    return None


def span_iou(a, b):
    i = max(0.0, min(a[1], b[1]) - max(a[0], b[0])); u = max(a[1], b[1]) - min(a[0], b[0])
    return i / u if u > 0 else 0.0


def rrf(lists, k=60, merge=0.5):
    """여러 질문(원래 + 바꾼 질문)의 후보 순위를 합침: 점수 = Σ 가중치 / (k + 순위). 겹치는(IoU ≥ merge) 구간은 같은 후보."""
    cands = []
    for w, top in lists:
        for r, sp in enumerate(top):
            for c in cands:
                if span_iou(c["span"], sp) >= merge:
                    c["score"] += w / (k + r + 1); break
            else:
                cands.append({"span": tuple(sp), "score": w / (k + r + 1)})
    return [c["span"] for c in sorted(cands, key=lambda c: -c["score"])]


def intents(q):
    return [name for name, pat, _ in INTENTS if re.search(pat, q)]


def official_answer(pid, q, p=None):
    if not pid:
        return None
    p = p or POLICIES[pid]; out = []
    for name, pat, fields in INTENTS:
        if re.search(pat, q):
            for f in fields:
                if p.get(f):
                    out.append({"intent": name, "field": f, "value": p[f]})
    return {"policyId": pid, "items": out, "source": p["source"], "baseYear": p["baseYear"], "updatedAt": p["updatedAt"],
            "fetchedAt": p["fetchedAt"]}


# 추천 질문 칩 (2026-11-15). 검색창 아래: 시연·캐시된 질문(바로 나옴). 정책 화면: 정책 이름 + 질문 틀(서류·방법·대상·기간 — INTENTS와 같은 낱말)
SUGGEST_HOME = ["기초연금 신청할 때 뭐 챙겨가야 돼요?", "월세 지원 받으려면 뭐 내야 돼요?", "아이돌봄 어디서 신청해요?", "노인성 질병 종류와 질병코드 표"]
CHIP_TEMPLATES = ["{n} 신청할 때 필요한 서류", "{n} 신청 방법", "{n} 누가 받을 수 있어요?", "{n} 지금 신청 되나요?"]


def policy_chips(pid=None, name=None):
    n = POLICIES[pid]["keywords"][0] if pid in POLICIES else re.sub(r"\s*(지원사업|지원|사업)$", "", name or "")
    return [t.format(n=n) for t in CHIP_TEMPLATES] if n else []


class QueryCache:
    """시연 질문·추천 질문 결과 캐시(서비스 속도 개선, 2026-11-15). 키 = 질문 + 정책 맥락 + 설정 + 시연 목록·정책 정보 판(바뀌면 자동 무효)."""

    def __init__(self, path):
        self.con = sqlite3.connect(path, check_same_thread=False)
        self.con.execute("CREATE TABLE IF NOT EXISTS query_cache (key TEXT PRIMARY KEY, query TEXT, ctx TEXT, result TEXT, created_at TEXT)")
        ver = hashlib.sha1()
        for f in ("backend/data/demo_videos.json", "backend/data/policies.json"):
            ver.update((ROOT / f).read_bytes())
        self.ver = ver.hexdigest()[:12]
        self.lock = threading.Lock()

    def key(self, q, ctx, opts, mode):
        return hashlib.sha1(json.dumps([q.strip(), ctx or "", opts, mode, self.ver], ensure_ascii=False, sort_keys=True).encode()).hexdigest()

    def get(self, k):
        with self.lock:
            r = self.con.execute("SELECT result FROM query_cache WHERE key=?", (k,)).fetchone()
        return json.loads(r[0]) if r else None

    def put(self, k, q, ctx, out):
        with self.lock:
            self.con.execute("INSERT OR REPLACE INTO query_cache VALUES (?,?,?,?,?)", (k, q, ctx or "", json.dumps(out, ensure_ascii=False), time.strftime("%Y-%m-%d %H:%M")))
            self.con.commit()


class Searcher:
    """엔진(GPU)과 비동기 VLM 확인 작업을 관리."""

    def __init__(self, mode="n3_vlm", opts=None):
        from ai.features.welfare_search import WelfareSearch
        self.mode = mode
        self.opts = dict(DEFAULT_OPTS) | (opts or {})
        self.ws = WelfareSearch(use_vlm=(mode == "n3_vlm"))
        self.jobs = {}
        self.queue_lock = threading.Lock()
        self._pol_emb = None
        self._steps = {}
        # 서비스 속도 개선: BADGE_MODE=fast면 미리 만든 장면 정보로 배지를 바로 정하고 애매할 때만 실시간 VLM, QUERY_CACHE=on이면 캐시 사용
        self.badge_mode = os.environ.get("BADGE_MODE", "vlm")
        self.si = None
        if self.badge_mode == "fast":
            from ai.features.welfare_search import SceneInfo
            self.si = SceneInfo(self.ws.minilm)
        dbp = Path(os.environ.get("WELFARE_DATA_DIR", "/nfs/team/data/scenefinder_vlm")) / "demo/scene_info.sqlite"
        self.cache = QueryCache(dbp) if os.environ.get("QUERY_CACHE", "off") == "on" else None
        # 검색 기록(기관용 안내 공백 리포트): 질문과 결과 요약만 저장, 개인정보·접속 정보는 저장하지 않음
        self.log = sqlite3.connect(dbp, check_same_thread=False); self.log_lock = threading.Lock()
        self.log.execute("""CREATE TABLE IF NOT EXISTS search_log (ts TEXT, query TEXT, ctx TEXT, policy_id TEXT, no_video INTEGER,
                            notice_reason TEXT, official_items INTEGER, top_video TEXT, top_verification TEXT, cached INTEGER)""")

    # ---------- 정책 찾기: MiniLM 유사도 (키워드·별칭이 없을 때) ----------
    def policy_scores(self, q):
        from sentence_transformers import util
        if self._pol_emb is None:
            self._pol_ids = list(POLICIES)
            texts = [" ".join([POLICIES[p]["name"], POLICIES[p].get("target", "")] + RULES["policy_aliases"].get(p, [])) for p in self._pol_ids]
            self._pol_emb = self.ws.minilm.encode(texts, convert_to_tensor=True)
        sc = util.cos_sim(self.ws.minilm.encode(q, convert_to_tensor=True), self._pol_emb)[0].tolist()
        return sorted(zip(self._pol_ids, sc), key=lambda x: -x[1])

    def sim_policy(self, q):
        t = self.opts.get("sim_threshold")
        if t is None:
            return None
        sc = self.policy_scores(q)
        return sc[0][0] if sc[0][1] >= t and sc[0][1] - sc[1][1] >= RULES["policy_similarity"]["margin"] else None

    def find_policy(self, q, ctx=None, opts=None):
        o = opts or self.opts
        return match_policy(q, ctx, o["policy"], self.sim_policy if o["policy"] == "alias+sim" else None)

    def rewrites(self, q, pid, opts=None):
        o = opts or self.opts
        if o["rewrite"] == "rules":
            return rule_rewrites(q, pid)
        if o["rewrite"] == "llm" and self.ws.judge:
            out = self.ws.judge.generate([RULES["rewrite_llm_prompt"].format(q=q)])[0]
            lines = [re.sub(r"^[\s\-•·*\d.)]+", "", l).strip().strip('"「」') for l in re.split(r"[\n/]", out)]
            return [l for l in lines if l and l != q][:2]
        return []

    # ---------- 단계 카드 (검수 완료 또는 자동 확인 통과) ----------
    def step_span(self, y, k):
        if y not in self._steps:
            f = ROOT / "backend/data/steps" / f"{y}.json"
            st = json.loads(f.read_text()) if f.exists() else {}
            self._steps[y] = sorted([c for c in st.get("chapters", []) if c.get("step") and (st.get("status") == "reviewed" or c.get("confident"))],
                                    key=lambda c: c["start"])
        c = next((c for c in self._steps[y] if c["step"] == k), None)
        return (float(c["start"]), float(c["end"])) if c else None

    def rank_video(self, y, variants, encs, pin=None):
        """한 영상의 후보 순위: 질문이 하나면 N3 그대로, 여럿이면 RRF로 합침. pin(단계 카드 구간)이 있으면 1순위로."""
        lists, raw = [], 0.0
        for (v, w), (mq, qv) in zip(variants, encs):
            r = self.ws.n3(y, mq, qv); lists.append((w, r["top"])); raw = max(raw, r["raw_sub"] + r["raw_frame"])
        top = lists[0][1] if len(lists) == 1 else rrf(lists, RULES["fusion"]["k"], RULES["fusion"]["merge_iou"])[:5]
        if pin:
            top = [pin] + [t for t in top if span_iou(t, pin) < 0.5]
        return {"top": [tuple(t) for t in top[:5]], "raw": raw, "pinned": pin}

    def plan(self, q, ctx=None, opts=None):
        o = opts or self.opts
        pid = self.find_policy(q, ctx, o)
        rw = self.rewrites(q, pid, o)
        variants = [(q, RULES["fusion"]["w_original"])] + [(r, RULES["fusion"]["w_rewrite"]) for r in rw]
        k = step_intent(q) if o["step_first"] else None
        return pid, variants, k

    def videos_for(self, pid):
        cat = {y: v for y, v in self.ws.catalog.items() if v.get("in_search", True)}   # in_search=False: 영상 화면에서만 (index_demo.SEARCH_EXCLUDE)
        if pid:   # 정책을 찾았으면 그 정책에 연결된 영상만 (없으면 빈 목록 — 다른 정책 영상을 보여 주지 않음)
            return [y for y, v in cat.items() if policy_of(v["policy_hint"]) == pid]
        return list(cat)

    def db_policy(self, q, ctx):
        """시연 정책(15개)을 못 찾았을 때만: 정책 화면 맥락(db:서비스ID) 또는 질문이 통합 정책 DB의 중앙 서비스를 분명히 가리키면 그 서비스.
        시연 정책과 같은 서비스면 쓰지 않음(시연 정책 경로 그대로)."""
        from policy_db import db
        d = db()
        sid = ctx[3:] if ctx and ctx.startswith("db:") else d.strong_match(q)
        row = next((r for r in d.rows if r["id"] == sid), None) if sid else None
        return d.as_policy(sid) if row and not row["curated"] else None

    def base(self, q, ctx=None, opts=None):
        t0 = time.time()
        db_ctx = bool(ctx and ctx.startswith("db:"))   # 통합 정책 DB 정책 화면에서 온 질문은 그 정책이 먼저(예: 구미시 청년월세 → 국가 청년월세로 가지 않게)
        pid0 = None if db_ctx else self.find_policy(q, ctx, opts)
        dbp = self.db_policy(q, ctx) if not pid0 else None
        if dbp:   # 영상 없는 정책: 정책 정보 + 「영상 준비 중」 (장면 검색 안 함)
            return {"query": q, "ctx": ctx, "policyId": None, "dbPolicy": dbp, "intents": intents(q), "official": official_answer(dbp["policyId"], q, dbp),
                    "videos": [], "rewrites": [], "related": [], "otherVideos": [], "status": "done", "noVideo": True,
                    "noAnswerInVideo": True if "when" in intents(q) else None, "noticeReason": "time_sensitive" if "when" in intents(q) else None,
                    "timing": {"base_sec": round(time.time() - t0, 3)}}
        with self.ws.lock:
            pid, variants, k = self.plan(q, ctx, opts)
            encs = [self.ws.encode(v) for v, _ in variants]
            res = {y: self.rank_video(y, variants, encs, self.step_span(y, k) if k else None) for y in self.videos_for(pid)}
        order = sorted(res, key=lambda y: -res[y]["raw"])
        form_y = None
        if pid and FORM_INTENT.search(q):   # 신청서 작성 의도 → 신청서 지도가 있는 그 정책 영상을 1위, 신청서 설명 시작 장면으로
            form_y = next((y for y in order if form_start(y)), None)
            if form_y:
                sp = form_start(form_y)
                res[form_y]["top"] = [sp] + [t for t in res[form_y]["top"] if span_iou(t, sp) < 0.5][:4]
                res[form_y]["pinned"] = sp
                order = [form_y] + [y for y in order if y != form_y]
        no_video = bool(pid) and not res
        out = {"query": q, "ctx": ctx, "policyId": pid, "intents": intents(q), "official": official_answer(pid, q),
               "videos": [{"youtubeId": y, "top": res[y]["top"], "pinned": res[y]["pinned"], "formStart": y == form_y,
                           "verification": ["pending"] * 3 if self.mode == "n3_vlm" else ["none"] * 3} for y in order[:MAX_VIDEOS]],
               "rewrites": [v for v, _ in variants[1:]],
               "related": [{"youtubeId": y, "top": res[y]["top"]} for y in order[MAX_VIDEOS:MAX_VIDEOS + MAX_RELATED]] if pid else [],
               "otherVideos": order[MAX_VIDEOS:], "status": "pending" if self.mode == "n3_vlm" and not no_video else "done", "noVideo": no_video,
               "noAnswerInVideo": True if "when" in intents(q) else None,
               "noticeReason": "time_sensitive" if "when" in intents(q) else None, "timing": {"base_sec": round(time.time() - t0, 3)}}
        return out

    def start(self, q, ctx=None, opts=None):
        if self.cache and opts is None:
            hit = self.cache.get(self.cache.key(q, ctx, self.opts, self.mode))
            if hit:
                t0 = time.time()
                out = copy.deepcopy(hit); out["jobId"] = uuid.uuid4().hex[:12]; out["status"] = "done"
                out["timing"] = {"base_sec": round(time.time() - t0, 3), "cached": True}
                self.jobs[out["jobId"]] = out
                self.record(out, cached=True)
                return out
        out = self.base(q, ctx, opts)
        jid = uuid.uuid4().hex[:12]
        out["jobId"] = jid
        self.jobs[jid] = out
        if self.mode == "n3_vlm" and out["status"] == "pending":
            threading.Thread(target=self._verify, args=(jid,), daemon=True).start()
        else:
            self.record(out)
        return out

    def _verify(self, jid):
        out = self.jobs[jid]; t0 = time.time()
        try:
            with self.ws.lock:
                mq = self.ws.encode(out["query"])[0] if self.si else None
                for v in out["videos"]:
                    if self.si:   # 빠른 배지: 상위 3개를 모두 장면 정보로 정할 수 있으면 실시간 VLM 생략(순서는 N3 그대로)
                        dec = [self.si.decide(*self.si.scores(mq, v["youtubeId"], sp, self.ws.subtitle_text(v["youtubeId"], sp))) for sp in v["top"][:3]]
                        if all(dec):
                            v.update(verification=dec + ["none"] * (3 - len(dec)), badgeSource="scene_info"); continue
                    r = self.ws.rejudge(v["youtubeId"], out["query"], v["top"])
                    v["badgeSource"] = "vlm"
                    if v.get("pinned"):   # 단계 카드 1순위는 재판별 뒤에도 1순위로 유지
                        i = next(j for j, t in enumerate(r["top"]) if span_iou(t, v["pinned"]) > 0.99)
                        if i > 0:
                            for key in ("top", "p_answer"):
                                r[key].insert(0, r[key].pop(i))
                            if i < 3:
                                r["verification"].insert(0, r["verification"].pop(i)); r["p_screen"].insert(0, r["p_screen"].pop(i))
                            else:
                                r["verification"] = ["none"] + r["verification"][:2]; r["p_screen"] = [0.0] + r["p_screen"][:2]
                    v.update(top=r["top"], verification=r["verification"], pAnswer=r["p_answer"], pScreen=r["p_screen"])
            # 한 번 보여 준 카드 자리는 유지(순서를 바꾸지 않고 배지만 갱신)
            if out["noticeReason"] != "time_sensitive" and out["videos"] and not out["videos"][0].get("formStart"):
                # 보이는 장면이 모두 「확인 안 됨」일 때만 (화면이나 자막에서 확인된 장면이 하나라도 있으면 안내하지 않음)
                out["noAnswerInVideo"] = all(x == "none" for v in out["videos"] for x in v["verification"][:3])
                out["noticeReason"] = "vlm_no_answer" if out["noAnswerInVideo"] else None
            out["status"] = "done"
        except Exception as e:   # 확인 실패 시 기본 결과 그대로 두고 표시만
            out["status"] = "error"; out["error"] = str(e)[:200]
        out["timing"]["verify_sec"] = round(time.time() - t0, 3)
        self.record(out)

    def record(self, out, cached=False):
        try:
            v = out["videos"][0] if out.get("videos") else None
            with self.log_lock:
                self.log.execute("INSERT INTO search_log VALUES (?,?,?,?,?,?,?,?,?,?)", (
                    time.strftime("%Y-%m-%d %H:%M:%S"), out["query"], out.get("ctx") or "", out.get("policyId") or (out.get("dbPolicy") or {}).get("policyId") or "", int(bool(out.get("noVideo"))),
                    out.get("noticeReason") or "", len((out.get("official") or {}).get("items", [])), v["youtubeId"] if v else "",
                    v["verification"][0] if v else "", int(cached)))
                self.log.commit()
        except Exception:
            pass

    def job(self, jid):
        return self.jobs.get(jid)
