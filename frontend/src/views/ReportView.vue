<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { api, blobUrl } from '../lib/api'
import { confirmDialog } from '../lib/confirm'
import { fmtDate, initials, relative } from '../lib/format'
import { setCourse } from '../lib/store'
import { toast } from '../lib/toast'
import Icon from '../components/Icon.vue'
import ScoreRing from '../components/ScoreRing.vue'
import StatusBadge from '../components/StatusBadge.vue'

const props = defineProps({ id: String })

const sub = ref(null)
const error = ref('')
const audio = reactive({}) // turn id -> object URL
const drafts = reactive({}) // dim index -> { score, note }
const editing = ref(null)
const saving = ref(null)
let timer = null

async function load() {
  try {
    sub.value = await api(`/api/submissions/${props.id}`)
    setCourse(sub.value.course)
  } catch (e) {
    error.value = e.message
    return
  }
  for (const t of sub.value.turns) {
    if (t.has_audio && !audio[t.id]) blobUrl(`/api/turns/${t.id}/audio`).then((u) => (audio[t.id] = u)).catch(() => {})
  }
  sub.value.score?.dimensions.forEach((d, i) => {
    drafts[i] = { score: d.override_score ?? null, note: d.override_note || '' }
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
      body: { override_score: d.score, override_note: d.note },
    })
    Object.assign(sub.value.score, res)
    sub.value.overall = res.overall
    sub.value.needs_review = res.needs_review
    editing.value = null
    toast(d.score == null ? 'Reverted to AI score' : 'Score updated')
  } catch (e) {
    toast(e.message, { type: 'error' })
  } finally {
    saving.value = null
  }
}

async function rescore() {
  const ok = await confirmDialog({
    title: 'Re-run AI scoring?',
    message: 'The AI will score the viva again from the transcript. Your overrides on this submission will be cleared.',
    confirmText: 'Re-run scoring',
    danger: true,
  })
  if (!ok) return
  await api(`/api/submissions/${props.id}/retry`, { method: 'POST' })
  await load()
}

async function openPdf(page) {
  const url = await blobUrl(`/api/submissions/${props.id}/pdf`)
  window.open(page ? `${url}#page=${page}` : url, '_blank')
}

const openRegrades = computed(() => (sub.value?.regrade_requests || []).filter((r) => r.status === 'open'))
const regradeFor = (i) => openRegrades.value.find((r) => r.dimension_index === i)
const turnsFor = (i) => sub.value.turns.filter((t) => t.question_index === i)
const QUALITY = {
  strong: 'bg-emerald-50 text-emerald-700',
  partial: 'bg-amber-50 text-amber-700',
  weak: 'bg-rose-50 text-rose-700',
  no_answer: 'bg-slate-100 text-slate-500',
}

onMounted(load)
onUnmounted(() => {
  clearTimeout(timer)
  setCourse(null)
  Object.values(audio).forEach(URL.revokeObjectURL)
})
</script>

<template>
  <p v-if="error" class="error-box mb-4">{{ error }}</p>
  <div v-if="!sub && !error" class="space-y-4">
    <div class="skeleton h-5 w-48"></div>
    <div class="skeleton h-28 w-full"></div>
    <div class="skeleton h-72 w-full"></div>
  </div>

  <div v-if="sub" class="animate-fade-up">
    <nav class="mb-4 flex items-center gap-1.5 text-sm text-slate-500">
      <RouterLink :to="`/courses/${sub.course.id}`" class="hover:text-slate-900">{{ sub.course.code || sub.course.name }}</RouterLink>
      <Icon name="chevron-right" :size="14" class="text-slate-300" />
      <RouterLink :to="`/assignments/${sub.assignment.id}`" class="truncate hover:text-slate-900">{{ sub.assignment.title }}</RouterLink>
    </nav>

    <!-- Header -->
    <header class="card flex flex-wrap items-center gap-5">
      <span class="grid size-14 shrink-0 place-items-center rounded-full bg-slate-900 text-lg font-semibold text-white">{{ initials(sub.student?.name) }}</span>
      <div class="min-w-0 flex-1">
        <h1 class="text-xl font-semibold tracking-tight">{{ sub.student?.name }}</h1>
        <p class="truncate text-sm text-slate-500">{{ sub.student?.email }}</p>
        <div class="mt-2 flex flex-wrap items-center gap-2">
          <StatusBadge :status="sub.status" :needs-review="sub.needs_review" :late="sub.late" />
          <span class="text-xs text-slate-400">Submitted {{ fmtDate(sub.created_at) }}</span>
        </div>
      </div>
      <button class="btn-secondary" @click="openPdf()"><Icon name="file" />{{ sub.filename }}<Icon name="external" :size="13" class="text-slate-400" /></button>
      <ScoreRing v-if="sub.score" :value="sub.overall" :size="88" label="Score" />
    </header>

    <div v-if="sub.error" class="error-box mt-4">Error: {{ sub.error }}</div>
    <div v-if="sub.analysis?.embedded_instructions_detected" class="mt-4 flex items-start gap-2.5 rounded-xl border border-orange-200 bg-orange-50 p-3.5 text-sm text-orange-900">
      <Icon name="alert" class="mt-0.5 text-orange-500" />
      The PDF contains text that appears to address an AI or grader. It was ignored during analysis and scoring.
    </div>
    <div v-if="openRegrades.length" class="mt-4 flex flex-wrap items-center gap-3 rounded-xl border border-orange-200 bg-orange-50 p-3.5 text-sm text-orange-900">
      <Icon name="regrade" class="text-orange-500" />
      <span class="flex-1">{{ openRegrades.length }} open regrade request{{ openRegrades.length === 1 ? '' : 's' }} on this submission.</span>
      <RouterLink :to="`/courses/${sub.course.id}/regrades`" class="font-medium underline-offset-2 hover:underline">Respond</RouterLink>
    </div>

    <!-- Scores -->
    <section v-if="sub.score" class="mt-8">
      <div class="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 class="text-lg font-semibold tracking-tight">Rubric scores</h2>
        <div class="flex items-center gap-2">
          <span class="text-xs" :class="sub.grades_published ? 'text-emerald-600' : 'text-slate-400'">
            {{ sub.grades_published ? 'Visible to student' : 'Hidden from student until published' }}
          </span>
          <button class="btn-ghost btn-sm" @click="rescore"><Icon name="regrade" :size="13" />Re-run scoring</button>
        </div>
      </div>
      <p class="mb-4 leading-relaxed text-slate-700">{{ sub.score.summary }}</p>

      <div class="space-y-3">
        <div
          v-for="(d, i) in sub.score.dimensions"
          :key="d.dimension"
          class="card"
          :class="{ 'border-orange-300 ring-4 ring-orange-50': d.needs_review && d.override_score == null }"
        >
          <div class="flex flex-wrap items-start justify-between gap-3">
            <div class="min-w-0">
              <div class="flex flex-wrap items-center gap-2">
                <h3 class="font-semibold">{{ d.dimension }}</h3>
                <span v-if="d.needs_review && d.override_score == null" class="rounded-full bg-orange-100 px-2 py-0.5 text-xs font-medium text-orange-800">Needs review</span>
                <span v-if="regradeFor(i)" class="inline-flex items-center gap-1 rounded-full bg-orange-50 px-2 py-0.5 text-xs font-medium text-orange-700 ring-1 ring-orange-200 ring-inset">
                  <Icon name="regrade" :size="11" />Regrade requested
                </span>
              </div>
              <div class="mt-1 flex items-center gap-2 text-xs text-slate-500">
                <span class="inline-flex items-center gap-1.5">
                  AI confidence
                  <span class="inline-block h-1 w-12 overflow-hidden rounded-full bg-slate-100">
                    <span class="block h-full rounded-full" :class="d.confidence >= 0.6 ? 'bg-emerald-500' : 'bg-orange-500'" :style="{ width: d.confidence * 100 + '%' }"></span>
                  </span>
                  {{ Math.round(d.confidence * 100) }}%
                </span>
                <span v-if="!d.quote_verified" class="text-orange-600">· quote not found verbatim in transcript</span>
              </div>
            </div>
            <div class="text-right">
              <div class="font-mono text-2xl font-semibold">
                <template v-if="d.override_score != null">
                  {{ d.override_score }}<span class="text-base text-slate-400">/5</span>
                  <span class="ml-1 text-sm font-normal text-slate-400 line-through">{{ d.score }}</span>
                </template>
                <template v-else>{{ d.score }}<span class="text-base text-slate-400">/5</span></template>
              </div>
              <div v-if="d.override_score != null" class="text-xs text-slate-500">set by {{ d.overridden_by }}</div>
            </div>
          </div>

          <blockquote v-if="d.evidence_quote" class="mt-3 border-l-2 border-indigo-200 pl-3 text-sm text-slate-700 italic">“{{ d.evidence_quote }}”</blockquote>
          <p class="mt-2 text-sm text-slate-600">{{ d.rationale }}</p>
          <div v-if="regradeFor(i)" class="mt-3 rounded-lg bg-orange-50/70 p-3 text-sm">
            <div class="mb-0.5 text-xs font-medium text-orange-700">Student’s regrade request · {{ relative(regradeFor(i).created_at) }}</div>
            <p class="whitespace-pre-line text-slate-700">{{ regradeFor(i).message }}</p>
          </div>
          <p v-if="d.override_note && editing !== i" class="mt-2 rounded-lg bg-slate-50 px-3 py-2 text-sm text-slate-600"><b>Note:</b> {{ d.override_note }}</p>

          <div class="mt-3">
            <button v-if="editing !== i" class="btn-ghost btn-sm -ml-2" @click="editing = i"><Icon name="pencil" :size="13" />Override score</button>
            <div v-else-if="drafts[i]" class="space-y-3 rounded-xl border border-slate-200 bg-slate-50/60 p-3.5">
              <div class="flex flex-wrap items-center gap-1.5">
                <button
                  type="button"
                  class="h-9 rounded-lg px-3 text-xs font-medium ring-1 transition ring-inset"
                  :class="drafts[i].score == null ? 'bg-slate-900 text-white ring-slate-900' : 'bg-white text-slate-600 ring-slate-200 hover:ring-slate-300'"
                  @click="drafts[i].score = null"
                >
                  AI ({{ d.score }})
                </button>
                <button
                  v-for="n in 5"
                  :key="n"
                  type="button"
                  class="size-9 rounded-lg text-sm font-semibold ring-1 transition ring-inset"
                  :class="drafts[i].score === n ? 'bg-indigo-600 text-white ring-indigo-600' : 'bg-white text-slate-700 ring-slate-200 hover:ring-indigo-300'"
                  @click="drafts[i].score = n"
                >
                  {{ n }}
                </button>
              </div>
              <input v-model="drafts[i].note" class="input" placeholder="Note (optional — shown to the student when grades are published)" />
              <div class="flex justify-end gap-2">
                <button class="btn-secondary btn-sm" @click="editing = null">Cancel</button>
                <button class="btn-primary btn-sm" :disabled="saving === i" @click="saveOverride(i)">Save</button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
    <div v-else-if="sub.status === 'scoring'" class="card mt-8 flex items-center gap-3 text-slate-600">
      <span class="size-4 animate-spin rounded-full border-2 border-indigo-200 border-t-indigo-600"></span>Scoring in progress…
    </div>

    <!-- Transcript -->
    <section v-if="sub.page_map" class="mt-10">
      <div class="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h2 class="text-lg font-semibold tracking-tight">Answer pages</h2>
        <p class="text-xs text-slate-500">
          {{ sub.pages_confirmed_at ? `Confirmed by the student ${fmtDate(sub.pages_confirmed_at)}` : 'AI match, not yet confirmed by the student' }}
        </p>
      </div>
      <div class="card divide-y divide-slate-100 p-0 text-sm">
        <div v-for="(q, i) in sub.parts" :key="i" class="flex flex-wrap items-baseline gap-2 px-4 py-3">
          <span class="font-medium">Q{{ i + 1 }}.</span>
          <span class="min-w-0 flex-1 text-slate-700">{{ q }}</span>
          <span class="flex flex-wrap gap-1">
            <button
              v-for="p in sub.page_map[i]"
              :key="p"
              class="rounded-md bg-indigo-50 px-2 py-0.5 text-xs font-medium text-indigo-700 hover:bg-indigo-100"
              @click="openPdf(p)"
            >
              p. {{ p }}
            </button>
            <span v-if="!sub.page_map[i]?.length" class="text-xs text-orange-600">No pages</span>
          </span>
        </div>
      </div>
    </section>

    <section v-if="sub.questions.length" class="mt-10">
      <div class="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h2 class="text-lg font-semibold tracking-tight">Viva transcript</h2>
        <p v-if="sub.consent_at" class="text-xs text-slate-500">Recording consent given {{ fmtDate(sub.consent_at) }}</p>
      </div>
      <div class="space-y-4">
        <div v-for="(q, i) in sub.questions" :key="i" class="card space-y-4">
          <div class="flex items-center gap-2 text-xs text-slate-500">
            <span class="rounded-md bg-slate-900 px-1.5 py-0.5 font-semibold text-white">Q{{ i + 1 }}</span>
            about “{{ q.target }}” · page {{ q.page }}
          </div>
          <template v-if="!turnsFor(i).length">
            <p class="font-medium">{{ q.question }}</p>
            <p class="text-sm text-slate-400">Not answered yet.</p>
          </template>
          <div v-for="t in turnsFor(i)" :key="t.id" class="space-y-2">
            <div class="flex gap-2.5">
              <span class="grid size-7 shrink-0 place-items-center rounded-full bg-indigo-100 text-indigo-600"><Icon name="sparkles" :size="13" /></span>
              <p class="rounded-2xl rounded-tl-sm bg-slate-100 px-3.5 py-2 text-sm font-medium text-slate-800">
                <span v-if="t.kind === 'followup'" class="text-indigo-600">Follow-up · </span>{{ t.question }}
              </p>
            </div>
            <div class="flex justify-end gap-2.5">
              <div class="max-w-[85%] space-y-1.5">
                <p class="rounded-2xl rounded-tr-sm bg-indigo-600 px-3.5 py-2 text-sm whitespace-pre-line text-white">{{ t.transcript || '(no speech detected)' }}</p>
                <div class="flex flex-wrap items-center justify-end gap-2 text-xs text-slate-500">
                  <span class="inline-flex items-center gap-1"><Icon :name="t.answer_mode === 'typed' ? 'keyboard' : 'mic'" :size="12" />{{ t.answer_mode === 'typed' ? 'Typed' : 'Voice' }}</span>
                  <span v-if="t.quality" class="rounded-full px-2 py-0.5 font-medium capitalize" :class="QUALITY[t.quality]">{{ t.quality.replace('_', ' ') }}</span>
                  <span v-if="t.notes" class="text-slate-400">{{ t.notes }}</span>
                </div>
                <audio v-if="audio[t.id]" :src="audio[t.id]" controls class="ml-auto h-8 w-full max-w-xs"></audio>
              </div>
              <span class="grid size-7 shrink-0 place-items-center rounded-full bg-slate-900 text-[10px] font-semibold text-white">{{ initials(sub.student?.name) }}</span>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- Analysis -->
    <section v-if="sub.analysis" class="mt-10">
      <h2 class="mb-1 text-lg font-semibold tracking-tight">PDF analysis</h2>
      <p class="mb-4 leading-relaxed text-slate-600">{{ sub.analysis.summary }}</p>
      <div class="overflow-hidden rounded-2xl border border-slate-200/80 bg-white shadow-xs">
        <table class="w-full text-sm">
          <thead class="border-b border-slate-100 bg-slate-50/60">
            <tr>
              <th class="th">Type</th>
              <th class="th">Method / decision</th>
              <th class="th text-right">Page</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-100">
            <tr v-for="(it, i) in sub.analysis.items" :key="i" class="align-top">
              <td class="td"><span class="rounded-md bg-slate-100 px-1.5 py-0.5 text-xs font-medium text-slate-600 capitalize">{{ it.kind }}</span></td>
              <td class="td">
                <div class="font-medium">{{ it.name }}</div>
                <div class="text-slate-600">{{ it.description }}</div>
                <div v-if="it.excerpt" class="mt-1 text-xs text-slate-500 italic">“{{ it.excerpt }}”</div>
              </td>
              <td class="td text-right font-mono text-slate-500">{{ it.page }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</template>
