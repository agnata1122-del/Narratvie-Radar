const fmt = new Intl.DateTimeFormat('ko-KR', {
  month: 'numeric',
  day: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
})

export function formatTime(iso: string): string {
  return fmt.format(new Date(iso))
}

export function addHours(iso: string, hours: number): string {
  return new Date(new Date(iso).getTime() + hours * 3_600_000).toISOString()
}

/** 분석 범위: 처음 기록과 지금 사이에서 최근 days일. 기록이 없으면 지금 기준 하루. */
export function defaultRange(start: string | null, now: string, days: number): { start: string; end: string } {
  const end = new Date(now).getTime()
  const earliest = start ? new Date(start).getTime() : end - 86_400_000
  const from = Math.max(earliest, end - days * 86_400_000)
  return { start: new Date(Math.min(from, end - 3_600_000)).toISOString(), end: new Date(end).toISOString() }
}

/** 기준 시각에서 얼마나 전인지 ("3시간 전"). 기준보다 뒤면 "방금". */
export function relativeTime(iso: string, reference: string): string {
  const diff = (new Date(reference).getTime() - new Date(iso).getTime()) / 60_000
  if (diff < 1) return '방금'
  if (diff < 60) return `${Math.round(diff)}분 전`
  if (diff < 60 * 24) return `${Math.round(diff / 60)}시간 전`
  return `${Math.round(diff / 60 / 24)}일 전`
}
