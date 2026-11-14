<script setup>
import { computed } from 'vue'

const props = defineProps({ status: String, needsReview: Boolean, late: Boolean })

const MAP = {
  analyzing: ['Processing PDF', 'bg-amber-50 text-amber-700 ring-amber-200', 'bg-amber-500 animate-pulse'],
  analysis_failed: ['Analysis failed', 'bg-rose-50 text-rose-700 ring-rose-200', 'bg-rose-500'],
  ready: ['Viva ready', 'bg-sky-50 text-sky-700 ring-sky-200', 'bg-sky-500'],
  viva_in_progress: ['Viva in progress', 'bg-indigo-50 text-indigo-700 ring-indigo-200', 'bg-indigo-500 animate-pulse'],
  scoring: ['Scoring', 'bg-amber-50 text-amber-700 ring-amber-200', 'bg-amber-500 animate-pulse'],
  scoring_failed: ['Scoring failed', 'bg-rose-50 text-rose-700 ring-rose-200', 'bg-rose-500'],
  completed: ['Completed', 'bg-emerald-50 text-emerald-700 ring-emerald-200', 'bg-emerald-500'],
}
const info = computed(() => MAP[props.status] || ['No submission', 'bg-slate-50 text-slate-500 ring-slate-200', 'bg-slate-300'])
</script>

<template>
  <span class="inline-flex flex-wrap items-center gap-1">
    <span class="inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap ring-1 ring-inset" :class="info[1]">
      <span class="size-1.5 rounded-full" :class="info[2]"></span>{{ info[0] }}
    </span>
    <span v-if="late" class="rounded-full bg-orange-50 px-2 py-0.5 text-xs font-medium text-orange-700 ring-1 ring-orange-200 ring-inset">Late</span>
    <span v-if="needsReview" class="rounded-full bg-orange-50 px-2 py-0.5 text-xs font-medium whitespace-nowrap text-orange-700 ring-1 ring-orange-200 ring-inset">Needs review</span>
  </span>
</template>
