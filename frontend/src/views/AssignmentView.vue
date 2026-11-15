<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, blobUrl } from '../lib/api'
import { auth } from '../lib/auth'
import { dueState, fmtDate, fmtPts, humanize, initials, now, relative, scoreTone, tzAbbr } from '../lib/format'
import { loadCourses, setCourse } from '../lib/store'
import { toast } from '../lib/toast'
import AssignmentFormModal from '../components/AssignmentFormModal.vue'
import ClassInsights from '../components/ClassInsights.vue'
import Icon from '../components/Icon.vue'
import Modal from '../components/Modal.vue'
import ScoreRing from '../components/ScoreRing.vue'
import StatusBadge from '../components/StatusBadge.vue'

const props = defineProps({ id: String })
const router = useRouter()
const isInstructor = auth.user?.role === 'instructor'

const a = ref(null)
const error = ref('')
const file = ref(null)
const dragging = ref(false)
const uploading = ref(false)
const editOpen = ref(false)
const publishing = ref(false)
const q = ref('')
const filter = ref('all')
const regrade = reactive({ open: false, index: null, message: '', busy: false })
let timer = null

const mySub = computed(() => a.value?.my_submission)
const results = computed(() => a.value?.my_results)
const pending = (s) => s === 'analyzing' || s === 'scoring'
const state = computed(() => (a.value ? dueState(a.value, now.value) : 'none'))

async function load() {
  try {
    a.value = await api(`/api/assignments/${props.id}`)
    setCourse(a.value.course)
  } catch (e) {
    error.value = e.message
  }
  // Poll while something is processing in the background.
  const list = isInstructor ? a.value?.submissions || [] : mySub.value ? [mySub.value] : []
  clearTimeout(timer)
  if (list.some((s) => pending(s.status))) timer = setTimeout(load, 3000)
}

// ---------- Student ----------

const canUpload = computed(
  () => a.value?.accepting_submissions && (!mySub.value || ['analyzing', 'analysis_failed', 'off_topic', 'ready'].includes(mySub.value.status)),
)

const STEPS = ['Submit PDF', 'AI reads it', 'Viva', 'Scoring', 'Grade']
const step = computed(() => {
  const s = mySub.value?.status
  if (!s) return 0
  if (s === 'analyzing' || s === 'analysis_failed' || s === 'off_topic') return 1
  if (s === 'ready' || s === 'viva_in_progress') return 2
  if (s === 'scoring' || s === 'scoring_failed') return 3
  return results.value ? 5 : 4
})

function pick(f) {
  if (!f) return
  if (f.type && f.type !== 'application/pdf') {
    toast('Please choose a PDF file', { type: 'error' })
    return
  }
  file.value = f
}
function onDrop(e) {
  dragging.value = false
  pick(e.dataTransfer.files[0])
}

async function upload() {
  if (!file.value) return
  uploading.value = true
  error.value = ''
  try {
    const form = new FormData()
    form.append('file', file.value)
    await api(`/api/assignments/${props.id}/submissions`, { method: 'POST', form })
    file.value = null
    toast('PDF uploaded — preparing your viva')
    await load()
  } catch (e) {
    error.value = e.message
  } finally {
    uploading.value = false
  }
}

async function openBrief() {
  window.open(await blobUrl(`/api/assignments/${props.id}/brief`), '_blank')
}

const pct = (x) => `${Math.round(x * 100)}%`

async function retry(subId) {
  try {
    await api(`/api/submissions/${subId}/retry`, { method: 'POST' })
    await load()
  } catch (e) {
    error.value = e.message
  }
}

const requestFor = (i) => results.value?.regrade_requests.find((r) => r.dimension_index === i && r.status === 'open')
const lastResolvedFor = (i) => results.value?.regrade_requests.find((r) => r.dimension_index === i && r.status === 'resolved')

function openRegrade(i) {
  Object.assign(regrade, { open: true, index: i, message: '', busy: false })
}
async function sendRegrade() {
  regrade.busy = true
  try {
    await api(`/api/submissions/${mySub.value.id}/regrade-requests`, {
      method: 'POST',
      body: { dimension_index: regrade.index, message: regrade.message },
    })
    regrade.open = false
    toast('Regrade request sent to your instructor')
    await load()
  } catch (e) {
    toast(e.message, { type: 'error' })
  } finally {
    regrade.busy = false
  }
}

// ---------- Instructor ----------

/** Submissions plus roster students who haven't submitted, as one list. */
const people = computed(() => {
  if (!a.value?.submissions) return []
  const subs = a.value.submissions.map((s) => ({ ...s, key: s.id }))
  const missing = a.value.missing.map((m) => ({ key: `m-${m.id}`, student: m, status: null, missing: true }))
  return [...subs, ...missing]
})
const stats = computed(() => {
  const subs = a.value?.submissions || []
  const done = subs.filter((s) => s.status === 'completed')
  const scored = done.filter((s) => s.overall != null)
  const finals = subs.filter((s) => s.final != null)
  return {
    submitted: subs.length,
    total: a.value?.student_count || 0,
    completed: done.length,
    review: done.filter((s) => s.needs_review).length,
    late: subs.filter((s) => s.late).length,
    avg: scored.length ? Math.round(scored.reduce((t, s) => t + s.overall, 0) / scored.length) : null,
    avgFinal: finals.length ? Math.round(finals.reduce((t, s) => t + s.final, 0) / finals.length) : null,
    ungraded: done.filter((s) => s.grader_points == null).length,
    offTopic: subs.filter((s) => s.status === 'off_topic').length,
    regrades: subs.reduce((t, s) => t + (s.open_regrades || 0), 0),
  }
})
const FILTERS = [
  ['all', 'All'],
  ['review', 'Needs review'],
  ['ungraded', 'Not graded'],
  ['off_topic', "Doesn't match"],
  ['completed', 'Completed'],
  ['progress', 'In progress'],
  ['missing', 'Missing'],
]
const shown = computed(() => {
  const term = q.value.trim().toLowerCase()
  return people.value.filter((p) => {
    if (term && !`${p.student?.name} ${p.student?.email}`.toLowerCase().includes(term)) return false
    switch (filter.value) {
      case 'review': return p.status === 'completed' && p.needs_review
      case 'ungraded': return p.status === 'completed' && p.grader_points == null
      case 'off_topic': return p.status === 'off_topic'
      case 'completed': return p.status === 'completed'
      case 'progress': return p.status && p.status !== 'completed'
      case 'missing': return p.missing
      default: return true
    }
  })
})
const filterCount = (k) =>
  ({
    all: people.value.length,
    review: stats.value.review,
    ungraded: stats.value.ungraded,
    off_topic: stats.value.offTopic,
    completed: stats.value.completed,
    progress: stats.value.submitted - stats.value.completed,
    missing: a.value?.missing.length || 0,
  })[k]

async function togglePublish() {
  publishing.value = true
  try {
    const next = !a.value.grades_published
    await api(`/api/assignments/${props.id}`, { method: 'PATCH', body: { grades_published: next } })
    a.value.grades_published = next
    toast(next ? 'Grades published — students can now see their scores' : 'Grades hidden from students')
  } catch (e) {
    toast(e.message, { type: 'error' })
  } finally {
    publishing.value = false
  }
}

async function onEdited() {
  editOpen.value = false
  await load()
  loadCourses()
  toast('Assignment updated')
}

const scheduleLabel = computed(() => {
  const x = a.value
  if (!x) return ''
  switch (state.value) {
    case 'scheduled': return `Opens in ${humanize(new Date(x.release_date) - now.value)}`
    case 'open':
    case 'soon': return `${humanize(new Date(x.due_date) - now.value)} left`
    case 'late': return `Late submissions accepted for ${humanize(new Date(x.late_due_date) - now.value)}`
    case 'closed': return 'Closed for submissions'
    default: return 'No due date'
  }
})
const scheduleTone = computed(
  () =>
    ({
      soon: 'bg-amber-50 text-amber-700 ring-amber-200',
      late: 'bg-orange-50 text-orange-700 ring-orange-200',
      closed: 'bg-slate-100 text-slate-600 ring-slate-200',
      scheduled: 'bg-violet-50 text-violet-700 ring-violet-200',
    })[state.value] || 'bg-indigo-50 text-indigo-700 ring-indigo-200',
)

onMounted(load)
onUnmounted(() => {
  clearTimeout(timer)
  setCourse(null)
})
</script>

<template>
  <p v-if="error && !a" class="error-box">{{ error }}</p>
  <div v-if="!a && !error" class="space-y-4">
    <div class="skeleton h-5 w-48"></div>
    <div class="skeleton h-10 w-2/3"></div>
    <div class="skeleton h-72 w-full"></div>
  </div>

  <div v-if="a" class="animate-fade-up">
    <!-- Breadcrumb -->
    <nav class="mb-4 flex items-center gap-1.5 text-sm text-slate-500">
      <RouterLink :to="`/courses/${a.course.id}`" class="hover:text-slate-900">{{ a.course.code || a.course.name }}</RouterLink>
      <Icon name="chevron-right" :size="14" class="text-slate-300" />
      <span class="truncate text-slate-400">Assignment</span>
    </nav>

    <!-- Header -->
    <header class="flex flex-wrap items-start justify-between gap-4">
      <div class="min-w-0">
        <h1 class="text-2xl font-semibold tracking-tight sm:text-3xl">{{ a.title }}</h1>
        <div class="mt-3 flex flex-wrap items-center gap-2">
          <span class="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ring-1 ring-inset" :class="scheduleTone">
            <Icon :name="state === 'closed' ? 'lock' : state === 'scheduled' ? 'eye-off' : 'clock'" :size="12" />{{ scheduleLabel }}
          </span>
          <span v-if="isInstructor && a.grades_published" class="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-700 ring-1 ring-emerald-200 ring-inset">
            <Icon name="check" :size="12" />Grades published
          </span>
        </div>
      </div>
      <div v-if="isInstructor" class="flex flex-wrap items-center gap-2">
        <button class="btn-secondary" @click="editOpen = true"><Icon name="pencil" />Edit</button>
        <button
          class="flex items-center gap-2.5 rounded-lg border px-3 py-2 text-sm font-medium transition"
          :class="a.grades_published ? 'border-emerald-200 bg-emerald-50 text-emerald-800' : 'border-slate-200 bg-white text-slate-700 hover:bg-slate-50'"
          :disabled="publishing"
          role="switch"
          :aria-checked="a.grades_published"
          @click="togglePublish"
        >
          <span class="relative h-5 w-9 rounded-full transition" :class="a.grades_published ? 'bg-emerald-500' : 'bg-slate-300'">
            <span class="absolute top-0.5 left-0.5 size-4 rounded-full bg-white shadow transition" :class="a.grades_published && 'translate-x-4'"></span>
          </span>
          {{ a.grades_published ? 'Published' : 'Publish grades' }}
        </button>
      </div>
    </header>

    <p v-if="error" class="error-box mt-4">{{ error }}</p>

    <div class="mt-8 grid gap-6 lg:grid-cols-[minmax(0,1fr)_18rem]">
      <!-- Main column -->
      <div class="min-w-0 space-y-6">
        <section v-if="a.description" class="card">
          <h2 class="eyebrow mb-2">Instructions</h2>
          <p class="leading-relaxed whitespace-pre-line text-slate-700">{{ a.description }}</p>
        </section>

        <section v-if="a.parts?.length" class="card">
          <h2 class="eyebrow mb-2">Questions</h2>
          <ol class="list-decimal space-y-1.5 pl-5 leading-relaxed text-slate-700">
            <li v-for="(q, i) in a.parts" :key="i" class="whitespace-pre-line">
              {{ q }} <span v-if="a.part_points?.[i] != null" class="text-xs font-medium whitespace-nowrap text-slate-400">· {{ fmtPts(a.part_points[i]) }} pts</span>
            </li>
          </ol>
        </section>

        <!-- ===== Student ===== -->
        <template v-if="!isInstructor">
          <section class="card space-y-6">
            <div class="flex flex-wrap items-center justify-between gap-3">
              <h2 class="font-semibold">Your submission</h2>
              <StatusBadge :status="mySub?.status" :late="mySub?.late" />
            </div>

            <!-- Progress -->
            <ol class="grid grid-cols-5 gap-2">
              <li v-for="(s, i) in STEPS" :key="s" class="min-w-0">
                <div class="h-1.5 rounded-full transition-colors" :class="i < step ? 'bg-indigo-500' : i === step ? 'bg-indigo-200' : 'bg-slate-100'"></div>
                <div class="mt-1.5 truncate text-[11px] font-medium" :class="i <= step ? 'text-slate-700' : 'text-slate-400'">{{ s }}</div>
              </li>
            </ol>

            <div v-if="mySub" class="flex items-center gap-3 rounded-xl border border-slate-200 p-3">
              <span class="grid size-10 place-items-center rounded-lg bg-rose-50 text-rose-600"><Icon name="file" :size="18" /></span>
              <div class="min-w-0 flex-1">
                <div class="truncate text-sm font-medium">{{ mySub.filename }}</div>
                <div class="text-xs text-slate-500">Submitted {{ relative(mySub.created_at) }}<span v-if="mySub.late" class="text-orange-600"> · late</span></div>
              </div>
              <RouterLink
                v-if="!mySub.pages_pending && !['analyzing', 'analysis_failed'].includes(mySub.status)"
                :to="`/submissions/${mySub.id}/grade`"
                class="btn-secondary btn-sm"
              ><Icon name="eye" :size="14" />{{ results?.question_grades ? 'View graded pages' : 'View pages' }}</RouterLink>
            </div>

            <div v-if="mySub?.status === 'analyzing'" class="flex items-center gap-3 rounded-xl bg-amber-50 p-4 text-sm text-amber-900">
              <span class="size-4 shrink-0 animate-spin rounded-full border-2 border-amber-300 border-t-amber-700"></span>
              Reading your PDF and preparing questions. This usually takes under a minute…
            </div>
            <div v-if="mySub?.status === 'analysis_failed'" class="error-box">
              We couldn't analyze your PDF. <button class="font-medium underline" @click="retry(mySub.id)">Try again</button> or upload a different file.
              <div v-if="mySub.error" class="mt-1 text-xs opacity-80">{{ mySub.error }}</div>
            </div>
            <div v-if="mySub?.status === 'off_topic'" class="error-box space-y-1">
              <p class="font-medium">Your PDF doesn't seem to answer this assignment's questions, so the viva hasn't opened.</p>
              <p v-if="mySub.relevance_note" class="text-sm">{{ mySub.relevance_note }}</p>
              <p class="text-sm">Upload the right file below. If you think this is a mistake, ask your instructor. They can let it through.</p>
            </div>
            <div v-if="mySub?.status === 'ready' && mySub.pages_pending" class="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-indigo-200 bg-indigo-50/60 p-4">
              <div class="max-w-md">
                <div class="font-semibold text-slate-900">Check your answer pages</div>
                <p class="mt-1 text-sm text-slate-600">We matched your PDF pages to each question. Look them over, fix anything wrong, then confirm.</p>
              </div>
              <RouterLink :to="`/submissions/${mySub.id}/pages`" class="btn-primary"><Icon name="file" />Select pages</RouterLink>
            </div>
            <div v-if="(mySub?.status === 'ready' && !mySub.pages_pending) || mySub?.status === 'viva_in_progress'" class="flex flex-wrap items-center justify-between gap-4 rounded-xl bg-linear-to-br from-indigo-600 to-violet-600 p-5 text-white">
              <div class="max-w-md">
                <div class="font-semibold">{{ mySub.status === 'ready' ? 'Your viva is ready' : 'Pick up where you left off' }}</div>
                <p class="mt-1 text-sm text-indigo-100">A few short spoken questions about your own work. Find a quiet spot — it takes about 5–10 minutes.</p>
              </div>
              <RouterLink :to="`/submissions/${mySub.id}/viva`" class="btn bg-white text-indigo-700 shadow-sm hover:bg-indigo-50">
                <Icon name="mic" />{{ mySub.status === 'ready' ? 'Start viva' : 'Continue viva' }}
              </RouterLink>
            </div>
            <RouterLink v-if="mySub?.status === 'ready' && mySub.page_map && !mySub.pages_pending" :to="`/submissions/${mySub.id}/pages`" class="btn-ghost btn-sm"><Icon name="file" :size="14" />Reselect answer pages</RouterLink>
            <div v-if="(mySub?.status === 'scoring' || mySub?.status === 'completed') && !results" class="flex items-center gap-3 rounded-xl bg-emerald-50 p-4 text-sm text-emerald-900">
              <Icon name="check-circle" :size="18" class="text-emerald-600" />
              Viva complete — thanks! You’ll see your grade here once your instructor publishes it.
            </div>
            <div v-if="mySub?.status === 'scoring_failed'" class="error-box">
              Viva complete, but scoring hit an error. <button class="font-medium underline" @click="retry(mySub.id)">Retry scoring</button>
            </div>

            <p v-if="!a.accepting_submissions && !mySub" class="flex items-center gap-2 text-sm text-slate-500"><Icon name="lock" />Submissions are closed.</p>

            <!-- Upload -->
            <form v-if="canUpload" class="space-y-3" @submit.prevent="upload">
              <div v-if="state === 'late'" class="flex items-center gap-2 rounded-xl bg-orange-50 px-3.5 py-2.5 text-sm text-orange-800">
                <Icon name="clock" />The due date has passed — submissions now are marked <b>late</b>.
              </div>
              <label
                class="flex cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed px-6 py-8 text-center transition"
                :class="dragging ? 'border-indigo-400 bg-indigo-50' : file ? 'border-emerald-300 bg-emerald-50/50' : 'border-slate-200 hover:border-indigo-300 hover:bg-slate-50'"
                @dragover.prevent="dragging = true"
                @dragleave.prevent="dragging = false"
                @drop.prevent="onDrop"
              >
                <input type="file" accept="application/pdf" class="sr-only" @change="pick($event.target.files[0])" />
                <span class="grid size-11 place-items-center rounded-full" :class="file ? 'bg-emerald-100 text-emerald-600' : 'bg-slate-100 text-slate-500'">
                  <Icon :name="file ? 'check' : 'upload'" :size="20" />
                </span>
                <template v-if="file">
                  <span class="mt-3 text-sm font-medium text-slate-800">{{ file.name }}</span>
                  <span class="text-xs text-slate-500">{{ (file.size / 1024 / 1024).toFixed(2) }} MB · click to change</span>
                </template>
                <template v-else>
                  <span class="mt-3 text-sm font-medium text-slate-800"><span class="text-indigo-600">Click to upload</span> or drag and drop</span>
                  <span class="text-xs text-slate-500">PDF up to 20 MB</span>
                </template>
              </label>
              <div class="flex justify-end">
                <button class="btn-primary" :disabled="!file || uploading">
                  <span v-if="uploading" class="size-4 animate-spin rounded-full border-2 border-white/40 border-t-white"></span>
                  {{ uploading ? 'Uploading…' : mySub ? 'Replace PDF' : 'Submit PDF' }}
                </button>
              </div>
            </form>
          </section>

          <!-- Results -->
          <section v-if="results" class="card space-y-6">
            <div class="flex flex-wrap items-center gap-6">
              <ScoreRing :value="results.overall ?? results.viva" :size="104" :label="results.overall != null ? 'Final' : 'Viva'" />
              <div class="min-w-0 flex-1">
                <h2 class="font-semibold">Your results</h2>
                <p class="mt-1 text-sm leading-relaxed text-slate-600">{{ results.summary }}</p>
              </div>
            </div>
            <div class="grid gap-3 sm:grid-cols-2">
              <div class="rounded-xl border border-slate-200 p-4">
                <div class="text-xs font-medium text-slate-500">Written solution · {{ pct(1 - results.viva_weight) }} of grade</div>
                <div v-if="results.grader_points != null" class="mt-1 flex flex-wrap items-baseline justify-between gap-2">
                  <span class="text-xl font-semibold">{{ fmtPts(results.grader_points) }}<span class="text-sm font-normal text-slate-400"> / {{ fmtPts(results.max_points) }}</span></span>
                  <RouterLink v-if="results.question_grades" :to="`/submissions/${mySub.id}/grade`" class="text-sm font-medium text-indigo-600 hover:text-indigo-500">Marks per question →</RouterLink>
                </div>
                <div v-else class="mt-1 text-sm text-slate-500">Not graded yet</div>
                <p v-if="results.grader_note" class="mt-2 text-sm whitespace-pre-line text-slate-700">{{ results.grader_note }}</p>
              </div>
              <div class="rounded-xl border border-slate-200 p-4">
                <div class="text-xs font-medium text-slate-500">Viva (understanding) · {{ pct(results.viva_weight) }} of grade</div>
                <div class="mt-1 text-xl font-semibold">{{ Math.round(results.viva) }}%</div>
              </div>
            </div>
            <div class="divide-y divide-slate-100 rounded-xl border border-slate-200">
              <div v-for="(d, i) in results.dimensions" :key="d.dimension" class="p-4">
                <div class="flex flex-wrap items-center justify-between gap-3">
                  <div class="flex items-center gap-2">
                    <h3 class="font-medium">{{ d.dimension }}</h3>
                    <span v-if="d.adjusted" class="rounded-full bg-indigo-50 px-2 py-0.5 text-[11px] font-medium text-indigo-700">Adjusted by instructor</span>
                  </div>
                  <div class="flex items-center gap-3">
                    <div class="flex gap-1" :aria-label="`${d.score} out of ${d.max}`">
                      <span v-for="n in d.max" :key="n" class="h-2 w-5 rounded-full" :class="n <= d.score ? 'bg-indigo-500' : 'bg-slate-200'"></span>
                    </div>
                    <span class="w-8 text-right font-mono text-sm font-semibold">{{ d.score }}/{{ d.max }}</span>
                  </div>
                </div>
                <p v-if="d.rationale" class="mt-2 text-sm text-slate-600">{{ d.rationale }}</p>
                <blockquote v-if="d.evidence_quote" class="mt-2 border-l-2 border-indigo-200 pl-3 text-sm text-slate-500 italic">“{{ d.evidence_quote }}”</blockquote>
                <p v-if="d.instructor_note" class="mt-2 rounded-lg bg-slate-50 px-3 py-2 text-sm text-slate-700"><b>Instructor:</b> {{ d.instructor_note }}</p>

                <div class="mt-3">
                  <span v-if="requestFor(i)" class="inline-flex items-center gap-1.5 text-xs font-medium text-orange-700">
                    <Icon name="regrade" :size="13" />Regrade requested {{ relative(requestFor(i).created_at) }}
                  </span>
                  <template v-else>
                    <div v-if="lastResolvedFor(i)" class="mb-2 rounded-lg bg-emerald-50 px-3 py-2 text-xs text-emerald-800">
                      <b>Regrade resolved</b> by {{ lastResolvedFor(i).resolved_by }}<template v-if="lastResolvedFor(i).response">: {{ lastResolvedFor(i).response }}</template>
                    </div>
                    <button class="btn-ghost btn-sm -ml-2" @click="openRegrade(i)"><Icon name="flag" :size="13" />Request regrade</button>
                  </template>
                </div>
              </div>
            </div>
            <RouterLink :to="`/courses/${a.course.id}/regrades`" class="inline-flex items-center gap-1 text-sm text-indigo-600 hover:text-indigo-500">
              View all your regrade requests<Icon name="arrow-right" :size="14" />
            </RouterLink>
          </section>
        </template>

        <!-- ===== Instructor ===== -->
        <template v-else>
          <div class="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <div class="card p-4">
              <div class="text-xs font-medium text-slate-500">Submitted</div>
              <div class="mt-1 text-2xl font-semibold tracking-tight">{{ stats.submitted }}<span class="text-base font-normal text-slate-400"> / {{ stats.total }}</span></div>
              <div class="mt-2 h-1 overflow-hidden rounded-full bg-slate-100"><div class="h-full rounded-full bg-indigo-500" :style="{ width: (stats.total ? (stats.submitted / stats.total) * 100 : 0) + '%' }"></div></div>
            </div>
            <div class="card p-4">
              <div class="text-xs font-medium text-slate-500">Vivas completed</div>
              <div class="mt-1 text-2xl font-semibold tracking-tight">{{ stats.completed }}</div>
              <div v-if="stats.late" class="mt-1 text-xs text-orange-600">{{ stats.late }} late</div>
            </div>
            <div class="card p-4">
              <div class="text-xs font-medium text-slate-500">Needs review</div>
              <div class="mt-1 text-2xl font-semibold tracking-tight" :class="stats.review && 'text-orange-600'">{{ stats.review }}</div>
              <div v-if="stats.regrades" class="mt-1 text-xs text-orange-600">{{ stats.regrades }} open regrade{{ stats.regrades === 1 ? '' : 's' }}</div>
            </div>
            <div class="card p-4">
              <div class="text-xs font-medium text-slate-500">Average final grade</div>
              <div class="mt-1 text-2xl font-semibold tracking-tight">{{ stats.avgFinal != null ? stats.avgFinal + '%' : '—' }}</div>
              <div class="mt-1 text-xs text-slate-500">Viva avg {{ stats.avg != null ? stats.avg + '%' : '—' }}<span v-if="stats.ungraded" class="text-orange-600"> · {{ stats.ungraded }} not graded</span></div>
            </div>
          </div>

          <section>
            <div class="mb-3 flex flex-wrap items-center gap-3">
              <h2 class="mr-auto font-semibold">Students</h2>
              <div class="relative w-full sm:w-56">
                <Icon name="search" class="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-slate-400" />
                <input v-model="q" class="input py-1.5 pl-9" placeholder="Search" aria-label="Search students" />
              </div>
            </div>
            <div class="mb-3 flex flex-wrap gap-1.5">
              <button
                v-for="[k, label] in FILTERS"
                :key="k"
                class="inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium ring-1 transition ring-inset"
                :class="filter === k ? 'bg-slate-900 text-white ring-slate-900' : 'bg-white text-slate-600 ring-slate-200 hover:ring-slate-300'"
                @click="filter = k"
              >
                {{ label }}<span class="opacity-60">{{ filterCount(k) }}</span>
              </button>
            </div>

            <div class="overflow-hidden rounded-2xl border border-slate-200/80 bg-white shadow-xs">
              <table class="w-full text-sm">
                <thead class="border-b border-slate-100 bg-slate-50/60">
                  <tr>
                    <th class="th">Student</th>
                    <th class="th hidden md:table-cell">Submitted</th>
                    <th class="th">Status</th>
                    <th class="th hidden text-right sm:table-cell">Viva</th>
                    <th class="th text-right">Final</th>
                  </tr>
                </thead>
                <tbody class="divide-y divide-slate-100">
                  <tr
                    v-for="p in shown"
                    :key="p.key"
                    class="transition"
                    :class="p.missing ? 'text-slate-500' : 'group cursor-pointer hover:bg-slate-50/80'"
                    @click="!p.missing && router.push(`/submissions/${p.id}/report`)"
                  >
                    <td class="td">
                      <div class="flex items-center gap-3">
                        <span class="grid size-8 shrink-0 place-items-center rounded-full text-xs font-semibold" :class="p.missing ? 'bg-slate-50 text-slate-400' : 'bg-slate-100 text-slate-600'">{{ initials(p.student?.name) }}</span>
                        <div class="min-w-0">
                          <div class="truncate font-medium" :class="!p.missing && 'text-slate-900 group-hover:text-indigo-700'">{{ p.student?.name }}</div>
                          <div class="truncate text-xs text-slate-500">{{ p.student?.email }}</div>
                        </div>
                      </div>
                    </td>
                    <td class="td hidden text-slate-500 md:table-cell">
                      <span v-if="p.created_at" :title="fmtDate(p.created_at)">{{ relative(p.created_at) }}</span>
                      <span v-else>—</span>
                    </td>
                    <td class="td">
                      <StatusBadge :status="p.status" :needs-review="p.needs_review && p.status === 'completed'" :late="p.late" />
                      <span v-if="p.open_regrades" class="ml-1 inline-flex items-center gap-1 rounded-full bg-orange-50 px-2 py-0.5 text-xs font-medium text-orange-700 ring-1 ring-orange-200 ring-inset">
                        <Icon name="regrade" :size="11" />{{ p.open_regrades }}
                      </span>
                    </td>
                    <td class="td hidden text-right font-mono text-slate-600 sm:table-cell">
                      <span v-if="p.overall != null">{{ Math.round(p.overall) }}%</span>
                      <span v-else class="text-slate-300">—</span>
                    </td>
                    <td class="td text-right">
                      <span v-if="p.final != null" class="inline-flex rounded-lg px-2 py-0.5 font-mono text-sm font-semibold" :class="scoreTone(p.final)">{{ Math.round(p.final) }}%</span>
                      <RouterLink
                        v-else-if="!p.missing && !['analyzing', 'analysis_failed'].includes(p.status)"
                        :to="`/submissions/${p.id}/grade`"
                        class="inline-flex items-center gap-1 rounded-lg px-2 py-0.5 text-xs font-medium text-indigo-700 ring-1 ring-indigo-200 ring-inset hover:bg-indigo-50"
                        @click.stop
                      ><Icon name="pencil" :size="11" />{{ p.questions_graded ? `${p.questions_graded}/${a.parts.length} graded` : 'Grade' }}</RouterLink>
                      <span v-else class="text-slate-300">—</span>
                    </td>
                  </tr>
                  <tr v-if="!shown.length">
                    <td colspan="5" class="px-4 py-10 text-center text-sm text-slate-500">{{ people.length ? 'No students match.' : 'No students in this class yet.' }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>

          <ClassInsights :assignment-id="id" />
        </template>
      </div>

      <!-- Side column -->
      <aside class="space-y-4">
        <section class="card">
          <h2 class="eyebrow mb-4">Schedule <span class="font-normal normal-case">· {{ tzAbbr }}</span></h2>
          <ol class="relative space-y-4 border-l border-slate-200 pl-5">
            <li class="relative">
              <span class="absolute top-1 -left-[25px] size-2.5 rounded-full ring-4 ring-white" :class="state !== 'scheduled' ? 'bg-indigo-500' : 'bg-slate-300'"></span>
              <div class="text-xs text-slate-500">Released</div>
              <div class="text-sm font-medium">{{ a.release_date ? fmtDate(a.release_date) : 'Immediately' }}</div>
            </li>
            <li class="relative">
              <span class="absolute top-1 -left-[25px] size-2.5 rounded-full ring-4 ring-white" :class="['late', 'closed'].includes(state) ? 'bg-indigo-500' : 'bg-slate-300'"></span>
              <div class="text-xs text-slate-500">Due</div>
              <div class="text-sm font-medium">{{ a.due_date ? fmtDate(a.due_date) : 'No due date' }}</div>
            </li>
            <li v-if="a.late_due_date" class="relative">
              <span class="absolute top-1 -left-[25px] size-2.5 rounded-full ring-4 ring-white" :class="state === 'closed' ? 'bg-orange-500' : 'bg-slate-300'"></span>
              <div class="text-xs text-slate-500">Late due</div>
              <div class="text-sm font-medium">{{ fmtDate(a.late_due_date) }}</div>
            </li>
          </ol>
        </section>

        <section class="card">
          <h2 class="eyebrow mb-3">Rubric</h2>
          <ul class="space-y-3">
            <li v-for="(r, i) in a.rubric" :key="r.name" class="flex gap-3">
              <span class="grid size-6 shrink-0 place-items-center rounded-md bg-slate-100 text-xs font-semibold text-slate-500">{{ i + 1 }}</span>
              <div>
                <div class="text-sm font-medium">{{ r.name }}</div>
                <div class="text-xs leading-relaxed text-slate-500">{{ r.description }}</div>
              </div>
            </li>
          </ul>
          <p class="mt-4 border-t border-slate-100 pt-3 text-xs text-slate-400">Each dimension is scored 0–5 in the viva. 0 means no understanding shown.</p>
        </section>

        <section class="card">
          <h2 class="eyebrow mb-3">Grading</h2>
          <div class="flex h-2 overflow-hidden rounded-full">
            <div class="bg-slate-400" :style="{ width: pct(1 - a.viva_weight) }"></div>
            <div class="bg-indigo-500" :style="{ width: pct(a.viva_weight) }"></div>
          </div>
          <ul class="mt-3 space-y-1.5 text-sm">
            <li class="flex justify-between gap-2"><span class="flex items-center gap-2"><span class="size-2 rounded-full bg-slate-400"></span>Written solution (grader, out of {{ fmtPts(a.max_points) }})</span><b>{{ pct(1 - a.viva_weight) }}</b></li>
            <li class="flex justify-between gap-2"><span class="flex items-center gap-2"><span class="size-2 rounded-full bg-indigo-500"></span>Viva (AI, reviewed)</span><b>{{ pct(a.viva_weight) }}</b></li>
          </ul>
          <p v-if="isInstructor" class="mt-3 border-t border-slate-100 pt-3 text-xs text-slate-400">Change the weighting under Edit.</p>
        </section>

        <section v-if="a.has_brief" class="card">
          <h2 class="eyebrow mb-3">Assignment handout</h2>
          <button class="btn-secondary btn-sm w-full" @click="openBrief"><Icon name="file" :size="14" />{{ a.brief_filename || 'Assignment PDF' }}<Icon name="external" :size="12" class="text-slate-400" /></button>
        </section>
      </aside>
    </div>

    <AssignmentFormModal v-if="isInstructor" :open="editOpen" :assignment="a" @close="editOpen = false" @saved="onEdited" />

    <Modal
      :open="regrade.open"
      title="Request a regrade"
      :description="regrade.index != null && results ? `${results.dimensions[regrade.index].dimension} · currently ${results.dimensions[regrade.index].score}/${results.dimensions[regrade.index].max}` : ''"
      @close="regrade.open = false"
    >
      <form id="regrade-form" @submit.prevent="sendRegrade">
        <label class="label" for="rg-msg">Why should this be looked at again?</label>
        <textarea id="rg-msg" v-model="regrade.message" class="input" rows="5" maxlength="2000" placeholder="Point to the part of your answer you think was missed." required></textarea>
        <p class="hint">Your instructor will see this message alongside your transcript.</p>
      </form>
      <template #footer>
        <button type="button" class="btn-secondary" @click="regrade.open = false">Cancel</button>
        <button form="regrade-form" class="btn-primary" :disabled="!regrade.message.trim() || regrade.busy"><Icon name="send" />Send request</button>
      </template>
    </Modal>
  </div>
</template>
