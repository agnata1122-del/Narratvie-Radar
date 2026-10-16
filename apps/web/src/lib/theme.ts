import { useCallback, useState, useSyncExternalStore } from 'react'

export type ThemeMode = 'system' | 'light' | 'dark'

const KEY = 'nr-theme'
const DARK_QUERY = '(prefers-color-scheme: dark)'

export function readStoredTheme(): ThemeMode {
  try {
    const v = localStorage.getItem(KEY)
    return v === 'light' || v === 'dark' ? v : 'system'
  } catch {
    return 'system'
  }
}

/** data-theme을 붙이면 index.css의 토큰이 바뀐다. 시스템이면 속성을 지운다. */
export function applyTheme(mode: ThemeMode): void {
  const root = document.documentElement
  if (mode === 'system') root.removeAttribute('data-theme')
  else root.setAttribute('data-theme', mode)
  try {
    if (mode === 'system') localStorage.removeItem(KEY)
    else localStorage.setItem(KEY, mode)
  } catch {
    // 저장이 막혀 있어도 이번 화면에서는 적용된다
  }
}

function subscribeDark(onChange: () => void): () => void {
  if (typeof matchMedia !== 'function') return () => {}
  const mq = matchMedia(DARK_QUERY)
  mq.addEventListener('change', onChange)
  return () => mq.removeEventListener('change', onChange)
}

const systemDark = () => typeof matchMedia === 'function' && matchMedia(DARK_QUERY).matches

/** 지금 화면에 적용된 테마 (그래프 캔버스가 색을 다시 읽어야 하는지 판단할 때 쓴다) */
export function useTheme() {
  const [mode, setModeState] = useState<ThemeMode>(readStoredTheme)
  const dark = useSyncExternalStore(subscribeDark, systemDark, () => false)
  const setMode = useCallback((next: ThemeMode) => {
    applyTheme(next)
    setModeState(next)
  }, [])
  const resolved: 'light' | 'dark' = mode === 'system' ? (dark ? 'dark' : 'light') : mode
  return { mode, setMode, resolved }
}
