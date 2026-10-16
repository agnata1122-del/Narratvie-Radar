import type { Frames } from '../api'

/** 프레임 시각 중 iso 이하인 마지막 프레임. 모두 이후면 0. */
export function frameIndexAt(frames: Frames['frames'], iso: string): number {
  const t = new Date(iso).getTime()
  let found = 0
  frames.forEach((f, i) => {
    if (new Date(f.t).getTime() <= t) found = i
  })
  return found
}

/** 0..1 사이 위치. 범위 밖은 잘라낸다. */
export function positionIn(start: string, end: string, iso: string): number {
  const a = new Date(start).getTime()
  const b = new Date(end).getTime()
  if (b <= a) return 0
  return Math.min(1, Math.max(0, (new Date(iso).getTime() - a) / (b - a)))
}

/** 라벨 → 노드 ID (위키의 [[링크]]를 노드로 옮길 때). 같은 라벨이 여럿이면 처음 것. */
export function nodeIdsByLabel(frames: Frames | undefined): Map<string, string> {
  const map = new Map<string, string>()
  if (!frames) return map
  for (const [id, meta] of Object.entries(frames.nodes)) {
    if (!map.has(meta.label)) map.set(meta.label, id)
  }
  return map
}
