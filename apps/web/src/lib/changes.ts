import type { ChangeItem } from '../api'

export type ChangeWindow = 'visit' | '24h' | '7d'

export function changeKey(item: ChangeItem): string {
  return `${item.kind}:${item.edge_id ?? item.narrative_id ?? item.node_ids.join(',')}`
}
