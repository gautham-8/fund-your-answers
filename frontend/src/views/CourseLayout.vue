<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../lib/api'
import { auth } from '../lib/auth'
import { copyText } from '../lib/clipboard'
import { confirmDialog } from '../lib/confirm'
import { courseColor, courseMonogram, plural } from '../lib/format'
import { loadCourses, setCourse } from '../lib/store'
import { toast } from '../lib/toast'
import CopyChip from '../components/CopyChip.vue'
import CourseFormModal from '../components/CourseFormModal.vue'
import Icon from '../components/Icon.vue'

const props = defineProps({ id: String })
const route = useRoute()
const router = useRouter()
const isInstructor = auth.user?.role === 'instructor'

const course = ref(null)
const error = ref('')
const settingsOpen = ref(false)
const menuOpen = ref(false)

const base = computed(() => `/courses/${props.id}`)
const tabs = computed(() => {
  const c = course.value
  const t = [
    { to: base.value, label: 'Assignments', icon: 'file', count: c?.assignments.length, exact: true },
    { to: `${base.value}/regrades`, label: 'Regrade requests', icon: 'regrade', badge: c?.open_regrades },
  ]
  if (isInstructor) t.push({ to: `${base.value}/roster`, label: 'Roster', icon: 'users', count: c?.students.length })
  return t
})
const isActive = (t) => (t.exact ? route.path === t.to : route.path.startsWith(t.to))
const inviteLink = computed(() => course.value && `${location.origin}/join/${course.value.join_code}`)

async function load() {
  try {
    course.value = await api(`/api/courses/${props.id}`)
    setCourse(course.value)
    error.value = ''
  } catch (e) {
    error.value = e.message
  }
}

async function onSaved() {
  settingsOpen.value = false
  await Promise.all([load(), loadCourses()])
  toast('Class updated')
}

async function unenroll() {
  menuOpen.value = false
  const ok = await confirmDialog({
    title: `Leave ${course.value.code || course.value.name}?`,
    message: 'You will lose access to its assignments. Your past submissions are kept, and you can rejoin with the code.',
    confirmText: 'Unenroll',
    danger: true,
  })
  if (!ok) return
  try {
    await api(`/api/courses/${props.id}/enrollment`, { method: 'DELETE' })
    await loadCourses()
    toast('You left the class')
    router.push('/')
  } catch (e) {
    toast(e.message, { type: 'error' })
  }
}

watch(() => props.id, load)
onMounted(load)
onUnmounted(() => setCourse(null))
</script>

<template>
  <p v-if="error" class="error-box">{{ error }}</p>
  <div v-if="!course && !error" class="space-y-4">
    <div class="skeleton h-5 w-40"></div>
    <div class="skeleton h-16 w-full"></div>
    <div class="skeleton h-64 w-full"></div>
  </div>

  <div v-if="course" class="animate-fade-up">
    <!-- Breadcrumb -->
    <nav class="mb-4 flex items-center gap-1.5 text-sm text-slate-500">
      <RouterLink to="/" class="hover:text-slate-900">Dashboard</RouterLink>
      <Icon name="chevron-right" :size="14" class="text-slate-300" />
      <span class="text-slate-400">{{ course.term }}</span>
    </nav>

    <!-- Header -->
    <header class="flex flex-wrap items-start justify-between gap-5">
      <div class="flex min-w-0 items-start gap-4">
        <span class="grid size-14 shrink-0 place-items-center rounded-2xl bg-linear-to-br font-mono text-lg font-bold text-white shadow-sm" :class="courseColor(course.id).grad">
          {{ courseMonogram(course) }}
        </span>
        <div class="min-w-0">
          <h1 class="text-2xl font-semibold tracking-tight">{{ course.code || course.name }}</h1>
          <p v-if="course.code" class="text-slate-500">{{ course.name }}</p>
          <div class="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-slate-500">
            <span class="inline-flex items-center gap-1.5"><Icon name="calendar" :size="14" />{{ course.term }}</span>
            <span v-if="course.instructor_name" class="inline-flex items-center gap-1.5"><Icon name="user" :size="14" />{{ course.instructor_name }}</span>
            <span class="inline-flex items-center gap-1.5"><Icon name="users" :size="14" />{{ plural(course.student_count, 'student') }}</span>
          </div>
        </div>
      </div>

      <div class="flex items-center gap-2">
        <template v-if="isInstructor">
          <div class="flex items-center gap-2 rounded-xl border border-slate-200 bg-white py-1.5 pr-1.5 pl-3 shadow-xs">
            <span class="text-xs font-medium text-slate-500">Join code</span>
            <CopyChip :value="course.join_code" :message="`Join code ${course.join_code} copied`" />
            <button class="icon-btn size-7" title="Copy invite link" @click="copyText(inviteLink, 'Invite link copied')"><Icon name="link" :size="14" /></button>
          </div>
          <button class="btn-secondary" @click="settingsOpen = true"><Icon name="settings" />Settings</button>
        </template>
        <div v-else class="relative">
          <div v-if="menuOpen" class="fixed inset-0 z-10" @click="menuOpen = false"></div>
          <button class="icon-btn border border-slate-200 bg-white" aria-label="Class actions" @click="menuOpen = !menuOpen"><Icon name="more" /></button>
          <Transition name="pop">
            <div v-if="menuOpen" class="absolute right-0 z-20 mt-2 w-48 rounded-xl border border-slate-200 bg-white p-1.5 shadow-xl">
              <button class="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-sm text-rose-600 hover:bg-rose-50" @click="unenroll">
                <Icon name="door" />Unenroll from class
              </button>
            </div>
          </Transition>
        </div>
      </div>
    </header>

    <!-- Tabs -->
    <div class="mt-6 border-b border-slate-200">
      <nav class="-mb-px flex gap-6 overflow-x-auto">
        <RouterLink
          v-for="t in tabs"
          :key="t.to"
          :to="t.to"
          class="flex items-center gap-2 border-b-2 py-3 text-sm font-medium whitespace-nowrap transition"
          :class="isActive(t) ? 'border-indigo-600 text-indigo-700' : 'border-transparent text-slate-500 hover:border-slate-300 hover:text-slate-800'"
        >
          <Icon :name="t.icon" :size="15" />{{ t.label }}
          <span v-if="t.badge" class="rounded-full bg-orange-100 px-1.5 py-0.5 text-[11px] font-semibold text-orange-700">{{ t.badge }}</span>
          <span v-else-if="t.count != null" class="rounded-full bg-slate-100 px-1.5 py-0.5 text-[11px] font-semibold text-slate-500">{{ t.count }}</span>
        </RouterLink>
      </nav>
    </div>

    <div class="mt-6">
      <RouterView v-slot="{ Component }">
        <component :is="Component" :course="course" @changed="load" />
      </RouterView>
    </div>

    <CourseFormModal v-if="isInstructor" :open="settingsOpen" :course="course" @close="settingsOpen = false" @saved="onSaved" />
  </div>
</template>
