import { reactive } from 'vue'

export const toasts = reactive([])
let seq = 0

/** Show a short notification. type: success | error | info */
export function toast(message, { type = 'success', timeout = 2600 } = {}) {
  const id = ++seq
  toasts.push({ id, message, type })
  setTimeout(() => dismiss(id), timeout)
}

export function dismiss(id) {
  const i = toasts.findIndex((t) => t.id === id)
  if (i >= 0) toasts.splice(i, 1)
}
