<script setup>
import { computed } from 'vue'
import { dueState, fmtDate, humanize, now } from '../lib/format'

const props = defineProps({ a: { type: Object, required: true }, compact: Boolean })

const state = computed(() => dueState(props.a, now.value))
const due = computed(() => (props.a.due_date ? new Date(props.a.due_date).getTime() : null))
const lateDue = computed(() => (props.a.late_due_date ? new Date(props.a.late_due_date).getTime() : null))

/** Share of the release→due window that has passed. */
const elapsed = computed(() => {
  if (!due.value) return 0
  const start = props.a.release_date ? new Date(props.a.release_date).getTime() : due.value - 14 * 864e5
  return Math.max(0, Math.min(1, (now.value - start) / Math.max(1, due.value - start)))
})

const label = computed(() => {
  switch (state.value) {
    case 'scheduled': return `Opens in ${humanize(new Date(props.a.release_date).getTime() - now.value)}`
    case 'open':
    case 'soon': return `${humanize(due.value - now.value)} left`
    case 'late': return `Late window · ${humanize(lateDue.value - now.value)} left`
    case 'closed': return 'Closed'
    default: return 'No due date'
  }
})
const tone = computed(
  () => ({ soon: 'text-amber-600', late: 'text-orange-600', closed: 'text-slate-400', scheduled: 'text-violet-600' })[state.value] || 'text-slate-600',
)
const bar = computed(() => ({ soon: 'bg-amber-500', late: 'bg-orange-500' })[state.value] || 'bg-indigo-500')
const showBar = computed(() => ['open', 'soon', 'late'].includes(state.value))
</script>

<template>
  <div class="min-w-[11rem]">
    <div class="flex items-baseline justify-between gap-3">
      <span class="text-sm font-medium text-slate-800">{{ a.due_date ? fmtDate(a.due_date) : '—' }}</span>
    </div>
    <div v-if="a.late_due_date && !compact" class="text-xs text-slate-500">Late due {{ fmtDate(a.late_due_date) }}</div>
    <div v-if="showBar" class="mt-1.5 h-1 w-full overflow-hidden rounded-full bg-slate-100">
      <div class="h-full rounded-full transition-all" :class="bar" :style="{ width: (state === 'late' ? 100 : elapsed * 100) + '%' }"></div>
    </div>
    <div class="mt-1 text-xs font-medium" :class="tone">{{ label }}</div>
  </div>
</template>
