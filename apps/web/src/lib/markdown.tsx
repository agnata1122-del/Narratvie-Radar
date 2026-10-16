import type { ReactNode } from 'react'
import { safeHref } from './url'

// 위키 섹션용 작은 마크다운 렌더러. HTML을 해석하지 않고 React 요소만 만든다.
// 지원: 문단(빈 줄), "- " 목록, **굵게**, [[노드]], [글](http/https 링크).
// 위키 본문에는 커뮤니티 글 발췌가 들어가므로 신뢰하지 않는 텍스트로 다룬다.

export type MarkdownOptions = {
  onNodeLink?: (label: string) => void
  /** 이 라벨에 해당하는 노드가 지금 화면에 있는지. 없으면 링크 대신 글자로 둔다. */
  isKnownNode?: (label: string) => boolean
}

const INLINE = /\*\*(.+?)\*\*|\[\[(.+?)\]\]|\[([^\]]+)\]\(([^)\s]+)\)/g

function renderInline(text: string, opts: MarkdownOptions = {}, keyPrefix = 'i'): ReactNode[] {
  const out: ReactNode[] = []
  let last = 0
  let n = 0
  for (const m of text.matchAll(INLINE)) {
    const at = m.index ?? 0
    if (at > last) out.push(text.slice(last, at))
    const key = `${keyPrefix}-${n++}`
    if (m[1] !== undefined) {
      out.push(<strong key={key}>{m[1]}</strong>)
    } else if (m[2] !== undefined) {
      const name = m[2]
      const known = opts.onNodeLink && (opts.isKnownNode?.(name) ?? true)
      out.push(
        known ? (
          <button
            key={key}
            type="button"
            className="text-nr-accent underline-offset-2 hover:underline"
            onClick={() => opts.onNodeLink?.(name)}
          >
            {name}
          </button>
        ) : (
          <span key={key} className="text-nr-text">
            {name}
          </span>
        ),
      )
    } else {
      const href = safeHref(m[4])
      out.push(
        href ? (
          <a key={key} href={href} target="_blank" rel="noopener noreferrer nofollow" className="text-nr-accent hover:underline">
            {m[3]}
          </a>
        ) : (
          m[3]
        ),
      )
    }
    last = at + m[0].length
  }
  if (last < text.length) out.push(text.slice(last))
  return out
}

export function Markdown({ source, ...opts }: { source: string } & MarkdownOptions) {
  const blocks = source.split(/\n{2,}/)
  return (
    <div className="space-y-2">
      {blocks.map((block, b) => {
        const lines = block.split('\n')
        const nodes: ReactNode[] = []
        let items: string[] = []
        const flush = () => {
          if (items.length === 0) return
          const listKey = `l-${b}-${nodes.length}`
          nodes.push(
            <ul key={listKey} className="list-disc space-y-1 pl-4">
              {items.map((item, i) => (
                <li key={i}>{renderInline(item, opts, `${listKey}-${i}`)}</li>
              ))}
            </ul>,
          )
          items = []
        }
        lines.forEach((line, i) => {
          if (line.startsWith('- ')) {
            items.push(line.slice(2))
            return
          }
          flush()
          if (line.trim()) nodes.push(<p key={`p-${b}-${i}`}>{renderInline(line, opts, `p-${b}-${i}`)}</p>)
        })
        flush()
        return <div key={b}>{nodes}</div>
      })}
    </div>
  )
}
