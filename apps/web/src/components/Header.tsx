import type { Health, Overview, SourceStatus } from '../api'
import type { ThemeMode } from '../lib/theme'
import { MoonIcon, RadarMark, SunIcon, SystemIcon } from './icons'

const STATUS_LABEL: Record<SourceStatus['access_status'], string> = {
  not_authorized: '수집 꺼짐',
  test_mode: 'TEST MODE',
  live: 'LIVE',
  paused: '일시 중지',
  blocked: '차단 감지 · 중단됨',
  stopped: '오류 · 중단됨',
}

type Props = {
  overview: Overview | undefined
  health: Health | undefined
  healthPending: boolean
  healthError: boolean
  theme: ThemeMode
  onTheme: (mode: ThemeMode) => void
  /** 경로나 하위 가지를 누르면 그 관심사로 이동한다. null은 최상위 관심사 */
  onOpenProfile: (profileId: string | null) => void
}

const NEXT_THEME: Record<ThemeMode, ThemeMode> = { system: 'light', light: 'dark', dark: 'system' }
const THEME_LABEL: Record<ThemeMode, string> = { system: '시스템 테마', light: '밝은 테마', dark: '어두운 테마' }

function statusDot(status: SourceStatus['access_status']): string {
  if (status === 'live') return 'bg-[#0ca30c]'
  if (status === 'blocked' || status === 'stopped') return 'bg-nr-warn'
  return 'bg-nr-border-strong'
}

/** 소스 상태 요약. 상태색은 늘 글자와 함께 쓴다 (dataviz: 색만으로 상태를 말하지 않는다). */
function CollectionStatus({ sources }: { sources: SourceStatus[] }) {
  const live = sources.filter((s) => s.access_status === 'live').length
  const halted = sources.filter((s) => s.access_status === 'blocked' || s.access_status === 'stopped').length
  const summary = halted > 0 ? `수집 중단 ${halted}` : live > 0 ? `LIVE ${live}/${sources.length}` : '수집 꺼짐'
  const tone = halted > 0 ? 'bg-nr-warn-bg text-nr-warn-text ring-transparent' : 'bg-nr-surface text-nr-text-2 ring-nr-border'
  return (
    <details className="group relative">
      <summary
        className={`flex cursor-pointer list-none items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-medium ring-1 ring-inset select-none ${tone}`}
      >
        <span
          className={`inline-block size-1.5 rounded-full ${halted ? 'bg-nr-warn' : live ? 'bg-[#0ca30c] text-[#0ca30c]' : 'bg-nr-border-strong'}`}
          style={live && !halted ? { animation: 'nr-live 2s ease-out infinite' } : undefined}
        />
        {summary}
      </summary>
      <div className="nr-rise absolute right-0 z-30 mt-2 w-64 rounded-xl border border-nr-border bg-nr-surface p-1.5 shadow-nr">
        <p className="px-2 pt-1 pb-1.5 text-[11px] text-nr-muted">소스별 수집 상태</p>
        <ul>
          {sources.map((s) => (
            <li key={s.id} className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-xs text-nr-text-2" title={s.id}>
              <span className={`inline-block size-1.5 shrink-0 rounded-full ${statusDot(s.access_status)}`} />
              <span>
                {s.display_name} · {STATUS_LABEL[s.access_status]}
              </span>
            </li>
          ))}
        </ul>
      </div>
    </details>
  )
}

/** 루트 관심사부터 지금 가지까지: NVIDIA › HBM › SK hynix. 앞쪽은 눌러서 돌아갈 수 있다. */
function Lineage({ overview, onOpenProfile }: { overview: Overview; onOpenProfile: Props['onOpenProfile'] }) {
  const path = overview.lineage.length ? overview.lineage : []
  const kids = overview.children
  return (
    <nav aria-label="탐색 경로" className="flex min-w-0 flex-wrap items-center gap-1 text-xs">
      {path.map((x, i) => {
        const current = i === path.length - 1
        return (
          <span key={x.profile_id} className="flex items-center gap-1">
            {i > 0 && <span className="text-nr-muted" aria-hidden="true">›</span>}
            {current ? (
              <span aria-current="page" className="nr-fade rounded-md bg-nr-text px-2 py-0.5 text-[12px] font-semibold text-nr-surface">
                {x.root_label}
              </span>
            ) : (
              <button
                type="button"
                onClick={() => onOpenProfile(i === 0 && !x.parent_profile_id ? null : x.profile_id)}
                className="rounded-md px-1.5 py-0.5 font-medium text-nr-text-2 transition-colors hover:bg-nr-surface-2 hover:text-nr-text"
              >
                {x.root_label}
              </button>
            )}
          </span>
        )
      })}
      {kids.length > 0 && (
        <details className="group relative">
          <summary className="ml-1 cursor-pointer list-none rounded-md px-1.5 py-0.5 text-[11px] font-medium text-nr-muted ring-1 ring-nr-border select-none ring-inset hover:text-nr-text">
            가지 {kids.length} ▾
          </summary>
          <div className="nr-rise absolute left-0 z-30 mt-2 w-56 rounded-xl border border-nr-border bg-nr-surface p-1.5 shadow-nr">
            <p className="px-2 pt-1 pb-1.5 text-[11px] text-nr-muted">여기서 갈라진 가지</p>
            {kids.map((k) => (
              <button
                key={k.profile_id}
                type="button"
                onClick={() => onOpenProfile(k.profile_id)}
                className="block w-full rounded-lg px-2 py-1.5 text-left text-xs text-nr-text-2 hover:bg-nr-surface-2 hover:text-nr-text"
              >
                {k.root_label}
              </button>
            ))}
          </div>
        </details>
      )}
    </nav>
  )
}

export default function Header({ overview, health, healthPending, healthError, theme, onTheme, onOpenProfile }: Props) {
  const p = overview?.profile
  const live = health?.sources.some((s) => s.access_status === 'live') ?? false
  const ThemeIcon = theme === 'dark' ? MoonIcon : theme === 'light' ? SunIcon : SystemIcon
  return (
    <header className="relative z-20 flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-nr-border bg-nr-surface px-4 py-2.5">
      <div className="flex items-center gap-2 text-nr-text">
        <RadarMark live={live} />
        <h1 className="text-[15px] font-semibold tracking-tight">Narrative Radar</h1>
      </div>
      <span className="hidden h-4 w-px bg-nr-border-strong sm:block" aria-hidden="true" />
      <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-xs">
        {overview && overview.lineage.length > 0 ? (
          <Lineage overview={overview} onOpenProfile={onOpenProfile} />
        ) : (
          <span className="rounded-md bg-nr-text px-2 py-0.5 text-[12px] font-semibold text-nr-surface">{p?.root_label ?? p?.name ?? '—'}</span>
        )}
        {p && (
          <span className="rounded-md bg-nr-surface-2 px-1.5 py-0.5 text-[11px] font-medium text-nr-text-2 ring-1 ring-nr-border ring-inset" title="도메인 팩: 키 규칙·분류 지침·소스를 정한다">
            {p.domain.name}
          </span>
        )}
        {p && (
          <span className="text-nr-text-2">
            Depth {p.max_depth} · 자동 확장 {p.auto_expand ? 'ON' : 'OFF'}
          </span>
        )}
        {overview && (
          <span className="text-nr-muted tabular-nums">
            · 글 {overview.counts.documents.toLocaleString('ko-KR')} · 노드 {overview.counts.nodes} · 연결 {overview.counts.edges}
          </span>
        )}
      </div>
      <div className="ml-auto flex items-center gap-2">
        {healthPending && <span className="text-[11px] text-nr-muted">API 확인 중…</span>}
        {healthError && <span className="rounded-full bg-nr-warn-bg px-2.5 py-1 text-[11px] font-medium text-nr-warn-text">API 연결 안 됨</span>}
        {health && <CollectionStatus sources={health.sources} />}
        <button
          type="button"
          onClick={() => onTheme(NEXT_THEME[theme])}
          className="grid size-8 place-items-center rounded-full text-nr-text-2 ring-1 ring-nr-border transition-colors ring-inset hover:bg-nr-surface-2 hover:text-nr-text"
          aria-label={`${THEME_LABEL[theme]} (눌러서 바꾸기)`}
          title={THEME_LABEL[theme]}
        >
          <span key={theme} className="nr-fade">
            <ThemeIcon />
          </span>
        </button>
      </div>
    </header>
  )
}
