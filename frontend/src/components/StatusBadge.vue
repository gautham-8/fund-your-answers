<script setup>
import { computed } from 'vue'

const props = defineProps({ status: String, needsReview: Boolean })

const MAP = {
  analyzing: ['Analyzing PDF', 'bg-amber-100 text-amber-800'],
  analysis_failed: ['Analysis failed', 'bg-rose-100 text-rose-800'],
  ready: ['Viva not started', 'bg-sky-100 text-sky-800'],
  viva_in_progress: ['Viva in progress', 'bg-indigo-100 text-indigo-800'],
  scoring: ['Scoring', 'bg-amber-100 text-amber-800'],
  scoring_failed: ['Scoring failed', 'bg-rose-100 text-rose-800'],
  completed: ['Completed', 'bg-emerald-100 text-emerald-800'],
}
const info = computed(() => MAP[props.status] || ['Not submitted', 'bg-slate-100 text-slate-600'])
</script>

<template>
  <span class="inline-flex items-center gap-1">
    <span class="rounded-full px-2 py-0.5 text-xs font-medium" :class="info[1]">{{ info[0] }}</span>
    <span v-if="needsReview" class="rounded-full bg-orange-100 px-2 py-0.5 text-xs font-medium text-orange-800">Needs review</span>
  </span>
</template>
