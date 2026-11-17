"""통합 정책 검색 DB 만들기: fetch_policy_db.py로 받은 원본 → <WELFARE_DATA_DIR>/policy_db.sqlite (저장소에 올리지 않음)

- 대상: 행정안전부 「대한민국 공공서비스(혜택) 정보」 중 사용자구분에 「개인」 또는 「가구」가 있는 서비스(2026-11-15 수집 9,934개, 650개 기관)
- 정책 내용(지원대상·선정기준·지원내용·신청방법·구비서류·문의처 등)은 API 원문 그대로 저장(고치거나 요약하지 않음)
- 지역: 소관기관유형이 시군구·광역시도면 기관명에서, 지방공기업·출자출연기관은 소관기관코드가 같은 시군구·시도에서, 교육청은 이름에서.
  중앙행정기관·공공기관은 「전국」
- 대상(규칙 분류, 사람이 검수하지 않음 — 화면에 「분류는 자동」 표시):
  · 어르신: 지원조건 나이 시작 ≥ 60세, 또는 서비스명·지원대상에 노인·어르신·고령·경로·65세 이상·60세 이상·치매·장기요양
  · 청년: 지원조건 나이가 19~45세 안쪽(시작 ≥ 15, 끝 ≤ 45), 또는 서비스명·지원대상에 청년
  · 아이 키우는 가정: 서비스명·지원대상에 아동·영유아·영아·유아·자녀·양육·보육·출산·임신·임산부·어린이·육아·다자녀·한부모·아이돌봄, 또는 서비스분야 임신·출산
  · 장애인: 서비스명·지원대상에 장애인·장애아·장애 정도·장애정도·발달장애·장애등급·장애아동
- 시연 정책 15개(backend/data/policies.json)와 서비스 ID가 같으면 연결(영상이 있는 정책)
- 한국사회보장정보원 「지자체복지서비스」 목록(약 4,828개, 2026-11-15 인증키 승인)과 교차 확인: 같은 시도·시군구에서 서비스명(띄어쓰기·괄호·끝의 지원/사업 뺌)이
  같거나 한쪽(6자 이상)이 다른 쪽을 포함하면 같은 서비스로 보고 연결(local_id). 맞는 것이 없는 지자체 서비스는 따로 넣음(source=local, 상세는 열 때 API에서 받아 저장).
  지자체 서비스 대상: 생애주기 노년→어르신, 청년→청년, 영유아·아동·임신·출산→아이 키우는 가정, 가구상황 장애인→장애인 (+ 위 낱말 규칙)

    python backend/scripts/build_policy_db.py
"""
import json, os, re, sqlite3, sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
D = Path(os.environ.get("WELFARE_DATA_DIR", "/nfs/team/data/scenefinder_vlm"))
RAW, OUT = D / "policy_raw", D / "policy_db.sqlite"

AUD_TEXT = {
    "senior": r"노인|어르신|고령|경로|65세\s*이상|60세\s*이상|치매|장기요양",
    "youth": r"청년",
    "family": r"아동|영유아|영아|유아|자녀|양육|보육|출산|임신|임산부|어린이|육아|다자녀|한부모|아이돌봄",
    "disabled": r"장애인|장애아|장애\s*정도|장애정도|발달장애|장애등급",
}
AUD_LABEL = {"senior": "어르신", "youth": "청년", "family": "아이 키우는 가정", "disabled": "장애인"}


def audiences(r, cond):
    text = f"{r['서비스명']} {r.get('지원대상') or ''}"
    a0, a1 = cond.get("JA0110"), cond.get("JA0111")
    out = [k for k, pat in AUD_TEXT.items() if re.search(pat, text)]
    if isinstance(a0, (int, float)) and a0 >= 60 and "senior" not in out:
        out.append("senior")
    if isinstance(a0, (int, float)) and isinstance(a1, (int, float)) and a0 >= 15 and 0 < a1 <= 45 and "youth" not in out:
        out.append("youth")
    if r.get("서비스분야") == "임신·출산" and "family" not in out:
        out.append("family")
    return [k for k in AUD_TEXT if k in out]


LIFE = {"노년": "senior", "청년": "youth", "영유아": "family", "아동": "family", "임신 · 출산": "family"}


def core(n, sd="", sg=""):
    from re import sub
    n = sub(r"^\(.*?\)", "", n or "").strip()
    for pre in sorted({sd, sg, sg[:-1] + "시" if sg.endswith("군") else "", sd.replace("특별자치", "").replace("광역", "")[:2]} - {""}, key=len, reverse=True):
        if n.startswith(pre):   # 「통영시 출산지원금」처럼 이름 앞의 지역명은 빼고 비교
            n = n[len(pre):]; break
    n = sub(r"[\s()\[\]·ㆍ・,.'\"「」『』<>-]", "", n)
    return sub(r"(지원사업|지원|사업|서비스)$", "", n)


def add_local(con, gov_rows):
    f = RAW / "ssis_local_list.json"
    if not f.exists():
        return 0, 0
    L = json.loads(f.read_text())
    by_region = {}
    for i, n, sd, sg in con.execute("SELECT id, name, sido, sigungu FROM services"):
        by_region.setdefault((sd, sg), []).append((i, core(n, sd, sg)))
    n_local = n_cross = 0
    for r in L:
        sd, sg = r["ctpvNm"], r.get("sggNm") or ""; c = core(r["servNm"], sd, sg)
        hit = next((i for i, gc in by_region.get((sd, sg), []) if gc == c or (min(len(gc), len(c)) >= 6 and (gc in c or c in gc))), None)
        if hit:
            con.execute("UPDATE services SET local_id=? WHERE id=? AND local_id IS NULL", (r["servId"], hit)); n_cross += 1; continue
        life = [x.strip() for x in (r.get("lifeNmArray") or "").split(",")]
        tg = [x.strip() for x in (r.get("trgterIndvdlNmArray") or "").split(",")]
        aud = {LIFE[x] for x in life if x in LIFE} | ({"disabled"} if "장애인" in tg else set())
        aud |= {k for k, pat in AUD_TEXT.items() if re.search(pat, f"{r['servNm']} {r.get('servDgst', '')}")}
        con.execute("INSERT OR IGNORE INTO services (id, name, summary, field, user_type, agency, agency_type, sido, sigungu, audiences, support_type, views, updated, curated, list_json, detail_json, cond_json, source) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                        r["servId"], r["servNm"], r.get("servDgst") or "", r.get("intrsThemaNmArray") or "", "개인", r.get("bizChrDeptNm") or f"{sd} {sg}".strip(),
                        "시군구" if sg else "광역시도", sd, sg, ",".join(k for k in AUD_TEXT if k in aud), r.get("srvPvsnNm") or "", int(r.get("inqNum") or 0),
                        r.get("lastModYmd") or "", None, json.dumps(r, ensure_ascii=False), "{}", "{}", "local"))
        n_local += 1
    return n_local, n_cross


def main():
    L = json.loads((RAW / "gov24_serviceList.json").read_text())
    det = {r["서비스ID"]: r for r in json.loads((RAW / "gov24_serviceDetail.json").read_text())}
    cond = {r["서비스ID"]: r for r in json.loads((RAW / "gov24_supportConditions.json").read_text())}
    fetched = (RAW / "fetched_at.txt").read_text().strip()
    curated = {p["sourceIds"].get("gov24"): p["policyId"] for p in json.loads((ROOT / "backend/data/policies.json").read_text())
               if (p.get("sourceIds") or {}).get("gov24")}
    rows = [r for r in L if any(k in (r["사용자구분"] or "") for k in ("개인", "가구"))]
    # 지역: 기관 코드 → (시도, 시군구)
    code_region, sidos = {}, set()
    for r in rows:
        t, n = r["소관기관유형"], r["소관기관명"]
        if t == "광역시도":
            code_region[r["소관기관코드"]] = (n, ""); sidos.add(n)
        elif t == "시군구":
            sd, _, sg = n.partition(" "); code_region[r["소관기관코드"]] = (sd, sg); sidos.add(sd)

    def region(r):
        t, n, c = r["소관기관유형"], r["소관기관명"], r["소관기관코드"]
        if t in ("중앙행정기관", "공공기관"):
            return ("전국", "")
        if c in code_region:
            return code_region[c]
        for sd in sorted(sidos, key=len, reverse=True):
            if n.startswith(sd):
                return (sd, "")
        return ("", "")

    if OUT.exists():
        OUT.unlink()
    con = sqlite3.connect(OUT)
    con.execute("""CREATE TABLE services (id TEXT PRIMARY KEY, name TEXT, summary TEXT, field TEXT, user_type TEXT, agency TEXT, agency_type TEXT,
                   sido TEXT, sigungu TEXT, audiences TEXT, support_type TEXT, views INTEGER, updated TEXT, curated TEXT, list_json TEXT, detail_json TEXT, cond_json TEXT,
                   source TEXT DEFAULT 'gov24', local_id TEXT)""")
    con.execute("CREATE TABLE local_detail (id TEXT PRIMARY KEY, detail_json TEXT, fetched_at TEXT)")
    con.execute("CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT)")
    cnt, agencies, unknown = Counter(), {k: set() for k in AUD_TEXT}, 0
    for r in rows:
        c = cond.get(r["서비스ID"], {}); aud = audiences(r, c); sd, sg = region(r)
        unknown += not sd
        for a in aud:
            cnt[a] += 1; agencies[a].add(r["소관기관명"])
        con.execute("INSERT INTO services (id, name, summary, field, user_type, agency, agency_type, sido, sigungu, audiences, support_type, views, updated, curated, list_json, detail_json, cond_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            r["서비스ID"], r["서비스명"], r.get("서비스목적요약") or "", r.get("서비스분야") or "", r["사용자구분"], r["소관기관명"], r["소관기관유형"],
            sd, sg, ",".join(aud), r.get("지원유형") or "", int(r.get("조회수") or 0), r.get("수정일시") or "", curated.get(r["서비스ID"]),
            json.dumps(r, ensure_ascii=False), json.dumps(det.get(r["서비스ID"], {}), ensure_ascii=False), json.dumps(c, ensure_ascii=False)))
    n_local, n_cross = add_local(con, rows)
    meta = {"source": "행정안전부 「대한민국 공공서비스(혜택) 정보」(공공데이터포털 Open API)", "fetchedAt": fetched, "count": len(rows),
            "localSource": "한국사회보장정보원 「지자체복지서비스」(공공데이터포털 Open API)", "localOnly": n_local, "crossChecked": n_cross,
            "agencies": len({r["소관기관명"] for r in rows}), "audienceRule": "규칙 분류(build_policy_db.py), 사람 검수 없음",
            "audienceLabels": AUD_LABEL, "localApi": "한국사회보장정보원 지자체복지서비스: gov24와 교차 확인, gov24에 없는 지자체 서비스 추가"}
    for k, v in meta.items():
        con.execute("INSERT INTO meta VALUES (?,?)", (k, json.dumps(v, ensure_ascii=False)))
    con.commit()
    print(f"서비스 {len(rows)}개, 기관 {meta['agencies']}개, 지역 모름 {unknown}개, 시연 정책 연결 {sum(1 for r in rows if r['서비스ID'] in curated)}개")
    for a in AUD_TEXT:
        print(f"  {AUD_LABEL[a]}: {cnt[a]}개 서비스, {len(agencies[a])}개 기관")
    print(f"지자체복지서비스: gov24와 교차 확인 {n_cross}개, 지자체 API에만 있는 서비스 {n_local}개 추가")
    print("→", OUT)


if __name__ == "__main__":
    main()
