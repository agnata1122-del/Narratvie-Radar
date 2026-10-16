import type { ReactNode } from 'react'

export function Chip({ children, title, tone = 'plain' }: { children: ReactNode; title?: string; tone?: 'plain' | 'warn' | 'accent' }) {
  const toneClass =
    tone === 'warn'
      ? 'border-transparent bg-nr-warn-bg text-nr-warn-text'
      : tone === 'accent'
        ? 'border-nr-accent/40 text-nr-accent'
        : 'border-nr-border text-nr-text'
  return (
    <span title={title} className={`inline-flex items-center rounded border bg-nr-surface px-1.5 py-0.5 text-[11px] leading-4 whitespace-nowrap ${toneClass}`}>
      {children}
    </span>
  )
}

export function Panel({ title, actions, children, className = '' }: { title: string; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`flex flex-col bg-nr-surface md:min-h-0 ${className}`}>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 border-b border-nr-border px-3 py-2">
        <h2 className="text-xs font-semibold tracking-wide text-nr-muted">{title}</h2>
        <div className="ml-auto flex items-center gap-2">{actions}</div>
      </div>
      {/* 넓은 화면에서는 패널 안에서 스크롤, 좁은 화면에서는 페이지가 스크롤된다 */}
      <div className="flex-1 md:min-h-0 md:overflow-auto">{children}</div>
    </section>
  )
}

export function Muted({ children }: { children: ReactNode }) {
  return <p className="text-xs leading-5 text-nr-muted">{children}</p>
}
