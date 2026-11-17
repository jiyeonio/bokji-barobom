import { useEffect, useState, type FormEvent } from 'react';
import '../styles/results.css';
import { Icon } from '../components/Icon';
import { FreshWarn, SceneRow, SourceTag, Thumb, VerifyBadge } from '../components/Common';
import { RagCard } from '../components/RagCard';
import { getSuggest, pollSearch, searchWelfare, SUGGEST_FALLBACK, type SearchResponse } from '../data/api';
import type { SceneResult } from '../data/types';
import { go } from '../router';
import { contacts, fmt } from '../utils';

const FIELD_LABEL: Record<string, string> = {
  requiredDocs: '구비서류', applyWhen: '신청 기간', updatedAt: '정보 수정일', applyMethod: '신청 방법', applyUrl: '공식 신청 페이지',
  targetDetail: '지원 대상', criteria: '선정 기준', amount: '금액', benefit: '지원 내용',
};
const firstLine = (t?: string) => (t ?? '').split('\n').map((x) => x.replace(/^[\s○ㅇ◦•\-·※*]+/, '').trim()).filter(Boolean)[0] ?? '';

type Filter = 'all' | 'scenes' | 'policy' | 'screen';

export default function Results({ query, policyCtx }: { query: string; policyCtx?: string }) {
  const [q, setQ] = useState(query);
  const [data, setData] = useState<SearchResponse | null>(null);
  const [error, setError] = useState('');
  const [filter, setFilter] = useState<Filter>('all');
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const [checked, setChecked] = useState<Record<string, boolean>>({});
  const [suggest, setSuggest] = useState<string[]>(SUGGEST_FALLBACK);
  useEffect(() => { getSuggest().then(setSuggest); }, []);

  useEffect(() => {
    setQ(query);
    setData(null);
    setError('');
    let stop = false;
    let timer = 0;
    const poll = (jobId: string, n: number) => {
      timer = window.setTimeout(() => {
        pollSearch(jobId).then((d) => {
          if (stop) return;
          setData(d);
          if (d.status === 'pending' && n < 40) poll(jobId, n + 1);
        }).catch(() => undefined);
      }, 800);
    };
    searchWelfare(query, policyCtx).then((d) => {
      if (stop) return;
      setData(d);
      if (d.status === 'pending' && d.jobId) poll(d.jobId, 0);
    }).catch((e: Error) => setError(e.message));
    return () => { stop = true; window.clearTimeout(timer); };
  }, [query, policyCtx]);

  const onSubmit = (e: FormEvent) => { e.preventDefault(); if (q.trim()) go(`/results?q=${encodeURIComponent(q.trim())}`); };

  const policy = data?.policies[0];
  const official = data?.official;
  const notice = data?.notice;
  const pending = data?.status === 'pending';
  // 한 번 보여 준 카드는 자리를 유지하고 배지만 바꿈. 확인 안 된 장면·같은 정책의 관련 영상은 「관련 영상」(장면 시간·배지 없음)
  const all = (data?.scenes ?? []).filter((s) => filter !== 'screen' || s.found.verification === 'screen');
  // 신청서 작성 질문의 1위(신청서 설명 시작 장면)는 확인 배지와 관계없이 장면 카드로
  const isRel = (s: SceneResult) => !s.formStart && (!!s.related || (!pending && s.found.verification === 'none'));
  const top = notice?.show ? undefined : all[0];
  const rest = notice?.show ? all : all.slice(1);
  const showPolicy = filter === 'all' || filter === 'policy';
  const showScenes = filter !== 'policy';
  // 구비서류는 한 곳에만: 서류를 물으면 위 공식 답변(누르면 체크), 아니면 오른쪽 체크리스트
  const docsInAnswer = !!official?.items.some((it) => it.field === 'requiredDocs');
  const docs = (policy?.requiredDocs ?? []).map((name, i) => ({ id: `d${i}`, name }));
  const doneCount = docs.filter((d) => checked[d.id]).length;
  const job = data?.jobId ? `&job=${data.jobId}` : '';
  const hrefOf = (s: SceneResult, t = s.found.start, e: number | undefined = s.found.end) => `#/watch/${s.videoId}?t=${t}${e ? `&e=${e}` : ''}${job}${s.formStart && t === s.found.start ? '&tab=photo' : ''}`;
  const formTag = (s: SceneResult) => s.formMap && <span className="tag tag-blue"><Icon name="scan" />신청서 지도 있음</span>;
  const answerItems = (official?.items ?? []).filter((it) => it.field !== 'updatedAt');
  // 추천 질문: 정책을 찾았으면 그 정책 질문(정책 맥락 함께), 아니면 검색창 아래 기본 추천
  const chips = data?.chips && data.chips.length > 0 ? data.chips : suggest.filter((c) => c !== query);
  const chipHref = (c: string) => `#/results?q=${encodeURIComponent(c)}${policy && data?.chips?.length ? `&policy=${encodeURIComponent(policy.policyId)}` : ''}`;
  // 결과가 애매하면(확인 끝났는데 1위 장면이 확인 안 됨 · 영상에 답 없음 안내 · 장면 없음) 그 정책의 단계 카드 버튼
  const ambiguous = !!data && !pending && !data.noVideo && (!top || isRel(top) || notice?.reason === 'vlm_no_answer');
  const stepCards = ambiguous ? data?.stepCards ?? [] : [];

  const moreScenes = (s: SceneResult) => s.otherScenes && s.otherScenes.length > 0 && (
    <>
      <button className="btn btn-line" style={{ minHeight: '2.3rem', marginTop: '.6rem' }} aria-expanded={!!open[s.videoId]}
        onClick={() => setOpen({ ...open, [s.videoId]: !open[s.videoId] })}>
        {open[s.videoId] ? '접기' : `이 영상의 다른 장면 ${s.otherScenes.length}개 더 보기`}
      </button>
      {open[s.videoId] && (
        <div className="others">
          {s.otherScenes.map((o) => <SceneRow key={o.start} href={hrefOf(s, o.start, o.end)} t={o.start} label={o.label} />)}
        </div>
      )}
    </>
  );

  const relatedCard = (s: SceneResult) => (
    <article key={s.videoId} className="card vr mini">
      <Thumb href={`#/watch/${s.videoId}`} type={s.thumbType} duration={s.duration} src={s.thumbnailUrl} />
      <h3>{s.title}</h3>
      <div className="meta"><b>{s.publisher}</b><span>· 게시 {s.publishedAt}</span></div>
      <div className="tm"><span className="tag tag-gray">관련 영상</span></div>
      <a className="btn btn-line" href={`#/watch/${s.videoId}`}><Icon name="play" fill />영상 보기</a>
    </article>
  );

  const smallCard = (s: SceneResult) => isRel(s) ? relatedCard(s) : (
    <article key={s.videoId} className="card vr mini">
      <Thumb href={hrefOf(s)} type={s.thumbType} duration={s.duration} src={s.thumbnailUrl} />
      <h3>{s.title}</h3>
      <div className="meta"><b>{s.publisher}</b><span>· 게시 {s.publishedAt}</span></div>
      <div className="tm"><b className="num">{fmt(s.found.start)} – {fmt(s.found.end)}</b><VerifyBadge v={s.found.verification} />{formTag(s)}</div>
      {s.found.warnings?.[0] && <FreshWarn w={s.found.warnings[0]} />}
      <a className="btn btn-line" href={hrefOf(s)}><Icon name="play" fill />이 장면 보기</a>
      {moreScenes(s)}
    </article>
  );

  return (
    <main className="page-results">
      <section className="sbar sg-band"><div className="wrap">
        <h1 className="sg-title">{query}</h1>
        <div className="sg-meta">
          <span><Icon name="play" fill />영상 장면 {data?.scenes.length ?? 0}개</span><i />
          <span><Icon name="db" />공식 정책 {data?.policies.length ?? 0}건</span>
          {pending && <><i /><VerifyBadge v="pending" /></>}
        </div>
        <form className="srow" role="search" onSubmit={onSubmit}>
          <label className="in"><span className="sr-only">검색어</span><Icon name="search" />
            <input type="search" value={q} onChange={(e) => setQ(e.target.value)} />
          </label>
          <button className="btn btn-pri btn-lg" type="submit">다시 검색</button>
        </form>
        {chips.length > 0 && (
          <div className="sugg" aria-label="추천 질문">
            <span>{data?.chips?.length ? '이 정책 더 물어보기' : '이렇게 물어보세요'}</span>
            {chips.slice(0, 4).map((c) => <a key={c} className="chip" href={chipHref(c)}>{c}</a>)}
          </div>
        )}
        <div className="filters">
          {([['all', '전체'], ['scenes', '영상 장면'], ['policy', '공식 정책'], ['screen', '화면에서 확인된 것만']] as [Filter, string][]).map(([k, label]) => (
            <button key={k} className="chip" aria-pressed={filter === k} onClick={() => setFilter(k)}>{k === 'screen' && <Icon name="check" />}{label}</button>
          ))}
        </div>
      </div></section>

      <div className="wrap">
        {!data && !error && <p style={{ padding: '2rem 0', color: 'var(--muted)' }}>찾고 있어요…</p>}
        {error && <p style={{ padding: '2rem 0', color: 'var(--red)' }}>{error} 잠시 후 다시 시도해 주세요.</p>}

        {stepCards.length > 0 && (
          <section className="card stepbtns" aria-label="신청 단계 장면">
            <div><b>찾는 장면이 아닌가요? {policy?.name} 신청 단계별 장면으로 바로 가기</b><small>AI가 나눈 신청 단계 장면이에요</small></div>
            <div className="row">
              {stepCards.map((c) => (
                <a key={c.step} className="btn btn-line" href={`#/watch/${c.videoId}?t=${c.start}&e=${c.end}`}>{c.label}<em className="num">{fmt(c.start)}</em></a>
              ))}
            </div>
          </section>
        )}
        {data && !policy && !pending && (
          <p className="tofind"><Icon name="db" />공공서비스 9,934개에서 찾아보기 → <a href={`#/policies?q=${encodeURIComponent(query)}`}>정책 찾기</a></p>
        )}

        {/* 바로 답: 왼쪽 1위 장면, 오른쪽 공식 답변 */}
        {data && (
          <section className="ans" aria-label="바로 답">
            {showScenes && (data.noVideo ? (
              <article className="card ans-scene" role="status">
                <div className="vh0"><SourceTag kind="ai" /><span>영상 장면</span></div>
                <h3>이 정책의 공식 안내 영상을 준비하고 있어요</h3>
                <p className="note">아래 공식 정책 정보로 지원 대상·신청 방법을 확인할 수 있어요.</p>
                {policy?.fromDb && <a className="btn btn-line" href={`#/policy/${policy.policyId.replace(/^db:/, '')}`}>공식 정보 전체 보기</a>}
              </article>
            ) : top ? (
              <article className="card vr ans-scene">
                <div className="vh0"><SourceTag kind="ai" /><span>{top.formStart ? '신청서 작성 시작 장면' : isRel(top) ? '관련 영상' : pending ? 'AI가 찾은 장면 · 화면 확인 중' : 'AI가 찾은 장면'}</span>{formTag(top)}</div>
                <Thumb href={isRel(top) ? `#/watch/${top.videoId}` : hrefOf(top)} type={top.thumbType} duration={top.duration} src={top.thumbnailUrl} />
                <h3>{top.title}</h3>
                <div className="meta"><b>{top.publisher}</b><span>· 게시 {top.publishedAt}</span><span>· 전체 {top.duration}</span></div>
                {isRel(top) ? (
                  <div className="found">
                    <div className="tm"><span className="tag tag-gray">관련 영상</span></div>
                    <span className="ev">질문과 맞는 장면을 확인하지 못했어요. 영상의 신청 단계부터 볼 수 있어요.</span>
                    <a className="btn btn-pri btn-lg" href={`#/watch/${top.videoId}`}><Icon name="play" fill />영상 보기</a>
                  </div>
                ) : (
                <div className={`found${top.found.verification === 'subtitle' ? ' sub' : ''}`}>
                    <div className="tm"><b className="num">{fmt(top.found.start)} – {fmt(top.found.end)}</b>{top.formStart ? (top.found.verification !== 'none' && top.found.verification !== 'pending' && <VerifyBadge v={top.found.verification} />) : <VerifyBadge v={top.found.verification} />}</div>
                    <span className="ev">{top.found.label}</span>
                    {top.found.warnings?.[0] && <FreshWarn w={top.found.warnings[0]} />}
                    <a className="btn btn-pri btn-lg" href={hrefOf(top)}><Icon name="play" fill />{top.formStart ? '신청서 작성 장면부터 보기 · 내 신청서 비추기' : '찾은 장면부터 보기'}</a>
                  </div>
                )}
                {!isRel(top) && moreScenes(top)}
              </article>
            ) : (
              <article className="card warnc ans-scene" role="status">
                <h3><span style={{ display: 'flex', alignItems: 'center', gap: '.4rem' }}><Icon name="alert" style={{ color: 'var(--amber)' }} />영상에는 해당 내용이 없어요</span></h3>
                <p>{notice?.message || '영상에서 확인된 장면이 없어요. 공식 정보를 확인하세요.'}</p>
              </article>
            ))}
            <div className="ans-col">
            <RagCard question={query} policyId={policy?.policyId}
              scene={top && !isRel(top) ? { href: hrefOf(top), t: top.found.start, title: top.title, videoId: top.videoId } : undefined} />
            {(answerItems.length > 0 || policy) && (
              <article className="card pol ans-off">
                <div className="strip"><SourceTag kind="gov" />공식 답변</div>
                <div className="in">
                  {answerItems.length > 0 ? answerItems.map((it) => (
                    <div key={it.field} className="ai">
                      <div className="k">{FIELD_LABEL[it.field] ?? it.field}{it.field === 'requiredDocs' && docs.length > 0 && <span> · {docs.length}개 중 {doneCount}개 준비</span>}</div>
                      {it.field === 'requiredDocs' ? (
                        <div className="chips">
                          {docs.map((d) => (
                            <button key={d.id} className="chip" aria-pressed={!!checked[d.id]} onClick={() => setChecked({ ...checked, [d.id]: !checked[d.id] })}>
                              {checked[d.id] && <Icon name="check" />}{d.name}
                            </button>
                          ))}
                        </div>
                      ) : it.field === 'applyUrl' ? (
                        <a className="btn btn-line" href={String(it.value)} target="_blank" rel="noreferrer">공식 신청 페이지<Icon name="ext" /></a>
                      ) : it.field === 'amount' && Array.isArray(it.value) ? (
                        <div className="v">{(it.value as { label: string; value: string }[]).map((a) => `${a.label} ${a.value}`).join(' · ')}</div>
                      ) : (
                        <div className="v">{firstLine(String(it.value))}</div>
                      )}
                    </div>
                  )) : policy && (
                    <div className="ai"><div className="k">{policy.name}</div><div className="v">{firstLine(policy.targetDetail) || policy.target}</div></div>
                  )}
                  {docsInAnswer && <p className="note">누르면 준비한 서류로 표시돼요. 자격 판정이 아니에요.</p>}
                  <p className="src1">출처 {official?.source ?? policy?.source} · {official?.baseYear ?? policy?.baseYear}년 기준 · 수정 {official?.updatedAt ?? policy?.updatedAt}</p>
                </div>
              </article>
            )}
            {/* 문의: 정책 API 문의처 그대로 */}
            {policy && contacts(policy.contact).length > 0 && (
              <section className="card">
                <h3>문의</h3>
                {contacts(policy.contact).map((c) => c.tel ? (
                  <a key={c.name + c.tel} className="tel" href={`tel:${c.tel.replace(/-/g, '')}`}><span><small>{c.name}</small><b>{c.tel}</b></span><span className="c"><Icon name="phone" /></span></a>
                ) : <p key={c.name} className="note">{c.name}</p>)}
                <p className="note" style={{ marginTop: '.6rem' }}>출처 {policy.source} · {policy.name} 문의처 · 수정 {policy.updatedAt}</p>
              </section>
            )}
            {!docsInAnswer && docs.length > 0 && (
              <section className="card">
                <h3>준비 서류 체크리스트</h3>
                <p className="note">준비했는지 확인하는 용도예요. 자격 판정이 아니에요.</p>
                <div className="docs">
                  {docs.map((d) => (
                    <label key={d.id}>
                      <input type="checkbox" checked={!!checked[d.id]} onChange={(e) => setChecked({ ...checked, [d.id]: e.target.checked })} />
                      <span>{d.name}</span>
                    </label>
                  ))}
                </div>
                <div className="prog"><div><i style={{ width: `${(doneCount / docs.length) * 100}%` }} /></div>{docs.length}개 중 {doneCount}개 준비</div>
                {policy && <p className="note">출처 {policy.source} · 수정 {policy.updatedAt}</p>}
              </section>
            )}
            </div>
          </section>
        )}

        <div className="grid one">
          <div>
            {/* 다른 영상 장면 */}
            {data && showScenes && rest.length > 0 && (
              <>
                <div className="vh"><div><SourceTag kind="ai" /><h2>다른 영상 장면</h2></div></div>
                <div className="minis">{rest.map(smallCard)}</div>
              </>
            )}

            {/* 정책 요약 */}
            {policy && showPolicy && (
              <article className="card pol" style={{ marginTop: '2rem' }}>
                <div className="strip"><SourceTag kind="gov" />{policy.source}<span className="r">{policy.baseYear}년 기준 · 수정 {policy.updatedAt}</span></div>
                <div className="in">
                  <div className="tt">
                    <div><span className="tag tag-gray">{policy.category}</span><h2>{policy.name}</h2></div>
                    <a className="btn btn-pri" href={policy.applyUrl} target="_blank" rel="noreferrer">공식 신청하기<Icon name="ext" /></a>
                  </div>
                  <div className="facts">
                    <div className="fact"><div className="k">받을 수 있는 분</div><div className="v">{firstLine(policy.targetDetail) || policy.target}</div></div>
                    {policy.amount && policy.amount.length > 0 ? (
                      <div className="fact"><div className="k">받는 금액</div><div className="v blue num">{policy.amount[0].label.replace(/\(.*\)/, '')} {policy.amount[0].value}</div>
                        <div className="s">{policy.amount.slice(1).map((a) => `${a.label} ${a.value}`).join(' · ')}</div></div>
                    ) : (
                      <div className="fact"><div className="k">지원 내용</div><div className="v">{firstLine(policy.benefit)}</div></div>
                    )}
                    <div className="fact"><div className="k">신청 방법</div><div className="v">{firstLine(policy.applyMethod)}</div><div className="s">{policy.applyWhen}</div></div>
                  </div>
                  <details style={{ marginTop: '1rem' }}>
                    <summary>자세히 보기 (지원 대상·선정 기준·지원 내용·신청 방법 원문)</summary>
                    {([['지원 대상', policy.targetDetail], ['선정 기준', policy.criteria], ['지원 내용', policy.benefit], ['신청 방법', policy.applyMethod]] as [string, string][]).map(([k, v]) => v && (
                      <div key={k} style={{ marginTop: '.8rem' }}><b>{k}</b><p style={{ whiteSpace: 'pre-line' }}>{v}</p></div>
                    ))}
                    <p>{policy.officialUrls.map((u) => <a key={u.url} href={u.url} target="_blank" rel="noreferrer" style={{ marginRight: '1rem' }}>{u.label}<Icon name="ext" /></a>)}</p>
                  </details>
                </div>
              </article>
            )}
          </div>

        </div>
      </div>
    </main>
  );
}
