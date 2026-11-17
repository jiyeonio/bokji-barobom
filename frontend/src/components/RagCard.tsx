// AI 답변 카드 (RAG) — 공공데이터 정책 정보(청크)로만 답한 문장 + 근거 항목 + 공식 출처·기준일 + 관련 장면.
// 누를 때만 질문을 보냄(질문이 AI로 전송됨을 안내).
import { useEffect, useState } from 'react';
import { Icon } from './Icon';
import { SourceTag } from './Common';
import { askRag, type RagAnswer } from '../data/api';
import { fmt } from '../utils';

const fieldOf = (id: string) => id.split('#')[1] ?? id;

export function RagCard({ question, policyId, scene }: { question: string; policyId?: string; scene?: { href: string; t: number; title: string; videoId: string } }) {
  const [res, setRes] = useState<RagAnswer | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { setRes(null); setBusy(false); }, [question]);
  const run = () => {
    setBusy(true);
    askRag({ question, policyId: policyId && !policyId.startsWith('db:') ? policyId : undefined, videoId: scene?.videoId, t: scene?.t }).then((r) => { setRes(r); setBusy(false); });
  };
  return (
    <article className="card rag" aria-label="AI 답변">
      <div className="strip"><span className="rag-tag"><Icon name="scan" />AI 답변</span><span className="r">공식 정책 정보(공공데이터)로만 답해요</span></div>
      <div className="in">
        {!res && (
          <button className="btn btn-pri" onClick={run} disabled={busy}><Icon name="scan" />{busy ? 'AI가 공식 정보를 찾는 중…' : 'AI 답변 받기'}</button>
        )}
        {res?.error && <p className="err">{res.error}</p>}
        {res && !res.error && (
          <>
            <div className="rag-ans">
              {(res.sentences ?? []).map((s, i) => (
                <p key={i} className={s.kind}>
                  {s.kind === 'video_diff' && <Icon name="alert" />}
                  {s.text}
                  {s.chunk_ids.map((c) => <sup key={c} title={c}>{fieldOf(c)}</sup>)}
                </p>
              ))}
            </div>
            {(res.sources ?? []).length > 0 && (
              <div className="srcs">
                {res.sources!.map((s) => (
                  <p key={s.policyId}><SourceTag kind="gov" /><b>{s.policyName}</b> · 기준일 {s.baseDate} ·{' '}
                    {s.urls.map((u) => <a key={u.url} href={u.url} target="_blank" rel="noreferrer">{u.label}<Icon name="ext" /></a>)}</p>
                ))}
              </div>
            )}
            {scene && <a className="btn btn-line scn" href={scene.href}><Icon name="play" fill />관련 장면 바로가기 <span className="num">{fmt(scene.t)}</span> · {scene.title}</a>}
            <button className="btn btn-line again" onClick={run} disabled={busy}>{busy ? '다시 묻는 중…' : '다시 받기'}</button>
          </>
        )}
        <p className="notice"><Icon name="info" />질문이 AI(Anthropic Claude)로 전송됩니다. 이름·주민등록번호 같은 개인정보는 적지 마세요.</p>
      </div>
    </article>
  );
}
