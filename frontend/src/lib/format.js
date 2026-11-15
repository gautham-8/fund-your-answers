import { ref } from 'vue'

/** A clock that ticks every 30s so "3 hours left" labels stay fresh. */
export const now = ref(Date.now())
setInterval(() => (now.value = Date.now()), 30_000)

const MIN = 60_000
const HOUR = 60 * MIN
const DAY = 24 * HOUR
const WEEK = 7 * DAY

export const tzAbbr = (() => {
  try {
    return new Intl.DateTimeFormat('en-US', { timeZoneName: 'short' }).formatToParts(new Date()).find((p) => p.type === 'timeZoneName')?.value || ''
  } catch {
    return ''
  }
})()
export const tzName = Intl.DateTimeFormat().resolvedOptions().timeZone

/** "Nov 25 at 11:55 PM" (adds the year when it isn't this year). */
export function fmtDate(d) {
  if (!d) return ''
  const date = new Date(d)
  const sameYear = date.getFullYear() === new Date().getFullYear()
  const day = date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', ...(sameYear ? {} : { year: 'numeric' }) })
  const time = date.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })
  return `${day} at ${time}`
}

/** "Nov 25" */
export function fmtDay(d) {
  if (!d) return ''
  return new Date(d).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

/** Two largest units: "1 week, 4 days", "3 hours, 5 min", "12 min". */
export function humanize(ms) {
  ms = Math.abs(ms)
  if (ms < MIN) return 'less than a minute'
  const parts = []
  const units = [
    [WEEK, 'week'],
    [DAY, 'day'],
    [HOUR, 'hour'],
    [MIN, 'min'],
  ]
  for (const [size, name] of units) {
    const n = Math.floor(ms / size)
    if (n) {
      parts.push(`${n} ${name}${n === 1 || name === 'min' ? '' : 's'}`)
      ms -= n * size
    }
    if (parts.length === 2 || (parts.length === 1 && n === 0)) break
  }
  return parts.join(', ')
}

/** "2 hours ago" / "in 3 days" */
export function relative(d, at = now.value) {
  if (!d) return ''
  const diff = new Date(d).getTime() - at
  const rtf = new Intl.RelativeTimeFormat('en', { numeric: 'auto' })
  const abs = Math.abs(diff)
  if (abs < MIN) return 'just now'
  if (abs < HOUR) return rtf.format(Math.round(diff / MIN), 'minute')
  if (abs < DAY) return rtf.format(Math.round(diff / HOUR), 'hour')
  if (abs < WEEK * 2) return rtf.format(Math.round(diff / DAY), 'day')
  return rtf.format(Math.round(diff / WEEK), 'week')
}

/**
 * Where an assignment is in its schedule.
 * scheduled → open → soon (<48h) → late (past due, inside the late window) → closed. "none" = no due date.
 */
export function dueState(a, at = now.value) {
  const release = a.release_date ? new Date(a.release_date).getTime() : null
  const due = a.due_date ? new Date(a.due_date).getTime() : null
  const late = a.late_due_date ? new Date(a.late_due_date).getTime() : null
  if (release && at < release) return 'scheduled'
  if (!due) return 'none'
  if (at <= due) return due - at < 2 * DAY ? 'soon' : 'open'
  if (late && at <= late) return 'late'
  return 'closed'
}

/** For <input type="datetime-local">: ISO → "YYYY-MM-DDTHH:mm" in local time, and back. */
export function toLocalInput(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}
export const fromLocalInput = (v) => (v ? new Date(v).toISOString() : null)

export function initials(name = '') {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  return ((parts[0]?.[0] || '') + (parts.length > 1 ? parts[parts.length - 1][0] : '')).toUpperCase() || '?'
}

export function greeting() {
  const h = new Date().getHours()
  return h < 5 ? 'Working late' : h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening'
}

const SEASONS = { Winter: 0, Spring: 1, Summer: 2, Fall: 3, Autumn: 3 }
/** Sort key so terms list newest first: "Fall 2026" > "Spring 2026". */
export function termRank(term = '') {
  const [season, year] = term.split(/\s+/)
  return (Number(year) || 0) * 10 + (SEASONS[season] ?? 5)
}

export function termOptions() {
  const d = new Date()
  const y = d.getFullYear()
  const cur = d.getMonth() <= 4 ? 1 : d.getMonth() <= 6 ? 2 : 3
  const names = ['Winter', 'Spring', 'Summer', 'Fall']
  const out = []
  for (let i = -1; i <= 3; i++) {
    let idx = cur + i
    let year = y
    while (idx > 3) { idx -= 3; year++ }
    while (idx < 1) { idx += 3; year-- }
    out.push(`${names[idx]} ${year}`)
  }
  return out
}

export const currentTerm = () => termOptions()[1]

// Full class strings so Tailwind can see them.
const PALETTE = [
  { grad: 'from-indigo-500 to-violet-500', soft: 'bg-indigo-50 text-indigo-700 ring-indigo-200', dot: 'bg-indigo-500' },
  { grad: 'from-sky-500 to-cyan-500', soft: 'bg-sky-50 text-sky-700 ring-sky-200', dot: 'bg-sky-500' },
  { grad: 'from-emerald-500 to-teal-500', soft: 'bg-emerald-50 text-emerald-700 ring-emerald-200', dot: 'bg-emerald-500' },
  { grad: 'from-amber-500 to-orange-500', soft: 'bg-amber-50 text-amber-700 ring-amber-200', dot: 'bg-amber-500' },
  { grad: 'from-rose-500 to-pink-500', soft: 'bg-rose-50 text-rose-700 ring-rose-200', dot: 'bg-rose-500' },
  { grad: 'from-fuchsia-500 to-purple-500', soft: 'bg-fuchsia-50 text-fuchsia-700 ring-fuchsia-200', dot: 'bg-fuchsia-500' },
  { grad: 'from-blue-600 to-indigo-500', soft: 'bg-blue-50 text-blue-700 ring-blue-200', dot: 'bg-blue-600' },
  { grad: 'from-teal-500 to-lime-500', soft: 'bg-teal-50 text-teal-700 ring-teal-200', dot: 'bg-teal-500' },
]
export function courseColor(id = '') {
  let h = 0
  for (const ch of id) h = (h * 31 + ch.charCodeAt(0)) >>> 0
  return PALETTE[h % PALETTE.length]
}

/** Short label for a course avatar: "CS 682" → "682", "Machine Learning" → "ML". */
export function courseMonogram(c) {
  const num = (c.code || '').match(/\d{2,4}/)?.[0]
  if (num) return num
  return initials(c.code || c.name).slice(0, 2)
}

export function scoreTone(pct) {
  if (pct == null) return 'bg-slate-100 text-slate-600'
  if (pct >= 80) return 'bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200'
  if (pct >= 60) return 'bg-amber-50 text-amber-700 ring-1 ring-amber-200'
  return 'bg-rose-50 text-rose-700 ring-1 ring-rose-200'
}

export const plural = (n, word, many = word + 's') => `${n} ${n === 1 ? word : many}`

/** Points without trailing noise: 10, 7.5, 33.3 */
export const fmtPts = (x) => (x == null || x === '' ? '—' : Number.isInteger(+x) ? String(+x) : (+x).toFixed(1).replace(/\.0$/, ''))
