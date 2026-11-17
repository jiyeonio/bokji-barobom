// 신청서 지도 · 내 신청서 비추기 (2026-11-15)
// - 지도: 국가법령정보센터 공식 빈 서식 PDF를 이미지로, 칸 위치는 PDF 글자 좌표. 칸을 누르면 그 칸 설명 장면 재생 + 이 칸에 쓸 것
// - 비추기: 사진을 서버에서 빈 서식에 겹쳐(OpenCV) 칸 위치를 옮김. 사진은 저장하지 않음(브라우저 화면에만, 서버는 메모리에서 처리 후 버림)
import { useEffect, useRef, useState } from 'react';
import { Icon } from './Icon';
import { SourceTag } from './Common';
import { fmt } from '../utils';

const BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? '';

export interface FormField {
  id: string; page: number; section: string; label: string; box: number[];
  scene: { start: number; end: number }; sceneLevel: 'field' | 'section';
  write: { text: string; source: 'official' | 'video'; label: string } | null;
  also: { text: string; source: 'official' | 'video'; label: string } | null;
  videoExplained: boolean; sectionGuide: string | null;
}
export interface FormMapData {
  form: { id: string; title: string; revision: string; source: string; sourceUrl: string; note: string; pages: { n: number; image: string; width: number; height: number }[] };
  video: string; fields: FormField[];
}
interface AlignResult { matched: boolean; reason?: string; title?: string; page?: number; width: number; height: number; fields?: { id: string; box: number[] }[] }

const pctBox = (b: number[], w: number, h: number, pad = 0.006) => ({
  left: `${(b[0] / w - pad) * 100}%`, top: `${(b[1] / h - pad) * 100}%`,
  width: `${((b[2] - b[0]) / w + 2 * pad) * 100}%`, height: `${((b[3] - b[1]) / h + 2 * pad) * 100}%`,
});
const cls = (f: FormField) => (f.videoExplained ? 'fx ok' : f.write ? 'fx off' : 'fx none');

function FieldInfo({ f, onSeek }: { f: FormField; onSeek: (t: number) => void }) {
  return (
    <div className="fm-info" role="status" aria-live="polite">
      <div className="t"><small>{f.section}</small><b>{f.label}</b>
        <button className="btn btn-line" onClick={() => onSeek(f.scene.start)}><Icon name="play" fill />{f.sceneLevel === 'field' ? '이 칸 설명' : '이 구역 설명'} {fmt(f.scene.start)}</button>
      </div>
      <div className="w">
        <span className="k">이 칸에 쓸 것</span>
        {f.write ? (
          <>
            <p>{f.write.text}</p>
            <span className={`src1 ${f.write.source}`}>{f.write.source === 'official' ? <SourceTag kind="gov" /> : <SourceTag kind="ai" />}{f.write.label}</span>
            {f.also && <><p className="also">{f.also.text}</p><span className="src1 video"><SourceTag kind="ai" />{f.also.label}</span></>}
          </>
        ) : (
          <p className="none">이 칸은 영상에 설명이 없어요.{f.sceneLevel === 'section' && ' 이 칸이 있는 구역의 설명 장면을 재생해요.'}</p>
        )}
        {!f.videoExplained && f.write && <p className="none sm">영상에는 이 칸 설명이 따로 없어요.</p>}
        {f.sectionGuide && <p className="guide"><b>구역 안내</b> {f.sectionGuide} <span className="src1 video">영상 화면 기준</span></p>}
      </div>
    </div>
  );
}

export function FormMapView({ videoId, mode, onSeek }: { videoId: string; mode: 'map' | 'photo'; onSeek: (t: number) => void }) {
  const [m, setM] = useState<FormMapData | null>(null);
  const [page, setPage] = useState(1);
  const [sel, setSel] = useState<string | null>(null);
  const [big, setBig] = useState(false);
  // 비추기
  const [photo, setPhoto] = useState<string | null>(null);
  const [res, setRes] = useState<AlignResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [isExample, setIsExample] = useState(false);
  const [cam, setCam] = useState(false);
  const fileRef = useRef<HTMLInputElement | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);

  useEffect(() => { fetch(`${BASE}/api/forms/map/${videoId}`).then((r) => (r.ok ? r.json() : null)).then(setM).catch(() => setM(null)); }, [videoId]);
  useEffect(() => () => { if (photo) URL.revokeObjectURL(photo); }, [photo]);
  useEffect(() => () => streamRef.current?.getTracks().forEach((t) => t.stop()), []);
  useEffect(() => { setSel(null); }, [mode]);
  if (!m) return null;
  const byId = Object.fromEntries(m.fields.map((f) => [f.id, f]));
  const pick = (id: string) => { const f = byId[id]; if (!f) return; setSel(id); setBig(false); onSeek(f.scene.start); };
  const cur = sel ? byId[sel] : null;

  const process = async (blob: Blob, example: boolean) => {
    if (photo) URL.revokeObjectURL(photo);
    setPhoto(URL.createObjectURL(blob)); setRes(null); setSel(null); setBusy(true); setIsExample(example);
    try {
      const r = await fetch(`${BASE}/api/forms/align`, { method: 'POST', headers: { 'Content-Type': blob.type || 'image/jpeg' }, body: blob });
      setRes(r.ok ? await r.json() : { matched: false, reason: '사진을 처리하지 못했어요', width: 1, height: 1 });
    } catch { setRes({ matched: false, reason: '사진을 처리하지 못했어요', width: 1, height: 1 }); }
    setBusy(false);
  };
  const tryExample = async () => { const b = await (await fetch(`forms/${m.form.id}_example_photo.jpg`)).blob(); process(b, true); };
  const openCam = async () => {
    try { const s = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } }); streamRef.current = s; setCam(true); setTimeout(() => { if (videoRef.current) { videoRef.current.srcObject = s; videoRef.current.play(); } }, 50); } catch { alert('카메라를 열 수 없어요. 사진 올리기를 이용해 주세요.'); }
  };
  const shoot = () => {
    const v = videoRef.current; if (!v) return;
    const c = document.createElement('canvas'); c.width = v.videoWidth; c.height = v.videoHeight; c.getContext('2d')!.drawImage(v, 0, 0);
    streamRef.current?.getTracks().forEach((t) => t.stop()); streamRef.current = null; setCam(false);
    c.toBlob((b) => b && process(b, false), 'image/jpeg', 0.9);
  };

  const pg = m.form.pages.find((p) => p.n === page)!;
  const mapImage = (inModal: boolean) => (
    <div className={`fm-img${inModal ? ' big' : ''}`}>
      <img src={pg.image} alt={`${m.form.title} ${page}쪽`} />
      {m.fields.filter((f) => f.page === page).map((f) => (
        <button key={f.id} className={`${cls(f)}${sel === f.id ? ' sel' : ''}`} style={pctBox(f.box, pg.width, pg.height)} title={f.label} aria-label={`${f.section} ${f.label}`} onClick={() => pick(f.id)} />
      ))}
    </div>
  );
  const photoImage = (inModal: boolean) => photo && res?.matched && (
    <div className={`fm-img${inModal ? ' big' : ''}`}>
      <img src={photo} alt="올린 신청서 사진" />
      {res.fields!.map((x) => byId[x.id] && (
        <button key={x.id} className={`${cls(byId[x.id])}${sel === x.id ? ' sel' : ''}`} style={pctBox(x.box, res.width, res.height, 0.004)} title={byId[x.id].label}
          aria-label={`${byId[x.id].section} ${byId[x.id].label}`} onClick={() => pick(x.id)} />
      ))}
    </div>
  );
  const legend = <p className="fm-legend"><i className="fx ok" />영상 설명 있음 <i className="fx off" />공식 작성 방법만 <i className="fx none" />설명 없음</p>;

  return (
    <div className="fm">
      {mode === 'map' ? (
        <>
          <div className="fm-pages" role="tablist">
            {m.form.pages.map((p) => <button key={p.n} role="tab" aria-selected={page === p.n} onClick={() => { setPage(p.n); setSel(null); }}>{p.n}쪽</button>)}
            <button className="btn btn-line fm-big" onClick={() => setBig(true)}><Icon name="full" />크게 보기</button>
          </div>
          {mapImage(false)}
          {legend}
        </>
      ) : (
        <>
          <p className="fm-privacy"><Icon name="info" /><b>사진은 저장되지 않아요.</b> 인쇄된 서식 선만 맞추고 손글씨·개인정보는 읽지 않아요. 처리 후 바로 지워요.</p>
          <div className="fm-acts">
            <button className="btn btn-pri btn-lg" onClick={tryExample} disabled={busy}><Icon name="scan" />예시 신청서로 해보기</button>
            <button className="btn btn-line" onClick={() => fileRef.current?.click()} disabled={busy}>내 신청서 사진 올리기</button>
            {typeof navigator !== 'undefined' && !!navigator.mediaDevices?.getUserMedia && <button className="btn btn-line" onClick={openCam} disabled={busy}>카메라로 찍기</button>}
            <input ref={fileRef} type="file" accept="image/*" capture="environment" hidden onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ''; if (f) process(f, false); }} />
          </div>
          {cam && (
            <div className="fm-cam"><video ref={videoRef} playsInline muted /><div><button className="btn btn-pri" onClick={shoot}>찍기</button>
              <button className="btn btn-line" onClick={() => { streamRef.current?.getTracks().forEach((t) => t.stop()); setCam(false); }}>닫기</button></div></div>
          )}
          {busy && <p className="fm-note">서식을 맞추는 중…</p>}
          {res && !res.matched && (
            <div className="fm-fail" role="status"><b>이 사진에서 신청서를 알아보지 못했어요.</b> {res.reason}<br />지금은 「{m.form.title}」만 알아볼 수 있어요. 서식 전체가 보이게, 밝은 곳에서 찍어 주세요.</div>
          )}
          {res?.matched && (
            <>
              <p className="fm-ok"><Icon name="check" />「{res.title}」 {res.page}쪽으로 알아봤어요 · 칸 {res.fields!.length}개 <button className="btn btn-line fm-big" onClick={() => setBig(true)}><Icon name="full" />크게 보기</button></p>
              {photoImage(false)}
              {legend}
            </>
          )}
          {isExample && <p className="fm-note">예시 사진: 국가법령정보센터 공식 빈 서식을 기울이고 조명을 넣어 만든 시험용 이미지예요.</p>}
        </>
      )}
      {cur ? <FieldInfo f={cur} onSeek={onSeek} /> : <p className="fm-note">칸을 누르면 그 칸을 설명하는 장면이 나오고, 이 칸에 쓸 것을 보여 줘요.</p>}
      <p className="fm-src"><SourceTag kind="gov" />서식 출처: <a href={m.form.sourceUrl} target="_blank" rel="noreferrer">{m.form.source}</a> 「{m.form.title}」 &lt;{m.form.revision}&gt;. {m.form.note}</p>
      {big && (
        <div className="fm-modal" role="dialog" aria-label="신청서 크게 보기" onClick={(e) => { if (e.target === e.currentTarget) setBig(false); }}>
          <div className="in">
            <div className="hd"><b>{mode === 'map' ? `${m.form.title} ${page}쪽` : '내 신청서'}</b><span>칸을 누르면 그 장면이 재생돼요</span><button className="btn btn-line" onClick={() => setBig(false)}>닫기</button></div>
            {mode === 'map' ? mapImage(true) : photoImage(true)}
          </div>
        </div>
      )}
    </div>
  );
}
