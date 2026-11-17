"""신청서 칸 찾기 시험 (2026-11-15): Qwen3-VL-4B grounding이 서식 이미지에서 칸 이름 위치를 얼마나 정확히 찾는지.

정답: 국가법령정보센터 「사회보장급여 관련 공통서식에 관한 고시」 [별지 제1호서식] 사회보장급여 신청(변경)서 1쪽 PDF의
글자 위치(PDF에 들어 있는 글자 좌표, 사람이 손으로 그린 것 아님) — 칸 이름 33개.
조건: ① 깨끗한 서식(150dpi) ② 휴대폰 사진 흉내(기울임·원근·흐림·조명·JPEG) ③ ①②를 위·아래 반으로 나눠 묻기
맞음 기준: 예측 칸 이름이 정답 이름과 같고(띄어쓰기·각주 숫자 무시, 한쪽이 다른 쪽을 포함해도 됨) 예측 상자 가운데가
정답 상자(사방 12px 여유) 안. 정답 하나에 예측 하나만.
비교: OpenCV 서식 맞추기(ORB 특징점 + 호모그래피로 사진을 빈 서식에 겹친 뒤, PDF 칸 위치를 그대로 옮김) — VLM 없이.

    python ai/experiments/form_map/grounding_test.py <서식 PNG> <결과 폴더>   (GPU — API 서버를 내린 뒤)
"""
import json, re, sys, time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / "ai/experiments/vlm_model")]

# (구역, 칸 이름, 정답 상자 x0,y0,x1,y1 — 150dpi 1240×1753, PDF 글자 좌표)
GT = [("신청인", "성명", [172, 322, 213, 342]), ("신청인", "주민등록번호", [343, 298, 484, 366]), ("신청인", "세대주와의 관계", [623, 308, 727, 355]),
      ("신청인", "전화번호", [835, 322, 918, 342]), ("신청인", "주소", [172, 415, 213, 436]), ("신청인", "휴대전화", [834, 384, 919, 408]),
      ("신청인", "전자우편", [835, 444, 918, 464]),
      ("가족사항", "세대주와의 관계", [161, 510, 265, 558]), ("가족사항", "성명", [281, 523, 323, 544]), ("가족사항", "주민등록번호", [360, 495, 500, 573]),
      ("가족사항", "동거여부", [523, 509, 613, 559]), ("가족사항", "학력·재학여부", [613, 509, 737, 559]), ("가족사항", "건강상태", [738, 509, 825, 559]),
      ("가족사항", "취업상태", [882, 500, 966, 521]), ("가족사항", "직업", [858, 546, 895, 565]), ("가족사항", "직장명", [947, 546, 1004, 565]),
      ("가족사항", "전화번호", [1030, 509, 1114, 559]),
      ("가족사항", "배우자 관계", [180, 802, 330, 823]), ("가족사항", "외국 여권 소지자명", [720, 802, 915, 823]),
      ("가족사항", "국외 출생자명", [180, 832, 345, 853]), ("가족사항", "복수국적자명", [728, 832, 875, 853]),
      ("부양의무자", "수급권자와의 관계", [159, 886, 267, 932]), ("부양의무자", "성명", [281, 899, 323, 920]), ("부양의무자", "주민등록번호", [360, 876, 500, 942]),
      ("부양의무자", "주소", [632, 899, 715, 920]), ("부양의무자", "가구원 수", [830, 899, 923, 920]), ("부양의무자", "전화번호", [982, 899, 1066, 920]),
      ("급여계좌", "신청인과의 관계", [161, 1175, 265, 1221]), ("급여계좌", "성명", [281, 1187, 323, 1208]), ("급여계좌", "금융기관명", [378, 1187, 482, 1208]),
      ("급여계좌", "계좌번호", [632, 1187, 715, 1208]), ("급여계좌", "비고(사유)", [914, 1185, 1031, 1208]), ("통지방법", "통지방법", [152, 1344, 236, 1365])]
PROMPT = """이 이미지는 복지 신청서 서식입니다. 서식에 인쇄된 칸 이름(예: 성명, 주민등록번호, 주소, 전화번호, 계좌번호 등 사람이 내용을 써야 하는 칸의 제목)을 모두 찾아,
각각의 위치를 JSON 목록으로만 답하세요. 형식: [{"label": "칸 이름", "bbox_2d": [x1, y1, x2, y2]}, ...]
같은 이름이 여러 번 나오면 모두 따로 쓰세요. 칸 제목 글자만 상자로 감싸세요."""


def norm(t):
    t = re.sub(r"\(.*?\)|[0-9)\s·ㆍ.,:/]", "", t or "")
    return t


def parse(txt, W, H, ox=0, oy=0, rel=True):
    m = re.search(r"\[.*\]", txt, re.S)
    try:
        items = json.loads(m.group(0)) if m else []
    except Exception:
        items = [json.loads(x) for x in re.findall(r"\{[^{}]*\}", txt) if '"bbox_2d"' in x and _ok(x)]
    out = []
    for it in items:
        b = it.get("bbox_2d")
        if not (isinstance(b, list) and len(b) == 4):
            continue
        b = [float(v) for v in b]
        if rel:
            b = [b[0] / 1000 * W, b[1] / 1000 * H, b[2] / 1000 * W, b[3] / 1000 * H]
        out.append({"label": str(it.get("label", "")), "box": [b[0] + ox, b[1] + oy, b[2] + ox, b[3] + oy]})
    return out


def _ok(x):
    try:
        json.loads(x); return True
    except Exception:
        return False


def score(preds, gts, pad=12):
    used, hits = set(), []
    for gi, (sec, lab, g) in enumerate(gts):
        best = None
        for pi, p in enumerate(preds):
            if pi in used:
                continue
            a, b = norm(p["label"]), norm(lab)
            if not a or not (a == b or a in b or b in a):
                continue
            cx, cy = (p["box"][0] + p["box"][2]) / 2, (p["box"][1] + p["box"][3]) / 2
            if g[0] - pad <= cx <= g[2] + pad and g[1] - pad <= cy <= g[3] + pad:
                best = pi; break
        if best is not None:
            used.add(best); hits.append(gi)
    pos = sum(1 for g in gts if any(g[2][0] - 12 <= (p["box"][0] + p["box"][2]) / 2 <= g[2][2] + 12 and g[2][1] - 12 <= (p["box"][1] + p["box"][3]) / 2 <= g[2][3] + 12 for p in preds))
    return {"correct": len(hits), "total": len(gts), "preds": len(preds), "precision": round(len(hits) / max(1, len(preds)), 3), "position_only": pos, "hit_ids": hits}


def photo_like(img, seed=0):
    """휴대폰으로 찍은 것처럼: 원근(모서리 4곳 3~6% 흔들기) + 2° 회전 + 흐림 + 한쪽 어두운 조명 + JPEG 70. 정답 상자도 같은 변환으로 옮김."""
    rng = np.random.default_rng(seed); H, W = img.shape[:2]
    src = np.float32([[0, 0], [W, 0], [W, H], [0, H]])
    d = rng.uniform(0.03, 0.06, (4, 2)) * [W, H] * [[1, 1], [-1, 1], [-1, -1], [1, -1]]
    dst = (src + d).astype(np.float32)
    M = cv2.getPerspectiveTransform(src, dst)
    R = cv2.getRotationMatrix2D((W / 2, H / 2), 2.0, 1.0); R3 = np.vstack([R, [0, 0, 1]])
    M = R3 @ M
    out = cv2.warpPerspective(img, M, (W, H), borderValue=(200, 200, 200))
    out = cv2.GaussianBlur(out, (5, 5), 1.2)
    grad = np.linspace(0.7, 1.05, W)[None, :, None]
    out = np.clip(out * grad, 0, 255).astype(np.uint8)
    ok, enc = cv2.imencode(".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, 70]); out = cv2.imdecode(enc, 1)

    def tb(b):
        pts = np.float32([[b[0], b[1]], [b[2], b[1]], [b[2], b[3]], [b[0], b[3]]])[None]
        q = cv2.perspectiveTransform(pts, M)[0]
        return [float(q[:, 0].min()), float(q[:, 1].min()), float(q[:, 0].max()), float(q[:, 1].max())]
    return out, [(s, l, tb(b)) for s, l, b in GT], M


def align_transfer(photo, template):
    """OpenCV 서식 맞추기: ORB 특징점 → 호모그래피(템플릿→사진) → PDF 칸 상자를 사진 좌표로."""
    g1 = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY); g2 = cv2.cvtColor(photo, cv2.COLOR_BGR2GRAY)
    orb = cv2.ORB_create(5000)
    k1, d1 = orb.detectAndCompute(g1, None); k2, d2 = orb.detectAndCompute(g2, None)
    m = sorted(cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True).match(d1, d2), key=lambda x: x.distance)[:800]
    A = np.float32([k1[x.queryIdx].pt for x in m]); B = np.float32([k2[x.trainIdx].pt for x in m])
    Hm, inl = cv2.findHomography(A, B, cv2.RANSAC, 4.0)
    preds = []
    for s, l, b in GT:
        pts = np.float32([[b[0], b[1]], [b[2], b[1]], [b[2], b[3]], [b[0], b[3]]])[None]
        q = cv2.perspectiveTransform(pts, Hm)[0]
        preds.append({"label": l, "box": [float(q[:, 0].min()), float(q[:, 1].min()), float(q[:, 0].max()), float(q[:, 1].max())]})
    return preds, int(inl.sum())


def draw(img, preds, gts, hits, path):
    im = img.copy()
    for i, (s, l, g) in enumerate(gts):
        cv2.rectangle(im, (int(g[0]), int(g[1])), (int(g[2]), int(g[3])), (0, 170, 0) if i in hits else (0, 0, 255), 2)
    for p in preds:
        b = [int(v) for v in p["box"]]
        cv2.rectangle(im, (b[0], b[1]), (b[2], b[3]), (255, 120, 0), 1)
    cv2.imwrite(str(path), im)


def main():
    src, out = Path(sys.argv[1]), Path(sys.argv[2]); out.mkdir(parents=True, exist_ok=True)
    clean = cv2.imread(str(src)); H, W = clean.shape[:2]
    photo, gt_photo, _ = photo_like(clean)
    cv2.imwrite(str(out / "photo_like.jpg"), photo)
    res = {}
    # 비교: OpenCV 서식 맞추기 (사진 → 빈 서식)
    t0 = time.time(); ap, ninl = align_transfer(photo, clean)
    res["opencv_align_photo"] = score(ap, gt_photo) | {"inliers": ninl, "sec": round(time.time() - t0, 2)}
    draw(photo, ap, gt_photo, res["opencv_align_photo"]["hit_ids"], out / "opencv_align_photo.jpg")
    from lora_make_data import Gen
    g = Gen()

    def ask(img, ox=0, oy=0):
        h, w = img.shape[:2]
        msgs = [[{"role": "user", "content": [{"type": "image", "image": cv2.cvtColor(img, cv2.COLOR_BGR2RGB)}, {"type": "text", "text": PROMPT}]}]]
        t = time.time(); txt = g(msgs, max_new=3000)[0]
        return txt, parse(txt, w, h, ox, oy), time.time() - t
    for name, img, gts in [("clean", clean, GT), ("photo", photo, gt_photo)]:
        txt, preds, sec = ask(img)
        res[f"vlm_{name}_full"] = score(preds, gts) | {"sec": round(sec, 1)}
        (out / f"vlm_{name}_full.txt").write_text(txt)
        draw(img, preds, gts, res[f"vlm_{name}_full"]["hit_ids"], out / f"vlm_{name}_full.jpg")
        # 위·아래 반 (겹침 10%)
        h = img.shape[0]; cut = int(h * 0.55); top = img[:cut]; bot_y = int(h * 0.45); bot = img[bot_y:]
        t1, p1, s1 = ask(top); t2, p2, s2 = ask(bot, 0, bot_y)
        preds = p1 + p2
        res[f"vlm_{name}_halves"] = score(preds, gts) | {"sec": round(s1 + s2, 1)}
        (out / f"vlm_{name}_halves.txt").write_text(t1 + "\n----\n" + t2)
        draw(img, preds, gts, res[f"vlm_{name}_halves"]["hit_ids"], out / f"vlm_{name}_halves.jpg")
        print(name, res[f"vlm_{name}_full"], res[f"vlm_{name}_halves"], flush=True)
    for k, v in res.items():
        v.pop("hit_ids", None)
    (out / "result.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
