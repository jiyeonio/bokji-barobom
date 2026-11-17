"""복지바로봄 시연용 백엔드 (복지 검색·영상 API만, Supabase·기존 분석 라우터 없이).

    cd ~/scenefinder && set -a && . backend/.env && set +a
    HF_HUB_OFFLINE=1 HF_HOME=/nfs/team/data/huggingface SEARCH_MODEL=n3_vlm QUERY_CACHE=on \
      .venv/bin/uvicorn backend.welfare_app:app --host 127.0.0.1 --port 8000

SEARCH_MODEL: n3_vlm(기본, VLM 재판별 포함) / n3. QUERY_CACHE=on: 시연·추천 질문 캐시(backend/scripts/precompute_cache.py). 첫 요청 전에 모델·색인을 미리 올림(startup).
"""
import sys, threading
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend/services")]
from welfare_router import create_welfare_router, searcher  # noqa: E402

app = FastAPI(title="복지바로봄 API")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"], allow_methods=["*"], allow_headers=["*"])
app.include_router(create_welfare_router())


@app.on_event("startup")
def _load():
    def warm():   # 모델과 시연 영상 색인(자막 창 임베딩 등)을 미리 올려 첫 질문도 빠르게
        s = searcher()
        for y in s.ws.catalog:
            s.ws.video(y)
    threading.Thread(target=warm, daemon=True).start()
