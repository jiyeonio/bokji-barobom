"""통합 정책 검색 DB 원본 받기 → <WELFARE_DATA_DIR>/policy_raw/*.json (저장소에 올리지 않음)

- 행정안전부 「대한민국 공공서비스(혜택) 정보」(gov24): serviceList·serviceDetail·supportConditions 전체(약 10,942개, 1,000개씩)
- 한국사회보장정보원 「중앙부처복지서비스」(SSIS): 목록 전체(약 461개, 생애주기·가구상황 분류)
- 한국사회보장정보원 「지자체복지서비스」: 목록 전체(약 4,828개, 2026-11-15 인증키 승인). 상세는 정책을 열 때 받음(policy_db.py)
호출 사이 0.5초. 키는 출력하지 않음.

    python backend/scripts/fetch_policy_db.py
"""
import json, math, os, sys, time
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend/services"))
import welfare_api as w

OUT = Path(os.environ.get("WELFARE_DATA_DIR", "/nfs/team/data/scenefinder_vlm")) / "policy_raw"
LOCAL = "https://apis.data.go.kr/B554287/LocalGovernmentWelfareInformations/LcgvWelfarelist"


def gov24_all(path):
    first = w.gov24(path, page=1, perPage=1000); rows = first["data"]
    for pg in range(2, math.ceil(first["totalCount"] / 1000) + 1):
        time.sleep(0.5); rows += w.gov24(path, page=pg, perPage=1000)["data"]
    print(path, len(rows), "/", first["totalCount"], flush=True)
    return rows


def ssis_all(url, params, item_tag):
    rows, pg = [], 1
    while True:
        r = w._get(url, {**params, "pageNo": pg, "numOfRows": 500})
        if r.status_code != 200:
            print(url.rsplit("/", 1)[-1], "HTTP", r.status_code, w._redact(r.text[:200]).replace("\n", " ")); return None
        root = ET.fromstring(r.text)
        items = [{c.tag: (c.text or "").strip() for c in it} for it in root.iter(item_tag)]
        rows += items; total = int(root.findtext(".//totalCount") or 0)
        if not items or len(rows) >= total:
            break
        pg += 1; time.sleep(0.5)
    print(url.rsplit("/", 1)[-1], len(rows), flush=True)
    return rows


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for p in ("serviceList", "serviceDetail", "supportConditions"):
        (OUT / f"gov24_{p}.json").write_text(json.dumps(gov24_all(p), ensure_ascii=False))
    s = ssis_all(f"{w.SSIS}/NationalWelfarelistV001", {"callTp": "L", "srchKeyCode": "001"}, "servList")
    if s is not None:
        (OUT / "ssis_central_list.json").write_text(json.dumps(s, ensure_ascii=False))
    s = ssis_all(LOCAL, {}, "servList")
    if s is not None:
        (OUT / "ssis_local_list.json").write_text(json.dumps(s, ensure_ascii=False))
    (OUT / "fetched_at.txt").write_text(time.strftime("%Y-%m-%d %H:%M"))


if __name__ == "__main__":
    main()
