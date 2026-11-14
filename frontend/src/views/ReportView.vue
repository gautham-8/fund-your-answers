<script setup>
import { onMounted, onUnmounted, reactive, ref } from 'vue'
import { api, blobUrl } from '../lib/api'
import StatusBadge from '../components/StatusBadge.vue'

const props = defineProps({ id: String })

const sub = ref(null)
const error = ref('')
const audio = reactive({}) // turn id -> object URL
const drafts = reactive({}) // dim index -> { score, note }
const saving = ref(null)
let timer = null

async function load() {
  try {
    sub.value = await api(`/api/submissions/${props.id}`)
  } catch (e) {
    error.value = e.message
    return
  }
  for (const t of sub.value.turns) {
    if (t.has_audio && !audio[t.id]) blobUrl(`/api/turns/${t.id}/audio`).then((u) => (audio[t.id] = u)).catch(() => {})
  }
  sub.value.score?.dimensions.forEach((d, i) => {
    drafts[i] = { score: d.override_score ?? '', note: d.override_note || '' }
  })
  clearTimeout(timer)
  if (['analyzing', 'scoring'].includes(sub.value.status)) timer = setTimeout(load, 3000)
}

async function saveOverride(i) {
  saving.value = i
  try {
    const d = drafts[i]
    const res = await api(`/api/submissions/${props.id}/scores/${i}`, {
      method: 'PATCH',
      body: { override_score: d.score === '' ? null : Number(d.score), override_note: d.note },
    })
    Object.assign(sub.value.score, res)
    sub.value.overall = res.overall
    sub.value.needs_review = res.needs_review
  } catch (e) {
    error.value = e.message
  } finally {
    saving.value = null
  }
}

async function rescore() {
  if (!confirm('Re-run AI scoring? Your overrides will be cleared.')) return
  await api(`/api/submissions/${props.id}/retry`, { method: 'POST' })
  await load()
}

async function openPdf() {
  window.open(await blobUrl(`/api/submissions/${props.id}/pdf`), '_blank')
}

const turnsFor = (i) => sub.value.turns.filter((t) => t.question_index === i)
const qualityColor = { strong: 'text-emerald-700', partial: 'text-amber-700', weak: 'text-rose-700', no_answer: 'text-slate-500' }

onMounted(load)
onUnmounted(() => {
  clearTimeout(timer)
  Object.values(audio).forEach(URL.revokeObjectURL)
})
</script>

<template>
  <p v-if="error" class="error-box mb-4">{{ error }}</p>
  <template v-if="sub">
    <RouterLink :to="`/assignments/${sub.assignment.id}`" class="text-sm text-indigo-600 hover:underline">← {{ sub.assignment.title }}</RouterLink>

    <div class="mt-2 mb-6 flex flex-wrap items-start justify-between gap-4">
      <div>
        <h1 class="text-2xl font-bold">{{ sub.student?.name }}</h1>
        <p class="text-sm text-slate-500">{{ sub.student?.email }} · {{ sub.filename }}</p>
        <div class="mt-2"><StatusBadge :status="sub.status" :needs-review="sub.needs_review" /></div>
      </div>
      <div class="flex items-center gap-3">
        <button class="btn-secondary" @click="openPdf">View PDF</button>
        <div v-if="sub.score" class="card py-3 text-center">
          <div class="text-xs text-slate-500">Understanding score</div>
          <div class="text-3xl font-bold text-indigo-700">{{ sub.overall }}%</div>
        </div>
      </div>
    </div>

    <div v-if="sub.error" class="error-box mb-4">Error: {{ sub.error }}</div>
    <div v-if="sub.analysis?.embedded_instructions_detected" class="mb-4 rounded-lg bg-orange-50 p-3 text-sm text-orange-900">
      The PDF contains text that appears to address an AI or grader. It was ignored during analysis and scoring.
    </div>

    <!-- Scores -->
    <section v-if="sub.score" class="mb-8">
      <div class="mb-3 flex items-center justify-between">
        <h2 class="text-lg font-semibold">Rubric scores</h2>
        <button class="text-sm text-slate-600 hover:underline" @click="rescore">Re-run scoring</button>
      </div>
      <p class="mb-4 text-slate-700">{{ sub.score.summary }}</p>
      <div class="space-y-3">
        <div v-for="(d, i) in sub.score.dimensions" :key="d.dimension" class="card" :class="{ 'border-orange-300': d.needs_review && d.override_score == null }">
          <div class="flex flex-wrap items-start justify-between gap-3">
            <div>
              <div class="flex items-center gap-2">
                <h3 class="font-semibold">{{ d.dimension }}</h3>
                <span v-if="d.needs_review && d.override_score == null" class="rounded-full bg-orange-100 px-2 py-0.5 text-xs text-orange-800">Needs review</span>
              </div>
              <div class="text-xs text-slate-500">
                AI confidence {{ Math.round(d.confidence * 100) }}%
                <span v-if="!d.quote_verified"> · quote not found verbatim in transcript</span>
              </div>
            </div>
            <div class="text-right">
              <div class="text-2xl font-bold">
                <template v-if="d.override_score != null">
                  {{ d.override_score }}<span class="text-base text-slate-400">/5</span>
                  <span class="ml-1 text-sm font-normal text-slate-400 line-through">{{ d.score }}</span>
                </template>
                <template v-else>{{ d.score }}<span class="text-base text-slate-400">/5</span></template>
              </div>
              <div v-if="d.override_score != null" class="text-xs text-slate-500">overridden by {{ d.overridden_by }}</div>
            </div>
          </div>
          <blockquote v-if="d.evidence_quote" class="mt-3 border-l-4 border-indigo-200 pl-3 text-sm text-slate-700 italic">“{{ d.evidence_quote }}”</blockquote>
          <p class="mt-2 text-sm text-slate-600">{{ d.rationale }}</p>

          <details class="mt-3 text-sm">
            <summary class="cursor-pointer text-indigo-600">Override score</summary>
            <div v-if="drafts[i]" class="mt-2 flex flex-wrap items-center gap-2">
              <select v-model="drafts[i].score" class="input w-32">
                <option value="">Use AI score</option>
                <option v-for="n in 5" :key="n" :value="n">{{ n }}</option>
              </select>
              <input v-model="drafts[i].note" class="input flex-1" placeholder="Note (optional)" />
              <button class="btn-primary" :disabled="saving === i" @click="saveOverride(i)">Save</button>
            </div>
            <p v-if="d.override_note" class="mt-2 text-slate-600">Note: {{ d.override_note }}</p>
          </details>
        </div>
      </div>
    </section>
    <div v-else-if="sub.status === 'scoring'" class="card mb-8 text-slate-600">Scoring in progress…</div>

    <!-- Transcript -->
    <section v-if="sub.questions.length" class="mb-8">
      <h2 class="mb-3 text-lg font-semibold">Viva transcript</h2>
      <p v-if="sub.consent_at" class="mb-3 text-xs text-slate-500">Recording consent given {{ new Date(sub.consent_at).toLocaleString() }}</p>
      <div class="space-y-4">
        <div v-for="(q, i) in sub.questions" :key="i" class="card space-y-3">
          <div class="text-xs text-slate-500">Q{{ i + 1 }} · about “{{ q.target }}” (page {{ q.page }})</div>
          <p v-if="!turnsFor(i).length" class="font-medium">{{ q.question }}</p>
          <p v-if="!turnsFor(i).length" class="text-sm text-slate-400">Not answered yet.</p>
          <div v-for="t in turnsFor(i)" :key="t.id" :class="{ 'ml-4 border-l-2 border-slate-200 pl-4': t.kind === 'followup' }">
            <p class="font-medium"><span v-if="t.kind === 'followup'" class="text-indigo-600">Follow-up: </span>{{ t.question }}</p>
            <p class="mt-1 whitespace-pre-line text-slate-700">{{ t.transcript || '(no speech detected)' }}</p>
            <div class="mt-1 flex flex-wrap items-center gap-3 text-xs text-slate-500">
              <span>{{ t.answer_mode === 'typed' ? 'Typed answer' : 'Voice answer' }}</span>
              <span v-if="t.quality" :class="qualityColor[t.quality]">{{ t.quality.replace('_', ' ') }}</span>
              <span v-if="t.notes">{{ t.notes }}</span>
            </div>
            <audio v-if="audio[t.id]" :src="audio[t.id]" controls class="mt-2 h-8 w-full max-w-md"></audio>
          </div>
        </div>
      </div>
    </section>

    <!-- Analysis -->
    <section v-if="sub.analysis">
      <h2 class="mb-3 text-lg font-semibold">PDF analysis</h2>
      <p class="mb-3 text-slate-700">{{ sub.analysis.summary }}</p>
      <div class="card overflow-x-auto p-0">
        <table class="w-full text-left text-sm">
          <thead class="border-b border-slate-200 bg-slate-50 text-slate-600">
            <tr>
              <th class="px-4 py-2 font-medium">Type</th>
              <th class="px-4 py-2 font-medium">Method / decision</th>
              <th class="px-4 py-2 font-medium">Page</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(it, i) in sub.analysis.items" :key="i" class="border-b border-slate-100 align-top last:border-0">
              <td class="px-4 py-2 capitalize text-slate-500">{{ it.kind }}</td>
              <td class="px-4 py-2">
                <div class="font-medium">{{ it.name }}</div>
                <div class="text-slate-600">{{ it.description }}</div>
                <div v-if="it.excerpt" class="mt-1 text-xs text-slate-500 italic">“{{ it.excerpt }}”</div>
              </td>
              <td class="px-4 py-2">{{ it.page }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </template>
</template>
