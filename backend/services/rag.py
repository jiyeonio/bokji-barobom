"""정책 RAG (2026-11-15): 공공데이터 정책 청크(backend/data/rag/chunks.jsonl) 검색 + Claude 답변.

- 검색: 서비스의 파인튜닝 MiniLM(SCENEFINDER_MINILM_MODEL_PATH)으로 청크 임베딩 → 코사인 상위 k(기본 5). 임베딩은 backend/data/rag/emb.npy에
  저장하고 청크 파일이 바뀌면 다시 만듦. 청크 임베딩 글 = 「[정책명 · 필드] 원문」.
- 답변: Claude API(claude-opus-5-5, effort low, 구조화 출력). 규칙은 SYSTEM_RAG. 서버가 확인하는 것:
  · 문장마다 근거 청크 ID — 검색된 청크가 아닌 ID는 지우고, 근거가 하나도 없는 사실 문장은 답에서 뺌(debug에 남김)
  · 공식 URL·기준일은 모델이 쓰지 않고 인용된 청크의 메타데이터로 서버가 붙임
  · 근거 문장이 하나도 없으면 「공식 정보에서 확인되지 않아요」
- API 키: 환경변수 ANTHROPIC_API_KEY(backend/.env, git 제외). SDK는 저장소 안 pylib/(git 제외)에 설치.
"""
import hashlib, json, os, re, sys, time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
CHUNKS = ROOT / "backend/data/rag/chunks.jsonl"
EMB = ROOT / "backend/data/rag/emb.npy"
MODEL = "claude-opus-5-5"
NOT_FOUND = "공식 정보에서 확인되지 않아요"
if str(ROOT / "pylib") not in sys.path:
    sys.path.append(str(ROOT / "pylib"))   # .venv 패키지가 먼저, pylib은 없는 것만 채움

# 질문 의도 낱말 → 필드 (welfare_service.INTENTS와 같은 낱말 + 문의처). 파인튜닝 MiniLM은 영상 자막 검색용이라 「얼마」 같은 질문을 필드에 잘 못 맞춤
INTENT_FIELDS = [(r"서류|챙겨|준비물|가져가|내야|제출|필요한 거|뭐 내|뭘 내", ["구비서류"]),
                 (r"언제|기간|아직|마감|지금도|신청 되|신청돼|되는 거|접수", ["신청기간"]),
                 (r"어디|어떻게 신청|신청하는 법|신청 방법|신청방법|신청해요|신청하나요", ["신청방법"]),
                 (r"누가|대상|자격|받을 수|해당|조건", ["지원대상", "선정기준"]),
                 (r"얼마|금액|받는 돈|지원금|몇 만|만 원|만원", ["지원내용"]),
                 (r"문의|전화|연락|상담", ["문의처"])]
BOOST = 0.15

SYSTEM_RAG = """당신은 복지 정책 안내 도우미입니다. 사용자의 질문에 아래 <documents>의 공식 정책 정보(공공데이터)만 근거로 한국어로 답합니다.

규칙:
1. <documents>에 있는 내용으로만 답하세요. 문서에 없는 사실·숫자·절차를 추측하거나 일반 지식으로 채우지 마세요.
2. 사실을 말하는 문장(kind="fact")마다 그 근거가 된 문서의 chunk_id를 chunk_ids에 넣으세요. 근거가 없는 문장은 쓰지 마세요.
3. 질문의 전체 또는 일부가 문서에 없으면, 그 부분에 대해 "…는 공식 정보에서 확인되지 않아요."라는 문장을 kind="not_found", chunk_ids=[]로 쓰세요.
   질문 전체에 답할 근거가 없으면 not_found=true로 하고 sentences에는 그 한 문장만 쓰세요.
4. <video_subtitles>나 질문에 영상에서 들은 금액·조건이 나오고 문서 내용과 다르면, 문서(최신 공식 정보) 기준으로 안내하고
   "영상에서는 …라고 나오지만, 현재 공식 정보는 …예요." 같은 문장을 kind="video_diff"로, 근거 문서의 chunk_id와 함께 쓰세요.
   영상 내용은 게시 당시 기준이라 최신이 아닐 수 있습니다. 영상 내용만으로 사실을 단정하지 마세요.
   <video_subtitles>는 질문과 관련된 금액·조건이 문서와 다른지 확인할 때만 쓰고, 질문과 관계없는 영상 내용은 언급하지 마세요
   (영상에 있는 다른 내용에 대해 "확인되지 않아요" 문장을 쓰지 마세요. "확인되지 않아요"는 사용자가 물은 것에만).
5. 공식 URL과 기준일은 쓰지 마세요(서버가 붙입니다). 답은 짧고 쉬운 말로, 3~6문장 안에서."""

SYSTEM_LLM_ONLY = """당신은 복지 정책 안내 도우미입니다. 사용자의 질문에 한국어로 답합니다. 참고 문서는 주어지지 않습니다.
아는 범위에서 정확하게 답하고, 확실하지 않거나 모르는 부분은 "공식 정보에서 확인되지 않아요"라고 말하세요.
영상에서 들은 금액이 질문에 나오면 현재 기준과 다른지 알려 주세요. 답은 짧고 쉬운 말로, 3~6문장 안에서. chunk_ids는 비워 두세요."""

SCHEMA = {
    "type": "object",
    "properties": {
        "not_found": {"type": "boolean"},
        "sentences": {"type": "array", "items": {
            "type": "object",
            "properties": {"text": {"type": "string"}, "kind": {"type": "string", "enum": ["fact", "not_found", "video_diff"]},
                           "chunk_ids": {"type": "array", "items": {"type": "string"}}},
            "required": ["text", "kind", "chunk_ids"], "additionalProperties": False}},
    },
    "required": ["not_found", "sentences"], "additionalProperties": False,
}


def load_chunks():
    return [json.loads(l) for l in CHUNKS.read_text(encoding="utf-8").splitlines() if l.strip()]


class RagIndex:
    def __init__(self, minilm=None):
        self.chunks = load_chunks()
        self.by_id = {c["chunk_id"]: c for c in self.chunks}
        if minilm is None:
            from sentence_transformers import SentenceTransformer
            minilm = SentenceTransformer(os.environ["SCENEFINDER_MINILM_MODEL_PATH"])
        self.m = minilm
        texts = [f"[{c['policy_name']} · {c['field']}] {c['text']}" for c in self.chunks]
        h = hashlib.sha1("\n".join(texts).encode()).hexdigest()[:12]
        meta = EMB.with_suffix(".json")
        if EMB.exists() and meta.exists() and json.loads(meta.read_text()).get("hash") == h:
            self.emb = np.load(EMB)
        else:
            self.emb = np.asarray(self.m.encode(texts, normalize_embeddings=True, convert_to_numpy=True), dtype=np.float32)
            np.save(EMB, self.emb); meta.write_text(json.dumps({"hash": h, "n": len(texts), "model": "fine-tuned MiniLM"}))

    def search(self, q, k=5, policy_id=None, boost=True):
        """코사인 상위 k. boost=True면 질문 의도 낱말(서비스의 welfare_service.INTENTS와 같은 규칙)에 맞는 필드 청크에 +BOOST."""
        qv = np.asarray(self.m.encode(q, normalize_embeddings=True, convert_to_numpy=True), dtype=np.float32)
        sc = self.emb @ qv
        if boost:
            want = {f for pat, fs in INTENT_FIELDS if re.search(pat, q) for f in fs}
            if want:
                sc = sc + np.array([BOOST if c["field"] in want else 0.0 for c in self.chunks], dtype=np.float32)
        idx = [i for i in np.argsort(-sc) if not policy_id or self.chunks[i]["policy_id"] == policy_id][:k]
        return [self.chunks[i] | {"score": round(float(sc[i]), 4)} for i in idx]


_client = None


def has_key():
    """backend/.env의 ANTHROPIC_API_KEY(값은 출력하지 않음)."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        from dotenv import load_dotenv
        load_dotenv(ROOT / "backend/.env")
    return bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())


def client():
    global _client
    if _client is None:
        import anthropic
        _client = anthropic.Anthropic()
    return _client


def _docs_block(chunks):
    return "<documents>\n" + "\n".join(
        f'<document chunk_id="{c["chunk_id"]}" policy="{c["policy_name"]}" field="{c["field"]}" base_date="{c["base_date"]}">\n{c["text"]}\n</document>'
        for c in chunks) + "\n</documents>"


def generate(question, chunks=None, video=None, mode="rag"):
    """mode='rag': 검색된 청크로만 답함 / 'llm_only': 문서 없이(평가 비교용). 반환: 화면용 답 + 근거·출처·디버그."""
    t0 = time.time()
    if mode == "rag":
        parts = [_docs_block(chunks or [])]
        if video:
            parts.append(f'<video_subtitles title="{video.get("title", "")}" published="{video.get("published", "")}" note="게시 당시 기준, 최신 아님">\n'
                         f'{video.get("text", "")}\n</video_subtitles>')
        user = "\n\n".join(parts) + f"\n\n<question>{question}</question>"
        system = SYSTEM_RAG
    else:
        user = f"<question>{question}</question>"
        system = SYSTEM_LLM_ONLY
    import anthropic
    if not has_key():   # 키가 없으면 SDK는 요청할 때 TypeError — 미리 확인
        return {"error": "AI 답변을 쓸 수 없어요(API 키 확인 필요)", "mode": mode}
    cl = client()
    try:
        r = cl.beta.messages.create(
            model=MODEL, max_tokens=8000, system=system, messages=[{"role": "user", "content": user}],
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
            betas=["server-side-fallback-2026-07-01"], fallbacks="default",
        )
    except anthropic.AuthenticationError:
        return {"error": "AI 답변을 쓸 수 없어요(API 키 확인 필요)", "mode": mode}
    except anthropic.RateLimitError:
        return {"error": "요청이 많아요. 잠시 후 다시 시도해 주세요", "mode": mode}
    except anthropic.APIStatusError as e:
        return {"error": f"AI 답변 오류({e.status_code})", "mode": mode}
    except anthropic.APIConnectionError:
        return {"error": "AI 서버에 연결하지 못했어요", "mode": mode}
    usage = {"input_tokens": r.usage.input_tokens, "output_tokens": r.usage.output_tokens, "model": r.model, "sec": round(time.time() - t0, 2)}
    if r.stop_reason == "refusal":
        return {"error": "AI가 이 질문에는 답하지 않았어요", "mode": mode, "usage": usage}
    text = next((b.text for b in r.content if b.type == "text"), "")
    try:
        out = json.loads(text)
    except json.JSONDecodeError:
        return {"error": "AI 답변 형식 오류", "mode": mode, "usage": usage, "raw": text[:500]}
    return post_process(out, chunks or [], mode) | {"usage": usage, "mode": mode}


def post_process(out, chunks, mode):
    by = {c["chunk_id"]: c for c in chunks}
    kept, dropped = [], []
    for s in out.get("sentences", []):
        ids = [i for i in s.get("chunk_ids", []) if i in by]
        bad = [i for i in s.get("chunk_ids", []) if i not in by]
        if mode == "rag" and s.get("kind") in ("fact", "video_diff") and not ids:
            dropped.append(s | {"why": "근거 청크 없음"}); continue
        kept.append({"text": s["text"].strip(), "kind": s.get("kind", "fact"), "chunk_ids": ids} | ({"invalid_ids": bad} if bad else {}))
    grounded = [s for s in kept if s["kind"] in ("fact", "video_diff")]
    not_found = mode == "rag" and (bool(out.get("not_found")) or not grounded)
    if not_found and not grounded:
        kept = [{"text": f"{NOT_FOUND}.", "kind": "not_found", "chunk_ids": []}]
    used = {i for s in kept for i in s["chunk_ids"]}
    sources, seen = [], set()
    for i in sorted(used):
        c = by[i]
        if c["policy_id"] in seen:
            continue
        seen.add(c["policy_id"])
        sources.append({"policyId": c["policy_id"], "policyName": c["policy_name"], "urls": c["official_urls"], "baseDate": c["base_date"],
                        "fetchedAt": c["fetched_at"], "source": c["source"]})
    answer = " ".join(s["text"] for s in kept)
    footer = " / ".join(f"{s['policyName']}: {s['urls'][0]['url'] if s['urls'] else ''} (기준일 {s['baseDate']})" for s in sources)
    return {"answer": answer, "sentences": kept, "notFound": not_found, "sources": sources, "footer": footer,
            "debug": {"dropped": dropped, "retrieved": [c["chunk_id"] for c in chunks]}}
