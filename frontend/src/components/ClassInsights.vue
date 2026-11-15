<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../lib/api'
import Icon from './Icon.vue'

const props = defineProps({ assignmentId: String })

const data = ref(null)
const error = ref('')
const busy = ref(false)

async function load() {
  try {
    data.value = await api(`/api/assignments/${props.assignmentId}/insights`)
  } catch (e) {
    error.value = e.message
  }
}

async function analyse() {
  busy.value = true
  error.value = ''
  try {
    data.value.concept_gaps = await api(`/api/assignments/${props.assignmentId}/insights/concept-gaps`, { method: 'POST' })
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = false
  }
}

const pct = (x) => (x == null ? '—' : `${Math.round(x * 100)}%`)
const num = (x) => (x == null ? '—' : x)
const signed = (x) => (x == null ? '—' : `${x > 0 ? '+' : ''}${x}`)

onMounted(load)
defineExpose({ load })
</script>

<template>
  <section v-if="data" class="space-y-4 pt-2">
    <h2 class="flex items-center gap-2 font-semibold"><Icon name="chart" class="text-indigo-500" />Class insights</h2>
    <p v-if="error" class="error-box">{{ error }}</p>

    <p v-if="!data.completed" class="rounded-2xl border border-dashed border-slate-300 bg-white px-5 py-8 text-center text-sm text-slate-500">Insights appear once students complete their vivas.</p>
    <template v-else>
      <!-- Headline numbers -->
      <div class="grid gap-3 sm:grid-cols-3">
        <div class="card py-3">
          <div class="text-xs text-slate-500">Completed vivas</div>
          <div class="text-2xl font-bold">{{ data.completed }}</div>
        </div>
        <div class="card py-3">
          <div class="text-xs text-slate-500">Average understanding score</div>
          <div class="text-2xl font-bold">{{ data.avg_overall != null ? data.avg_overall + '%' : '—' }}</div>
        </div>
        <div class="card py-3">
          <div class="text-xs text-slate-500">Flagged “needs review”</div>
          <div class="text-2xl font-bold">{{ data.needs_review }}</div>
        </div>
      </div>

      <!-- Rubric + AI vs instructor -->
      <div class="overflow-x-auto rounded-2xl border border-slate-200/80 bg-white shadow-xs">
        <table class="w-full text-left text-sm">
          <thead class="border-b border-slate-100 bg-slate-50/60 text-xs tracking-wide text-slate-500 uppercase">
            <tr>
              <th class="px-4 py-2 font-medium">Rubric dimension</th>
              <th class="px-4 py-2 font-medium">Avg AI score</th>
              <th class="px-4 py-2 font-medium">Avg final score</th>
              <th class="px-4 py-2 font-medium">Instructor overrides</th>
              <th class="px-4 py-2 font-medium" title="Average of (instructor score − AI score) where overridden">Avg adjustment</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in data.rubric" :key="r.dimension" class="border-b border-slate-100 last:border-0">
              <td class="px-4 py-2 font-medium">{{ r.dimension }}</td>
              <td class="px-4 py-2">{{ num(r.avg_ai) }}</td>
              <td class="px-4 py-2">{{ num(r.avg_final) }}</td>
              <td class="px-4 py-2">{{ r.overrides }}</td>
              <td class="px-4 py-2" :class="{ 'text-emerald-700': r.avg_adjustment > 0, 'text-rose-700': r.avg_adjustment < 0 }">
                {{ signed(r.avg_adjustment) }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p class="text-sm text-slate-600">
        <b>AI vs instructor:</b>
        instructors kept {{ pct(data.agreement.untouched_rate) }} of AI scores unchanged
        ({{ data.agreement.overridden }} of {{ data.agreement.scored_dimensions }} changed).
        <template v-if="data.agreement.overridden">
          Where they changed one, the AI was off by {{ data.agreement.mean_abs_difference }} points on average,
          and within 1 point {{ pct(data.agreement.within_one) }} of the time.
        </template>
      </p>

      <!-- Concept gaps -->
      <div class="card space-y-4">
        <div class="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 class="font-semibold">Concepts the class struggled to explain</h3>
            <p class="text-xs text-slate-500">
              Uses every completed viva. Students are anonymised before anything is sent to the AI.
            </p>
          </div>
          <button class="btn-primary" :disabled="busy || data.completed < 2" @click="analyse">
            {{ busy ? 'Analysing…' : data.concept_gaps ? 'Re-analyse' : 'Analyse class' }}
          </button>
        </div>
        <p v-if="data.completed < 2" class="text-sm text-slate-500">Needs at least 2 completed vivas.</p>

        <template v-if="data.concept_gaps">
          <p class="text-sm text-slate-700">{{ data.concept_gaps.overview }}</p>
          <p v-if="!data.concept_gaps.gaps.length" class="text-sm text-slate-500">No shared gaps found.</p>
          <div v-for="g in data.concept_gaps.gaps" :key="g.concept" class="rounded-xl border border-slate-200 p-4">
            <div class="flex items-start justify-between gap-3">
              <h4 class="font-medium">{{ g.concept }}</h4>
              <span class="shrink-0 rounded-full bg-amber-100 px-2 py-0.5 text-xs text-amber-800">
                {{ Math.round((g.student_count / data.concept_gaps.based_on) * 100) }}% · {{ g.student_count }} of {{ data.concept_gaps.based_on }} students
              </span>
            </div>
            <p class="mt-1 text-sm text-slate-600">{{ g.explanation }}</p>
            <blockquote v-if="g.example_quote" class="mt-2 border-l-4 border-slate-200 pl-3 text-sm text-slate-600 italic">“{{ g.example_quote }}”</blockquote>
            <p class="mt-2 text-sm"><b>Idea:</b> {{ g.teaching_suggestion }}</p>
          </div>
          <p class="text-xs text-slate-400">
            Based on {{ data.concept_gaps.based_on }} vivas · {{ new Date(data.concept_gaps.generated_at).toLocaleString() }}
          </p>
        </template>
      </div>
    </template>
  </section>
</template>
