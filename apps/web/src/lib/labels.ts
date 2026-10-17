// 화면 문구. 백엔드 위키(wiki/build.py)와 같은 표현을 쓴다.

export const NODE_TYPE_LABEL: Record<string, string> = {
  organization: '조직',
  person: '인물',
  product: '제품·작품',
  technology: '기술',
  topic: '주제',
  event: '사건',
  place: '장소',
  narrative: '내러티브',
  // 예전 값 (마이그레이션 0008 이전 데이터)
  company: '조직',
  industry: '주제',
}

export const SERIES_LABEL: Record<string, string> = {
  entity: '조직·인물',
  concept: '제품·기술·주제',
  narrative: '내러티브',
}

export const RELATION_LABEL: Record<string, string> = {
  RELATED_TO: '관련',
  PART_OF: '일부',
  BELONGS_TO: '소속',
  SUPPLIES_TO: '공급',
  COMPETES_WITH: '경쟁',
  AFFECTS: '영향',
  CLAIMED_CAUSE_OF: '원인이라는 주장',
  CO_MENTIONED_WITH: '함께 언급',
}

export const EDGE_STATUS_LABEL: Record<string, string> = {
  candidate: '발견 후보',
  confirmed: '관측 확정',
  weakened: '약해짐',
}

export const NODE_STATUS_LABEL: Record<string, string> = {
  active: '활성',
  candidate: '후보',
  dormant: '휴면',
}

export const MEMBERSHIP_LABEL: Record<string, string> = {
  root: '관심 대상',
  admitted: '포함',
  pending_review: '검토 대기',
}

export const NARRATIVE_STATE_LABEL: Record<string, string> = {
  emerging: '새로 등장',
  spreading: '확산 중',
  contested: '논쟁 중',
  reversed: '논조 반전',
  fading: '잦아듦',
  split: '갈라짐',
}

export const CAUSE_LABEL: Record<string, string> = {
  observed_new: '새로 관측',
  backfill: '과거 자료',
  reprocess: '재분류',
  source_added: '소스 추가',
  user_action: '사용자',
}

export const CHANGE_KIND_LABEL: Record<string, string> = {
  new_narrative: '새 내러티브',
  narrative_shift: '내러티브 변화',
  new_node: '새 대상',
  new_relation: '새 연결',
  attention_up: '관심 증가',
  attention_down: '관심 감소',
}

export const EVENT_TYPE_LABEL: Record<string, string> = {
  NODE_CREATED: '노드 생성',
  NODE_ACTIVATED: '노드 활성',
  NODE_DORMANT: '휴면',
  NODE_REACTIVATED: '재활성',
  NODE_MERGED: '노드 병합',
  NODE_REJECTED: '노드 거절',
  EDGE_CREATED: '연결 생성',
  EDGE_CONFIRMED: '연결 확정',
  EDGE_WEAKENED: '연결 약화',
  EDGE_TYPE_CHANGED: '연결 유형 변경',
  EDGE_REJECTED: '연결 거절',
  NARRATIVE_CREATED: '내러티브 생성',
  NARRATIVE_STATE_CHANGED: '내러티브 상태 변화',
  WIKI_REVISED: '위키 갱신',
}

export function label(dict: Record<string, string>, key: string | null | undefined): string {
  if (!key) return '알 수 없음'
  return dict[key] ?? key
}

export const EVIDENCE_STATUS_LABEL: Record<string, string> = {
  community_opinion: '커뮤니티 의견 · 미검증',
  speculation: '추측 · 미검증',
  reported_fact: '보도 인용 주장 · 미확인',
  official_source: '공식 자료 인용 주장 · 미확인',
}

export const SOURCE_LABEL: Record<string, string> = {
  bluesky_jetstream: 'Bluesky',
  hackernews: 'Hacker News',
  dcinside_stockus: '미주갤',
  naver_world_nvda: '네이버 해외주식 토론',
}
