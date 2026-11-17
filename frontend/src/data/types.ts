// 프론트와 백엔드가 주고받을 데이터 모양
// 백엔드 연동 시 이 타입에 맞춰 응답을 받으면 화면 코드를 거의 고치지 않아도 돼요.

/** 영상 장면 검증 상태 (VLM 재판별 결과). pending = AI가 화면을 확인하는 중 (확인 뒤 갱신) */
export type Verification = 'screen' | 'subtitle' | 'none' | 'pending';

/** 공식 정책정보 (사회보장 공공데이터 Open API: 한국사회보장정보원 복지서비스정보 · 행정안전부 공공서비스(혜택)) */
export interface Policy {
  policyId: string;
  name: string;
  category: string;
  target: string; // 한 줄 요약
  targetDetail: string; // 지원대상
  criteria: string; // 선정기준
  benefit: string; // 지원내용
  applyMethod: string; // 신청방법
  applyWhen: string; // 신청기한
  requiredDocs: string[]; // 구비서류
  contact: string; // 문의처
  agency: string; // 소관기관
  applyUrl: string; // 공식 신청 페이지
  officialUrls: { label: string; url: string }[];
  /** 금액 정보가 있는 정책만 (예: 기초연금). 공식 지원내용 원문에 있는 문구 그대로 */
  amount: { label: string; value: string }[] | null;
  source: string;
  baseYear: number | null;
  updatedAt: string; // 최종 수정일
  fetchedAt?: string; // 공공데이터를 받은 날
  /** 쉬운 말로 보기 (자동 검사·검토를 통과한 항목만). 원문은 항상 함께 보임 */
  easy?: { targetDetail?: string; criteria?: string };
  /** 구비서류 원문 메모 (통합 정책 DB 정책은 구비서류 원문을 그대로) */
  requiredDocsNotes?: string;
  /** 통합 정책 DB에서 온 정책 (영상 준비 중) */
  fromDb?: boolean;
  region?: string;
  audiences?: string[];
  /** 다른 공공데이터에도 있는 정책이면 그 출처 (교차 확인) */
  crossCheck?: string | null;
}

/** 결과가 애매할 때 보여 주는 그 정책의 단계 카드 버튼 */
export interface StepCard {
  step: number;
  label: string;
  videoId: string;
  start: number;
  end: number;
  title: string;
  videoTitle: string;
}

/** 통합 정책 DB 목록 한 줄 */
export interface PolicyBrief {
  id: string;
  name: string;
  summary: string;
  field: string;
  agency: string;
  agencyType: string;
  sido: string;
  sigungu: string;
  audiences: string[];
  supportType: string;
  views: number;
  updated: string;
  curated: string | null;
  videos: number;
  /** gov24 = 행정안전부 공공서비스(혜택), local = 한국사회보장정보원 지자체복지서비스에만 있음 */
  source: 'gov24' | 'local';
  /** 지자체복지서비스에도 있음(교차 확인) */
  localId: string | null;
}

/** 공식 정보로 답한 항목 (질문 의도에 맞는 정책 항목) */
export interface OfficialAnswer {
  policyId: string;
  items: { intent: string; field: string; value: unknown }[];
  source: string;
  baseYear: number | null;
  updatedAt: string;
}

/** 영상 정보 최신성 경고 — 장면 자막의 금액이 공공데이터 현재 값과 다를 때 (규칙: docs/service/freshness_rules.md) */
export interface FreshnessWarning {
  start: number;
  end: number;
  text: string; // 영상 자막 문장
  claim: string; // 영상 속 값 (예: 매달 25만 원)
  current: { label: string; value: string }[]; // 공공데이터 현재 값
  videoYear: string;
  policyName: string;
  source: string;
  baseYear: number | null;
  updatedAt: string;
  message: string;
}

/** 검색 결과의 영상 1개 + AI가 찾은 장면 */
export interface SceneResult {
  videoId: string;
  /** 신청서 작성 질문: 신청서 설명 시작 장면으로 고정된 1위 카드 (누르면 「내 신청서 비추기」) */
  formStart?: boolean;
  /** 이 영상에 신청서 지도가 있음 */
  formMap?: boolean;
  youtubeVideoId?: string;
  title: string;
  publisher: string;
  publishedAt: string;
  duration: string;
  thumbType?: 'screen' | 'paper' | 'phone'; // 실제 썸네일이 오기 전까지 쓰는 모양
  thumbnailUrl?: string;
  found: {
    start: number; // 초
    end: number;
    label: string;
    verification: Verification;
    warnings?: FreshnessWarning[];
  };
  otherScenes?: { start: number; end?: number; label: string; verification?: Verification; warnings?: FreshnessWarning[] }[];
  /** 같은 정책의 관련 영상(장면 확인 없음) — 장면 시간·배지 없이 영상으로만 보여 줌 */
  related?: boolean;
}

/** 영상 상세의 장면(챕터) — Policy-to-Scene Grounding 결과 */
export interface Chapter {
  id: string;
  start: number;
  end: number;
  title: string;
  short: string; // 타임라인에 쓰는 짧은 이름
  step: number | null; // 신청 단계 (없으면 null)
  stepLabel: string;
  verification: Verification;
  subtitle: string; // 대표 자막
  screenTitle: string; // 화면 예시 제목
  relatedDocs: string[]; // 이 장면에서 쓰는 서류 id
  follow?: { title: string; desc: string; at: number }[]; // 이 장면 따라 하기
  gap?: boolean; // 장면 사이 빈 곳 (타임라인·목록에는 안 보임)
}

export interface VideoDetail {
  videoId: string;
  youtubeVideoId?: string;
  title: string;
  publisher: string;
  publishedAt: string;
  durationSec: number;
  query: string;
  matchedChapterId: string;
  chapters: Chapter[];
  policy: Policy | null;
  docs: DocItem[];
  officialSteps: OfficialStep[];
  subtitles?: { start: number; end: number; text: string }[]; // 큰 자막용
  stepsStatus?: 'draft' | 'reviewed' | null; // 단계 카드 검수 상태
  freshness?: FreshnessWarning[]; // 이 영상의 오래된 정보 경고
  /** 정책 화면 추천 질문 */
  chips?: string[];
  /** 이 영상의 신청서 지도가 있음 (backend/data/form_maps) */
  formMap?: boolean;
}

export interface DocItem {
  id: string;
  name: string;
  note?: string;
}

export interface OfficialStep {
  step: number;
  title: string;
  note: string;
  videoAt?: number; // 영상 속 시작 시간 (없으면 '해당 장면 없음')
  verification: Verification;
}
