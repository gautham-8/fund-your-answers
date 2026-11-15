<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from '../lib/api'
import { relative } from '../lib/format'
import { toast } from '../lib/toast'
import Icon from '../components/Icon.vue'

const props = defineProps({ course: { type: Object, required: true } })

const data = ref(null)
const error = ref('')
const busy = ref(false)
const showAll = ref(false)

const TOP = 5
const stale = computed(() => data.value?.assignments.filter((a) => a.stale) ?? [])
const withVivas = computed(() => data.value?.assignments.filter((a) => a.completed) ?? [])
const gaps = computed(() => (showAll.value ? data.value.gaps : data.value.gaps.slice(0, TOP)))
const pct = (x) => `${Math.round(x * 100)}%`
// Strong colour for gaps that hit most of the class.
const tone = (share) =>
  share >= 0.5 ? { bar: 'bg-rose-500', text: 'text-rose-700' } : share >= 0.25 ? { bar: 'bg-amber-500', text: 'text-amber-700' } : { bar: 'bg-slate-400', text: 'text-slate-600' }

async function load() {
  try {
    data.value = await api(`/api/courses/${props.course.id}/concept-gaps`)
  } catch (e) {
    error.value = e.message
  }
}

async function refresh() {
  busy.value = true
  error.value = ''
  try {
    data.value = await api(`/api/courses/${props.course.id}/concept-gaps`, { method: 'POST' })
    if (data.value.failed.length) toast(`Couldn't analyse ${data.value.failed.map((f) => f.title).join(', ')} right now. Try again in a minute.`, { type: 'error' })
    else toast('Class insights updated')
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="space-y-6">
    <p v-if="error" class="error-box">{{ error }}</p>
    <div v-if="!data && !error" class="space-y-3">
      <div v-for="i in 3" :key="i" class="skeleton h-28 rounded-2xl"></div>
    </div>

    <template v-if="data">
      <!-- Header -->
      <div class="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 class="flex items-center gap-2 text-lg font-semibold"><Icon name="chart" class="text-indigo-500" />What to revisit in class</h2>
          <p class="mt-1 max-w-xl text-sm text-slate-500">
            Concepts students struggled to explain in their vivas, across every assignment, ranked by the share of the class affected.
            Students are anonymised before anything is sent to the AI.
          </p>
        </div>
        <button v-if="stale.length" class="btn-primary" :disabled="busy" @click="refresh">
          <span v-if="busy" class="size-4 animate-spin rounded-full border-2 border-white/40 border-t-white"></span>
          <Icon v-else name="sparkles" />{{ busy ? 'Analysing…' : `Analyse ${stale.length} assignment${stale.length === 1 ? '' : 's'}` }}
        </button>
      </div>

      <!-- Nothing yet -->
      <div v-if="!withVivas.length" class="rounded-2xl border border-dashed border-slate-300 bg-white px-6 py-14 text-center">
        <div class="mx-auto grid size-11 place-items-center rounded-xl bg-slate-100 text-slate-500"><Icon name="chart" :size="20" /></div>
        <p class="mt-3 font-medium">No completed vivas yet</p>
        <p class="mt-1 text-sm text-slate-500">Insights appear once at least {{ data.min_vivas }} students finish a viva for an assignment.</p>
      </div>

      <template v-else>
        <div v-if="!data.gaps.length" class="card text-sm text-slate-600">
          <template v-if="stale.length">New vivas are ready to analyse. Click <b>Analyse</b> to find what the class struggled with.</template>
          <template v-else-if="data.assignments.some((a) => a.analysed_on)">No shared gaps found — the class explained their work well.</template>
          <template v-else>Each assignment needs at least {{ data.min_vivas }} completed vivas before it can be analysed.</template>
        </div>

        <!-- Ranked gaps -->
        <ol v-else class="space-y-3">
          <li v-for="(g, i) in gaps" :key="`${g.assignment.id}-${g.concept}`" class="card space-y-3 p-5">
            <div class="flex items-start gap-4">
              <div class="w-16 shrink-0 text-right">
                <div class="text-2xl font-bold tabular-nums" :class="tone(g.share).text">{{ pct(g.share) }}</div>
                <div class="text-[11px] text-slate-500">{{ g.student_count }} of {{ g.based_on }}</div>
              </div>
              <div class="min-w-0 flex-1">
                <p class="font-medium text-slate-900">
                  <span class="text-slate-400">{{ i + 1 }}.</span>
                  {{ pct(g.share) }} of the class struggled with <b>{{ g.concept }}</b> in
                  <RouterLink :to="`/assignments/${g.assignment.id}`" class="text-indigo-700 hover:underline">{{ g.assignment.title }}</RouterLink>
                </p>
                <div class="mt-2 h-1.5 overflow-hidden rounded-full bg-slate-100">
                  <div class="h-full rounded-full" :class="tone(g.share).bar" :style="{ width: pct(g.share) }"></div>
                </div>
                <p class="mt-2 text-sm text-slate-600">{{ g.explanation }}</p>
                <blockquote v-if="g.example_quote" class="mt-2 border-l-4 border-slate-200 pl-3 text-sm text-slate-600 italic">“{{ g.example_quote }}”</blockquote>
                <p class="mt-2 rounded-lg bg-indigo-50/60 px-3 py-2 text-sm text-slate-700"><b class="text-indigo-700">Revisit:</b> {{ g.teaching_suggestion }}</p>
              </div>
            </div>
          </li>
        </ol>
        <button v-if="data.gaps.length > TOP" class="btn-ghost btn-sm" @click="showAll = !showAll">
          <Icon :name="showAll ? 'chevron-up' : 'chevron-down'" :size="14" />{{ showAll ? 'Show fewer' : `Show all ${data.gaps.length}` }}
        </button>

        <!-- Coverage per assignment -->
        <div class="overflow-x-auto rounded-2xl border border-slate-200/80 bg-white shadow-xs">
          <table class="w-full text-left text-sm">
            <thead class="border-b border-slate-100 bg-slate-50/60 text-xs tracking-wide text-slate-500 uppercase">
              <tr>
                <th class="px-4 py-2 font-medium">Assignment</th>
                <th class="px-4 py-2 font-medium">Completed vivas</th>
                <th class="px-4 py-2 font-medium">Analysis</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="a in data.assignments" :key="a.id" class="border-b border-slate-100 last:border-0">
                <td class="px-4 py-2 font-medium"><RouterLink :to="`/assignments/${a.id}`" class="hover:text-indigo-700">{{ a.title }}</RouterLink></td>
                <td class="px-4 py-2 tabular-nums">{{ a.completed }}</td>
                <td class="px-4 py-2 text-slate-600">
                  <span v-if="a.stale && a.analysed_on" class="text-amber-700">Out of date · {{ a.analysed_on }} analysed</span>
                  <span v-else-if="a.stale" class="text-amber-700">Ready to analyse</span>
                  <span v-else-if="a.analysed_on">Up to date · {{ relative(a.generated_at) }}</span>
                  <span v-else class="text-slate-400">Needs {{ data.min_vivas }}+ vivas</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>
    </template>
  </div>
</template>
