<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../lib/api'
import { auth } from '../lib/auth'
import { courseColor, courseMonogram, dueState, fmtDate, greeting, humanize, now, plural, termRank } from '../lib/format'
import { loadCourses, setCourse, store } from '../lib/store'
import { toast } from '../lib/toast'
import CopyChip from '../components/CopyChip.vue'
import CourseFormModal from '../components/CourseFormModal.vue'
import Icon from '../components/Icon.vue'
import Modal from '../components/Modal.vue'
import StatusBadge from '../components/StatusBadge.vue'

const route = useRoute()
const router = useRouter()
const isInstructor = auth.user?.role === 'instructor'
// First name, skipping titles like "Dr." or "Prof."
const firstName = (auth.user?.name || '').split(/\s+/).find((w) => w && !/^(dr|prof|mr|mrs|ms|mx)\.?$/i.test(w)) || ''

const upcoming = ref([])
const error = ref('')
const addOpen = ref(false)
const joinCode = ref('')
const joinError = ref('')
const joining = ref(false)

const today = new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })

/** Classes grouped by term, newest term first (like "Fall 2026"). */
const groups = computed(() => {
  const by = {}
  for (const c of store.courses) (by[c.term] ||= []).push(c)
  return Object.entries(by)
    .sort(([a], [b]) => termRank(b) - termRank(a))
    .map(([term, courses]) => ({ term, courses }))
})

async function load() {
  error.value = ''
  try {
    const [, up] = await Promise.all([loadCourses(), api('/api/upcoming')])
    upcoming.value = up
  } catch (e) {
    error.value = e.message
  }
}

function openAdd() {
  joinCode.value = ''
  joinError.value = ''
  addOpen.value = true
}
function closeAdd() {
  addOpen.value = false
  if (route.query.add) router.replace({ query: {} })
}

async function onCreated(course) {
  closeAdd()
  await loadCourses()
  toast(`Created ${course.code || course.name}`)
  router.push(`/courses/${course.id}`)
}

async function join() {
  joining.value = true
  joinError.value = ''
  try {
    const course = await api('/api/courses/join', { method: 'POST', body: { code: joinCode.value } })
    closeAdd()
    await loadCourses()
    toast(`Joined ${course.code || course.name}`)
    router.push(`/courses/${course.id}`)
  } catch (e) {
    joinError.value = e.message
  } finally {
    joining.value = false
  }
}

function onCodeInput(e) {
  joinCode.value = e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 6)
}

const dueTone = (a) => ({ soon: 'text-amber-600', late: 'text-orange-600' })[dueState(a, now.value)] || 'text-slate-500'
const dueText = (a) => {
  const s = dueState(a, now.value)
  if (s === 'late') return `Late window · ${humanize(new Date(a.late_due_date) - now.value)} left`
  return `Due in ${humanize(new Date(a.due_date) - now.value)}`
}

watch(() => route.query.add, (v) => v && openAdd(), { immediate: true })
onMounted(() => {
  setCourse(null)
  load()
})
</script>

<template>
  <div class="animate-fade-up">
    <!-- Header -->
    <div class="flex flex-wrap items-end justify-between gap-4">
      <div>
        <p class="text-sm text-slate-500">{{ today }}</p>
        <h1 class="mt-1 text-2xl font-semibold tracking-tight sm:text-3xl">{{ greeting() }}{{ firstName ? `, ${firstName}` : '' }}</h1>
      </div>
      <button class="btn-primary" @click="openAdd">
        <Icon name="plus" />{{ isInstructor ? 'New class' : 'Join a class' }}
      </button>
    </div>

    <p v-if="error" class="error-box mt-6">{{ error }}</p>

    <!-- Up next -->
    <section v-if="upcoming.length" class="mt-8">
      <div class="mb-3 flex items-center gap-2">
        <Icon name="clock" class="text-slate-400" />
        <h2 class="text-sm font-semibold text-slate-700">{{ isInstructor ? 'Upcoming deadlines' : 'Up next' }}</h2>
      </div>
      <div class="-mx-4 flex snap-x gap-3 overflow-x-auto px-4 pb-2 sm:mx-0 sm:grid sm:grid-cols-2 sm:overflow-visible sm:px-0 lg:grid-cols-3">
        <RouterLink
          v-for="a in upcoming.slice(0, 6)"
          :key="a.id"
          :to="`/assignments/${a.id}`"
          class="group w-72 shrink-0 snap-start rounded-xl border border-slate-200/80 bg-white p-4 shadow-xs transition hover:-translate-y-0.5 hover:border-slate-300 hover:shadow-md sm:w-auto"
        >
          <div class="flex items-center justify-between gap-2">
            <span class="inline-flex items-center gap-1.5 rounded-md px-1.5 py-0.5 text-[11px] font-semibold ring-1 ring-inset" :class="courseColor(a.course.id).soft">
              {{ a.course.code || a.course.name }}
            </span>
            <StatusBadge v-if="!isInstructor && a.my_status" :status="a.my_status" />
          </div>
          <div class="mt-2.5 line-clamp-1 font-medium text-slate-900 group-hover:text-indigo-700">{{ a.title }}</div>
          <div class="mt-1 flex items-center justify-between text-xs">
            <span :class="dueTone(a)" class="font-medium">{{ dueText(a) }}</span>
            <span class="text-slate-400">{{ fmtDate(a.due_date) }}</span>
          </div>
        </RouterLink>
      </div>
    </section>

    <!-- Loading -->
    <div v-if="!store.loaded" class="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      <div v-for="i in 3" :key="i" class="skeleton h-48 rounded-2xl"></div>
    </div>

    <!-- Empty -->
    <div v-else-if="!store.courses.length" class="mt-10 rounded-2xl border border-dashed border-slate-300 bg-white px-6 py-16 text-center">
      <div class="mx-auto grid size-12 place-items-center rounded-2xl bg-indigo-50 text-indigo-600"><Icon :name="isInstructor ? 'book' : 'cap'" :size="22" /></div>
      <h2 class="mt-4 font-semibold">{{ isInstructor ? 'Create your first class' : 'Join your first class' }}</h2>
      <p class="mx-auto mt-1 max-w-sm text-sm text-slate-500">
        {{ isInstructor ? 'You’ll get a join code and an invite link to share with students.' : 'Ask your instructor for the 6-character join code or invite link.' }}
      </p>
      <button class="btn-primary mt-5" @click="openAdd"><Icon name="plus" />{{ isInstructor ? 'New class' : 'Join a class' }}</button>
    </div>

    <!-- Classes by term -->
    <template v-else>
    <section v-for="g in groups" :key="g.term" class="mt-10">
      <div class="mb-3 flex items-baseline gap-2">
        <h2 class="text-lg font-semibold tracking-tight">{{ g.term }}</h2>
        <span class="text-sm text-slate-400">{{ plural(g.courses.length, 'class', 'classes') }}</span>
      </div>
      <div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <RouterLink
          v-for="c in g.courses"
          :key="c.id"
          :to="`/courses/${c.id}`"
          class="group flex flex-col overflow-hidden rounded-2xl border border-slate-200/80 bg-white shadow-xs transition duration-200 hover:-translate-y-0.5 hover:border-slate-300 hover:shadow-lg hover:shadow-slate-200/70"
        >
          <div class="relative h-20 bg-linear-to-br" :class="courseColor(c.id).grad">
            <div class="absolute inset-0 opacity-25 [background-image:radial-gradient(white_1px,transparent_1px)] [background-size:14px_14px]"></div>
            <span class="absolute bottom-3 left-4 font-mono text-2xl font-bold tracking-tight text-white/90">{{ courseMonogram(c) }}</span>
            <span v-if="c.open_regrades" class="absolute top-3 right-3 inline-flex items-center gap-1 rounded-full bg-white/95 px-2 py-0.5 text-[11px] font-semibold text-orange-700 shadow-sm">
              <Icon name="regrade" :size="11" />{{ c.open_regrades }} regrade{{ c.open_regrades === 1 ? '' : 's' }}
            </span>
          </div>
          <div class="flex flex-1 flex-col p-4">
            <h3 class="font-semibold text-slate-900 group-hover:text-indigo-700">{{ c.code || c.name }}</h3>
            <p v-if="c.code" class="mt-0.5 line-clamp-2 text-sm text-slate-500">{{ c.name }}</p>
            <p v-if="!isInstructor && c.instructor_name" class="mt-2 flex items-center gap-1.5 text-xs text-slate-500">
              <Icon name="user" :size="12" />{{ c.instructor_name }}
            </p>
            <div class="mt-auto flex items-center justify-between gap-2 pt-4 text-xs text-slate-500">
              <div class="flex items-center gap-3">
                <span class="inline-flex items-center gap-1"><Icon name="file" :size="13" />{{ plural(c.assignment_count, 'assignment') }}</span>
                <span v-if="isInstructor" class="inline-flex items-center gap-1"><Icon name="users" :size="13" />{{ c.student_count }}</span>
                <span v-else-if="c.todo_count" class="inline-flex items-center gap-1 font-medium text-indigo-600"><Icon name="clock" :size="13" />{{ c.todo_count }} to do</span>
              </div>
              <CopyChip v-if="c.join_code" :value="c.join_code" :message="`Join code ${c.join_code} copied`" />
            </div>
          </div>
        </RouterLink>

        <button
          type="button"
          class="group flex min-h-44 flex-col items-center justify-center gap-2 rounded-2xl border-2 border-dashed border-slate-200 text-sm font-medium text-slate-500 transition hover:border-indigo-300 hover:bg-indigo-50/40 hover:text-indigo-700"
          @click="openAdd"
        >
          <span class="grid size-10 place-items-center rounded-full bg-slate-100 transition group-hover:bg-white"><Icon name="plus" :size="18" /></span>
          {{ isInstructor ? 'Create a class' : 'Join a class' }}
        </button>
      </div>
    </section>
    </template>

    <!-- Add / join -->
    <CourseFormModal v-if="isInstructor" :open="addOpen" @close="closeAdd" @saved="onCreated" />
    <Modal v-else :open="addOpen" title="Join a class" description="Enter the 6-character code from your instructor." size="sm" @close="closeAdd">
      <form id="join-form" @submit.prevent="join">
        <input
          :value="joinCode"
          class="input py-3 text-center font-mono text-2xl font-semibold tracking-[0.5em] uppercase placeholder:tracking-[0.5em] placeholder:text-slate-300"
          placeholder="K7P2QX"
          inputmode="text"
          autocomplete="off"
          spellcheck="false"
          aria-label="Join code"
          @input="onCodeInput"
        />
        <p v-if="joinError" class="error-box mt-3">{{ joinError }}</p>
      </form>
      <template #footer>
        <button type="button" class="btn-secondary" @click="closeAdd">Cancel</button>
        <button form="join-form" class="btn-primary" :disabled="joinCode.length !== 6 || joining">Join class</button>
      </template>
    </Modal>
  </div>
</template>
