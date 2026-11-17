"""RAG 문서 만들기 (2026-11-15): 공공데이터 정책 정보(backend/data/policies.json) → backend/data/rag/chunks.jsonl

정책: 기초연금(basic-pension) · 청년월세 지원(youth-rent) · 아이돌봄서비스(child-care)
필드: 정책명(개요) · 지원대상 · 선정기준 · 지원내용 · 구비서류 · 신청방법 · 신청기간 · 문의처 · 공식URL (각 청크에 기준일·출처)
청크: 필드(항목) 단위. 긴 필드는 ○ ㅇ - ※ □ 로 시작하는 줄에서 나누고, 짧은 조각은 MAX_CHARS까지 이어 붙임. 내용은 API 원문 그대로(고치지 않음).
청크 ID: <policy_id>#<필드>#<번호>  예) youth-rent#지원대상#2
기준일: 공공데이터의 마지막 수정일(updatedAt). 받은 날(fetchedAt)도 함께 저장.

    python backend/scripts/build_rag_docs.py
"""
import json, re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "backend/data/rag/chunks.jsonl"
POLICIES = ["basic-pension", "youth-rent", "child-care"]
FIELDS = [("지원대상", "targetDetail"), ("선정기준", "criteria"), ("지원내용", "benefit"), ("신청방법", "applyMethod"),
          ("신청기간", "applyWhen"), ("문의처", "contact")]
MAX_CHARS = 420
ITEM = re.compile(r"^\s*(○|ㅇ|◦|•|-|※|□|\*|\d+\)|\d+\.)\s*")


def pieces(text):
    """항목 줄(○ ㅇ - ※ □ 1) 등)에서 나눈 뒤, 짧은 조각은 MAX_CHARS까지 붙임. 항목 앞 머리말(예: 「○ 아동 연령 기준」)은 다음 줄과 함께."""
    lines = [l.rstrip() for l in (text or "").replace("\r", "").split("\n") if l.strip()]
    blocks, cur = [], []
    for l in lines:
        if ITEM.match(l) and cur and not (len(cur) == 1 and len(cur[0]) < 20):
            blocks.append("\n".join(cur)); cur = []
        cur.append(l)
    if cur:
        blocks.append("\n".join(cur))
    out, buf = [], ""
    for b in blocks:
        if buf and len(buf) + len(b) + 1 > MAX_CHARS:
            out.append(buf); buf = b
        else:
            buf = f"{buf}\n{b}" if buf else b
    if buf:
        out.append(buf)
    return out or []


def main():
    pols = {p["policyId"]: p for p in json.loads((ROOT / "backend/data/policies.json").read_text())}
    rows = []
    for pid in POLICIES:
        p = pols[pid]
        urls = [{"label": u["label"], "url": u["url"]} for u in p.get("officialUrls", [])]
        meta = {"policy_id": pid, "policy_name": p["name"], "official_urls": urls, "base_date": p["updatedAt"], "fetched_at": p["fetchedAt"],
                "base_year": p.get("baseYear"), "source": p["source"]}

        def add(field, text, src):
            for i, t in enumerate(pieces(text), 1):
                rows.append({"chunk_id": f"{pid}#{field}#{i}", "field": field, "text": t, "field_source": src} | meta)
        fs = p.get("fieldSource", {})
        add("정책명", f"{p['name']} — {p.get('target', '')}\n소관: {p.get('agency', '')}\n분야: {p.get('category', '')}", "policies.json")
        for label, key in FIELDS:
            if p.get(key):
                add(label, p[key], fs.get(key, ""))
        docs = [d["name"] for d in p.get("requiredDocs", [])]
        notes = p.get("requiredDocsNotes") or []
        notes = notes if isinstance(notes, list) else [notes]
        if docs:
            add("구비서류", "\n".join(f"- {d}" for d in docs) + ("\n" + "\n".join(f"※ {n}" for n in notes if n) if notes else ""), fs.get("requiredDocs", "gov24"))
        add("공식URL", "\n".join(f"- {u['label']}: {u['url']}" for u in urls) + (f"\n- 공식 신청 페이지: {p['applyUrl']}" if p.get("applyUrl") else ""), "policies.json")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    by = {}
    for r in rows:
        by.setdefault(r["policy_id"], []).append(r["chunk_id"])
    print(f"청크 {len(rows)}개 → {OUT}")
    for pid, ids in by.items():
        print(" ", pid, len(ids), ids)


if __name__ == "__main__":
    main()
