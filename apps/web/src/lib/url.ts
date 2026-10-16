/** http(s) 링크만 허용한다. javascript: 같은 스킴은 버린다. */
export function safeHref(url: string): string | null {
  try {
    const u = new URL(url)
    return u.protocol === 'https:' || u.protocol === 'http:' ? u.href : null
  } catch {
    return null
  }
}
