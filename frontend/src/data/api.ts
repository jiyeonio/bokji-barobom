// 데이터 불러오기 — VITE_API_BASE_URL 이 있으면 복지바로봄 백엔드, 없으면 가짜 데이터
import { basicPension, sceneResults, videoDetail } from './mock';
import type { OfficialAnswer, Policy, PolicyBrief, SceneResult, StepCard, VideoDetail } from './types';

const BASE = import.meta.env.VITE_API_BASE_URL as string | undefined;

export interface SearchResponse {
  query: string;
  policies: Policy[];
  scenes: SceneResult[];
  /** VLM 화면 확인 작업 id — status가 'pending'이면 pollSearch로 갱신 */
  jobId?: string;
  status?: 'pending' | 'done' | 'error';
  official?: OfficialAnswer | null;
  /** 영상에 답이 없을 때 안내 (예: 신청 기간 질문) */
  notice?: { show: boolean; reason: string | null; message: string };
  /** 정책은 찾았지만 그 정책에 연결된 시연 영상이 없음 */
  noVideo?: boolean;
  /** 그 정책의 단계 카드 (결과가 애매할 때 버튼으로) */
  stepCards?: StepCard[];
  /** 정책 화면 추천 질문 */
  chips?: string[];
}

export async function searchWelfare(query: string, policy?: string): Promise<SearchResponse> {
  if (BASE) {
    const p = policy ? `&policy=${encodeURIComponent(policy)}` : '';
    const res = await fetch(`${BASE}/api/welfare/search?q=${encodeURIComponent(query)}${p}`);
    if (!res.ok) throw new Error('검색에 실패했어요');
    return res.json();
  }
  return { query, policies: [basicPension], scenes: sceneResults, status: 'done' };
}

/** VLM 화면 확인이 끝날 때까지 갱신된 결과를 받음 */
export async function pollSearch(jobId: string): Promise<SearchResponse> {
  const res = await fetch(`${BASE}/api/welfare/search/${jobId}`);
  if (!res.ok) throw new Error('검색 결과를 갱신하지 못했어요');
  return res.json();
}

export async function getVideo(videoId: string, opts: { jobId?: string; t?: number; e?: number } = {}): Promise<VideoDetail> {
  if (BASE) {
    const q = new URLSearchParams();
    if (opts.jobId) q.set('jobId', opts.jobId);
    if (opts.t !== undefined) q.set('t', String(opts.t));
    if (opts.e !== undefined) q.set('e', String(opts.e));
    const res = await fetch(`${BASE}/api/videos/${videoId}?${q}`);
    if (!res.ok) throw new Error('영상 정보를 불러오지 못했어요');
    return res.json();
  }
  return videoDetail;
}

async function getJson<T>(path: string, msg: string): Promise<T> {
  const res = await fetch(`${BASE ?? ''}${path}`);
  if (!res.ok) throw new Error(msg);
  return res.json();
}

/** 검색창 아래 추천 질문 (백엔드 SUGGEST_HOME, 없으면 기본값) */
export const SUGGEST_FALLBACK = ['기초연금 신청할 때 뭐 챙겨가야 돼요?', '월세 지원 받으려면 뭐 내야 돼요?', '아이돌봄 어디서 신청해요?', '노인성 질병 종류와 질병코드 표'];
export async function getSuggest(): Promise<string[]> {
  if (!BASE) return SUGGEST_FALLBACK;
  return getJson<{ home: string[] }>('/api/suggest', '').then((r) => r.home).catch(() => SUGGEST_FALLBACK);
}

export interface PoliciesMeta {
  meta: { source: string; fetchedAt: string; count: number; agencies: number; audienceRule: string; localApi: string; localSource?: string; localOnly?: number; crossChecked?: number };
  regions: Record<string, string[]>;
  audiences: Record<string, string>;
}
export const getPoliciesMeta = () => getJson<PoliciesMeta>('/api/policies/meta', '정책 정보를 불러오지 못했어요');

export interface PolicySearch { total: number; page: number; size: number; items: PolicyBrief[]; source: string; fetchedAt: string }
export function searchPolicies(p: { q?: string; audience?: string; sido?: string; sigungu?: string; nationwide?: boolean; page?: number }) {
  const u = new URLSearchParams();
  Object.entries(p).forEach(([k, v]) => { if (v !== undefined && v !== '') u.set(k, String(v)); });
  return getJson<PolicySearch>(`/api/policies/search?${u}`, '정책을 찾지 못했어요');
}

export interface PolicyItem {
  policy: Policy;
  raw: Record<string, string | null>;
  curatedPolicyId: string | null;
  curatedName: string | null;
  videos: { videoId: string; title: string; publisher: string; publishedAt: string; duration: string; thumbnailUrl: string }[];
  stepCards: StepCard[];
  chips: string[];
  chipCtx: string;
}
export const getPolicyItem = (id: string) => getJson<PolicyItem>(`/api/policies/item/${encodeURIComponent(id)}`, '정책 정보를 불러오지 못했어요');

/** AI 답변 (RAG, Claude API) — 공공데이터 청크로만 답함. 질문이 Anthropic API로 전송됨 */
export interface RagAnswer {
  answer?: string;
  sentences?: { text: string; kind: 'fact' | 'not_found' | 'video_diff'; chunk_ids: string[] }[];
  notFound?: boolean;
  sources?: { policyId: string; policyName: string; urls: { label: string; url: string }[]; baseDate: string; source: string }[];
  retrieved?: { chunkId: string; field: string; policyName: string; score: number; text: string }[];
  error?: string;
}
export async function askRag(body: { question: string; policyId?: string; videoId?: string; t?: number }): Promise<RagAnswer> {
  const res = await fetch(`${BASE ?? ''}/api/rag/answer`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  if (!res.ok) return { error: res.status === 400 ? '질문을 확인해 주세요' : 'AI 답변을 받지 못했어요' };
  return res.json();
}
