import { useEffect, useMemo, useState } from 'react';
import { useYouTubePlayer } from '../components/useYouTubePlayer';
import { FormMapView } from '../components/FormMap';
import '../styles/watch.css';
import { Icon } from '../components/Icon';
import { FreshWarn, SourceTag, VerifyBadge } from '../components/Common';
import { getVideo, pollSearch, searchWelfare, type SearchResponse } from '../data/api';
import type { Chapter, VideoDetail } from '../data/types';
import { contacts, fmt, pct } from '../utils';

const CIRCLED = ['①', '②', '③', '④', '⑤', '⑥', '⑦', '⑧'];
const SPEEDS = [0.75, 1, 1.25];

/** 쉬운 말로 보기 — 원문 아래에 펼쳐 보는 보조 설명(원문은 항상 위에 그대로) */
function EasyText({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="easy">
      <button className="btn btn-soft" style={{ minHeight: '2.2rem' }} aria-expanded={open} onClick={() => setOpen(!open)}>
        <Icon name="text" />{open ? '쉬운 말 접기' : '쉬운 말로 보기'}
      </button>
      {open && (
        <div className="easy-body">
          <p style={{ whiteSpace: 'pre-line' }}>{text}</p>
          <small>AI가 위 원문을 쉬운 말로 바꾼 것이에요. 숫자·조건은 원문을 기준으로 확인하세요.</small>
        </div>
      )}
    </div>
  );
}

function fallback(text: string, done: () => void) {
  const ta = document.createElement('textarea');
  ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
  document.body.appendChild(ta); ta.select();
  try { document.execCommand('copy'); done(); } finally { document.body.removeChild(ta); }
}

const CHAP_FIRST = 5;

export default function Watch({ videoId, startAt, endAt, jobId, tab }: { videoId: string; startAt?: number; endAt?: number; jobId?: string; tab?: string }) {
  const [video, setVideo] = useState<VideoDetail | null>(null);
  const [loopCh, setLoopCh] = useState<Chapter | null>(null);
  const [firstAt, setFirstAt] = useState(startAt ?? 0);
  const [repeat, setRepeat] = useState(false);
  const [bigSub, setBigSub] = useState(true);
  const [speed, setSpeed] = useState(1);
  const [checked, setChecked] = useState<Record<string, boolean>>({});
  const [ask, setAsk] = useState('');
  const [asked, setAsked] = useState<SearchResponse | null>(null);
  const [asking, setAsking] = useState(false);
  const [copied, setCopied] = useState(false);
  // 신청서 따라하기: 항목 장면을 끝까지 보면 「봤어요」로 표시, 다 보면 내 신청 준비 체크리스트
  const [formOpen, setFormOpen] = useState(false);
  const [formTab, setFormTab] = useState<'map' | 'photo' | 'list'>(tab === 'photo' ? 'photo' : tab === 'list' ? 'list' : 'map');
  useEffect(() => { if (tab === 'photo' || tab === 'map' || tab === 'list') setFormTab(tab); }, [tab, videoId]);
  const [seen, setSeen] = useState<Record<string, boolean>>({});
  const [listOpen, setListOpen] = useState(false);
  const [listCopied, setListCopied] = useState(false);

  useEffect(() => {
    getVideo(videoId, { jobId, t: startAt, e: endAt }).then((v) => {
      setVideo(v);
      const m = v.chapters.find((c) => c.id === v.matchedChapterId) ?? null;
      setLoopCh(m);
      setFirstAt(startAt ?? m?.start ?? 0);
    });
  }, [videoId, startAt, endAt, jobId]);

  // 검색 결과 확인(VLM)이 끝나기 전에 들어온 경우: 배지만 갱신 (재생 위치는 그대로)
  useEffect(() => {
    if (!video || !jobId || !video.chapters.some((c) => c.verification === 'pending')) return;
    const id = window.setTimeout(() => {
      getVideo(videoId, { jobId, t: startAt, e: endAt }).then((v) => setVideo((old) => (old ? { ...old, chapters: v.chapters } : v)));
    }, 1500);
    return () => window.clearTimeout(id);
  }, [video, videoId, jobId, startAt, endAt]);

  const yt = useYouTubePlayer(video?.youtubeVideoId ?? video?.videoId, firstAt);
  // 작은 플레이어: 원래 자리(slot)가 화면 밖으로 나가면 같은 플레이어(iframe)를 CSS로만 오른쪽 아래(휴대폰은 위쪽)에 고정 — 다시 만들지 않아 재생이 끊기지 않음
  const [slotEl, setSlotEl] = useState<HTMLDivElement | null>(null);
  const [mini, setMini] = useState(false);
  useEffect(() => {
    const el = slotEl;
    if (!el || typeof IntersectionObserver === 'undefined') { setMini(false); return; }
    const io = new IntersectionObserver(([e]) => setMini(!e.isIntersecting && e.boundingClientRect.top < 0), { threshold: 0 });
    io.observe(el);
    return () => io.disconnect();
  }, [slotEl]);
  const backToPlayer = () => slotEl?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  const [chapAll, setChapAll] = useState(false);
  const time = yt.time;
  const { seek: seekYt, setRate, ready: ytReady } = yt;
  const playing = yt.playing;
  const chapters = video?.chapters ?? [];
  const shown = chapters.filter((c) => !c.gap);
  const current = useMemo(
    () => chapters.find((c) => time >= c.start && time < c.end) ?? chapters[chapters.length - 1],
    [chapters, time],
  );
  const matched = chapters.find((c) => c.id === video?.matchedChapterId);

  // 구간 반복: 마지막으로 고른 장면(loopCh)의 끝에 닿으면 처음으로
  useEffect(() => {
    if (repeat && loopCh && playing && time >= loopCh.end - 0.15) seekYt(loopCh.start);
  }, [time, repeat, loopCh, playing, seekYt]);
  useEffect(() => { setRate(speed); }, [speed, ytReady, setRate]);
  useEffect(() => {
    if (!formOpen) return;
    const it = shown.find((c) => c.step === 3 && time >= c.end - 1.5 && time < c.end + 3);
    if (it && !seen[it.id]) setSeen((x) => ({ ...x, [it.id]: true }));
  }, [time, formOpen, shown, seen]);
  const subNow = video?.subtitles?.find((x) => time >= x.start && time < x.end)?.text;

  // 신청서 작성 질문 카드에서 들어오면(tab=photo) 「신청서 따라하기 · 내 신청서 비추기」까지 내려 줌 (영상은 고정이라 계속 보임)
  const formReady = !!video?.formMap;
  useEffect(() => {
    if (!formReady || !tab) return;
    const id = window.setTimeout(() => document.getElementById('formmode')?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 600);
    return () => window.clearTimeout(id);
  }, [formReady, tab, videoId]);
  if (!video || !current || !matched) {
    return <main className="page-watch"><div className="wrap top"><p style={{ color: 'var(--muted)' }}>영상을 불러오고 있어요…</p></div></main>;
  }

  const total = video.durationSec;
  // 진행바 위 장면 이름: 서로 가까우면(전체의 12% 안) 하나만 보임 — 지금 보는 장면·찾은 장면을 먼저
  const labelShown = (() => {
    const order = [...shown].sort((a, b) => Number(b.id === current.id) - Number(a.id === current.id) || Number(b.id === matched.id) - Number(a.id === matched.id) || a.start - b.start);
    const kept: Chapter[] = [];
    for (const c of order) if (kept.every((k) => Math.abs(k.start - c.start) / total >= 0.12)) kept.push(c);
    return new Set(kept.map((k) => k.id));
  })();
  const policy = video.policy;
  const docs = video.docs;
  const officialSteps = video.officialSteps;
  const stepChs = shown.filter((c) => c.step);
  const seek = (t: number) => {
    const ch = shown.find((c) => t >= c.start - 0.5 && t < c.end);
    if (ch) setLoopCh(ch);
    yt.seek(t);
  };
  /** 신청 단계 카드: 그 장면으로 가서 큰 자막을 켬 (구간 반복은 사용자가 버튼을 누를 때만) */
  const seekStep = (t: number) => { setBigSub(true); seek(t); };
  /** 가족에게 장면 보내기: 장면 시작 시간이 들어간 링크 + 준비 서류 목록을 카카오톡에 붙여넣기 좋은 글로 복사 */
  const share = () => {
    const at = Math.floor(current && !current.gap ? current.start : time);
    const yid = video.youtubeVideoId ?? video.videoId;
    const local = /^(localhost|127\.0\.0\.1)$/.test(window.location.hostname);
    const lines = [
      `[복지바로봄] ${policy ? `${policy.name} ` : ''}안내 영상 장면`,
      `「${video.title}」 ${fmt(at)}부터 보세요`,
      `▶ https://youtu.be/${yid}?t=${at}`,
      ...(local ? [] : [`복지바로봄에서 보기: ${window.location.origin}${window.location.pathname}#/watch/${video.videoId}?t=${at}`]),
      ...(docs.length ? ['', `준비 서류 (${docs.length}가지)`, ...docs.map((d, i) => `${i + 1}. ${d.name}`)] : []),
      ...(policy ? ['', `신청: ${policy.applyMethod.split('\n').map((x) => x.replace(/^[\s○ㅇ◦•\-·※*]+/, '').trim()).filter(Boolean)[0] ?? ''}`,
        `출처: ${policy.source} · ${policy.baseYear}년 기준 · 수정 ${policy.updatedAt}`] : []),
      '※ 자격·금액·기간은 공식 정보로 꼭 확인하세요.',
    ];
    const text = lines.join('\n');
    const done = () => { setCopied(true); window.setTimeout(() => setCopied(false), 2500); };
    if (navigator.clipboard?.writeText) navigator.clipboard.writeText(text).then(done).catch(() => fallback(text, done));
    else fallback(text, done);
  };
  // 신청서 따라하기 항목 = 「③ 신청서 작성」 단계 장면들 (영상에 나온 순서)
  const formItems = stepChs.filter((c) => c.step === 3);
  const itemName = (c: Chapter) => c.title.replace(/^③\s*신청서 작성\s*·?\s*/, '') || '신청서 작성';
  const seenCount = formItems.filter((c) => seen[c.id]).length;
  // 영상 장면 목록: 신청서 따라하기에 있는 장면은 빼고, 처음엔 5개(지금 재생 중인 장면은 항상 보임)
  const formShown = formItems.length >= 2;
  const formIds = new Set(formShown ? formItems.map((c) => c.id) : []);
  const chapList = shown.filter((c) => !formIds.has(c.id));
  const chapRows = chapAll ? chapList : chapList.filter((c, i) => i < CHAP_FIRST || c.id === current.id);
  // 신청 단계 따라 하기: 신청서 따라하기가 있으면 단계마다 한 줄(처음 장면), 없으면 단계 장면 전부
  // 단계 번호 순서(①②③④, 같은 단계는 시간 순). 시간은 오른쪽에 그대로
  const stepRows = (formShown ? stepChs.filter((c, i) => stepChs.findIndex((x) => x.step === c.step) === i) : stepChs)
    .slice().sort((a, b) => (a.step ?? 9) - (b.step ?? 9) || a.start - b.start);
  // 이전·다음 단계는 목록(단계 번호) 순서로: 지금 보는 줄(없으면 시작 시간이 지난 줄 중 가장 늦은 것) 기준
  const stepIdx = (() => {
    const inside = stepRows.findIndex((c) => time >= c.start && time < c.end);
    if (inside >= 0) return inside;
    let best = -1;
    stepRows.forEach((c, i) => { if (c.start <= time + 0.5 && (best < 0 || c.start > stepRows[best].start)) best = i; });
    return best;
  })();
  const nextStep = stepRows[stepIdx + 1];
  const prevStep = stepIdx > 0 ? stepRows[stepIdx - 1] : undefined;
  const stepName = (c: Chapter) => (formShown && c.step ? `${CIRCLED[c.step - 1]} ${c.short}` : c.title);
  /** 내 신청 준비 체크리스트를 가족에게 보내기 (개인정보 없이 공식 구비서류·신청서 항목·신청 방법만) */
  const shareChecklist = () => {
    const yid = video.youtubeVideoId ?? video.videoId;
    const lines = [
      `[복지바로봄] ${policy ? `${policy.name} ` : ''}신청 준비 체크리스트`,
      '',
      ...(docs.length ? [`□ 준비 서류 (공식 정보, ${docs.length}가지)`, ...docs.map((d) => `  ${checked[d.id] ? '☑' : '☐'} ${d.name}`), ''] : []),
      `□ 신청서에 쓰는 항목 (영상 「${video.title}」)`,
      ...formItems.map((c) => `  · ${itemName(c)} — https://youtu.be/${yid}?t=${Math.floor(c.start)}`),
      ...(policy ? ['', `□ 신청 방법: ${policy.applyMethod.split('\n').map((x) => x.replace(/^[\s○ㅇ◦•\-·※*]+/, '').trim()).filter(Boolean)[0] ?? ''}`,
        `□ 문의: ${policy.contact}`, `출처: ${policy.source} · ${policy.baseYear}년 기준 · 수정 ${policy.updatedAt}`] : []),
      '※ 자격·금액·기간은 공식 정보로 꼭 확인하세요.',
    ];
    const text = lines.join('\n');
    const done = () => { setListCopied(true); window.setTimeout(() => setListCopied(false), 2500); };
    if (navigator.clipboard?.writeText) navigator.clipboard.writeText(text).then(done).catch(() => fallback(text, done));
    else fallback(text, done);
  };
  /** 이 정책 맥락에서 질문 (예: 「이거 아직 신청 되는 거예요?」) — 공식 정보 답 + 영상 장면 */
  const onAsk = (e: React.FormEvent) => { e.preventDefault(); runAsk(ask); };
  const runAsk = (text: string) => {
    const q = text.trim(); if (!q) return;
    setAsk(q);
    setAsking(true); setAsked(null);
    searchWelfare(q, policy?.policyId).then((d) => {
      setAsked(d); setAsking(false);
      const poll = (n: number) => { if (d.jobId && n < 40) window.setTimeout(() => pollSearch(d.jobId!).then((x) => { setAsked(x); if (x.status === 'pending') poll(n + 1); }), 800); };
      if (d.status === 'pending') poll(0);
    }).catch(() => setAsking(false));
  };

  return (
    <main className="page-watch">
      <section className="sg-band"><div className="wrap">
        <div className="crumb"><span>홈</span>›<span>{policy?.category ?? '복지 안내'}</span>›<span>{policy?.name ?? '영상'}</span>›<b>신청 안내 영상</b></div>
        <div className="th">
          <div>
            <div style={{ display: 'flex', gap: '.4rem', flexWrap: 'wrap' }}>
              {policy && <span className="tag tag-blue">{policy.name}</span>}<span className="tag tag-gray">{video.subtitles?.length ? '자막 있음' : '자막 없음'}</span><span className="tag tag-gray">장면 {shown.length}개</span>
            </div>
            <h1 className="sg-title">{video.title}</h1>
          </div>
          <div className="acts">
            <button className="btn btn-line"><Icon name="bookmark" />저장</button>
            <button className="btn btn-line" onClick={share}><Icon name="share" />{copied ? '복사했어요' : '이 장면 공유'}</button>
          </div>
        </div>
        <div className="meta">
          <span className="src src-ai"><Icon name="scan" />영상</span><b>{video.publisher}</b><span>게시 {video.publishedAt} · {fmt(total)}</span>
          <span>|</span>
          {policy && <><span className="src src-gov"><Icon name="db" />정책정보</span><span>{policy.baseYear}년 기준 · 수정 {policy.updatedAt}</span></>}
        </div>

      </div></section>

      <div className="wrap top">
        {/* 데스크톱: 왼쪽 영상(크게, 스크롤해도 위에 고정) / 오른쪽 신청서·장면·정책 정보. 휴대폰: 한 줄, 영상이 밖으로 나가면 위쪽에 고정 */}
        <div className="grid wv">
          <div className="wv-left">
            {/* 플레이어 — YouTube IFrame (useYouTubePlayer), 컨트롤은 아래 디자인 그대로 */}
            <div className="player">
              <div className="stage-slot" ref={setSlotEl}>
              <div className={`stage${mini ? ' mini' : ''}`}>
                {mini && <button className="mini-close" onClick={backToPlayer} aria-label="작은 플레이어 닫고 원래 위치로"><Icon name="plus" /></button>}
                <div className="yt" ref={yt.mountRef} />
                {yt.error && <div className="yterr">{yt.error}</div>}
                {/* 일시정지하면 유튜브 추천 화면 대신 우리 덮개 (누르면 다시 재생) */}
                {yt.ready && !playing && (
                  <button className="pausecover" onClick={yt.toggle} aria-label="재생"><span><Icon name="play" fill /></span></button>
                )}
              </div>
              </div>
              {bigSub && <div className="ccbar" aria-live="polite">{subNow ? `“${subNow}”` : '\u00a0'}</div>}
              {(video.freshness ?? []).length > 0 && (
                <div className="freshs" aria-label="영상 정보 최신성">
                  {video.freshness!.map((w) => (
                    <FreshWarn key={w.start} w={w} active={time >= w.start - 1 && time < w.end + 6} onSeek={() => seek(w.start)} />
                  ))}
                </div>
              )}
              <div className="ctl">
                <div className="tl" aria-label="장면 타임라인">
                  {shown.map((c, i) => (
                    <span key={c.id} className={`lab${c.id === current.id ? ' on' : ''}${labelShown.has(c.id) ? '' : ' hid'}`} style={{ left: pct(c.start, total) }}>
                      {CIRCLED[i]} {c.short}
                    </span>
                  ))}
                  <div className="track" />
                  <div className="seg" style={{ left: pct(matched.start, total), width: pct(matched.end - matched.start, total) }} />
                  <div className="done" style={{ width: pct(time, total) }} />
                  {shown.map((c, i) => <span key={c.id} className="tick" title={`${CIRCLED[i]} ${c.short} · ${fmt(c.start)}`} style={{ left: pct(c.start, total) }} />)}
                  <span className="head" style={{ left: pct(time, total) }} />
                </div>
                <div className="cb">
                  <button className="pp" aria-label={playing ? '일시정지' : '재생'} onClick={yt.toggle}>
                    <Icon name={playing ? 'pause' : 'play'} fill={!playing} />
                  </button>
                  <button onClick={() => yt.seek(Math.max(0, time - 10))}><Icon name="rew" />10초 뒤로</button>
                  <span className="tm num">{fmt(time)} / {fmt(total)}</span>
                  <span className="sp" />
                  <button aria-pressed={repeat} onClick={() => setRepeat(!repeat)}><Icon name="repeat" />이 장면 반복</button>
                  <button aria-pressed={bigSub} onClick={() => setBigSub(!bigSub)}>큰 자막</button>
                  <div className="spd" role="group" aria-label="재생 속도">
                    {SPEEDS.map((s) => <button key={s} aria-pressed={speed === s} onClick={() => setSpeed(s)}>{s}배</button>)}
                  </div>
                  <button aria-label="전체 화면"><Icon name="full" /></button>
                </div>
              </div>
            </div>
          </div>

          <div className="wv-right">
            {/* 이 정책에 대해 물어보기 — 영상에 없는 내용은 공식 정보로 답함 */}
            {policy && (
              <section className="card follow" aria-label="이 정책에 대해 물어보기">
                <div className="hd"><h2>{policy.name}에 대해 물어보기</h2><p>영상에 없는 내용은 공식 정보로 답해요.</p></div>
                <form onSubmit={onAsk} style={{ display: 'flex', gap: '.5rem', marginTop: '.6rem' }}>
                  <input type="search" value={ask} onChange={(e) => setAsk(e.target.value)} placeholder="예: 이거 아직 신청 되는 거예요?"
                    aria-label="질문" style={{ flex: 1, fontSize: '1.05rem', padding: '.6rem .8rem', border: '1.5px solid var(--line-2)', borderRadius: '.6rem' }} />
                  <button className="btn btn-pri" type="submit" disabled={asking}>{asking ? '찾는 중…' : '물어보기'}</button>
                </form>
                {(video.chips ?? []).length > 0 && (
                  <div className="ask-chips" aria-label="추천 질문">
                    {video.chips!.map((c) => <button key={c} type="button" className="chip" disabled={asking} onClick={() => runAsk(c)}>{c}</button>)}
                  </div>
                )}
                {asked && (
                  <div style={{ marginTop: '.8rem' }}>
                    {asked.notice?.show && (
                      <div className="warn" role="status"><Icon name="alert" style={{ color: 'var(--amber)' }} /><span><b>영상에는 해당 내용이 없어요.</b> 공식 정보를 확인하세요.</span></div>
                    )}
                    {asked.official && asked.official.items.length > 0 && (
                      <div style={{ marginTop: '.6rem' }}>
                        <SourceTag kind="gov" />
                        {asked.official.items.map((it) => (
                          <p key={it.field} style={{ whiteSpace: 'pre-line', margin: '.4rem 0' }}>
                            <b>{({ applyWhen: '신청 기간', updatedAt: '정보 수정일', requiredDocs: '구비서류', applyMethod: '신청 방법', applyUrl: '공식 신청 페이지', targetDetail: '지원 대상', criteria: '선정 기준', amount: '금액', benefit: '지원 내용' } as Record<string, string>)[it.field] ?? it.field}</b>{' '}
                            {Array.isArray(it.value) ? (it.value as (string | { name?: string; label?: string; value?: string })[]).map((x) => typeof x === 'string' ? x : x.name ?? `${x.label} ${x.value}`).join(' · ') : String(it.value)}
                          </p>
                        ))}
                        <small style={{ color: 'var(--muted)' }}>출처 {asked.official.source} · {asked.official.baseYear}년 기준 · 수정 {asked.official.updatedAt}</small>
                      </div>
                    )}
                    {!asked.notice?.show && asked.scenes.slice(0, 3).map((sc) => (
                      <div key={sc.videoId} className="fs" style={{ marginTop: '.5rem' }}>
                        <span className="n"><Icon name="play" fill /></span>
                        <div><b>{sc.title}</b><p>{fmt(sc.found.start)} · {sc.found.label}</p><VerifyBadge v={sc.found.verification} /></div>
                        {sc.videoId === video.videoId
                          ? <a className="lk" href="#" onClick={(e) => { e.preventDefault(); seek(sc.found.start); }}><Icon name="play" fill /><span className="num">{fmt(sc.found.start)}</span></a>
                          : <a className="lk" href={`#/watch/${sc.videoId}?t=${sc.found.start}&e=${sc.found.end}${asked.jobId ? `&job=${asked.jobId}` : ''}`}><Icon name="play" fill /><span className="num">{fmt(sc.found.start)}</span></a>}
                      </div>
                    ))}
                  </div>
                )}
              </section>
            )}

            {/* 장면 목록 */}
            <section className="card chap">
              <div className="hd"><h2>영상 장면</h2><p>누르면 그 시간부터 재생돼요.{formShown && ' 신청서 작성 장면은 위 「신청서 따라하기」에 있어요.'}</p></div>
              {chapRows.map((c) => (
                <div key={c.id} className="ch" aria-current={c.id === current.id ? 'true' : undefined}>
                  <div className="t num">{fmt(c.start)}<small>{c.id === current.id ? '재생 중' : c.id === matched.id ? '찾은 장면' : c.step ? '신청 단계' : c.stepLabel}</small></div>
                  <b className="one" title={c.title}>{c.title}</b>
                  <button className="go" onClick={() => (c.step ? seekStep(c.start) : seek(c.start))}><Icon name="play" fill />{c.id === current.id ? '다시 보기' : '여기부터'}</button>
                </div>
              ))}
              {chapList.length > CHAP_FIRST && (
                <button className="btn btn-line chap-more" aria-expanded={chapAll} onClick={() => setChapAll(!chapAll)}>
                  {chapAll ? '접기' : `장면 ${chapList.length - chapRows.length}개 더 보기`}
                </button>
              )}
              <div className="fb"><span>장면 구분과 검증 상태는 AI 분석 결과라 틀릴 수 있어요.</span><a href="#">장면이 다르면 알려주기</a></div>
            </section>

            {/* 신청 단계 따라 하기 — 줄이 둘 이상일 때만 (하나뿐이면 칸을 숨김). 단계 제목 한 줄씩, 자막 미리보기 없음.
                신청서 따라하기가 있으면 같은 단계는 한 줄(처음 장면)만, 신청서 작성은 아래 신청서 따라하기로 */}
            {stepRows.length > 1 && (
              <section className="card follow steps1">
                <div className="hd">
                  <h2>신청 단계 따라 하기</h2>
                  <p>누르면 그 장면부터 재생돼요. 영상에 나온 순서예요.</p>
                </div>
                {stepRows.map((c, i) => {
                  const toForm = formShown && c.step === 3;
                  const now = !toForm && time >= c.start && time < c.end;
                  const done = !toForm && time >= c.end;
                  return (
                    <div key={c.id} className={`fs${done ? ' done' : now ? ' now' : ''}`}>
                      <span className="n">{done ? <Icon name="check" /> : i + 1}</span>
                      <b className="one" title={c.title}>{formShown && c.step ? `${CIRCLED[c.step - 1]} ${c.short}` : c.title}{now && <span className="st">보는 중</span>}</b>
                      {toForm ? (
                        <a className="lk" href="#formmode" onClick={(e) => { e.preventDefault(); document.getElementById('formmode')?.scrollIntoView({ behavior: 'smooth', block: 'start' }); }}>아래 신청서 따라하기에서 자세히<Icon name="arrow" /></a>
                      ) : (
                        <a className="lk" href="#" onClick={(e) => { e.preventDefault(); seekStep(c.start); }}><Icon name="play" fill /><span className="num">{fmt(c.start)}</span></a>
                      )}
                    </div>
                  );
                })}
                <div className="nx">
                  {prevStep ? <button className="btn btn-line" onClick={() => seekStep(prevStep.start)}><Icon name="back" />{stepName(prevStep)}</button> : <span />}
                  {nextStep && <button className="btn btn-dark" onClick={() => seekStep(nextStep.start)}>{stepName(nextStep)}<Icon name="arrow" /></button>}
                </div>
              </section>
            )}

            {/* 신청서 따라하기 — 신청서 작성 장면이 둘 이상인 영상에서만 */}
            {(formShown || video.formMap) && (
              <section className="card follow formmode" id="formmode" aria-label="신청서 따라하기">
                <div className="hd">
                  <h2>신청서 따라하기</h2>
                  <p>{video.formMap ? '신청서의 칸을 누르면 그 칸을 설명하는 장면이 나와요.' : '신청서 항목을 누르면 그 항목을 쓰는 장면이 나와요.'} 개인정보는 입력하지 않아요.</p>
                </div>
                {video.formMap && (
                  <div className="fm-tabs" role="tablist" aria-label="신청서 따라하기 보기">
                    <button role="tab" aria-selected={formTab === 'map'} onClick={() => setFormTab('map')}>서식 지도</button>
                    <button role="tab" aria-selected={formTab === 'photo'} onClick={() => setFormTab('photo')}>내 신청서 비추기</button>
                    {formShown && <button role="tab" aria-selected={formTab === 'list'} onClick={() => setFormTab('list')}>항목 목록</button>}
                  </div>
                )}
                {video.formMap && formTab !== 'list' ? (
                  <FormMapView videoId={video.videoId} mode={formTab} onSeek={(t) => seekStep(t)} />
                ) : !formOpen ? (
                  <button className="btn btn-pri btn-lg" style={{ marginTop: '.6rem' }} onClick={() => { setFormOpen(true); seekStep(formItems[0].start); }}>
                    <Icon name="play" fill />신청서 따라하기 시작 ({formItems.length}개 항목)
                  </button>
                ) : (
                  <>
                    <div className="prog" style={{ margin: '.6rem 0' }}><div><i style={{ width: `${(seenCount / formItems.length) * 100}%` }} /></div>{formItems.length}개 중 {seenCount}개 봤어요</div>
                    {formItems.map((c, i) => {
                      const now = time >= c.start && time < c.end;
                      return (
                        <div key={c.id} className={`fs${seen[c.id] ? ' done' : now ? ' now' : ''}`}>
                          <span className="n">{seen[c.id] ? <Icon name="check" /> : i + 1}</span>
                          <div>{now && <span className="st">지금 보는 항목</span>}<b>{itemName(c)}</b></div>
                          <a className="lk" href="#" onClick={(e) => { e.preventDefault(); seekStep(c.start); }}><Icon name="play" fill /><span className="num">{fmt(c.start)}</span></a>
                        </div>
                      );
                    })}
                    <div className="nx">
                      <button className="btn btn-line" onClick={() => setSeen(Object.fromEntries(formItems.map((c) => [c.id, true])))}>모두 봤어요</button>
                      <button className="btn btn-dark" onClick={() => setListOpen(true)} disabled={seenCount === 0}>내 신청 준비 체크리스트<Icon name="arrow" /></button>
                    </div>
                    {listOpen && (
                      <div className="checklist">
                        <h3>내 신청 준비 체크리스트</h3>
                        {docs.length > 0 && (
                          <>
                            <b>준비 서류 (공식 정보)</b>
                            <div className="docs">
                              {docs.map((d) => (
                                <label key={d.id}><input type="checkbox" checked={!!checked[d.id]} onChange={(e) => setChecked({ ...checked, [d.id]: e.target.checked })} /><span>{d.name}</span></label>
                              ))}
                            </div>
                          </>
                        )}
                        <b>신청서에 쓰는 항목</b>
                        <ul>{formItems.map((c) => <li key={c.id}>{seen[c.id] ? '☑' : '☐'} {itemName(c)} <span className="num">({fmt(c.start)})</span></li>)}</ul>
                        {policy && <p><b>신청 방법</b> {policy.applyMethod.split('\n').map((x) => x.replace(/^[\s○ㅇ◦•\-·※*]+/, '').trim()).filter(Boolean)[0]}<br /><b>문의</b> {policy.contact}</p>}
                        <p className="note">출처 {policy?.source} · 수정 {policy?.updatedAt}. 자격 판정이 아니라 준비 확인용이에요.</p>
                        <button className="btn btn-pri" onClick={shareChecklist}><Icon name="share" />{listCopied ? '복사했어요 — 카카오톡에 붙여넣으세요' : '가족에게 보내기'}</button>
                      </div>
                    )}
                  </>
                )}
              </section>
            )}


          {/* 공식 정책정보 (공공데이터 항목) */}
          {!policy && (
            <aside className="card pp-card" aria-label="공식 정책정보">
              <div className="hd"><div className="r1"><SourceTag kind="gov" /></div><h2>공식 정책 정보</h2></div>
              <div className="blk">
                <p>이 영상과 연결된 공식 정책 정보가 없어요.</p>
                <p className="note">사회보장 공공데이터(복지서비스정보·공공서비스(혜택) 정보)에서 이 영상과 같은 정책을 확실하게 찾지 못했어요.</p>
              </div>
              <div className="cta">
                <a className="btn btn-line btn-lg btn-block" href="https://www.bokjiro.go.kr" target="_blank" rel="noreferrer">복지로에서 찾아보기<Icon name="ext" /></a>
              </div>
            </aside>
          )}
          {policy && <aside className="card pp-card" aria-label="공식 정책정보">
            <div className="hd">
              <div className="r1"><SourceTag kind="gov" /><span style={{ fontSize: '.8rem', color: 'var(--muted)' }}>{policy.baseYear}년 기준</span></div>
              <h2>{policy.name}</h2>
              <p>출처 {policy.source} · 수정 {policy.updatedAt}</p>
            </div>
            <div className="blk"><h3><span className="n">1</span>받을 수 있는 분</h3>
              <p style={{ whiteSpace: 'pre-line' }}>{policy.targetDetail || policy.target}</p>
              {policy.easy?.targetDetail && <EasyText text={policy.easy.targetDetail} />}</div>
            <div className="blk"><details>
              <summary><span className="n">2</span>선정 기준<span className="r">자세히<Icon name="chev" /></span></summary>
              <p style={{ whiteSpace: 'pre-line' }}>{policy.criteria}</p>
              {policy.easy?.criteria && <EasyText text={policy.easy.criteria} />}
            </details></div>
            {policy.amount && policy.amount.length > 0 ? (
              <div className="blk"><h3><span className="n">3</span>받는 금액</h3>
                {policy.amount.map((a, i) => (
                  <div key={a.label} className="money" style={i ? { marginTop: '.1rem' } : undefined}><span>{a.label}</span><b className="num" style={i ? { fontSize: '1.1rem', color: 'var(--ink)' } : undefined}>{a.value}</b></div>
                ))}
                <details><summary>지원 내용 전체<span className="r"><Icon name="chev" /></span></summary><p style={{ whiteSpace: 'pre-line' }}>{policy.benefit}</p></details></div>
            ) : (
              <div className="blk"><details open>
                <summary><span className="n">3</span>지원 내용<span className="r"><Icon name="chev" /></span></summary>
                <p style={{ whiteSpace: 'pre-line' }}>{policy.benefit}</p>
              </details></div>
            )}
            <div className="blk"><details>
              <summary><span className="n">4</span>신청 방법·시기<span className="r">{policy.applyWhen}<Icon name="chev" /></span></summary>
              <p style={{ whiteSpace: 'pre-line' }}>{policy.applyMethod}</p>
            </details></div>
            <div className="blk"><h3><span className="n">5</span>준비 서류 확인</h3>
              <div className="docs">
                {docs.map((d) => (
                  <label key={d.id} className={current.relatedDocs.includes(d.id) ? 'rel' : ''}>
                    <input type="checkbox" checked={!!checked[d.id]} onChange={(e) => setChecked({ ...checked, [d.id]: e.target.checked })} />
                    <span>{d.name}</span>
                    {current.relatedDocs.includes(d.id) && <span className="tag tag-blue">이 장면</span>}
                  </label>
                ))}
              </div>
              <p className="note">준비 여부를 확인하는 용도예요. 자격을 판정하지 않아요.</p></div>
            {officialSteps.length > 0 && <div className="blk"><h3><span className="n">6</span>공식 신청 단계</h3>
              <ol className="flow">
                {officialSteps.map((s) => {
                  const cur = current.step ?? 0;
                  const state = s.step < cur ? 'done' : s.step === cur ? 'now' : '';
                  return (
                    <li key={s.step} className={state} style={s.videoAt !== undefined ? { cursor: 'pointer' } : undefined}
                      onClick={s.videoAt !== undefined ? () => seekStep(s.videoAt!) : undefined}>
                      <span className="d">{state === 'done' ? <Icon name="check" style={{ width: '.8rem', height: '.8rem' }} /> : s.step}</span>
                      <div>
                        <b>{s.title}{state === 'now' ? ' · 지금 보는 중' : ''}</b>
                        <small>
                          {s.videoAt !== undefined && <a href="#" onClick={(e) => { e.preventDefault(); e.stopPropagation(); seekStep(s.videoAt!); }}>영상 {fmt(s.videoAt)}부터 보기 </a>}
                          {s.verification === 'subtitle' && <span className="vb vb-sub" style={{ fontSize: '.72rem', padding: '0 .4rem' }}>자막에서 확인됨</span>}
                          {s.videoAt === undefined && <span className="vb vb-none" style={{ fontSize: '.72rem', padding: '0 .4rem' }}>해당 장면 없음</span>}
                          {s.verification !== 'screen' && ` ${s.note}`}
                        </small>
                      </div>
                    </li>
                  );
                })}
              </ol></div>}
            <div className="blk"><h3><span className="n">7</span>문의·공식 링크</h3>
              {contacts(policy.contact).map((c) => (
                <p key={c.name + c.tel}>{c.name}{c.tel && <> · <a href={`tel:${c.tel.replace(/-/g, '')}`}>{c.tel}</a></>}</p>
              ))}
              {policy.officialUrls.map((u) => <p key={u.url}><a href={u.url} target="_blank" rel="noreferrer">{u.label}<Icon name="ext" /></a></p>)}
            </div>
            <div className="cta">
              <a className="btn btn-pri btn-lg btn-block" href={policy.applyUrl} target="_blank" rel="noreferrer">공식 신청 페이지로<Icon name="ext" /></a>
              <div className="two">
                <a className="btn btn-line" href="https://www.bokjiro.go.kr/ssis-tbu/twatca/wlfcl/wlfclPage.do" target="_blank" rel="noreferrer" title="복지로 복지지도"><Icon name="pin" />주민센터 찾기</a>
                {contacts(policy.contact).filter((c) => c.tel).slice(0, 1).map((c) => (
                  <a key={c.tel} className="btn btn-line" href={`tel:${c.tel.replace(/-/g, '')}`}><Icon name="phone" />{c.tel} 문의</a>
                ))}
              </div>
              <p>신청은 공식 기관 사이트에서 이뤄져요. 복지바로봄은 개인정보를 받지 않아요. 자격·금액·기간은 공식 정보를 기준으로 하세요.</p>
            </div>
          </aside>}
          </div>
        </div>
      </div>
    </main>
  );
}
