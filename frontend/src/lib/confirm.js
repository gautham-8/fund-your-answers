import { reactive } from 'vue'

export const confirmState = reactive({ open: false, title: '', message: '', confirmText: 'Confirm', danger: false, resolve: null })

/** Promise-based replacement for window.confirm(), rendered by <ConfirmHost>. */
export function confirmDialog(opts) {
  return new Promise((resolve) => {
    Object.assign(confirmState, { title: 'Are you sure?', message: '', confirmText: 'Confirm', danger: false, ...opts, open: true, resolve })
  })
}

export function settleConfirm(value) {
  confirmState.open = false
  confirmState.resolve?.(value)
  confirmState.resolve = null
}
