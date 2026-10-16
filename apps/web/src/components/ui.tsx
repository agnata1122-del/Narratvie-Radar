import type { ReactNode } from 'react'

type Tone = 'plain' | 'warn' | 'ink' | 'quiet'

export function Chip({ children, title, tone = 'plain' }: { children: ReactNode; title?: string; tone?: Tone }) {
  const toneClass = {
    plain: 'border-nr-border text-nr-text-2 bg-nr-surface',
    warn: 'border-transparent bg-nr-warn-bg text-nr-warn-text',
    ink: 'border-transparent bg-nr-text text-nr-surface',
    quiet: 'border-transparent bg-nr-surface-2 text-nr-muted',
  }[tone]
  return (
    <span title={title} className={`inline-flex items-center gap-1 rounded-md border px-1.5 py-px text-[11px] leading-4 font-medium whitespace-nowrap ${toneClass}`}>
      {children}
    </span>
  )
}

export function Panel({
  title,
  subtitle,
  actions,
  children,
  className = '',
}: {
  title: string
  subtitle?: ReactNode
  actions?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <section className={`flex flex-col bg-nr-surface lg:min-h-0 ${className}`}>
      <div className="flex min-h-11 flex-wrap items-center gap-x-2 gap-y-1 border-b border-nr-border px-4 py-2">
        <h2 className="text-[13px] font-semibold text-nr-text">{title}</h2>
        {subtitle && <span className="text-[11px] text-nr-muted tabular-nums">{subtitle}</span>}
        <div className="ml-auto flex items-center gap-3">{actions}</div>
      </div>
      {/* 넓은 화면에서는 패널 안에서 스크롤, 좁은 화면에서는 페이지가 스크롤된다 */}
      <div className="flex-1 lg:min-h-0 lg:overflow-auto">{children}</div>
    </section>
  )
}

export function Muted({ children }: { children: ReactNode }) {
  return <p className="text-xs leading-5 text-nr-muted">{children}</p>
}

/** 같은 너비 칸 사이를 미끄러지는 표시가 있는 선택 버튼 묶음 */
export function Segmented<T extends string | number>({
  label,
  value,
  options,
  onChange,
}: {
  label: string
  value: T
  options: { value: T; text: string }[]
  onChange: (v: T) => void
}) {
  const i = Math.max(0, options.findIndex((o) => o.value === value))
  return (
    <div
      role="radiogroup"
      aria-label={label}
      className="relative grid rounded-lg bg-nr-surface-2 p-0.5 ring-1 ring-nr-border ring-inset"
      style={{ gridTemplateColumns: `repeat(${options.length}, minmax(0, 1fr))` }}
    >
      <span
        aria-hidden="true"
        className="absolute top-0.5 bottom-0.5 left-0.5 rounded-md bg-nr-surface shadow-[0_1px_2px_rgb(0_0_0/0.12)] ring-1 ring-nr-border transition-transform duration-[var(--nr-dur-3)] ease-nr-out"
        style={{ width: `calc((100% - 4px) / ${options.length})`, transform: `translateX(${i * 100}%)` }}
      />
      {options.map((o) => (
        <button
          key={String(o.value)}
          type="button"
          role="radio"
          aria-checked={o.value === value}
          onClick={() => onChange(o.value)}
          className={`relative z-10 px-2.5 py-1 text-[11px] font-medium whitespace-nowrap transition-colors duration-[var(--nr-dur-2)] ${
            o.value === value ? 'text-nr-text' : 'text-nr-muted hover:text-nr-text-2'
          }`}
        >
          {o.text}
        </button>
      ))}
    </div>
  )
}

export function Switch({ checked, onChange, children }: { checked: boolean; onChange: (v: boolean) => void; children: string }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className="group flex items-center gap-1.5 text-[11px] font-medium whitespace-nowrap text-nr-text-2"
    >
      <span
        className={`relative inline-flex h-4 w-7 shrink-0 items-center rounded-full transition-colors duration-[var(--nr-dur-2)] ${
          checked ? 'bg-nr-text' : 'bg-nr-border-strong'
        }`}
      >
        <span
          className={`absolute size-3 rounded-full bg-nr-surface shadow transition-transform duration-[var(--nr-dur-3)] ease-nr-spring ${
            checked ? 'translate-x-3.5' : 'translate-x-0.5'
          }`}
        />
      </span>
      {children}
    </button>
  )
}

/**
 * 확산 대비 독립 근거 막대. 같은 잉크 계열의 옅은 칸(확산 전체) 위에 진한 칸(독립 근거)을 채운다.
 * 숫자는 막대 옆 글자로 함께 적는다 (색만으로 읽게 하지 않는다).
 */
export function EvidenceMeter({ spread, independent }: { spread: number; independent: number }) {
  const total = Math.max(spread, independent, 1)
  const share = Math.min(1, independent / total)
  return (
    <div className="flex items-center gap-2 text-[11px] text-nr-muted tabular-nums">
      <div className="relative h-1 w-16 overflow-hidden rounded-full bg-nr-border-strong" aria-hidden="true">
        <div
          className="absolute inset-y-0 left-0 rounded-full bg-nr-text-2 transition-[width] duration-[var(--nr-dur-4)] ease-nr-out"
          style={{ width: `${share * 100}%` }}
        />
      </div>
      <span>
        독립 <span className="font-semibold text-nr-text">{independent}</span> / 확산 {spread}
      </span>
    </div>
  )
}

export function Skeleton({ className = '' }: { className?: string }) {
  return <div className={`nr-skeleton ${className}`} aria-hidden="true" />
}
