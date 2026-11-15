import { auth, logout } from './auth'
import router from '../router'

const BASE = import.meta.env.VITE_API_BASE || ''

const UNREACHABLE =
  "Can't reach the server right now. If the app was idle or just updated, it can take up to a minute to start. Please try again."
const RETRY_DELAYS = [1500, 4000] // ms; covers a server restart or a sleeping host waking up
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

/**
 * fetch, retried when the server can't be reached at all (network error) or the host says it's temporarily
 * unavailable (502/503/504, e.g. mid-deploy). Real API errors are returned as they are.
 */
async function fetchWithRetry(url, init) {
  for (let attempt = 0; ; attempt++) {
    try {
      const res = await fetch(url, init)
      if (![502, 503, 504].includes(res.status) || attempt >= RETRY_DELAYS.length) return res
    } catch {
      if (attempt >= RETRY_DELAYS.length) throw new Error(UNREACHABLE)
    }
    await sleep(RETRY_DELAYS[attempt])
  }
}

/** Call the backend. Pass `body` for JSON or `form` (FormData) for uploads. */
export async function api(path, { method = 'GET', body, form } = {}) {
  const headers = {}
  if (auth.token) headers.Authorization = `Bearer ${auth.token}`
  if (body !== undefined) headers['Content-Type'] = 'application/json'

  const res = await fetchWithRetry(BASE + path, {
    method,
    headers,
    body: form ?? (body !== undefined ? JSON.stringify(body) : undefined),
  })
  if ([502, 503, 504].includes(res.status)) throw new Error(UNREACHABLE)

  if (res.status === 401 && auth.token) {
    logout()
    router.push('/login')
  }
  if (!res.ok) {
    let msg = `Request failed (${res.status})`
    try {
      const data = await res.json()
      if (typeof data.detail === 'string') msg = data.detail
      else if (Array.isArray(data.detail)) msg = data.detail.map((d) => d.msg).join(', ')
    } catch {}
    throw new Error(msg)
  }
  return res.status === 204 ? null : res.json()
}

/** Fetch a protected file (audio/PDF) and return an object URL usable in <audio>/<a>. */
export async function blobUrl(path) {
  const res = await fetchWithRetry(BASE + path, { headers: { Authorization: `Bearer ${auth.token}` } })
  if (!res.ok) throw new Error('Could not load file')
  return URL.createObjectURL(await res.blob())
}
