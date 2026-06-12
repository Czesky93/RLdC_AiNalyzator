export const ADMIN_TOKEN_STORAGE_KEY = 'rldc_admin_token'

export function getAdminToken(): string {
  if (typeof window === 'undefined') return ''
  try {
    return (localStorage.getItem(ADMIN_TOKEN_STORAGE_KEY) || '').trim()
  } catch {
    return ''
  }
}

export function withAdminToken(headers: Record<string, string> = {}): Record<string, string> {
  const token = getAdminToken()
  if (!token) return headers
  return { ...headers, 'X-Admin-Token': token }
}

export function getApiBase(): string {
  const envBase = process.env.NEXT_PUBLIC_API_BASE?.trim()
  if (envBase) return envBase.replace(/\/+$/, '')

  if (typeof window !== 'undefined') {
    const host = window.location.hostname
    const protocol = window.location.protocol || 'http:'
    return `${protocol}//${host}:8000`
  }

  return 'http://localhost:8000'
}
