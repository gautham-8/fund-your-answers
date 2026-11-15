<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { onBeforeRouteLeave, useRouter } from 'vue-router'
import { api } from '../lib/api'
import { auth } from '../lib/auth'
import { confirmDialog } from '../lib/confirm'
import { fmtPts } from '../lib/format'
import { usePdfPages } from '../lib/pdfPages'
import { setCourse } from '../lib/store'
import { toast } from '../lib/toast'
import Icon from '../components/Icon.vue'
import StatusBadge from '../components/StatusBadge.vue'

/**
 * Gradescope-style grading: the submission's pages on the left, one page at a time, and the assignment's
 * questions on the right. Instructors enter points (and comments) per question; students see the same
 * view read-only, with their marks once grades are published.
 */
const props = defineProps({ id: String })
const router = useRouter()
const isInstructor = auth.user?.role === 'instructor'
const ZOOMS = [0.5, 0.75, 1, 1.25, 1.5, 2]

const sub = ref(null)
const error = ref('')
const order = ref([]) // PDF page numbers in the student's order
const savedRot = ref([]) // the student's rotation per page (index = page - 1)
const extraRot = ref([]) // rotation added here, only for viewing
const pos = ref(0) // index into `order` of the page shown
const zoom = ref(2) // index into ZOOMS
const grid = ref(false)
const active = ref(0) // question selected on the right
const form = reactive({ grades: [], note: '' }) // instructor's editable copy
const total = reactive({ points: '', note: '' }) // assignments without questions: one mark
const saving = ref(false)
const snapshot = ref('')
const nextId = ref(null)
const { images, open, render, renderAll } = usePdfPages()

const parts = computed(() => sub.value?.parts || [])
const maxes = computed(() => sub.value?.assignment.part_points || [])
const maxTotal = computed(() => sub.value?.assignment.max_points ?? 0)
const pageMap = computed(() => sub.value?.page_map || parts.value.map(() => []))
const page = computed(() => order.value[pos.value])
const rotOf = (p) => ((savedRot.value[p - 1] || 0) + (extraRot.value[p - 1] || 0)) % 360
const owners = (p) => pageMap.value.flatMap((list, i) => (list.includes(p) ? [i] : []))
/** A question's pages in the order they appear in the student's PDF. */
const pagesOf = (i) => [...(pageMap.value[i] || [])].sort((a, b) => order.value.indexOf(a) - order.value.indexOf(b))

// What the right-hand panel shows: the instructor's draft, or the student's published marks.
const results = computed(() => sub.value?.results)
const shownGrades = computed(() => (isInstructor ? form.grades : results.value?.question_grades || null))
const isSet = (v) => v !== '' && v != null
const gradedCount = computed(() => (shownGrades.value || []).filter((g) => isSet(g.points)).length)
const sumPoints = computed(() => (shownGrades.value || []).reduce((t, g) => t + (isSet(g.points) ? Number(g.points) : 0), 0))
const complete = computed(() => parts.value.length > 0 && gradedCount.value === parts.value.length)
const dirty = computed(() => isInstructor && sub.value && JSON.stringify([form, total]) !== snapshot.value)

const vivaWeight = computed(() => sub.value?.assignment.viva_weight ?? 0.3)
/** Final grade preview, same formula as the server: (1 - w) x grader % + w x viva %. */
const finalPreview = computed(() => {
  const s = sub.value
  if (!s) return null
  if (!isInstructor) return results.value?.overall ?? null
  const pts = parts.value.length ? (complete.value ? sumPoints.value : null) : isSet(total.points) ? Number(total.points) : null
  if (pts == null || s.overall == null || s.status !== 'completed' || !maxTotal.value) return null
  const g = Math.min(1, pts / maxTotal.value) * 100
  return Math.round(((1 - vivaWeight.value) * g + vivaWeight.value * s.overall) * 10) / 10
})

async function load() {
  try {
    const s = await api(`/api/submissions/${props.id}`)
    sub.value = s
    setCourse(s.course)
    form.grades = (s.question_grades || parts.value.map(() => ({ points: null, comment: '' }))).map((g) => ({
      points: g.points ?? '',
      comment: g.comment || '',
    }))
    form.note = s.grader_note || ''
    Object.assign(total, { points: s.grader_points ?? '', note: s.grader_note || '' })
    snapshot.value = JSON.stringify([form, total])

    const n = await open(`/api/submissions/${props.id}/pdf`)
    order.value = s.page_order?.length === n ? [...s.page_order] : Array.from({ length: n }, (_, i) => i + 1)
    savedRot.value = s.page_rotation?.length === n ? [...s.page_rotation] : Array(n).fill(0)
    extraRot.value = Array(n).fill(0)
    const first = pagesOf(0)[0]
    if (first) pos.value = order.value.indexOf(first)
    // The page on screen first, then the rest in order.
    renderAll([page.value, ...order.value.filter((p) => p !== page.value)], rotOf)
    if (isInstructor) findNext(s.assignment.id)
  } catch (e) {
    error.value = e.message
  }
}

/** The next submission in this assignment that still needs grading. */
async function findNext(assignmentId) {
  try {
    const a = await api(`/api/assignments/${assignmentId}`)
    const subs = a.submissions || []
    const todo = (x) => x.grader_points == null && !['analyzing', 'analysis_failed'].includes(x.status)
    const at = subs.findIndex((x) => x.id === props.id)
    const next = [...subs.slice(at + 1), ...subs.slice(0, Math.max(0, at))].find(todo)
    nextId.value = next?.id || null
  } catch {
    nextId.value = null
  }
}

function go(i) {
  if (i >= 0 && i < order.value.length) {
    pos.value = i
    grid.value = false
  }
}

function selectQuestion(i) {
  active.value = i
  const first = pagesOf(i)[0]
  if (first) go(order.value.indexOf(first))
}
function stepQuestion(d) {
  const i = active.value + d
  if (i >= 0 && i < parts.value.length) selectQuestion(i)
}

function rotate() {
  const p = page.value
  extraRot.value[p - 1] = ((extraRot.value[p - 1] || 0) + 90) % 360
  render(p, rotOf(p)).catch((e) => toast(e.message, { type: 'error' }))
}

function setPoints(i, v) {
  form.grades[i].points = v
}

async function save() {
  if (!isInstructor || saving.value) return
  for (const [i, g] of form.grades.entries()) {
    if (isSet(g.points) && (Number(g.points) < 0 || Number(g.points) > maxes.value[i])) {
      selectQuestion(i)
      toast(`Q${i + 1} must be between 0 and ${fmtPts(maxes.value[i])}`, { type: 'error' })
      return false
    }
  }
  saving.value = true
  try {
    if (parts.value.length) {
      const res = await api(`/api/submissions/${props.id}/question-grades`, {
        method: 'PUT',
        body: {
          questions: form.grades.map((g) => ({ points: isSet(g.points) ? Number(g.points) : null, comment: g.comment })),
          note: form.note,
        },
      })
      Object.assign(sub.value, res)
    } else {
      const res = await api(`/api/submissions/${props.id}/grade`, {
        method: 'PUT',
        body: { points: isSet(total.points) ? Number(total.points) : null, note: total.note },
      })
      Object.assign(sub.value, res)
    }
    snapshot.value = JSON.stringify([form, total])
    toast(complete.value || !parts.value.length ? 'Grade saved' : `Saved · ${gradedCount.value} of ${parts.value.length} questions graded`)
    return true
  } catch (e) {
    toast(e.message, { type: 'error' })
    return false
  } finally {
    saving.value = false
  }
}

async function nextStudent() {
  if (dirty.value && !(await save())) return
  router.push(`/submissions/${nextId.value}/grade`)
}

function onKey(e) {
  if ((e.metaKey || e.ctrlKey) && e.key === 's') {
    e.preventDefault()
    save()
    return
  }
  if (e.target.closest('input, textarea, select')) return
  if (e.key === 'ArrowLeft') go(pos.value - 1)
  else if (e.key === 'ArrowRight') go(pos.value + 1)
  else if (e.key === 'ArrowUp' && parts.value.length) (e.preventDefault(), stepQuestion(-1))
  else if (e.key === 'ArrowDown' && parts.value.length) (e.preventDefault(), stepQuestion(1))
}
function onBeforeUnload(e) {
  if (dirty.value) e.preventDefault()
}

onBeforeRouteLeave(async () => {
  if (!dirty.value) return true
  return confirmDialog({
    title: 'Leave without saving?',
    message: "Your grading changes on this submission haven't been saved.",
    confirmText: 'Leave',
    danger: true,
  })
})

onMounted(() => {
  load()
  window.addEventListener('keydown', onKey)
  window.addEventListener('beforeunload', onBeforeUnload)
})
onUnmounted(() => {
  window.removeEventListener('keydown', onKey)
  window.removeEventListener('beforeunload', onBeforeUnload)
  setCourse(null)
})
</script>

<template>
  <p v-if="error" class="error-box mb-4">{{ error }}</p>
  <div v-if="!sub && !error" class="skeleton h-[80vh] w-full rounded-2xl"></div>

  <div v-if="sub" class="grid gap-4 lg:h-[calc(100vh-2rem)] lg:grid-cols-[minmax(0,1fr)_23rem]">
    <!-- ===== Pages ===== -->
    <section class="flex min-h-[70vh] min-w-0 flex-col overflow-hidden rounded-2xl border border-slate-200/80 bg-slate-100/70 lg:min-h-0">
      <div class="flex flex-wrap items-center gap-2 border-b border-slate-200/80 bg-white/70 px-3 py-2">
        <RouterLink
          :to="isInstructor ? `/submissions/${id}/report` : `/assignments/${sub.assignment.id}`"
          class="btn-ghost btn-sm"
        ><Icon name="chevron-left" :size="14" />{{ isInstructor ? 'Report' : sub.assignment.title }}</RouterLink>
        <span class="text-sm text-slate-500">
          Page {{ page }}<span class="text-slate-400"> · {{ pos + 1 }} of {{ order.length }}</span>
        </span>
        <span v-for="q in owners(page)" :key="q" class="rounded px-1.5 py-0.5 text-[11px] font-semibold" :class="q === active ? 'bg-indigo-600 text-white' : 'bg-slate-200 text-slate-600'">Q{{ q + 1 }}</span>
        <div class="ml-auto flex items-center gap-1">
          <button class="icon-btn" :class="grid && 'bg-slate-200'" title="All pages" @click="grid = !grid"><Icon name="grid" :size="16" /></button>
          <button class="icon-btn" title="Rotate (view only)" :disabled="grid" @click="rotate"><Icon name="rotate-cw" :size="16" /></button>
          <button class="icon-btn" title="Zoom out" :disabled="zoom === 0" @click="zoom--"><Icon name="zoom-out" :size="16" /></button>
          <span class="w-11 text-center text-xs text-slate-500">{{ Math.round(ZOOMS[zoom] * 100) }}%</span>
          <button class="icon-btn" title="Zoom in" :disabled="zoom === ZOOMS.length - 1" @click="zoom++"><Icon name="zoom-in" :size="16" /></button>
        </div>
      </div>

      <!-- All pages -->
      <div v-if="grid" class="grid flex-1 grid-cols-2 content-start gap-4 overflow-auto p-4 sm:grid-cols-3 xl:grid-cols-4">
        <button v-for="(p, i) in order" :key="p" type="button" class="text-left" @click="go(i)">
          <span class="block overflow-hidden rounded-lg border-2 bg-white shadow-xs" :class="i === pos ? 'border-indigo-600' : 'border-transparent hover:border-indigo-300'">
            <img v-if="images[p - 1]" :src="images[p - 1]" :alt="`Page ${p}`" class="block w-full" />
            <span v-else class="skeleton block aspect-[8.5/11] w-full rounded-none"></span>
          </span>
          <span class="mt-1 flex flex-wrap items-center gap-1 text-xs text-slate-500">
            Page {{ p }}
            <span v-for="q in owners(p)" :key="q" class="rounded bg-slate-200 px-1 text-[10px] font-semibold text-slate-600">Q{{ q + 1 }}</span>
          </span>
        </button>
      </div>

      <!-- One page -->
      <div v-else class="relative flex-1 overflow-auto p-4">
        <div class="mx-auto" :style="{ width: `${ZOOMS[zoom] * 100}%`, maxWidth: `${ZOOMS[zoom] * 52}rem` }">
          <img v-if="images[page - 1]" :src="images[page - 1]" :alt="`Page ${page}`" class="block w-full rounded bg-white shadow-sm" />
          <div v-else class="skeleton aspect-[8.5/11] w-full"></div>
        </div>
      </div>
      <div v-if="!grid" class="flex items-center justify-between gap-2 border-t border-slate-200/80 bg-white/70 px-3 py-2">
        <button class="btn-secondary btn-sm" :disabled="pos <= 0" @click="go(pos - 1)"><Icon name="chevron-left" :size="14" />Previous page</button>
        <span class="hidden text-xs text-slate-400 sm:inline">← → pages · ↑ ↓ questions<template v-if="isInstructor"> · ⌘S save</template></span>
        <button class="btn-secondary btn-sm" :disabled="pos >= order.length - 1" @click="go(pos + 1)">Next page<Icon name="chevron-right" :size="14" /></button>
      </div>
    </section>

    <!-- ===== Questions & grades ===== -->
    <aside class="flex min-h-0 flex-col overflow-hidden rounded-2xl border border-slate-200/80 bg-white shadow-xs">
      <div class="flex-1 space-y-5 overflow-auto p-5">
        <div>
          <div class="flex items-start justify-between gap-2">
            <h1 class="text-lg font-semibold tracking-tight">{{ sub.assignment.title }}</h1>
            <span v-if="shownGrades && parts.length" class="mt-1 inline-flex shrink-0 items-center gap-1.5 text-xs font-medium" :class="complete ? 'text-emerald-700' : 'text-orange-600'">
              <span class="size-2 rounded-full" :class="complete ? 'bg-emerald-500' : 'bg-orange-400'"></span>
              {{ complete ? 'Graded' : `${gradedCount} of ${parts.length} graded` }}
            </span>
          </div>
          <div v-if="isInstructor" class="mt-1 flex flex-wrap items-center gap-2 text-sm text-slate-600">
            {{ sub.student?.name }} <StatusBadge :status="sub.status" :late="sub.late" />
          </div>
        </div>

        <!-- Student before publishing -->
        <p v-if="!isInstructor && !shownGrades" class="rounded-xl bg-slate-50 p-3 text-sm text-slate-600">
          Your grade isn't published yet. You can look through your pages here; marks and comments show up once your instructor publishes grades.
        </p>

        <div v-if="shownGrades || isInstructor" class="grid grid-cols-2 gap-3">
          <div class="rounded-xl bg-slate-50 p-3">
            <div class="text-xs text-slate-500">Written solution</div>
            <div class="mt-0.5 text-lg font-semibold">
              <template v-if="parts.length">{{ fmtPts(sumPoints) }}</template>
              <template v-else>{{ isInstructor ? fmtPts(total.points) : fmtPts(results?.grader_points) }}</template>
              <span class="text-sm font-normal text-slate-400"> / {{ fmtPts(maxTotal) }}</span>
            </div>
          </div>
          <div class="rounded-xl bg-slate-50 p-3">
            <div class="text-xs text-slate-500">Final grade</div>
            <div class="mt-0.5 text-lg font-semibold">{{ finalPreview != null ? finalPreview + '%' : '—' }}</div>
            <div class="text-[11px] text-slate-400">
              {{ Math.round((1 - vivaWeight) * 100) }}% solution + {{ Math.round(vivaWeight * 100) }}% viva<template v-if="(isInstructor ? sub.overall : results?.viva) != null"> ({{ Math.round(isInstructor ? sub.overall : results.viva) }}%)</template>
            </div>
          </div>
        </div>

        <!-- Questions -->
        <ol v-if="parts.length" class="space-y-1">
          <li
            v-for="(q, i) in parts"
            :key="i"
            class="rounded-xl border transition"
            :class="i === active ? 'border-indigo-300 bg-indigo-50/50 ring-4 ring-indigo-50' : 'border-transparent hover:bg-slate-50'"
          >
            <button type="button" class="flex w-full items-start gap-2 px-3 pt-2.5 pb-1.5 text-left" @click="selectQuestion(i)">
              <span class="mt-0.5 text-sm font-semibold" :class="i === active ? 'text-indigo-700' : 'text-slate-900'">Q{{ i + 1 }}</span>
              <span class="min-w-0 flex-1">
                <span class="text-sm text-slate-700" :class="i !== active && 'line-clamp-2'">{{ q }}</span>
                <span class="mt-1 block text-xs" :class="pagesOf(i).length ? 'text-slate-400' : 'text-orange-600'">
                  {{ pagesOf(i).length ? `Page${pagesOf(i).length > 1 ? 's' : ''} ${pagesOf(i).join(', ')}` : 'No pages selected by the student' }}
                </span>
              </span>
              <span v-if="!isInstructor && shownGrades" class="shrink-0 font-mono text-sm font-semibold">
                {{ fmtPts(shownGrades[i]?.points) }}<span class="font-normal text-slate-400"> / {{ fmtPts(maxes[i]) }}</span>
              </span>
              <span v-else-if="isInstructor && isSet(form.grades[i]?.points) && i !== active" class="shrink-0 font-mono text-sm font-semibold">
                {{ fmtPts(form.grades[i].points) }}<span class="font-normal text-slate-400"> / {{ fmtPts(maxes[i]) }}</span>
              </span>
              <span v-else-if="isInstructor && i !== active" class="shrink-0 text-xs text-slate-400">/ {{ fmtPts(maxes[i]) }}</span>
            </button>

            <!-- Grader's inputs for the selected question -->
            <div v-if="isInstructor && i === active && form.grades[i]" class="space-y-2 px-3 pb-3 pl-10">
              <!-- Fixed layout: nothing appears or wraps while typing, so the boxes below don't jump -->
              <div class="flex items-center gap-2">
                <input
                  v-model="form.grades[i].points"
                  type="number"
                  min="0"
                  :max="maxes[i]"
                  step="any"
                  class="input w-20 py-1.5 font-mono"
                  :class="isSet(form.grades[i].points) && (Number(form.grades[i].points) < 0 || Number(form.grades[i].points) > maxes[i]) && 'border-rose-400 bg-rose-50 text-rose-700'"
                  placeholder="—"
                  :aria-label="`Points for Q${i + 1}`"
                />
                <span class="text-sm whitespace-nowrap text-slate-500">/ {{ fmtPts(maxes[i]) }}</span>
                <div class="ml-auto flex items-center rounded-lg ring-1 ring-slate-200 ring-inset">
                  <button type="button" class="px-2 py-1 text-xs font-medium text-slate-600 hover:text-indigo-700" @click="setPoints(i, maxes[i])">Full</button>
                  <button type="button" class="border-l border-slate-200 px-2 py-1 text-xs font-medium text-slate-600 hover:text-indigo-700" @click="setPoints(i, 0)">Zero</button>
                  <button type="button" class="border-l border-slate-200 px-2 py-1 text-xs font-medium text-slate-400 hover:text-slate-700 disabled:opacity-40" :disabled="!isSet(form.grades[i].points)" @click="setPoints(i, '')">Clear</button>
                </div>
              </div>
              <textarea v-model="form.grades[i].comment" class="input text-sm" rows="2" placeholder="Comment for the student (optional)" :aria-label="`Comment for Q${i + 1}`"></textarea>
            </div>
            <p v-else-if="!isInstructor && shownGrades?.[i]?.comment" class="mx-3 mb-3 ml-10 rounded-lg bg-white px-3 py-2 text-sm whitespace-pre-line text-slate-700 ring-1 ring-slate-200">
              {{ shownGrades[i].comment }}
            </p>
          </li>
        </ol>

        <!-- No questions on this assignment: one total mark -->
        <div v-else-if="isInstructor" class="space-y-2">
          <label class="label" for="g-total">Points for the written solution</label>
          <div class="flex items-center gap-2">
            <input id="g-total" v-model="total.points" type="number" min="0" :max="maxTotal" step="any" class="input w-28 font-mono" placeholder="—" />
            <span class="text-sm text-slate-500">/ {{ fmtPts(maxTotal) }}</span>
          </div>
          <p class="hint">Add questions with points to the assignment to grade question by question.</p>
        </div>

        <!-- Overall feedback -->
        <div v-if="isInstructor">
          <label class="label" for="g-note">Overall feedback <span class="font-normal text-slate-400">(optional)</span></label>
          <textarea v-if="parts.length" id="g-note" v-model="form.note" class="input text-sm" rows="3"></textarea>
          <textarea v-else id="g-note" v-model="total.note" class="input text-sm" rows="3"></textarea>
          <p v-if="sub.graded_by" class="mt-1 text-xs text-slate-400">Last saved by {{ sub.graded_by }}</p>
        </div>
        <div v-else-if="results?.grader_note" class="rounded-xl bg-slate-50 p-3 text-sm">
          <div class="mb-1 text-xs font-medium text-slate-500">Grader's feedback</div>
          <p class="whitespace-pre-line text-slate-700">{{ results.grader_note }}</p>
        </div>
      </div>

      <!-- Actions -->
      <div v-if="isInstructor" class="space-y-2 border-t border-slate-100 p-3">
        <div v-if="parts.length" class="flex gap-2">
          <button class="btn-secondary btn-sm flex-1" :disabled="active === 0" @click="stepQuestion(-1)"><Icon name="chevron-up" :size="14" />Previous question</button>
          <button class="btn-secondary btn-sm flex-1" :disabled="active === parts.length - 1" @click="stepQuestion(1)">Next question<Icon name="chevron-down" :size="14" /></button>
        </div>
        <div class="flex gap-2">
          <button class="btn-primary flex-1" :disabled="saving || !dirty" @click="save">
            <Icon name="check" />{{ saving ? 'Saving…' : dirty ? 'Save' : 'Saved' }}
          </button>
          <button v-if="nextId" class="btn-secondary" :disabled="saving" title="Next submission that still needs grading" @click="nextStudent">
            Next student<Icon name="arrow-right" :size="14" />
          </button>
        </div>
      </div>
    </aside>
  </div>
</template>
