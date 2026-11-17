// 기관용 안내 공백 리포트 — 국민이 묻지만 영상·공공데이터 모두 답하지 못한 질문, 정보가 오래된 영상, 신청 단계 장면이 없는 영상
import { useEffect, useState } from 'react';
import '../styles/guide.css';
import { Icon } from '../components/Icon';
import { SourceTag } from '../components/Common';
import { fmt } from '../utils';

const BASE = import.meta.env.VITE_API_BASE_URL as string | undefined;

interface Report {
  generatedAt: string;
  videos: number;
  summary: { gaps: number; familyProxy: number; stale: number; noSteps: number; needVideo: number; formGaps: number };
  formGaps: { form: string; videoId: string; videoTitle: string; page: number; section: string; label: string; official: string | null; sectionGuide: string | null }[];
  gaps: { query: string; policy: string; count: number | null; source: string; theme: string; reason?: string; verdict?: string }[];
  stale: { videoId: string; title: string; channel: string; published: string; at: number; claim: string; current: { label: string; value: string }[]; policy: string; updatedAt: string }[];
  needVideo: { policyId: string; name: string; agency: string; count: number; queries: string[] }[];
  noSteps: { videoId: string; title: string; channel: string; policy: string; durationSec: number; chapters: number }[];
}

export default function Agency() {
  const [r, setR] = useState<Report | null>(null);
  const [err, setErr] = useState('');
  useEffect(() => {
    fetch(`${BASE ?? ''}/api/agency/report`).then((x) => (x.ok ? x.json() : Promise.reject(new Error('리포트를 불러오지 못했어요')))).then(setR).catch((e: Error) => setErr(e.message));
  }, []);
  return (
    <main className="page-guide">
      <section className="gh sg-band"><div className="wrap">
        <h1 className="sg-title">기관용 안내 공백 리포트</h1>
        <div className="sg-meta"><span>국민이 묻지만 영상·공공데이터가 답하지 못한 곳을 찾아 안내 콘텐츠 보강 우선순위를 정해요</span></div>
      </div></section>
      <div className="wrap" style={{ paddingBottom: '3rem' }}>
        {err && <p style={{ color: 'var(--red)' }}>{err}</p>}
        {!r && !err && <p style={{ color: 'var(--muted)' }}>불러오는 중…</p>}
        {r && (
          <>
            <div className="ag-sum">
              <div className="card"><small>답 없던 질문</small><b>{r.summary.gaps}</b><span>그중 가족 대리 신청 {r.summary.familyProxy}</span></div>
              <div className="card"><small>영상이 필요한 정책</small><b>{r.summary.needVideo}</b><span>질문은 있었는데 영상 없음</span></div>
              <div className="card"><small>오래된 정보 경고 영상</small><b>{r.summary.stale}</b><span>영상 속 금액 ≠ 공공데이터</span></div>
              <div className="card"><small>신청 단계 장면이 없는 영상</small><b>{r.summary.noSteps}</b><span>전체 {r.videos}개 중</span></div>
            </div>

            <section className="card ag-sec">
              <h2><Icon name="alert" />영상·공공데이터 모두 답하지 못한 질문</h2>
              <p className="note">검색 기록(질문 문장과 결과 요약만 저장 · 이름·연락처·로그인 정보는 받지 않음)과 평가에서 나온 실제 사용자 질문. 「가족 대리 신청」은 영상에도, 두 공공데이터 API에도 대리 신청 가능 여부가 없었어요.</p>
              <table>
                <thead><tr><th>질문</th><th>정책</th><th>분류</th><th>출처</th><th>근거</th></tr></thead>
                <tbody>
                  {r.gaps.map((g) => (
                    <tr key={g.query}>
                      <td><b>{g.query}</b></td><td>{g.policy}</td>
                      <td><span className={`tag ${g.theme === '가족 대리 신청' ? 'tag-blue' : 'tag-gray'}`}>{g.theme}</span></td>
                      <td>{g.source}{g.count ? ` · ${g.count}회` : ''}{g.verdict ? ` · 공공데이터 ${g.verdict}` : ''}</td>
                      <td className="small">{g.reason ?? '영상 장면 확인 안 됨 · 공식 정보에 해당 항목 없음'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>

            <section className="card ag-sec">
              <h2><Icon name="play" />안내 영상이 필요한 정책 (질문은 있었는데 영상이 없음)</h2>
              <p className="note">통합 정책 DB에서 정책은 찾았지만 연결된 공식 안내 영상이 없어 「영상 준비 중」으로 답한 질문이에요. 많이 물은 순.</p>
              {r.needVideo.length === 0 ? <p className="note">아직 없어요.</p> : (
                <table>
                  <thead><tr><th>정책</th><th>소관기관</th><th>질문 수</th><th>질문 예</th></tr></thead>
                  <tbody>
                    {r.needVideo.map((n) => (
                      <tr key={n.policyId}><td><a href={`#/policy/${n.policyId}`}><b>{n.name}</b></a></td><td>{n.agency}</td><td className="num">{n.count}</td><td className="small">{n.queries.join(' · ')}</td></tr>
                    ))}
                  </tbody>
                </table>
              )}
            </section>

            <section className="card ag-sec">
              <h2><Icon name="alert" />서식 칸 중 영상 설명이 없는 항목</h2>
              <p className="note">신청서 지도에서 영상이 그 칸을 따로 설명하지 않은 칸이에요. 공식 서식 작성 방법이 있으면 함께 표시해요. 안내 영상을 보강할 때 우선 다룰 칸이에요.</p>
              {r.formGaps.length === 0 ? <p className="note">없어요.</p> : (
                <table>
                  <thead><tr><th>서식 · 쪽</th><th>구역</th><th>칸</th><th>공식 작성 방법</th><th>영상</th></tr></thead>
                  <tbody>
                    {r.formGaps.map((g) => (
                      <tr key={g.videoId + g.page + g.section + g.label}>
                        <td>{g.form} · {g.page}쪽</td><td>{g.section}</td><td><b>{g.label}</b></td>
                        <td className="small">{g.official ?? '없음'}</td>
                        <td className="small"><a href={`#/watch/${g.videoId}`}>{g.videoTitle}</a>{g.sectionGuide && <><br />구역 안내만: {g.sectionGuide}</>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </section>

            <section className="card ag-sec">
              <h2><Icon name="alert" />정보가 오래된 영상 (영상 속 금액 ≠ 공공데이터)</h2>
              {r.stale.length === 0 ? <p className="note">없어요.</p> : (
                <table>
                  <thead><tr><th>영상</th><th>장면</th><th>영상 속 값</th><th>현재 공식 값</th></tr></thead>
                  <tbody>
                    {r.stale.map((s) => (
                      <tr key={s.videoId + s.at}>
                        <td><a href={`#/watch/${s.videoId}?t=${s.at}`}><b>{s.title}</b></a><br /><span className="small">{s.channel} · 게시 {s.published}</span></td>
                        <td className="num">{fmt(s.at)}</td><td>{s.claim}</td>
                        <td>{s.current.map((c) => `${c.label} ${c.value}`).join(' · ')}<br /><span className="small">{s.policy} · 수정 {s.updatedAt}</span></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </section>

            <section className="card ag-sec">
              <h2><Icon name="info" />장면 목록만 있고 신청 단계 장면이 없는 영상</h2>
              <p className="note">자동 확인을 통과한 신청 단계(자격 확인·서류 준비·신청서 작성·결과 확인) 장면이 없는 영상이에요. 정책과 연결된 영상부터 보여 줘요.</p>
              <table>
                <thead><tr><th>영상</th><th>정책</th><th>길이</th><th>장면 수</th></tr></thead>
                <tbody>
                  {r.noSteps.map((v) => (
                    <tr key={v.videoId}>
                      <td><a href={`#/watch/${v.videoId}`}><b>{v.title}</b></a><br /><span className="small">{v.channel}</span></td>
                      <td>{v.policy || <span className="small">연결 정책 없음</span>}</td><td className="num">{fmt(v.durationSec)}</td><td className="num">{v.chapters}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
            <p className="note" style={{ marginTop: '1rem' }}><SourceTag kind="gov" /> 공식 정보: 사회보장 공공데이터 · <SourceTag kind="ai" /> 장면·단계: AI 분석 결과(틀릴 수 있음) · 만든 시각 {r.generatedAt}</p>
          </>
        )}
      </div>
    </main>
  );
}
