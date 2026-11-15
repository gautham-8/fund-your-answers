<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { api, blobUrl } from '../lib/api'
import { confirmDialog } from '../lib/confirm'
import { fmtPts, initials, relative } from '../lib/format'
import { setCourse } from '../lib/store'
import { toast } from '../lib/toast'
import Icon from '../components/Icon.vue'
import StatusBadge from '../components/StatusBadge.vue'

const props = defineProps({ id: String })

const sub = ref(null)
const error = ref('')
const audio = reactive({}) // turn id -> object URL
const drafts = reactive({}) // dim index -> { score, note }
const editing = ref(null)
const saving = ref(null)
const allowing = ref(false)
const openDims = reactive(new Set()) // rubric rows showing their evidence
const openTurns = reactive(new Set()) // viva questions showing the full exchange
let timer = null
const toggle = (set, k) => (set.has(k) ? set.delete(k) : set.add(k))

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
    if (d.needs_review && d.override_score == null) openDims.add(i) // what needs a decision is open from the start
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

async function allowThrough() {
  const ok = await confirmDialog({
    title: 'Let this submission through?',
    message: "The AI thinks this PDF doesn't answer the assignment. If you let it through, viva questions are written from it and the student can start the viva.",
    confirmText: 'Let it through',
  })
  if (!ok) return
  allowing.value = true
  try {
    await api(`/api/submissions/${props.id}/allow`, { method: 'POST' })
    await load()
  } catch (e) {
    toast(e.message, { type: 'error' })
  } finally {
    allowing.value = false
  }
}

const vivaWeight = computed(() => sub.value?.assignment.viva_weight ?? 0.3)
const pct = (x) => `${Math.round(x * 100)}%`

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
  strong: ['Strong', 'bg-emerald-50 text-emerald-700 ring-emerald-200'],
  partial: ['Partial', 'bg-amber-50 text-amber-700 ring-amber-200'],
  weak: ['Weak', 'bg-rose-50 text-rose-700 ring-rose-200'],
  no_answer: ['No answer', 'bg-slate-100 text-slate-500 ring-slate-200'],
}
const finalOf = (d) => d.override_score ?? d.score
/** Plain-language integrity signals for one answer, e.g. ["Left the viva page 2× (35 s)", "Pasted 340 characters"]. */
function signalsOf(t) {
  const g = t.integrity
  if (!g) return []
  const out = []
  if (g.left_page_count) out.push(`Left the viva page ${g.left_page_count}× (${g.left_page_seconds} s)`)
  if (g.pasted_chars) out.push(`Pasted ${g.pasted_chars} characters`)
  return out
}
const flaggedTurns = computed(() => (sub.value?.turns || []).filter((t) => signalsOf(t).length).length)
const reviewCount = computed(() => (sub.value?.score?.dimensions || []).filter((d) => d.needs_review && d.override_score == null).length)
/** Short list of things the instructor has to act on; empty means nothing needs attention. */
const todo = computed(() => {
  const s = sub.value
  if (!s) return []
  const out = []
  if (s.status === 'completed' && s.grader_points == null) out.push(s.questions_graded ? `Finish grading the written solution (${s.questions_graded}/${s.parts.length} questions done)` : 'Grade the written solution')
  if (reviewCount.value) out.push(`Check ${reviewCount.value} viva score${reviewCount.value === 1 ? '' : 's'} the AI wasn't sure about`)
  if (flaggedTurns.value) out.push(`Look at ${flaggedTurns.value} answer${flaggedTurns.value === 1 ? '' : 's'} given while the student left the page or pasted text`)
  if (openRegrades.value.length) out.push(`Answer ${openRegrades.value.length} regrade request${openRegrades.value.length === 1 ? '' : 's'}`)
  return out
})

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
    <header class="flex flex-wrap items-center gap-4">
      <span class="grid size-12 shrink-0 place-items-center rounded-full bg-slate-900 font-semibold text-white">{{ initials(sub.student?.name) }}</span>
      <div class="min-w-0 flex-1">
        <h1 class="text-xl font-semibold tracking-tight">{{ sub.student?.name }}</h1>
        <div class="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-500">
          <StatusBadge :status="sub.status" :late="sub.late" />
          <span>Submitted {{ relative(sub.created_at) }}</span>
          <span v-if="sub.grades_published" class="text-emerald-600">· Grades published</span>
        </div>
      </div>
      <button class="btn-secondary" @click="openPdf()"><Icon name="file" />PDF<Icon name="external" :size="13" class="text-slate-400" /></button>
      <RouterLink :to="`/submissions/${id}/grade`" class="btn-primary"><Icon name="pencil" />{{ sub.grader_points != null ? 'Review grading' : 'Grade' }}</RouterLink>
    </header>

    <!-- Blocking problems -->
    <div v-if="sub.status === 'off_topic'" class="mt-5 flex flex-wrap items-start gap-3 rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-900">
      <Icon name="alert" class="mt-0.5 text-rose-500" />
      <div class="min-w-0 flex-1">
        <p class="font-medium">This PDF doesn't seem to answer the assignment, so no viva was opened.</p>
        <p v-if="sub.analysis?.relevance_note" class="mt-1">{{ sub.analysis.relevance_note }}</p>
      </div>
      <button class="btn-secondary btn-sm" :disabled="allowing" @click="allowThrough">Let it through anyway</button>
    </div>
    <div v-if="sub.error" class="error-box mt-5">Error: {{ sub.error }}</div>

    <!-- At a glance -->
    <section class="card mt-5 space-y-4">
      <div class="grid grid-cols-3 divide-x divide-slate-100 text-center">
        <div class="px-2">
          <div class="text-xs text-slate-500">Written solution</div>
          <div class="mt-1 text-2xl font-semibold tracking-tight">
            <template v-if="sub.grader_points != null">{{ fmtPts(sub.grader_points) }}<span class="text-sm font-normal text-slate-400"> / {{ fmtPts(sub.assignment.max_points) }}</span></template>
            <span v-else class="text-slate-300">—</span>
          </div>
          <div class="text-[11px] text-slate-400">{{ pct(1 - vivaWeight) }} of grade</div>
        </div>
        <div class="px-2">
          <div class="text-xs text-slate-500">Viva</div>
          <div class="mt-1 text-2xl font-semibold tracking-tight">
            <template v-if="sub.score">{{ Math.round(sub.overall) }}%</template>
            <span v-else class="text-slate-300">—</span>
          </div>
          <div class="text-[11px] text-slate-400">{{ pct(vivaWeight) }} of grade</div>
        </div>
        <div class="px-2">
          <div class="text-xs text-slate-500">Final grade</div>
          <div class="mt-1 text-2xl font-semibold tracking-tight" :class="sub.final != null && 'text-indigo-700'">
            <template v-if="sub.final != null">{{ sub.final }}%</template>
            <span v-else class="text-slate-300">—</span>
          </div>
          <div class="text-[11px] text-slate-400">{{ sub.final != null ? 'combined' : 'after grading' }}</div>
        </div>
      </div>

      <p v-if="sub.score?.summary" class="border-t border-slate-100 pt-4 text-sm leading-relaxed text-slate-600">{{ sub.score.summary }}</p>
      <div v-else-if="sub.status === 'scoring'" class="flex items-center gap-2 border-t border-slate-100 pt-4 text-sm text-slate-500">
        <span class="size-4 animate-spin rounded-full border-2 border-indigo-200 border-t-indigo-600"></span>Scoring the viva…
      </div>

      <ul v-if="todo.length" class="space-y-1.5 border-t border-slate-100 pt-4">
        <li v-for="t in todo" :key="t" class="flex items-center gap-2 text-sm text-orange-800">
          <span class="size-1.5 shrink-0 rounded-full bg-orange-500"></span>{{ t }}
          <RouterLink v-if="t.startsWith('Answer')" :to="`/courses/${sub.course.id}/regrades`" class="text-xs font-medium text-orange-700 underline-offset-2 hover:underline">Open</RouterLink>
        </li>
      </ul>
      <p v-else-if="sub.status === 'completed'" class="flex items-center gap-2 border-t border-slate-100 pt-4 text-sm text-emerald-700">
        <Icon name="check-circle" :size="15" />Nothing left to do here.
      </p>
      <p v-if="sub.analysis?.embedded_instructions_detected" class="text-xs text-orange-700">
        <Icon name="alert" :size="12" class="mr-1 inline" />The PDF contains text aimed at an AI or grader. It was ignored.
      </p>
    </section>

    <!-- Viva scores: one line each, details on demand -->
    <section v-if="sub.score" class="mt-8">
      <div class="mb-2 flex items-baseline justify-between gap-2">
        <h2 class="font-semibold">Viva scores</h2>
        <button class="btn-ghost btn-sm text-slate-500" @click="rescore"><Icon name="regrade" :size="13" />Re-run scoring</button>
      </div>
      <div class="card divide-y divide-slate-100 p-0">
        <div v-for="(d, i) in sub.score.dimensions" :key="d.dimension">
          <button type="button" class="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-slate-50/70" :aria-expanded="openDims.has(i)" @click="toggle(openDims, i)">
            <Icon name="chevron-right" :size="14" class="shrink-0 text-slate-400 transition" :class="openDims.has(i) && 'rotate-90'" />
            <span class="min-w-0 flex-1 truncate text-sm font-medium">{{ d.dimension }}</span>
            <span v-if="d.needs_review && d.override_score == null" class="rounded-full bg-orange-100 px-2 py-0.5 text-[11px] font-medium text-orange-800">Check</span>
            <span v-if="regradeFor(i)" class="rounded-full bg-orange-50 px-2 py-0.5 text-[11px] font-medium text-orange-700 ring-1 ring-orange-200 ring-inset">Regrade</span>
            <span v-if="d.override_score != null" class="text-[11px] text-slate-400">edited</span>
            <span class="hidden gap-0.5 sm:flex" aria-hidden="true">
              <span v-for="n in 5" :key="n" class="h-1.5 w-4 rounded-full" :class="n <= finalOf(d) ? 'bg-indigo-500' : 'bg-slate-200'"></span>
            </span>
            <span class="w-9 text-right font-mono text-sm font-semibold">{{ finalOf(d) }}<span class="font-normal text-slate-400">/5</span></span>
          </button>

          <div v-if="openDims.has(i)" class="space-y-3 px-4 pb-4 pl-11 text-sm">
            <blockquote v-if="d.evidence_quote" class="border-l-2 border-indigo-200 pl-3 text-slate-700 italic">“{{ d.evidence_quote }}”</blockquote>
            <p class="text-slate-600">{{ d.rationale }}</p>
            <p v-if="d.needs_review && d.override_score == null" class="text-xs text-orange-700">
              Why flagged:
              <template v-if="!d.quote_verified">the quote isn't word-for-word in the transcript</template>
              <template v-if="!d.quote_verified && d.confidence < 0.6"> and </template>
              <template v-if="d.confidence < 0.6">the AI was only {{ Math.round(d.confidence * 100) }}% confident</template>.
            </p>
            <div v-if="regradeFor(i)" class="rounded-lg bg-orange-50/70 p-3">
              <div class="mb-0.5 text-xs font-medium text-orange-700">Student's regrade request · {{ relative(regradeFor(i).created_at) }}</div>
              <p class="whitespace-pre-line text-slate-700">{{ regradeFor(i).message }}</p>
            </div>
            <p v-if="d.override_score != null" class="text-xs text-slate-500">
              AI gave {{ d.score }}/5; changed by {{ d.overridden_by }}<template v-if="d.override_note">: “{{ d.override_note }}”</template>
            </p>

            <button v-if="editing !== i" class="btn-ghost btn-sm -ml-2" @click="editing = i"><Icon name="pencil" :size="13" />Change score</button>
            <div v-else-if="drafts[i]" class="space-y-3 rounded-xl border border-slate-200 bg-slate-50/60 p-3.5">
              <div class="flex flex-wrap items-center gap-1.5">
                <button
                  type="button"
                  class="h-9 rounded-lg px-3 text-xs font-medium ring-1 transition ring-inset"
                  :class="drafts[i].score == null ? 'bg-slate-900 text-white ring-slate-900' : 'bg-white text-slate-600 ring-slate-200 hover:ring-slate-300'"
                  @click="drafts[i].score = null"
                >AI ({{ d.score }})</button>
                <button
                  v-for="n in [0, 1, 2, 3, 4, 5]"
                  :key="n"
                  type="button"
                  class="size-9 rounded-lg text-sm font-semibold ring-1 transition ring-inset"
                  :class="drafts[i].score === n ? 'bg-indigo-600 text-white ring-indigo-600' : 'bg-white text-slate-700 ring-slate-200 hover:ring-indigo-300'"
                  @click="drafts[i].score = n"
                >{{ n }}</button>
              </div>
              <input v-model="drafts[i].note" class="input" placeholder="Note for the student (optional)" />
              <div class="flex justify-end gap-2">
                <button class="btn-secondary btn-sm" @click="editing = null">Cancel</button>
                <button class="btn-primary btn-sm" :disabled="saving === i" @click="saveOverride(i)">Save</button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- Viva conversation: one line per question, full exchange on demand -->
    <section v-if="sub.questions.length" class="mt-8">
      <h2 class="mb-2 font-semibold">Viva conversation</h2>
      <div class="card divide-y divide-slate-100 p-0">
        <div v-for="(q, i) in sub.questions" :key="i">
          <button type="button" class="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-slate-50/70" :aria-expanded="openTurns.has(i)" @click="toggle(openTurns, i)">
            <Icon name="chevron-right" :size="14" class="shrink-0 text-slate-400 transition" :class="openTurns.has(i) && 'rotate-90'" />
            <span class="w-7 shrink-0 text-sm font-semibold text-slate-500">Q{{ i + 1 }}</span>
            <span class="min-w-0 flex-1 truncate text-sm">{{ q.target || q.question }}</span>
            <span v-if="!turnsFor(i).length" class="text-xs text-slate-400">Not answered</span>
            <span class="flex items-center gap-1">
              <template v-for="(t, k) in turnsFor(i)" :key="t.id">
                <Icon v-if="k > 0" name="arrow-right" :size="11" class="text-slate-300" />
                <span v-if="t.quality" class="rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ring-inset" :class="QUALITY[t.quality]?.[1]">{{ QUALITY[t.quality]?.[0] || t.quality }}</span>
              </template>
              <Icon v-if="turnsFor(i).some((t) => signalsOf(t).length)" name="eye" :size="13" class="ml-1 text-orange-600" title="Left the page or pasted text during this question" />
            </span>
          </button>

          <div v-if="openTurns.has(i)" class="space-y-4 px-4 pb-4 pl-11">
            <div v-for="t in turnsFor(i)" :key="t.id" class="space-y-1.5 text-sm">
              <p class="font-medium text-slate-800"><span v-if="t.kind === 'followup'" class="text-indigo-600">Follow-up: </span>{{ t.question }}</p>
              <p class="rounded-xl bg-slate-50 px-3 py-2 whitespace-pre-line text-slate-700">{{ t.transcript || '(no speech detected)' }}</p>
              <div class="flex flex-wrap items-center gap-2 text-xs text-slate-500">
                <span class="inline-flex items-center gap-1"><Icon :name="t.answer_mode === 'typed' ? 'keyboard' : 'mic'" :size="12" />{{ t.answer_mode === 'typed' ? 'Typed' : 'Spoken' }}</span>
                <span v-if="t.notes">· {{ t.notes }}</span>
              </div>
              <p v-if="signalsOf(t).length" class="inline-flex items-center gap-1.5 rounded-lg bg-orange-50 px-2 py-1 text-xs text-orange-800 ring-1 ring-orange-200 ring-inset" title="Measured by the browser while this question was open. Context for you to judge; it doesn't change the score.">
                <Icon name="eye" :size="12" />{{ signalsOf(t).join(' · ') }}
              </p>
              <audio v-if="audio[t.id]" :src="audio[t.id]" controls class="h-8 w-full max-w-xs"></audio>
            </div>
            <p v-if="!turnsFor(i).length" class="text-sm text-slate-600">{{ q.question }}</p>
          </div>
        </div>
      </div>
    </section>

    <!-- Reference material, folded away -->
    <details v-if="sub.page_map || sub.analysis" class="group card mt-8 p-0">
      <summary class="flex cursor-pointer list-none items-center gap-3 px-4 py-3 text-sm font-medium [&::-webkit-details-marker]:hidden">
        <Icon name="chevron-right" :size="14" class="text-slate-400 transition group-open:rotate-90" />
        Submission details
        <span class="font-normal text-slate-400">· answer pages and what the AI read in the PDF</span>
      </summary>
      <div class="space-y-6 border-t border-slate-100 px-4 py-4 pl-11 text-sm">
        <div v-if="sub.page_map">
          <h3 class="mb-2 text-xs font-medium tracking-wide text-slate-500 uppercase">
            Answer pages <span class="font-normal normal-case">· {{ sub.pages_confirmed_at ? 'confirmed by the student' : 'AI guess, not confirmed yet' }}</span>
          </h3>
          <div class="flex flex-wrap gap-1.5">
            <span v-for="(q, i) in sub.parts" :key="i" class="inline-flex items-center gap-1 rounded-lg bg-slate-50 px-2 py-1 text-xs ring-1 ring-slate-200 ring-inset" :title="q">
              <b>Q{{ i + 1 }}</b>
              <template v-if="sub.page_map[i]?.length">p. {{ sub.page_map[i].join(', ') }}</template>
              <span v-else class="text-orange-600">none</span>
            </span>
          </div>
        </div>
        <div v-if="sub.analysis">
          <h3 class="mb-2 text-xs font-medium tracking-wide text-slate-500 uppercase">What the AI found in the PDF</h3>
          <p class="mb-2 text-slate-600">{{ sub.analysis.summary }}</p>
          <ul class="space-y-1">
            <li v-for="(it, i) in sub.analysis.items" :key="i" class="flex gap-2" :title="it.description">
              <span class="w-8 shrink-0 font-mono text-xs text-slate-400">p. {{ it.page }}</span>
              <span class="text-slate-700">{{ it.name }}</span>
            </li>
          </ul>
        </div>
      </div>
    </details>
  </div>
</template>
