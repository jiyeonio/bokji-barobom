"""내 신청서 비추기 (2026-11-15): 사진 속 서식을 등록된 빈 서식(PDF를 이미지로 만든 것)에 겹쳐 칸 위치를 옮김.

- 방법: OpenCV ORB 특징점 + RANSAC 호모그래피(빈 서식 → 사진). VLM을 쓰지 않음
  (Qwen3-VL-4B grounding은 사진 흉내에서 10/33, OpenCV 서식 맞추기는 33/33 — docs/experiments/form_grounding.md)
- 사진은 메모리에서만 처리하고 저장·기록하지 않음(파일·DB·로그에 남기지 않음). 손글씨 내용은 읽지 않고 인쇄된 서식 선만 맞춤
- 등록된 서식이 아니거나 맞는 점이 적으면 matched=false (지어내지 않음)
"""
import json
import threading
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
MAPS = ROOT / "backend/data/form_maps"
PUBLIC = ROOT / "frontend/public"
MAX_SIDE = 1600
MIN_INLIERS = 60

_lock = threading.Lock()
_tpl = None


def form_map(video_id):
    f = MAPS / f"{video_id}.json"
    return json.loads(f.read_text()) if f.exists() else None


def _templates():
    """등록된 서식 쪽마다 ORB 특징점(처음 한 번)."""
    global _tpl
    with _lock:
        if _tpl is None:
            _tpl = []
            orb = cv2.ORB_create(5000)
            for f in sorted(MAPS.glob("*.json")):
                m = json.loads(f.read_text())
                for pg in m["form"]["pages"]:
                    img = cv2.imread(str(PUBLIC / pg["image"]), cv2.IMREAD_GRAYSCALE)
                    if img is None:
                        continue
                    k, d = orb.detectAndCompute(img, None)
                    _tpl.append({"video": m["video"], "form": m["form"]["id"], "title": m["form"]["title"], "page": pg["n"], "kp": k, "des": d,
                                 "size": img.shape[::-1], "fields": [x for x in m["fields"] if x["page"] == pg["n"]]})
    return _tpl


def align(data: bytes):
    arr = np.frombuffer(data, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
    del arr
    if img is None:
        return {"matched": False, "reason": "사진을 읽지 못했어요"}
    h, w = img.shape
    s = min(1.0, MAX_SIDE / max(h, w))
    if s < 1:
        img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    H_, W_ = img.shape
    orb = cv2.ORB_create(6000)
    kp, des = orb.detectAndCompute(img, None)
    del img
    if des is None or len(kp) < 50:
        return {"matched": False, "reason": "서식을 알아볼 만한 선·글자가 보이지 않아요", "width": W_, "height": H_}
    best = None
    bf = cv2.BFMatcher(cv2.NORM_HAMMING)
    for t in _templates():
        pairs = bf.knnMatch(t["des"], des, k=2)
        good = [m for m, n in (p for p in pairs if len(p) == 2) if m.distance < 0.8 * n.distance]
        if len(good) < MIN_INLIERS:
            continue
        A = np.float32([t["kp"][m.queryIdx].pt for m in good]); B = np.float32([kp[m.trainIdx].pt for m in good])
        Hm, inl = cv2.findHomography(A, B, cv2.RANSAC, 5.0)
        if Hm is None:
            continue
        n = int(inl.sum())
        if best is None or n > best[0]:
            best = (n, t, Hm)
    if not best or best[0] < MIN_INLIERS:
        return {"matched": False, "reason": "등록된 서식과 맞지 않아요", "width": W_, "height": H_, "inliers": best[0] if best else 0}
    n, t, Hm = best
    tw, th = t["size"]
    corners = cv2.perspectiveTransform(np.float32([[[0, 0], [tw, 0], [tw, th], [0, th]]]), Hm)[0]
    area = cv2.contourArea(corners)
    if not cv2.isContourConvex(corners.astype(np.int32)) or area < 0.15 * W_ * H_:   # 뒤집히거나 너무 작게 겹치면 믿지 않음
        return {"matched": False, "reason": "서식이 사진에서 너무 작거나 많이 기울어져 있어요", "width": W_, "height": H_, "inliers": n}
    out = []
    for f in t["fields"]:
        b = f["box"]
        q = cv2.perspectiveTransform(np.float32([[[b[0], b[1]], [b[2], b[1]], [b[2], b[3]], [b[0], b[3]]]]), Hm)[0]
        out.append({"id": f["id"], "box": [float(q[:, 0].min()), float(q[:, 1].min()), float(q[:, 0].max()), float(q[:, 1].max())]})
    return {"matched": True, "video": t["video"], "form": t["form"], "title": t["title"], "page": t["page"], "inliers": n,
            "width": W_, "height": H_, "fields": out}
