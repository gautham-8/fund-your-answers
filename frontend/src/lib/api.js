import { auth, logout } from './auth'
import router from '../router'

const BASE = import.meta.env.VITE_API_BASE || ''

/** Call the backend. Pass `body` for JSON or `form` (FormData) for uploads. */
export async function api(path, { method = 'GET', body, form } = {}) {
  const headers = {}
  if (auth.token) headers.Authorization = `Bearer ${auth.token}`
  if (body !== undefined) headers['Content-Type'] = 'application/json'

  const res = await fetch(BASE + path, {
    method,
    headers,
    body: form ?? (body !== undefined ? JSON.stringify(body) : undefined),
  })

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
  const res = await fetch(BASE + path, { headers: { Authorization: `Bearer ${auth.token}` } })
  if (!res.ok) throw new Error('Could not load file')
  return URL.createObjectURL(await res.blob())
}
