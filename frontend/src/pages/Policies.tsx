// 정책 찾기 — 통합 정책 검색 DB(행정안전부 공공서비스(혜택), 개인·가구 대상)에서 낱말·대상·지역으로 찾기. 영상이 없는 정책은 「영상 준비 중」
import { useEffect, useState, type FormEvent } from 'react';
import '../styles/guide.css';
import '../styles/policies.css';
import { Icon, type IconName } from '../components/Icon';
import { SourceTag } from '../components/Common';
import { getPoliciesMeta, searchPolicies, type PoliciesMeta, type PolicySearch } from '../data/api';
import { go } from '../router';

const AUD: { k: string; label: string; icon: IconName }[] = [
  { k: 'senior', label: '어르신', icon: 'elder' },
  { k: 'youth', label: '청년', icon: 'cap' },
  { k: 'family', label: '아이 키우는 가정', icon: 'family' },
  { k: 'disabled', label: '장애인', icon: 'wheel' },
];
const AUD_LABEL: Record<string, string> = Object.fromEntries(AUD.map((a) => [a.k, a.label]));

export default function Policies({ params }: { params: URLSearchParams }) {
  const q0 = params.get('q') ?? '';
  const aud = params.get('audience') ?? '';
  const sido = params.get('sido') ?? '';
  const sigungu = params.get('sigungu') ?? '';
  const nationwide = params.get('nationwide') !== '0';
  const [q, setQ] = useState(q0);
  const [meta, setMeta] = useState<PoliciesMeta | null>(null);
  const [res, setRes] = useState<PolicySearch | null>(null);
  const [page, setPage] = useState(1);
  const [err, setErr] = useState('');

  useEffect(() => { getPoliciesMeta().then(setMeta).catch((e: Error) => setErr(e.message)); }, []);
  useEffect(() => {
    setQ(q0); setPage(1); setRes(null);
    searchPolicies({ q: q0, audience: aud, sido, sigungu, nationwide, page: 1 }).then(setRes).catch((e: Error) => setErr(e.message));
  }, [q0, aud, sido, sigungu, nationwide]);

  const nav = (patch: Record<string, string>) => {
    const u = new URLSearchParams({ q: q0, audience: aud, sido, sigungu, nationwide: nationwide ? '1' : '0', ...patch });
    [...u.keys()].forEach((k) => { if (!u.get(k) || (k === 'nationwide' && u.get(k) === '1')) u.delete(k); });
    go(`/policies?${u}`);
  };
  const more = () => {
    const n = page + 1;
    searchPolicies({ q: q0, audience: aud, sido, sigungu, nationwide, page: n }).then((r) => {
      setRes((old) => old ? { ...r, items: [...old.items, ...r.items] } : r); setPage(n);
    }).catch(() => undefined);
  };
  const onSubmit = (e: FormEvent) => { e.preventDefault(); nav({ q: q.trim() }); };

  return (
    <main className="page-guide page-policies">
      <section className="gh sg-band"><div className="wrap">
        <h1 className="sg-title">정책 찾기</h1>
        <div className="sg-meta"><span><Icon name="db" />공공서비스 {meta ? meta.meta.count.toLocaleString() : '…'}개{meta?.meta.localOnly ? ` + 지자체 복지 ${meta.meta.localOnly.toLocaleString()}개` : ''}</span><i /><span>대상·지역으로 골라 보세요</span></div>
        <form className="pl-search" role="search" onSubmit={onSubmit}>
          <label><span className="sr-only">정책 이름이나 낱말</span><Icon name="search" />
            <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="예: 월세, 출산, 장애인 활동지원" />
          </label>
          <button className="btn btn-pri btn-lg" type="submit">찾기</button>
        </form>
      </div></section>

      <div className="wrap pl-body">
        <section className="pl-filters" aria-label="대상·지역">
          <div className="row">
            <b>대상</b>
            <button className="chip" aria-pressed={!aud} onClick={() => nav({ audience: '' })}>전체</button>
            {AUD.map((a) => (
              <button key={a.k} className="chip" aria-pressed={aud === a.k} onClick={() => nav({ audience: aud === a.k ? '' : a.k })}><Icon name={a.icon} />{a.label}</button>
            ))}
          </div>
          <div className="row">
            <b>지역</b>
            <label className="sel"><span className="sr-only">시도</span>
              <select value={sido} onChange={(e) => nav({ sido: e.target.value, sigungu: '' })}>
                <option value="">전국 (모든 지역)</option>
                {meta && Object.keys(meta.regions).map((s) => <option key={s}>{s}</option>)}
              </select>
            </label>
            {sido && meta && (meta.regions[sido] ?? []).length > 0 && (
              <label className="sel"><span className="sr-only">시군구</span>
                <select value={sigungu} onChange={(e) => nav({ sigungu: e.target.value })}>
                  <option value="">{sido} 전체</option>
                  {meta.regions[sido].map((s) => <option key={s}>{s}</option>)}
                </select>
              </label>
            )}
            {sido && (
              <label className="ck"><input type="checkbox" checked={nationwide} onChange={(e) => nav({ nationwide: e.target.checked ? '1' : '0' })} />전국 공통 정책도 함께</label>
            )}
          </div>
        </section>

        {err && <p style={{ color: 'var(--red)' }}>{err}</p>}
        {!res && !err && <p className="pl-note">찾고 있어요…</p>}
        {res && (
          <>
            <p className="pl-count"><b>{res.total.toLocaleString()}</b>개 정책{q0 && <> · 「{q0}」</>}{aud && <> · {AUD_LABEL[aud]}</>}{sido && <> · {sido} {sigungu}</>}</p>
            {res.total === 0 && <p className="pl-note">맞는 정책이 없어요. 낱말을 줄이거나 대상·지역을 풀어 보세요.</p>}
            <ul className="pl-list">
              {res.items.map((it) => (
                <li key={it.id} className="card">
                  <a className="pl-item" href={`#/policy/${it.id}`}>
                    <div className="tg">
                      <span className="tag tag-gray">{it.field || '공공서비스'}</span>
                      <span className="tag tag-gray">{it.sido === '전국' ? '전국' : `${it.sido} ${it.sigungu}`.trim()}</span>
                      {it.audiences.map((a) => <span key={a} className="tag tag-blue">{AUD_LABEL[a]}</span>)}
                      {it.source === 'local' && <span className="tag tag-gray">지자체복지서비스</span>}
                    </div>
                    <h3>{it.name}</h3>
                    <p>{it.summary}</p>
                    <div className="ft">
                      <span>{it.agency}</span>
                      {it.videos > 0 ? <span className="vd on"><Icon name="play" fill />안내 영상 {it.videos}개</span> : <span className="vd">영상 준비 중</span>}
                    </div>
                  </a>
                </li>
              ))}
            </ul>
            {res.items.length < res.total && <button className="btn btn-line pl-more" onClick={more}>더 보기 ({res.items.length} / {res.total.toLocaleString()})</button>}
            <p className="pl-note"><SourceTag kind="gov" /> 출처 {res.source}{meta?.meta.localSource ? ` · ${meta.meta.localSource}(같은 지역·같은 이름의 서비스는 교차 확인해 하나로, 행정안전부 데이터에 없는 지자체 서비스는 따로 표시)` : ''} · {res.fetchedAt} 수집 · 정책 내용은 공공데이터 원문 그대로예요.
              대상 분류는 지원대상 원문과 지원조건(나이)으로 자동 분류해 틀릴 수 있어요. 정확한 자격은 정책 원문과 문의처로 확인하세요.</p>
          </>
        )}
      </div>
    </main>
  );
}
