<script setup>
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { auth } from '../lib/auth'
import { dueState, fmtDate, now, scoreTone, tzAbbr, tzName } from '../lib/format'
import { toast } from '../lib/toast'
import AssignmentFormModal from '../components/AssignmentFormModal.vue'
import DueCell from '../components/DueCell.vue'
import Icon from '../components/Icon.vue'
import StatusBadge from '../components/StatusBadge.vue'

const props = defineProps({ course: { type: Object, required: true } })
const emit = defineEmits(['changed'])
const router = useRouter()
const isInstructor = auth.user?.role === 'instructor'

const q = ref('')
const filter = ref('all')
const sortKey = ref('due')
const sortDir = ref(-1) // newest due date first, like a course timeline
const formOpen = ref(false)

const FILTERS = isInstructor
  ? [['all', 'All'], ['active', 'Open'], ['scheduled', 'Scheduled'], ['closed', 'Closed']]
  : [['all', 'All'], ['todo', 'To do'], ['done', 'Done']]

const STATUS_RANK = { null: 0, off_topic: 1, analysis_failed: 1, analyzing: 2, ready: 3, viva_in_progress: 4, scoring_failed: 5, scoring: 6, completed: 7 }
const DONE = ['scoring', 'scoring_failed', 'completed']

function statusRank(a) {
  if (isInstructor) return a.submitted_count
  return a.my_score != null ? 100 + a.my_score : STATUS_RANK[a.my_status ?? 'null']
}
const ts = (d) => (d ? new Date(d).getTime() : null)

const rows = computed(() => {
  const term = q.value.trim().toLowerCase()
  let list = props.course.assignments.filter((a) => !term || a.title.toLowerCase().includes(term))
  list = list.filter((a) => {
    const s = dueState(a, now.value)
    switch (filter.value) {
      case 'active': return ['open', 'soon', 'late', 'none'].includes(s)
      case 'scheduled': return s === 'scheduled'
      case 'closed': return s === 'closed'
      case 'todo': return !DONE.includes(a.my_status) && s !== 'closed'
      case 'done': return DONE.includes(a.my_status)
      default: return true
    }
  })
  const key = {
    name: (a) => a.title.toLowerCase(),
    status: statusRank,
    released: (a) => ts(a.release_date),
    due: (a) => ts(a.due_date),
  }[sortKey.value]
  return [...list].sort((x, y) => {
    const a = key(x)
    const b = key(y)
    if (a == null && b == null) return 0
    if (a == null) return 1 // empty values always last
    if (b == null) return -1
    return (a < b ? -1 : a > b ? 1 : 0) * sortDir.value
  })
})

function sortBy(k) {
  if (sortKey.value === k) sortDir.value *= -1
  else {
    sortKey.value = k
    sortDir.value = k === 'name' ? 1 : -1
  }
}
const sortIcon = (k) => (sortKey.value !== k ? 'sort' : sortDir.value === 1 ? 'arrow-up' : 'arrow-down')

const COLUMNS = [
  ['name', 'Name', ''],
  ['status', 'Status', 'hidden sm:table-cell'],
  ['released', 'Released', 'hidden lg:table-cell'],
]

function open(a) {
  router.push(`/assignments/${a.id}`)
}

function onSaved(a) {
  formOpen.value = false
  emit('changed')
  toast(`Created “${a.title}”`)
  router.push(`/assignments/${a.id}`)
}
</script>

<template>
  <div>
    <!-- Toolbar -->
    <div class="mb-4 flex flex-wrap items-center gap-3">
      <div class="relative min-w-0 flex-1 sm:max-w-xs">
        <Icon name="search" class="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-slate-400" />
        <input v-model="q" class="input pl-9" placeholder="Search assignments" aria-label="Search assignments" />
      </div>
      <div class="flex rounded-lg bg-slate-100 p-0.5">
        <button
          v-for="[k, label] in FILTERS"
          :key="k"
          class="rounded-md px-3 py-1.5 text-xs font-medium transition"
          :class="filter === k ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-800'"
          @click="filter = k"
        >
          {{ label }}
        </button>
      </div>
      <button v-if="isInstructor" class="btn-primary ml-auto" @click="formOpen = true"><Icon name="plus" />New assignment</button>
    </div>

    <!-- Empty -->
    <div v-if="!course.assignments.length" class="rounded-2xl border border-dashed border-slate-300 bg-white px-6 py-14 text-center">
      <div class="mx-auto grid size-11 place-items-center rounded-xl bg-slate-100 text-slate-500"><Icon name="file" :size="20" /></div>
      <p class="mt-3 font-medium">No assignments yet</p>
      <p class="mt-1 text-sm text-slate-500">{{ isInstructor ? 'Create one to start collecting submissions.' : 'Your instructor hasn’t released any assignments.' }}</p>
      <button v-if="isInstructor" class="btn-primary mt-4" @click="formOpen = true"><Icon name="plus" />New assignment</button>
    </div>

    <div v-else class="overflow-hidden rounded-2xl border border-slate-200/80 bg-white shadow-xs">
      <table class="w-full text-sm">
        <thead class="border-b border-slate-100 bg-slate-50/60">
          <tr>
            <th v-for="[k, label, cls] in COLUMNS" :key="k" class="th" :class="cls">
              <button class="group inline-flex items-center gap-1 uppercase hover:text-slate-800" @click="sortBy(k)">
                {{ label }}
                <Icon :name="sortIcon(k)" :size="12" :class="sortKey === k ? 'text-indigo-600' : 'opacity-0 group-hover:opacity-60'" />
              </button>
            </th>
            <th class="th">
              <button class="group inline-flex items-center gap-1 uppercase hover:text-slate-800" @click="sortBy('due')">
                Due <abbr class="cursor-help font-normal no-underline" :title="tzName">({{ tzAbbr }})</abbr>
                <Icon :name="sortIcon('due')" :size="12" :class="sortKey === 'due' ? 'text-indigo-600' : 'opacity-0 group-hover:opacity-60'" />
              </button>
            </th>
          </tr>
        </thead>
        <tbody class="divide-y divide-slate-100">
          <tr v-for="a in rows" :key="a.id" class="group cursor-pointer transition hover:bg-slate-50/80" @click="open(a)">
            <td class="td">
              <RouterLink :to="`/assignments/${a.id}`" class="font-medium text-slate-900 group-hover:text-indigo-700" @click.stop>{{ a.title }}</RouterLink>
              <div class="mt-1 flex flex-wrap items-center gap-1.5">
                <span v-if="isInstructor && !a.released" class="inline-flex items-center gap-1 rounded-full bg-violet-50 px-2 py-0.5 text-[11px] font-medium text-violet-700 ring-1 ring-violet-200 ring-inset">
                  <Icon name="eye-off" :size="11" />Hidden until {{ fmtDate(a.release_date) }}
                </span>
                <span v-if="a.grades_published && isInstructor" class="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-medium text-emerald-700 ring-1 ring-emerald-200 ring-inset">
                  <Icon name="check" :size="11" />Grades published
                </span>
                <span v-if="a.open_regrades" class="inline-flex items-center gap-1 rounded-full bg-orange-50 px-2 py-0.5 text-[11px] font-medium text-orange-700 ring-1 ring-orange-200 ring-inset">
                  <Icon name="regrade" :size="11" />{{ a.open_regrades }} regrade{{ a.open_regrades === 1 ? '' : 's' }}
                </span>
                <!-- Status inline on phones -->
                <span class="sm:hidden">
                  <StatusBadge v-if="!isInstructor && a.my_score == null" :status="a.my_status" :late="a.my_late" />
                </span>
              </div>
            </td>
            <td class="td hidden sm:table-cell">
              <template v-if="isInstructor">
                <div class="text-sm font-medium text-slate-800">{{ a.submitted_count }} <span class="font-normal text-slate-400">/ {{ course.student_count }} submitted</span></div>
                <div class="mt-1.5 h-1 w-28 overflow-hidden rounded-full bg-slate-100">
                  <div class="h-full rounded-full bg-indigo-500" :style="{ width: (course.student_count ? (a.submitted_count / course.student_count) * 100 : 0) + '%' }"></div>
                </div>
                <div v-if="a.needs_review_count" class="mt-1 text-xs font-medium text-orange-600">{{ a.needs_review_count }} need review</div>
              </template>
              <template v-else>
                <span v-if="a.my_score != null" class="inline-flex items-center rounded-lg px-2 py-1 font-mono text-sm font-semibold" :class="scoreTone(a.my_score)">
                  {{ Math.round(a.my_score) }}<span class="text-xs opacity-60">&nbsp;/ 100</span>
                </span>
                <StatusBadge v-else :status="a.my_status" :late="a.my_late" />
              </template>
            </td>
            <td class="td hidden text-slate-600 lg:table-cell">{{ a.release_date ? fmtDate(a.release_date) : '—' }}</td>
            <td class="td"><DueCell :a="a" /></td>
          </tr>
          <tr v-if="!rows.length">
            <td colspan="4" class="px-4 py-10 text-center text-sm text-slate-500">No assignments match.</td>
          </tr>
        </tbody>
      </table>
    </div>

    <AssignmentFormModal v-if="isInstructor" :open="formOpen" :course-id="course.id" @close="formOpen = false" @saved="onSaved" />
  </div>
</template>
