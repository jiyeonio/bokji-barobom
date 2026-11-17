"""신청서 지도 만들기 (2026-11-15) → frontend/public/forms/<서식>_p<n>.png + backend/data/form_maps/<영상ID>.json

서식: 국가법령정보센터 「사회보장급여 관련 공통서식에 관한 고시」 [별지 제1호서식] 사회보장급여 신청(변경)서 <개정 2026. 5. 1.> PDF
(https://www.law.go.kr/LSW/flDownload.do?flSeq=163660115). 영상 「기초연금 서면 신청서 작성하기」(32mI5aXzCQk)가 이 신청서 4쪽을
3:01~10:08에 설명함(뒤의 소득재산신고서·금융정보 등 제공 동의서는 다른 서식이라 지도에 없음).

- 칸 위치: PDF에 들어 있는 글자 좌표(VLM 아님 — Qwen3-VL-4B grounding 시험 결과는 docs/experiments/form_grounding.md)
- 이 칸에 쓸 것: ① 서식 PDF의 공식 작성 방법(각주 1)~12)) 원문 ② 없으면 그 칸 이름이 나오는 영상 자막 원문 ③ 그것도 없으면 설명 없음.
  구역 전체 안내(예: 「가족사항은 배우자 정보만」)는 칸 설명이 아니라 구역 안내로 따로 표시
- 장면: 칸 이름이 나오는 자막부터(같은 구역 안, 최대 25초), 없으면 그 칸이 있는 구역 설명 장면
- 영상 구역 시간은 자막의 구역 시작 문장(아래 SECTIONS)에서 찾음

    PYTHONPATH=<pymupdf 설치 폴더> python backend/scripts/build_form_map.py
    (pymupdf는 .venv에 없음: uv pip install --target <폴더> --python .venv/bin/python pymupdf)
"""
import json, re, sys
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[2]
PDF = Path("/nfs/team/data/scenefinder_vlm/forms/ssb_form1_2026-05-01.pdf")
VIDEO = "32mI5aXzCQk"
SUBS = Path(f"/nfs/team/data/scenefinder_vlm/demo/index/{VIDEO}/subs.json")
FORM_ID = "ssb1"
DPI = 150
SC = DPI / 72
OUT_IMG = ROOT / "frontend/public/forms"
OUT = ROOT / "backend/data/form_maps" / f"{VIDEO}.json"

# 영상 구역: (구역, 시작 문장 일부) — 구역 끝 = 다음 구역 시작
SECTIONS = [("1쪽 안내", "첫 번째 장에는 신청인"), ("신청인", "첫 번째 항목인 신청인"), ("가족사항", "두 번째 항목인 가족사항"),
            ("급여계좌", "다음은 급여계좌 항목"), ("통지방법", "통지방법 선택란"), ("2쪽 안내", "두 번째 장에서 작성해야"),
            ("보장구분", "먼저 보장구분 항목"), ("요금 감면", "복지 대상자 요금 감면 신청 항목으로"), ("개인정보 수집 동의", "개인정보수집 및 활용동의가 반드시"),
            ("제3자 제공 동의", "3페이지 상단에 제3자 제공"), ("선택적 동의", "선택적 동의라는"), ("유의사항", "다음은 유의사항"),
            ("신청인 서명", "신청연월일과 신청인 성명"), ("4쪽 안내", "마지막 네 번째 장으로"), ("구비서식", "신청서 구비 소식과"), ("끝", "소득재산신고서 작성하기")]
# 구역 전체 안내(칸 설명이 아님): 구역 → 자막 문장 일부
SECTION_GUIDE = {"가족사항": "오직 배우자의 정보만", "부양의무자": "부양의무자 항목을 제외한", "급여계좌": "본인의 계좌정보를 작성"}
# 부양의무자는 영상에서 「작성하지 않음」만 말함 → 1쪽 안내 구역
SEC_OF = {"부양의무자": "1쪽 안내"}

# 칸: (id, 쪽, 구역, 칸 이름, PDF에서 찾을 글자, 몇 번째(0부터) 또는 (y최소,y최대) px, 자막 낱말, 공식 각주 번호)
F = [
    ("p1_name", 1, "신청인", "성명", "성명", (300, 360), ["성명", "성령"], None),
    ("p1_rrn", 1, "신청인", "주민등록번호", "주민등록번호", (290, 330), ["주민등록번호"], None),
    ("p1_rel", 1, "신청인", "세대주와의 관계", "세대주와의", (300, 340), ["세대주와의 관계"], None),
    ("p1_tel", 1, "신청인", "전화번호", "전화번호", (315, 350), ["전화번호"], None),
    ("p1_addr", 1, "신청인", "주소", "주소", (410, 440), ["주소"], 1),
    ("p1_mobile", 1, "신청인", "휴대전화", "휴대전화", (380, 412), ["휴대전화"], 2),
    ("p1_email", 1, "신청인", "전자우편", "전자우편", (440, 470), ["전자우편"], None),
    ("p1_f_rel", 1, "가족사항", "세대주와의 관계", "세대주와의", (505, 535), [], None),
    ("p1_f_name", 1, "가족사항", "성명", "성명", (520, 548), ["배우자의 성명"], None),
    ("p1_f_rrn", 1, "가족사항", "주민등록번호", "주민등록번호", (490, 520), ["주민등록번호"], None),
    ("p1_f_live", 1, "가족사항", "동거여부", "동거여부", (505, 532), ["동거여부"], None),
    ("p1_f_edu", 1, "가족사항", "학력·재학여부", "학력·재학여부", (505, 532), ["학력", "재학"], None),
    ("p1_f_health", 1, "가족사항", "건강상태", "건강상태", (505, 532), ["건강상태"], None),
    ("p1_f_job", 1, "가족사항", "취업상태", "취업상태", (495, 525), ["취업상태", "직업", "직장"], None),
    ("p1_f_tel", 1, "가족사항", "전화번호", "전화번호", (505, 532), ["전화번호"], None),
    ("p1_spouse", 1, "가족사항", "배우자 관계", "배우자 관계", (798, 828), ["배우자 관계"], 3),
    ("p1_passport", 1, "가족사항", "외국 여권 소지자명", "외국 여권 소지자명", (798, 828), ["여권"], 4),
    ("p1_born", 1, "가족사항", "국외 출생자명", "국외 출생자명", (828, 858), ["국외 출생"], 5),
    ("p1_dual", 1, "가족사항", "복수국적자명", "복수국적자명", (828, 858), ["복수국적"], 6),
    ("p1_dep", 1, "부양의무자", "부양의무자(전체)", "수급권자와의", (880, 912), ["부양의무자"], 7),
    ("p1_acc_rel", 1, "급여계좌", "신청인과의 관계", "신청인과의", (1170, 1200), [], None),
    ("p1_acc_name", 1, "급여계좌", "성명", "성명", (1183, 1212), [], None),
    ("p1_bank", 1, "급여계좌", "금융기관명", "금융기관명", (1183, 1212), ["금융기관"], None),
    ("p1_acc_no", 1, "급여계좌", "계좌번호", "계좌번호", (1183, 1212), ["계좌 정보", "계좌정보"], None),
    ("p1_acc_note", 1, "급여계좌", "비고(사유)", "비고(사유)", (1180, 1212), ["비고"], 8),
    ("p1_notice", 1, "통지방법", "통지방법", "통지방법", (1340, 1370), ["통지방법", "통지 방식"], None),
    ("p2_pension", 2, "보장구분", "노인 · 기초연금", "기초연금([", (560, 585), ["노인란의 기초연금"], None),
    ("p2_pension_sp", 2, "보장구분", "배우자 동시 신청", "배우자 동시 신청)", (560, 585), ["배우자 동시신청에도"], None),
    ("p2_fee_q", 2, "요금 감면", "자격구분 · 기초연금", "기초연금", (820, 840), ["기초연금과 휴대전화요금"], None),
    ("p2_fee_all", 2, "요금 감면", "전체 신청", "전체 신청", (848, 868), ["전체 서비스"], None),
    ("p2_fee_mobile", 2, "요금 감면", "휴대전화요금", "휴대전화요금", (875, 895), ["휴대전화요금 란"], None),
    ("p2_carrier", 2, "요금 감면", "이동통신사", "이동통신사", (970, 990), ["이동통신사를"], None),
    ("p2_fee_family", 2, "요금 감면", "가구원 추가 기재", "가구원 추가 기재", (1040, 1060), ["배우자의 휴대전화 요금 감면"], None),
    ("p2_privacy", 2, "개인정보 수집 동의", "개인정보 수집 및 활용 동의", "개인정보 수집 및 활용 동의", (1185, 1210), ["개인정보수집 및 활용동의란"], None),
    ("p3_third", 3, "제3자 제공 동의", "개인정보 제3자 제공 동의", "개인정보 제3자 제공 동의", (120, 145), ["제3자 제공"], None),
    ("p3_optional", 3, "선택적 동의", "선택적 동의", "선택적 동의", (370, 395), ["선택적 동의"], None),
    ("p3_caution", 3, "유의사항", "유의사항 확인", "유 의 사 항", (785, 810), ["유의사항의 내용"], None),
    ("p3_date", 3, "신청인 서명", "신청 연월일", "년", (1455, 1480), ["신청연월일"], None),
    ("p3_sign", 3, "신청인 서명", "신청인(대리 신청인) 성명·서명", "신청인(대리", (1488, 1512), ["신청인 성명, 서명란"], 12),
    ("p3_sign_sp", 3, "신청인 서명", "배우자 성명·서명", "(배우자 동시 신청 시) 배우자", (1510, 1537), ["배우자의 성명과 서명"], None),
    ("p4_period", 4, "4쪽 안내", "처리기한", "처 리", (255, 285), ["처리기한"], None),
    ("p4_forms", 4, "구비서식", "신청시 구비서식", "신청시 구비서식", (675, 695), ["구비 소식", "구비서식", "필수적으로 제출"], None),
    ("p4_docs", 4, "구비서식", "추가 제출서류", "추가 제출서류", (675, 695), ["추가 제출 서류", "추가 제출서류", "신분증", "통장계좌번호사본", "위임장"], None),
    ("p4_where", 4, "구비서식", "제출하는 곳", "제출하는 곳", (1455, 1480), ["제출하는 곳", "제출하시면", "국민연금공단"], None),
]


# 자막(음성 인식) 오타 중 뜻이 분명한 것만 화면 표시용으로 고침 — 원문 자막은 그대로 두고 화면에 「자막 오타 고침」 표시
ASR_FIX = {"성령": "성명", "과로 안에": "괄호 안에", "구비 소식": "구비서식", "실버주지": "실거주지", "법률원 배우자": "법률혼 배우자"}
DO = re.compile(r"작성|기재|체크|선택|적어|제출|입력|준비")
SKIP = re.compile(r"살펴보|넘어가|이동해|관한 부분입니다")


def fix_asr(t):
    fixed = t
    for a, b in ASR_FIX.items():
        fixed = fixed.replace(a, b)
    return fixed, fixed != t


def best_line(lines):
    """칸 이름이 나오는 자막 중 무엇을 하라는 문장(작성·체크·선택 등)을 먼저, 「살펴보겠습니다」류는 뒤로, 같으면 먼저 나오는 문장."""
    return max(lines, key=lambda x: (2 * bool(DO.search(x["text"])) - bool(SKIP.search(x["text"])), -x["start"]))


def norm(t):
    return re.sub(r"\s", "", t or "")


def find_box(page, text, rng):
    hits = page.search_for(text)
    for r in hits:
        y = (r.y0 + r.y1) / 2 * SC
        if rng[0] <= y <= rng[1]:
            return [round(r.x0 * SC), round(r.y0 * SC), round(r.x1 * SC), round(r.y1 * SC)]
    raise SystemExit(f"칸 위치 못 찾음: {text} {rng} 후보 {[(round(h.x0*SC), round((h.y0+h.y1)/2*SC)) for h in hits]}")


def notes(doc):
    """공식 각주(작성방법) 원문: 1쪽 1)~8), 3쪽 9)~12). 줄 단위로 읽어 번호별로 모음."""
    out = {}
    for pno, ymin in ((0, 1460), (2, 1570)):
        lines = {}
        for x0, y0, x1, y1, w, b, l, n in doc[pno].get_text("words"):
            if y0 * SC < ymin:
                continue
            lines.setdefault((b, l), [y0, []])[1].append(w)
        cur = None
        for y, ws in sorted(lines.values()):
            t = " ".join(ws)
            m = re.match(r"^(\d+)\)(?:,\s*(\d+)\))?\s*(.*)", t)
            if m:
                cur = [int(m.group(1))] + ([int(m.group(2))] if m.group(2) else [])
                for k in cur:
                    out[k] = m.group(3).strip()
            elif cur and not t.startswith("210mm"):
                for k in cur:
                    out[k] += " " + t
    return out


def main():
    doc = pymupdf.open(PDF)
    OUT_IMG.mkdir(parents=True, exist_ok=True); OUT.parent.mkdir(parents=True, exist_ok=True)
    pages = []
    for i, p in enumerate(doc):
        pix = p.get_pixmap(dpi=DPI); f = OUT_IMG / f"{FORM_ID}_p{i + 1}.png"; pix.save(f)
        pages.append({"n": i + 1, "image": f"forms/{f.name}", "width": pix.width, "height": pix.height})
    subs = [{"start": s["start_time"], "end": s["end_time"], "text": s["text"].strip()} for s in json.loads(SUBS.read_text())["segments"]]
    sec_t = []
    for name, phrase in SECTIONS:
        s = next((x for x in subs if norm(phrase) in norm(x["text"])), None)
        if not s:
            raise SystemExit(f"구역 시작 문장 못 찾음: {phrase}")
        sec_t.append((name, s["start"]))
    rng = {name: (t, sec_t[i + 1][1]) for i, (name, t) in enumerate(sec_t[:-1])}
    note = notes(doc)
    fields = []
    for fid, pg, sec, label, find, yr, keys, nk in F:
        box = find_box(doc[pg - 1], find, yr)
        s0, s1 = rng[SEC_OF.get(sec, sec)]
        inside = [x for x in subs if s0 - 0.5 <= x["start"] < s1]
        hits = [x for x in inside if any(norm(k) in norm(x["text"]) for k in keys)] if keys else []
        hit = hits[0] if hits else None
        if hit:
            scene = {"start": hit["start"], "end": min(s1, hit["start"] + 25)}   # 처음 나오는 곳부터
            vtext, vfix = fix_asr(best_line(hits)["text"])
        else:
            scene = {"start": s0, "end": min(s1, s0 + 40)}
            vtext, vfix = None, False
        guide = next((fix_asr(x["text"])[0] for x in subs if sec in SECTION_GUIDE and norm(SECTION_GUIDE[sec]) in norm(x["text"])), None)
        vlabel = "영상 화면 기준" + (" · 자막 오타 고침" if vfix else "")
        official = {"text": note[nk], "source": "official", "label": f"공식 서식 작성 방법 {nk})"} if nk and nk in note else None
        video = {"text": vtext, "source": "video", "label": vlabel} if vtext else None
        write = official or video
        also = video if official and video else None   # 공식 작성 방법이 1순위, 영상 설명은 둘째 줄
        fields.append({"id": fid, "page": pg, "section": sec, "label": label, "box": box, "scene": scene,
                       "sceneLevel": "field" if hit else "section", "write": write, "also": also, "videoExplained": bool(hit),
                       "videoText": vtext, "sectionGuide": guide})
    out = {"form": {"id": FORM_ID, "title": "사회보장급여 신청(변경)서", "revision": "개정 2026. 5. 1.",
                    "source": "국가법령정보센터 「사회보장급여 관련 공통서식에 관한 고시」 [별지 제1호서식]",
                    "sourceUrl": "https://www.law.go.kr/LSW/flDownload.do?flSeq=163660115", "pages": pages,
                    "note": "영상 속 서식은 이전 개정판이라 칸 위치·이름이 조금 다를 수 있어요."},
           "video": VIDEO, "videoRange": [sec_t[0][1], sec_t[-1][1]], "fields": fields}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    n_v = sum(f["videoExplained"] for f in fields); n_o = sum(1 for f in fields if f["write"] and f["write"]["source"] == "official")
    print(f"칸 {len(fields)}개 · 영상 설명 있음 {n_v} · 공식 작성 방법 {n_o} · 둘 다 없음 {sum(1 for f in fields if not f['write'])} → {OUT}")
    for f in fields:
        print(f"  p{f['page']} {f['section']}/{f['label']}: {f['sceneLevel']} {int(f['scene']['start'])//60}:{int(f['scene']['start'])%60:02d}",
              (f["write"] or {}).get("label", "설명 없음"), "|", ((f["write"] or {}).get("text") or "")[:50])


if __name__ == "__main__":
    main()
