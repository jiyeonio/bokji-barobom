import { useEffect, useState, type ReactNode } from 'react';
import { Icon } from './Icon';

type FontSize = '1' | '2' | '3';

function load(key: string): string | null {
  try { return localStorage.getItem(key); } catch { return null; }
}
function save(key: string, value: string) {
  try { localStorage.setItem(key, value); } catch { /* 저장 못 해도 동작에는 문제 없음 */ }
}

/** 글자 크기 · 고대비 상태 (html 태그의 data-fs / data-contrast 로 전체 화면에 적용) */
export function useA11y() {
  const [fs, setFs] = useState<FontSize>(() => (load('bb-fs') as FontSize) || '1');
  const [contrast, setContrast] = useState<boolean>(() => load('bb-contrast') === '1');

  useEffect(() => {
    document.documentElement.setAttribute('data-fs', fs);
    save('bb-fs', fs);
  }, [fs]);
  useEffect(() => {
    if (contrast) document.documentElement.setAttribute('data-contrast', 'high');
    else document.documentElement.removeAttribute('data-contrast');
    save('bb-contrast', contrast ? '1' : '0');
  }, [contrast]);

  return { fs, setFs, contrast, setContrast };
}

/** 화면 읽어주기 (브라우저 내장 음성, Web Speech API · 한국어). 켜면 지금 화면의 주요 내용을 읽고, 켜 둔 동안 누른 글을 읽음 */
function speak(text: string) {
  const synth = window.speechSynthesis;
  if (!synth || !text.trim()) return;
  synth.cancel();
  const u = new SpeechSynthesisUtterance(text.replace(/\s+/g, ' ').slice(0, 600));
  u.lang = 'ko-KR'; u.rate = 0.95;
  const ko = synth.getVoices().find((v) => v.lang.startsWith('ko'));
  if (ko) u.voice = ko;
  synth.speak(u);
}

function pageSummary(): string {
  const pick = (sel: string) => Array.from(document.querySelectorAll<HTMLElement>(sel)).map((e) => e.innerText.trim()).filter(Boolean);
  const parts = [...pick('main h1'), ...pick('main .ans-scene h3, main .ans-scene .tm, main .ans-off .ai'), ...pick('main .pp-card h2, main .pp-card .blk > h3 + p')];
  return parts.slice(0, 8).join('. ') || document.title;
}

function A11yBar() {
  const { fs, setFs, contrast, setContrast } = useA11y();
  const [reading, setReading] = useState(false);
  const canSpeak = typeof window !== 'undefined' && 'speechSynthesis' in window;
  useEffect(() => {
    if (!reading) { window.speechSynthesis?.cancel(); return; }
    speak(pageSummary());
    const onClick = (e: MouseEvent) => {   // 켜 둔 동안 누른 글을 읽음(버튼·링크 동작은 그대로)
      const el = (e.target as HTMLElement).closest('main p, main h1, main h2, main h3, main b, main li, main label, main button, main a, main span') as HTMLElement | null;
      if (el && !el.closest('.a11y')) speak(el.innerText);
    };
    document.addEventListener('click', onClick, true);
    return () => { document.removeEventListener('click', onClick, true); window.speechSynthesis?.cancel(); };
  }, [reading]);
  const sizes: { v: FontSize; label: string }[] = [
    { v: '1', label: '보통' }, { v: '2', label: '크게' }, { v: '3', label: '아주 크게' },
  ];
  return (
    <div className="a11y"><div className="wrap">
      <span className="lb">글자 크기</span>
      <div className="seg" role="group" aria-label="글자 크기">
        {sizes.map((s) => (
          <button key={s.v} className="fs-btn" data-v={s.v} aria-pressed={fs === s.v} onClick={() => setFs(s.v)}>
            <b>가</b>{s.label}
          </button>
        ))}
      </div>
      <button className="tog" aria-pressed={contrast} onClick={() => setContrast(!contrast)}><Icon name="contrast" />고대비</button>
      <button className="tog" aria-pressed={reading} disabled={!canSpeak} title={canSpeak ? '켜면 화면 내용을 읽어 주고, 켜 둔 동안 누른 글을 읽어요' : '이 브라우저는 음성 읽기를 지원하지 않아요'}
        onClick={() => setReading(!reading)}><Icon name="speaker" />{reading ? '읽어주기 끄기' : '화면 읽어주기'}</button>
      <span className="sp" />
      <span className="links">
        <a href="https://www.bokjiro.go.kr" target="_blank" rel="noreferrer">복지로 <Icon name="ext" /></a>
        <a href="https://www.gov.kr" target="_blank" rel="noreferrer">정부24 <Icon name="ext" /></a>
      </span>
    </div></div>
  );
}

const NAV = [
  { to: '/', label: '홈' },
  { to: '/policies', label: '정책 찾기' },
  { to: '/results', label: '영상 장면 찾기' },
  { to: '/guide', label: '이용 안내' },
];

function Header({ current }: { current: string }) {
  return (
    <header className="hdr np-hdr">
      <div className="wrap top">
        <a className="logo" href="#/"><b>복지바로봄</b></a>
        <div className="end">
          <a href="tel:129"><Icon name="phone" />상담 129</a>
          <a className="login" href="#/"><Icon name="arrow" />로그인</a>
        </div>
      </div>
      <nav className="gnb" aria-label="주요 메뉴"><div className="wrap">
        {NAV.map((n) => (
          <a key={n.to} href={`#${n.to}`} aria-current={current === n.to || (n.to === '/policies' && current === '/policy') || (n.to === '/results' && current === '/watch') ? 'page' : undefined}>{n.label}</a>
        ))}
      </div></nav>
    </header>
  );
}

function Footer() {
  return (
    <footer className="ft"><div className="wrap">
      <div>
        <a className="logo" href="#/"><b>복지바로봄</b></a>
        <p>공모전 시제품 · 정부 공식 서비스가 아니에요. 정책 정보는 사회보장 공공데이터 기준이며 출처·기준일을 함께 보여 줘요.</p>
        <p><a href="#/agency">기관용 안내 공백 리포트</a></p>
      </div>
      <div className="calls">
        <span>보건복지상담센터<b>국번 없이 129</b></span>
        <span>국민연금공단<b>1355</b></span>
        <span>손말이음센터(청각·언어)<b>107</b></span>
      </div>
    </div></footer>
  );
}

export function Layout({ current, children }: { current: string; children: ReactNode }) {
  return (
    <>
      <A11yBar />
      <Header current={current} />
      {children}
      <Footer />
    </>
  );
}
