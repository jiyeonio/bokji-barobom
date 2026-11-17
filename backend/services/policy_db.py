"""통합 정책 검색 DB (backend/scripts/build_policy_db.py가 만든 <WELFARE_DATA_DIR>/policy_db.sqlite).

- search(q, audience, sido, sigungu): 낱말 점수(서비스명 3 · 요약 1.5 · 지원대상 1 · 기관명 0.5) → 조회수 순. 정책 내용은 원문 그대로.
- strong_match(q): 시연 정책(15개)에 없는 질문에서, 질문이 특정 서비스를 분명히 가리킬 때만(서비스명이 질문에 그대로 있거나
  질문 낱말이 모두 서비스명에 있고, 중앙행정기관·공공기관 서비스 중 후보가 하나) 그 서비스.
- as_policy(id): 화면의 Policy 모양으로 (금액·구비서류 목록은 만들지 않음 — 원문 「구비서류」는 requiredDocsNotes로 그대로)
- 한국사회보장정보원 「지자체복지서비스」: gov24와 같은 서비스면 local_id로 연결(교차 확인), gov24에 없으면 source=local 줄.
  지자체 서비스 상세는 처음 열 때 API(LcgvWelfaredetailed)에서 받아 local_detail 표에 저장(원문 그대로)
"""
import json, os, re, sqlite3, sys, threading, time
import xml.etree.ElementTree as ET
from pathlib import Path

PATH = Path(os.environ.get("WELFARE_DATA_DIR", "/nfs/team/data/scenefinder_vlm")) / "policy_db.sqlite"
LOCAL_DETAIL = "https://apis.data.go.kr/B554287/LocalGovernmentWelfareInformations/LcgvWelfaredetailed"
LOCAL_SRC = "한국사회보장정보원 지자체복지서비스"
GOV24_SRC = "행정안전부 대한민국 공공서비스(혜택) 정보"
STOP = {"신청", "방법", "어떻게", "어디서", "어디", "뭐", "뭘", "서류", "필요", "필요한", "대상", "자격", "언제", "기간", "받으려면", "받을", "수",
        "있어요", "있나요", "돼요", "되나요", "해요", "하나요", "하는", "법", "알려줘", "알려주세요", "궁금해요", "지원", "제도", "서비스", "좀", "그", "얼마", "받아요", "받나요", "주나요", "되는", "거예요", "이거", "어떻게", "해주세요", "있는", "하면", "가능", "되요"}
JOSA = re.compile(r"(으로|에서|하려면|받으려면|하는|하기|은|는|이|가|을|를|에|의|도|로|랑|하고)$")
NORM = re.compile(r"[\s()\[\]·ㆍ・,.'\"「」『』<>-]")
CENTRAL = ("중앙행정기관", "공공기관")


def norm(t):
    return NORM.sub("", t or "")


def terms(q):
    out = []
    for w in re.split(r"\s+", (q or "").strip()):
        w = JOSA.sub("", re.sub(r"[?!.,~]", "", w))
        if len(w) >= 2 and w not in STOP:
            out.append(w)
    return out


class PolicyDB:
    def __init__(self, path=PATH):
        self.ok = path.exists()
        self.rows, self.meta, self.regions = [], {}, {}
        if not self.ok:
            return
        self.con = sqlite3.connect(path, check_same_thread=False); self.lock = threading.Lock()
        self.meta = {k: json.loads(v) for k, v in self.con.execute("SELECT k, v FROM meta")}
        for r in self.con.execute("SELECT id, name, summary, field, agency, agency_type, sido, sigungu, audiences, support_type, views, updated, curated, "
                                  "COALESCE(json_extract(list_json, '$.지원대상'), ''), source, local_id FROM services"):
            d = dict(zip(["id", "name", "summary", "field", "agency", "agencyType", "sido", "sigungu", "audiences", "supportType", "views",
                          "updated", "curated", "target", "source", "localId"], r))
            d["audiences"] = [a for a in d["audiences"].split(",") if a]
            d["_n"] = norm(d["name"]); d["_s"] = norm(d["summary"]); d["_t"] = norm(d["target"]); d["_a"] = norm(d["agency"])
            self.rows.append(d)
            if d["sido"] and d["sido"] != "전국":
                self.regions.setdefault(d["sido"], set())
                if d["sigungu"]:
                    self.regions[d["sido"]].add(d["sigungu"])
        self.regions = {k: sorted(v) for k, v in sorted(self.regions.items())}

    @staticmethod
    def brief(d):
        return {k: v for k, v in d.items() if not k.startswith("_") and k != "target"}

    def search(self, q="", audience=None, sido=None, sigungu=None, nationwide=True, page=1, size=20):
        ts = [norm(t) for t in terms(q)]
        res = []
        for d in self.rows:
            if audience and audience not in d["audiences"]:
                continue
            if sido:
                local = d["sido"] == sido and (not sigungu or d["sigungu"] in (sigungu, ""))
                if not (local or (nationwide and d["sido"] == "전국")):
                    continue
            if ts:
                sc = sum(3 * (t in d["_n"]) + 1.5 * (t in d["_s"]) + 1 * (t in d["_t"]) + 0.5 * (t in d["_a"]) for t in ts)
                if not any(t in d["_n"] or t in d["_s"] for t in ts):
                    continue
                if norm(q) and d["_n"] and d["_n"] in norm(q):
                    sc += 5
            else:
                sc = 0
            res.append((sc, d["curated"] is not None, bool(sido) and d["sido"] == sido, d["views"], d))
        # 점수 → 영상 있는 정책 → (지역을 골랐으면) 그 지역 정책 → 조회수
        res.sort(key=lambda x: (-x[0], not x[1], not x[2], -x[3]))
        return {"total": len(res), "page": page, "size": size, "items": [self.brief(x[4]) for x in res[(page - 1) * size: page * size]]}

    def strong_match(self, q):
        """중앙행정기관·공공기관 서비스만(지자체 서비스는 지역을 모르면 엉뚱할 수 있어 정책 찾기 화면에서 지역으로 고르게 함)."""
        if not self.ok:
            return None
        nq = norm(q); ts = [norm(t) for t in terms(q)]
        rows = [d for d in self.rows if d["agencyType"] in CENTRAL]
        core = lambda n: re.sub(r"(지원사업|지원|사업|서비스|제도)$", "", n)
        cands = [d for d in rows if len(core(d["_n"])) >= 4 and core(d["_n"]) in nq]
        if not cands and ts:
            cands = [d for d in rows if all(t in d["_n"] for t in ts)]
        if not cands:
            return None
        L = max(len(core(d["_n"])) for d in cands); cands = [d for d in cands if len(core(d["_n"])) == L]   # 가장 긴 이름
        return cands[0]["id"] if len(cands) == 1 else None

    def _local_detail(self, sid):
        """지자체복지서비스 상세: 저장된 것이 있으면 그것, 없으면 API에서 받아 저장(원문 그대로)."""
        with self.lock:
            r = self.con.execute("SELECT detail_json FROM local_detail WHERE id=?", (sid,)).fetchone()
        if r:
            return json.loads(r[0])
        sys.path.insert(0, str(Path(__file__).parent))
        import welfare_api as w
        try:
            res = w._get(LOCAL_DETAIL, {"servId": sid})
            if res.status_code != 200:
                return {}
            root = ET.fromstring(res.text)
        except Exception:
            return {}
        d = {c.tag: (c.text or "").strip() for c in root if not list(c)}
        d["inqpl"] = [{x.tag: (x.text or "").strip() for x in c} for c in root.iter("inqplCtadrList")]
        d["baslaw"] = [{x.tag: (x.text or "").strip() for x in c} for c in root.iter("baslawList")]
        if d.get("servId") == sid:
            with self.lock:
                self.con.execute("INSERT OR REPLACE INTO local_detail VALUES (?,?,?)", (sid, json.dumps(d, ensure_ascii=False), time.strftime("%Y-%m-%d %H:%M")))
                self.con.commit()
        return d

    @staticmethod
    def _local_as_korean(L, D):
        """지자체복지서비스 항목 → 화면 항목 이름(원문 그대로 옮기기만)."""
        ymd = lambda x: f"{x[:4]}.{x[4:6]}.{x[6:8]}" if x and len(x) == 8 and x != "99991231" else ("계속" if x == "99991231" else "")  # noqa: E731
        period = f"{ymd(D.get('enfcBgngYmd', ''))} ~ {ymd(D.get('enfcEndYmd', ''))}" if D.get("enfcBgngYmd") else ""
        inq = "\n".join(f"{x.get('wlfareInfoReldNm', '')} {x.get('wlfareInfoReldCn', '')}".strip() for x in D.get("inqpl", []) if x.get("wlfareInfoDtlCd") == "010")
        return {"서비스목적": D.get("servDgst") or L.get("servDgst"), "지원대상": D.get("sprtTrgtCn"), "선정기준": D.get("slctCritCn"),
                "지원내용": D.get("alwServCn"), "지원유형": D.get("srvPvsnNm") or L.get("srvPvsnNm"), "신청방법": D.get("aplyMtdCn") or L.get("aplyMtdNm"),
                "신청기한": period and f"시행 기간 {period}", "문의처": inq, "접수기관명": D.get("bizChrDeptNm") or L.get("bizChrDeptNm"),
                "법령": ", ".join(x.get("wlfareInfoReldNm", "") for x in D.get("baslaw", []))}

    def detail(self, sid):
        with self.lock:
            r = self.con.execute("SELECT list_json, detail_json, cond_json, sido, sigungu, audiences, curated, source, local_id FROM services WHERE id=?", (sid,)).fetchone()
        if not r:
            return None
        lst, det = json.loads(r[0]), json.loads(r[1])
        out = {"id": sid, "list": lst, "detail": det, "sido": r[3], "sigungu": r[4], "audiences": [a for a in r[5].split(",") if a], "curated": r[6],
               "source": r[7] or "gov24", "localId": r[8], "localLink": None}
        if out["source"] == "local":
            out["detail"] = self._local_as_korean(lst, self._local_detail(sid)); out["localLink"] = lst.get("servDtlLink")
        elif r[8]:   # 지자체복지서비스에도 있음(교차 확인) — 복지로 링크
            out["localLink"] = self.local_links().get(r[8])
        return out

    def local_links(self):
        if not hasattr(self, "_ll"):
            f = PATH.parent / "policy_raw/ssis_local_list.json"
            self._ll = {r["servId"]: r.get("servDtlLink") for r in json.loads(f.read_text())} if f.exists() else {}
        return self._ll

    def as_policy(self, sid):
        x = self.detail(sid)
        if not x:
            return None
        if x["source"] == "local":
            L, D = x["list"], x["detail"]
            upd = L.get("lastModYmd") or ""
            urls = [{"label": "복지로 상세", "url": x["localLink"]}] if x["localLink"] else []
            return {"policyId": f"db:{sid}", "name": L["servNm"], "category": L.get("intrsThemaNmArray") or "", "target": L.get("servDgst") or "",
                    "targetDetail": D.get("지원대상") or "", "criteria": D.get("선정기준") or "", "benefit": D.get("지원내용") or "",
                    "applyMethod": D.get("신청방법") or "", "applyWhen": D.get("신청기한") or "", "contact": D.get("문의처") or "",
                    "agency": L.get("bizChrDeptNm") or "", "applyUrl": x["localLink"] or "", "officialUrls": urls, "amount": [],
                    "source": LOCAL_SRC, "sourceIds": {"ssisLocal": sid}, "baseYear": int(upd[:4]) if upd[:4].isdigit() else None,
                    "updatedAt": f"{upd[:4]}-{upd[4:6]}-{upd[6:8]}" if len(upd) == 8 else "", "fetchedAt": self.meta.get("fetchedAt", ""),
                    "requiredDocs": [], "requiredDocsNotes": "", "easy": {}, "region": " ".join(t for t in (x["sido"], x["sigungu"]) if t),
                    "audiences": x["audiences"], "fromDb": True, "crossCheck": None}
        L, D = x["list"], x["detail"]
        g = lambda k: (D.get(k) or L.get(k) or "").strip()  # noqa: E731
        upd = (L.get("수정일시") or D.get("수정일시") or "")[:8]
        urls = [{"label": "정부24 상세", "url": L["상세조회URL"]}] if L.get("상세조회URL") else []
        if D.get("온라인신청사이트URL"):
            urls.append({"label": "온라인 신청", "url": D["온라인신청사이트URL"]})
        if x["localLink"]:
            urls.append({"label": "복지로 상세(지자체복지서비스)", "url": x["localLink"]})
        docs = "\n".join(t for t in [g("구비서류")] if t and t != "해당없음")
        return {"policyId": f"db:{sid}", "name": L["서비스명"], "category": L.get("서비스분야") or "", "target": L.get("서비스목적요약") or "",
                "targetDetail": g("지원대상"), "criteria": g("선정기준"), "benefit": g("지원내용"), "applyMethod": g("신청방법"),
                "applyWhen": g("신청기한"), "contact": g("문의처") or L.get("전화문의") or "", "agency": L.get("소관기관명") or "",
                "applyUrl": D.get("온라인신청사이트URL") or L.get("상세조회URL") or "", "officialUrls": urls, "amount": [],
                "source": GOV24_SRC, "sourceIds": {"gov24": sid} | ({"ssisLocal": x["localId"]} if x["localId"] else {}),
                "baseYear": int(upd[:4]) if upd[:4].isdigit() else None, "updatedAt": f"{upd[:4]}-{upd[4:6]}-{upd[6:8]}" if len(upd) == 8 else "",
                "fetchedAt": self.meta.get("fetchedAt", ""), "requiredDocs": [], "requiredDocsNotes": docs, "easy": {},
                "region": " ".join(t for t in (x["sido"], x["sigungu"]) if t), "audiences": x["audiences"], "fromDb": True,
                "crossCheck": LOCAL_SRC if x["localId"] else None}


_db = None
_dlock = threading.Lock()


def db():
    global _db
    with _dlock:
        if _db is None:
            _db = PolicyDB()
    return _db
