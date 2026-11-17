import type { FreshnessWarning, Verification } from '../data/types';
import { fmt } from '../utils';
import { Icon } from './Icon';

/** 영상 썸네일 — 실제 영상 캡처(thumbnailUrl)가 있으면 그걸 보여주고, 없으면 화면 모양으로 표시 */
export function Thumb({ href, type = 'screen', duration, src }: {
  href: string; type?: 'screen' | 'paper' | 'phone'; duration: string; src?: string;
}) {
  return (
    <a className={`thumb ${type === 'screen' ? '' : type}`} href={href}>
      {src ? (
        <img src={src} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
      ) : (
        <span className="scr"><i className="t" /><i /><i className="hl" /><i /></span>
      )}
      <span className="play"><Icon name="play" fill /></span>
      <span className="at">{duration}</span>
    </a>
  );
}

/** 검증 상태 배지 — 색 + 아이콘 + 글자로 구분 (pending: AI가 화면을 확인하는 중) */
export function VerifyBadge({ v, long }: { v: Verification; long?: boolean }) {
  if (v === 'pending') return <span className="vb vb-pending" aria-live="polite"><Icon name="scan" />AI가 화면 확인 중</span>;
  if (v === 'screen') return <span className="vb vb-screen"><Icon name="check" />화면에서 확인됨</span>;
  if (v === 'subtitle') return <span className="vb vb-sub"><Icon name="text" />{long ? '자막에서 확인됨 · 화면 없음' : '자막에서 확인됨'}</span>;
  return <span className="vb vb-none">{long ? '해당 장면 없음' : '확인 안 됨'}</span>;
}

/** 정보 출처 라벨 */
export function SourceTag({ kind }: { kind: 'gov' | 'ai' }) {
  return kind === 'gov'
    ? <span className="src src-gov"><Icon name="db" />공식 정책정보</span>
    : <span className="src src-ai"><Icon name="scan" />AI 영상 분석</span>;
}

/** 영상 정보 최신성 경고 — 「영상 속 정보는 OOOO년 기준이에요. 현재는 OOO이에요(출처·기준일)」 */
export function FreshWarn({ w, onSeek, active }: { w: FreshnessWarning; onSeek?: () => void; active?: boolean }) {
  return (
    <div className={`fresh${active ? ' on' : ''}`} role="note">
      <Icon name="alert" />
      <div>
        <b>영상 속 정보는 {w.videoYear}년 기준이에요</b>
        <p>영상: “{w.claim}” → 현재는 {w.current.map((c) => `${c.label} ${c.value}`).join(' · ')}이에요.</p>
        <small>출처 {w.source} · {w.baseYear}년 기준 · 수정 {w.updatedAt}</small>
      </div>
      {onSeek && <button className="btn btn-line" onClick={onSeek}><Icon name="play" fill />{fmt(w.start)}</button>}
    </div>
  );
}

/** 장면 행 (시간 + 이름) — 누르면 그 시간부터 재생 */
export function SceneRow({ href, t, label, hit }: { href: string; t: number; label: string; hit?: boolean }) {
  return (
    <a className={`scene${hit ? ' hit' : ''}`} href={href}>
      <span className="pl"><Icon name="play" fill /></span>
      <span className="t num">{fmt(t)}</span>
      <span className="l">{label}</span>
    </a>
  );
}
