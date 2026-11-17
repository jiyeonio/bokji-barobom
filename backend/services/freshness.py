"""영상 정보 최신성 경고: 장면 자막의 금액을 공공데이터 현재 값과 비교 (규칙: docs/service/freshness_rules.md).

틀린 경고를 내지 않는 것이 우선이라 아래를 모두 만족할 때만 경고한다.
  1. 영상이 그 정책과 연결돼 있고(시연 목록의 정책), 그 정책에 공공데이터 금액(amount)이 있음
  2. 자막 한 문장 안에서 금액이 「매달 / 매월 / 월 / 월 최대」 바로 뒤에 나옴 (지급액을 말하는 문장)
  3. 같은 문장에 접수비·신청비·수수료·요금·감면·보증금·월세·이체·환급·대출 같은 다른 돈 이야기가 없음
  4. 금액이 정책별 범위 안(기초연금 10만~100만 원)이고, 공공데이터 현재 값 어느 것과도 1,000원 넘게 다름
화면 글자(OCR)는 아직 비교하지 않는다(읽기 오류로 틀린 경고가 날 수 있어서).
"""
import re

AMOUNT = re.compile(r"(\d{1,3}(?:,\d{3})+|\d+)\s*(만\s*)?원")
CLAIM = re.compile(r"(매달|매월|월\s*최대|월)\s*(?:최대\s*)?(\d{1,3}(?:,\d{3})+|\d+)\s*(만\s*)?원")
OTHER_MONEY = re.compile(r"접수비|신청비|수수료|요금|감면|보증금|월세|이체|환급|대출|비용|부담금")
RANGE = {"basic-pension": (100_000, 1_000_000)}   # 비교하는 정책과 금액 범위 (시연: 기초연금)
TOLERANCE = 1_000


def won(num, man):
    n = int(num.replace(",", ""))
    return n * 10_000 if man else n


def fmt_won(n):
    return f"{n // 10_000}만 원" if n % 10_000 == 0 else f"{n:,}원"


def current_values(policy):
    out = []
    for a in policy.get("amount") or []:
        m = AMOUNT.search(a["value"])
        if m:
            out.append({"label": a["label"], "value": a["value"], "won": won(m.group(1), m.group(2))})
    return out


def check_video(policy, segments, published):
    """영상 자막 전체에서 경고 목록. policy 없으면 빈 목록."""
    if not policy or policy["policyId"] not in RANGE:
        return []
    cur = current_values(policy)
    if not cur:
        return []
    lo, hi = RANGE[policy["policyId"]]
    out = []
    for s in segments:
        text = s["text"].strip()
        if OTHER_MONEY.search(text):
            continue
        for m in CLAIM.finditer(text):
            claim = won(m.group(2), m.group(3))
            if not (lo <= claim <= hi):
                continue
            if any(abs(claim - c["won"]) <= TOLERANCE for c in cur):
                continue
            year = (published or "")[:4]
            now = " · ".join(f"{c['label']} {c['value']}" for c in cur)
            out.append({
                "start": s["start_time"], "end": s["end_time"], "text": text,
                "claim": f"{m.group(1)} {fmt_won(claim)}", "claimWon": claim, "current": cur,
                "videoYear": year, "policyName": policy["name"], "source": policy["source"],
                "baseYear": policy.get("baseYear"), "updatedAt": policy.get("updatedAt"),
                "message": f"영상 속 정보는 {year}년 영상 기준이에요(영상: {m.group(1)} {fmt_won(claim)}). "
                           f"현재는 {now}이에요.",
            })
    return out


def overlapping(warnings, start, end, pad=2.0):
    return [w for w in warnings if w["end"] > start - pad and w["start"] < end + pad]
