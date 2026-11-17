"""시연용 정책 정보 만들기: 사회보장 공공데이터 두 API에서 받아 화면에 쓰는 일반 항목으로 정리 → backend/data/policies.json

- 한국사회보장정보원 중앙부처복지서비스(SSIS): 서비스 ID·명칭·요약·소관부처·지원대상·선정기준·지원내용·기준연도·문의처
- 행정안전부 공공서비스(혜택)(gov24): 지원대상·선정기준·지원내용·신청방법·신청기한·구비서류·문의처·온라인 신청 URL·수정일시
두 API가 같은 항목을 주면 gov24(신청 실무 항목이 더 자세함)를 먼저 쓰고, 없으면 SSIS. 항목마다 어느 API에서 왔는지 남긴다.
금액(amount)은 정책별로 사람이 고른 문구만 넣고, 그 문구가 공식 지원내용 원문에 그대로 있는지 확인한다(없으면 실패).

    python backend/scripts/build_policies.py            # API 호출 → backend/data/policies.json
"""
import json, re, sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend/services"))
import welfare_api as w

OUT = ROOT / "backend/data/policies.json"

# 시연 정책 (2026-11-12, 중앙부처 서비스만). id는 두 API에서 서비스명으로 찾아 소관부처를 확인한 것.
POLICIES = [
    {"policyId": "basic-pension", "name": "기초연금", "category": "노후·연금", "ssis": "WLF00001164", "gov24": "SSE000000170",
     "keywords": ["기초연금", "노령연금", "65세", "어르신 연금"],
     "amount": [{"label": "혼자 사는 경우 최대(월)", "text": "349,700원"}, {"label": "부부 최대(월)", "text": "559,520원"}]},
    {"policyId": "child-care", "name": "아이돌봄서비스", "category": "돌봄·보육", "ssis": "WLF00000024", "gov24": "423000000362",
     "keywords": ["아이돌봄", "아이 돌봄", "돌보미", "육아 도우미", "맞벌이"], "amount": []},
    {"policyId": "youth-rent", "name": "청년월세 지원", "category": "주거", "ssis": "WLF00004661", "gov24": "161300000099",
     "keywords": ["청년월세", "청년 월세", "월세 지원", "청년 주거"], "amount": [{"label": "월 최대 (최대 24개월)", "text": "20만원"}]},
    {"policyId": "housing-benefit", "name": "주거급여(맞춤형 급여)", "category": "주거", "ssis": "WLF00003201", "gov24": "336000000096",
     "keywords": ["주거급여", "분리지급", "임차료", "청년 주거급여"], "amount": []},
    # 2026-11-15 추가 (시연 영상이 생긴 정책)
    {"policyId": "long-term-care", "name": "노인장기요양보험(장기요양인정)", "category": "노후·돌봄", "ssis": None, "gov24": "999000000089",
     "keywords": ["장기요양", "요양등급", "요양보험", "복지용구"], "amount": []},
    {"policyId": "senior-jobs", "name": "노인일자리 및 사회활동 지원", "category": "노후·일자리", "ssis": "WLF00001155", "gov24": "SSE000000100",
     "keywords": ["노인일자리", "노인 일자리", "시니어 일자리"], "amount": []},
    {"policyId": "dementia-screening", "name": "치매검진 지원", "category": "노후·건강", "ssis": "WLF00005004", "gov24": "135200005043",
     "keywords": ["치매"], "amount": []},
    {"policyId": "energy-voucher", "name": "에너지바우처", "category": "생활·에너지", "ssis": "WLF00000072", "gov24": "B55353000001",
     "keywords": ["에너지바우처", "에너지 바우처", "냉난방비"], "amount": []},
    # 2026-11-15 추가 — 서비스 ID로 정확히 연결 (목록 검색 뒤 상세에서 서비스명·소관부처 확인)
    {"policyId": "disability-pension", "name": "장애인연금", "category": "장애인·소득", "ssis": "WLF00003249", "gov24": "SD0000016119",
     "keywords": ["장애인연금", "장애인 연금"], "amount": []},
    {"policyId": "job-seeking-benefit", "name": "구직급여(실업급여)", "category": "일자리·고용", "ssis": None, "gov24": "SD0000015536",
     "keywords": ["실업급여", "구직급여", "실업인정"], "amount": []},
    {"policyId": "employment-support", "name": "국민취업지원제도", "category": "일자리·고용", "ssis": "WLF00003245", "gov24": "149200005007",
     "keywords": ["국민취업지원", "구직촉진수당"], "amount": []},
    {"policyId": "happy-housing", "name": "행복주택 공급", "category": "주거", "ssis": "WLF00004649", "gov24": "999000000026",
     "keywords": ["행복주택"], "amount": []},
    {"policyId": "naeil-card", "name": "국민내일배움카드", "category": "일자리·고용", "ssis": "WLF00006229", "gov24": "149200000026",
     "keywords": ["내일배움카드"], "amount": []},
    {"policyId": "didimdol-loan", "name": "내집마련 디딤돌 대출", "category": "주거·금융", "ssis": "WLF00003271", "gov24": "B55140800003",
     "keywords": ["디딤돌"], "amount": []},
    {"policyId": "disability-personal-budget", "name": "장애인 개인예산제 운영", "category": "장애인·돌봄", "ssis": "WLF00005853", "gov24": None,
     "keywords": ["개인예산"], "amount": []},
]


def clean(s):
    if not s:
        return ""
    s = s.replace("\r\n", "\n").replace("\r", "\n").replace("&divide;", "÷")
    return re.sub(r"\n{3,}", "\n\n", s).strip()


def lines(s):
    out = []
    for l in clean(s).split("\n"):
        l = re.sub(r"^(?:[\s○◦•\-·※*]|ㅇ(?=\s))+", "", l).strip()
        if l and l not in ("해당없음",):
            out.append(l)
    return out


def ssis(sid):
    root = w.ssis_detail(sid)
    return {e.tag: clean(e.text) for e in root.iter() if (e.text or "").strip() and len(list(e)) == 0}


def gov(sid):
    d = w.gov24("serviceDetail", **{"cond[서비스ID::EQ]": sid}).get("data", [])
    return {k: clean(v) if isinstance(v, str) else v for k, v in (d[0] if d else {}).items()}


def pick(g, gk, s, sk):
    if g.get(gk):
        return g[gk], "gov24"
    if s.get(sk):
        return s[sk], "ssis"
    return "", None


def build(p):
    # 한쪽 API에만 있는 정책: SSIS 없음(예: 장기요양인정·구직급여) / gov24 없음(예: 장애인 개인예산제)
    s, g = (ssis(p["ssis"]) if p.get("ssis") else {}), (gov(p["gov24"]) if p.get("gov24") else {})
    fields, src = {}, {}
    for name, gk, sk in [("targetDetail", "지원대상", "tgtrDtlCn"), ("criteria", "선정기준", "slctCritCn"),
                         ("benefit", "지원내용", "alwServCn"), ("applyMethod", "신청방법", None),
                         ("applyWhen", "신청기한", None), ("contact", "문의처", "rprsCtadr")]:
        fields[name], src[name] = pick(g, gk, s, sk or "")
    fields["contact"] = fields["contact"].replace("||", " · ")
    # 구비서류: 「(필수서류) 가, 나, 다」처럼 한 줄에 여러 서류가 있으면 나누고, 설명 줄(「(추가서류) …」, 「반드시 …」)은 참고로 뺌
    names, doc_notes = [], []
    for l in lines(g.get("구비서류")):
        m = re.match(r"^\(([^)]*)\)\s*(.*)$", l)
        if m and "필수" in m.group(1):
            names += [x.strip() for x in re.split(r",\s*(?![^()]*\))", m.group(2)) if x.strip()]
        elif m:
            doc_notes.append(f"{m.group(1)}: {m.group(2)}")
        elif re.search(r"반드시|인정|경우에만", l):
            doc_notes.append(l)
        else:
            names.append(l)
    docs = [{"id": f"{p['policyId']}-doc{i + 1}", "name": d} for i, d in enumerate(names)]
    amounts = []
    for a in p["amount"]:
        whole = s.get("alwServCn", "") + "\n" + g.get("지원내용", "")
        assert a["text"] in whole, f"{p['name']}: 금액 문구 「{a['text']}」가 공식 지원내용에 없음"
        amounts.append({"label": a["label"], "value": a["text"], "source": "지원내용 원문"})
    return {
        "policyId": p["policyId"], "name": p["name"], "category": p["category"],
        "target": clean(s.get("wlfareInfoOutlCn") or g.get("서비스목적") or ""),
        **fields,
        "requiredDocs": docs,
        "requiredDocsNotes": doc_notes,
        "agency": s.get("jurMnofNm") or g.get("소관기관명", ""),
        "applyUrl": g.get("온라인신청사이트URL") or (f"https://www.bokjiro.go.kr/ssis-tbu/twataa/wlfareInfo/moveTWAT52011M.do?wlfareInfoId={p['ssis']}"
                                                   if p.get("ssis") else f"https://www.gov.kr/portal/rcvfvrSvc/dtlEx/{p['gov24']}"),
        "officialUrls": ([{"label": "복지로 서비스 안내", "url": f"https://www.bokjiro.go.kr/ssis-tbu/twataa/wlfareInfo/moveTWAT52011M.do?wlfareInfoId={p['ssis']}"}]
                         if p.get("ssis") else []) + ([{"label": "정부24 서비스 안내", "url": f"https://www.gov.kr/portal/rcvfvrSvc/dtlEx/{p['gov24']}"}] if p.get("gov24") else []),
        "amount": amounts or None,
        "source": " · ".join(x for x in [("한국사회보장정보원 복지서비스정보" if p.get("ssis") else ""), ("행정안전부 공공서비스(혜택) 정보" if p.get("gov24") else "")] if x),
        "sourceIds": {"ssis": p["ssis"], "gov24": p["gov24"]},
        "fieldSource": src,
        "baseYear": int(s["crtrYr"]) if s.get("crtrYr", "").isdigit() else (int(g["수정일시"][:4]) if (g.get("수정일시") or "")[:4].isdigit() else None),
        "updatedAt": g.get("수정일시") or "수정일 정보 없음",
        "fetchedAt": date.today().isoformat(),
        "keywords": p["keywords"],
    }


def main():
    out = [build(p) for p in POLICIES]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    for p in out:
        print(f"{p['name']}: 기준 {p['baseYear']}년, 수정 {p['updatedAt']}, 서류 {len(p['requiredDocs'])}개, 금액 {p['amount']}, 출처 {p['fieldSource']}")
    print(f"→ {OUT}")


if __name__ == "__main__":
    main()
