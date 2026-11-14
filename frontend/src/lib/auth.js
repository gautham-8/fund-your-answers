import { reactive } from 'vue'

function load() {
  try {
    return JSON.parse(localStorage.getItem('viva_auth')) || { token: null, user: null }
  } catch {
    return { token: null, user: null }
  }
}

export const auth = reactive(load())

export function setAuth({ token, user }) {
  auth.token = token
  auth.user = user
  try { localStorage.setItem('viva_auth', JSON.stringify({ token, user })) } catch {}
}

export function logout() {
  auth.token = null
  auth.user = null
  try { localStorage.removeItem('viva_auth') } catch {}
}
