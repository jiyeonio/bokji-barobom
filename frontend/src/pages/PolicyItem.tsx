// 정책 상세 (통합 정책 DB) — 공공데이터 원문 그대로 + 안내 영상(있으면) 또는 「영상 준비 중」 + 추천 질문
import { useEffect, useState } from 'react';
import '../styles/guide.css';
import '../styles/policies.css';
import { Icon } from '../components/Icon';
import { SourceTag } from '../components/Common';
import { getPolicyItem, type PolicyItem as Item } from '../data/api';
import { fmt } from '../utils';

const FIELDS = ['서비스목적', '지원대상', '선정기준', '지원내용', '지원유형', '신청방법', '신청기한', '구비서류', '본인확인필요구비서류', '공무원확인구비서류', '접수기관명', '문의처', '전화문의', '법령'];
const AUD_LABEL: Record<string, string> = { senior: '어르신', youth: '청년', family: '아이 키우는 가정', disabled: '장애인' };

export default function PolicyItem({ id }: { id: string }) {
  const [d, setD] = useState<Item | null>(null);
  const [err, setErr] = useState('');
  useEffect(() => { setD(null); getPolicyItem(id).then(setD).catch((e: Error) => setErr(e.message)); }, [id]);
  const p = d?.policy;
  return (
    <main className="page-guide page-policies">
      <section className="gh sg-band"><div className="wrap">
        <a className="pl-back" href="#/policies"><Icon name="back" />정책 찾기</a>
        <h1 className="sg-title">{p?.name ?? (err ? '정책' : '불러오는 중…')}</h1>
        {p && <div className="sg-meta"><span>{p.agency}</span><i /><span>{p.region || '전국'}</span>{(p.audiences ?? []).map((a) => <span key={a} className="tag tag-blue">{AUD_LABEL[a]}</span>)}</div>}
      </div></section>
      <div className="wrap pl-body">
        {err && <p style={{ color: 'var(--red)' }}>{err}</p>}
        {d && p && (
          <div className="pl-detail">
            <div>
              <section className="card pl-sec">
                <div className="pl-strip"><SourceTag kind="gov" />{p.source}<span>수정 {p.updatedAt} · {p.fetchedAt} 수집</span></div>
                {p.crossCheck && <p className="pl-cross"><Icon name="check" />{p.crossCheck}에도 같은 서비스가 있어요(교차 확인)</p>}
                {p.target && <p className="pl-lead">{p.target}</p>}
                {FIELDS.map((k) => d.raw[k] && d.raw[k] !== '해당없음' && (
                  <div key={k} className="pl-f"><h3>{k}</h3><p>{d.raw[k]}</p></div>
                ))}
                <div className="pl-links">{p.officialUrls.map((u) => <a key={u.url} className="btn btn-line" href={u.url} target="_blank" rel="noreferrer">{u.label}<Icon name="ext" /></a>)}</div>
              </section>
            </div>
            <aside>
              <section className="card pl-sec">
                <h2><Icon name="play" fill />안내 영상</h2>
                {d.videos.length === 0 ? (
                  <p className="pl-note">이 정책의 공식 안내 영상을 준비하고 있어요. 왼쪽 공식 정보와 문의처로 확인하세요.</p>
                ) : (
                  <>
                    {d.videos.map((v) => (
                      <a key={v.videoId} className="pl-vid" href={`#/watch/${v.videoId}`}>
                        <img src={v.thumbnailUrl} alt="" loading="lazy" /><span><b>{v.title}</b><small>{v.publisher} · {v.duration}</small></span>
                      </a>
                    ))}
                    {d.stepCards.length > 0 && (
                      <div className="pl-steps"><small>신청 단계 장면</small>
                        {d.stepCards.map((s) => <a key={s.step} className="chip" href={`#/watch/${s.videoId}?t=${s.start}&e=${s.end}`}>{s.label}<em className="num">{fmt(s.start)}</em></a>)}
                      </div>
                    )}
                  </>
                )}
              </section>
              <section className="card pl-sec">
                <h2>이렇게 물어보세요</h2>
                <div className="pl-chips">
                  {d.chips.map((c) => <a key={c} className="chip" href={`#/results?q=${encodeURIComponent(c)}&policy=${encodeURIComponent(d.chipCtx)}`}>{c}</a>)}
                </div>
              </section>
            </aside>
          </div>
        )}
      </div>
    </main>
  );
}
