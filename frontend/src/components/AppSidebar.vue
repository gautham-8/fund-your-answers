<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { auth, logout } from '../lib/auth'
import { courseColor, courseMonogram, initials, termRank } from '../lib/format'
import { resetStore, store } from '../lib/store'
import Icon from './Icon.vue'

const props = defineProps({ collapsed: Boolean, mobileOpen: Boolean })
const emit = defineEmits(['toggle', 'close'])
const route = useRoute()
const router = useRouter()
const isInstructor = computed(() => auth.user?.role === 'instructor')
const menuOpen = ref(false)
const menuRoot = ref(null)

// Classes from the newest term first.
const courses = computed(() => [...store.courses].sort((a, b) => termRank(b.term) - termRank(a.term)))
const activeId = computed(() => store.course?.id)
const mini = computed(() => props.collapsed && !props.mobileOpen)

function courseLinks(c) {
  const base = `/courses/${c.id}`
  const links = [
    { to: base, label: 'Assignments', icon: 'file', exact: true },
    { to: `${base}/regrades`, label: 'Regrade requests', icon: 'regrade', badge: c.open_regrades },
  ]
  if (isInstructor.value) {
    links.push({ to: `${base}/insights`, label: 'Insights', icon: 'chart', badge: null })
    links.push({ to: `${base}/accommodations`, label: 'Accommodations', icon: 'keyboard', badge: c.pending_accommodations })
    links.push({ to: `${base}/students`, label: 'Students', icon: 'users', badge: null })
  }
  return links
}

function isActive(to, exact) {
  return exact ? route.path === to : route.path.startsWith(to)
}

function signOut() {
  menuOpen.value = false
  logout()
  resetStore()
  router.push('/login')
}

function onDocClick(e) {
  if (menuOpen.value && menuRoot.value && !menuRoot.value.contains(e.target)) menuOpen.value = false
}
onMounted(() => document.addEventListener('click', onDocClick))
onUnmounted(() => document.removeEventListener('click', onDocClick))
</script>

<template>
  <!-- Mobile backdrop -->
  <Transition name="modal">
    <div v-if="mobileOpen" class="fixed inset-0 z-40 bg-slate-900/40 backdrop-blur-[2px] lg:hidden" @click="emit('close')"></div>
  </Transition>

  <aside
    class="fixed inset-y-0 left-0 z-50 flex w-72 flex-col border-r border-slate-200/80 bg-white transition-all duration-200 lg:sticky lg:top-0 lg:z-auto lg:h-screen lg:translate-x-0"
    :class="[mobileOpen ? 'translate-x-0 shadow-2xl' : '-translate-x-full', collapsed ? 'lg:w-[72px]' : 'lg:w-64']"
  >
    <!-- Brand -->
    <div class="flex h-16 shrink-0 items-center gap-2 px-4" :class="mini ? 'justify-center' : 'justify-between'">
      <RouterLink to="/" class="flex items-center gap-2.5" @click="emit('close')">
        <span class="grid size-8 place-items-center rounded-lg bg-linear-to-br from-indigo-500 to-violet-600 text-sm font-bold text-white shadow-sm shadow-indigo-500/30">F</span>
        <span v-if="!mini" class="text-[15px] font-semibold tracking-tight">Fund your answers</span>
      </RouterLink>
      <button v-if="!mini" class="icon-btn hidden lg:inline-flex" title="Collapse sidebar" @click="emit('toggle')"><Icon name="panel" /></button>
      <button v-if="mobileOpen" class="icon-btn lg:hidden" aria-label="Close menu" @click="emit('close')"><Icon name="x" /></button>
    </div>
    <button v-if="mini" class="icon-btn mx-auto mb-2 hidden lg:inline-flex" title="Expand sidebar" @click="emit('toggle')"><Icon name="panel" /></button>

    <nav class="flex-1 space-y-6 overflow-y-auto px-3 pb-4" @click="($event.target.closest('a')) && emit('close')">
      <div>
        <RouterLink
          to="/"
          class="flex items-center gap-3 rounded-lg px-2.5 py-2 text-sm font-medium transition"
          :class="[route.path === '/' ? 'bg-indigo-50 text-indigo-700' : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900', mini && 'justify-center']"
          title="Dashboard"
        >
          <Icon name="home" :size="18" />
          <span v-if="!mini">Dashboard</span>
        </RouterLink>
      </div>

      <div>
        <div v-if="!mini" class="mb-1.5 flex items-center justify-between px-2.5">
          <span class="eyebrow">Classes</span>
          <RouterLink :to="{ path: '/', query: { add: '1' } }" class="icon-btn size-6" :title="isInstructor ? 'Create a class' : 'Join a class'">
            <Icon name="plus" :size="14" />
          </RouterLink>
        </div>
        <div v-else class="mx-auto mb-2 h-px w-6 bg-slate-200"></div>

        <div v-if="!store.loaded" class="space-y-2 px-2.5">
          <div v-for="i in 3" :key="i" class="skeleton h-7"></div>
        </div>
        <p v-else-if="!courses.length && !mini" class="px-2.5 text-xs text-slate-400">No classes yet.</p>

        <div v-for="c in courses" :key="c.id" class="mb-0.5">
          <RouterLink
            :to="`/courses/${c.id}`"
            class="group flex items-center gap-2.5 rounded-lg px-2 py-1.5 text-sm transition"
            :class="[activeId === c.id ? 'bg-slate-100 font-medium text-slate-900' : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900', mini && 'justify-center']"
            :title="c.code ? `${c.code} — ${c.name}` : c.name"
          >
            <span class="grid size-7 shrink-0 place-items-center rounded-md bg-linear-to-br text-[10px] font-bold text-white" :class="courseColor(c.id).grad">
              {{ courseMonogram(c) }}
            </span>
            <span v-if="!mini" class="min-w-0 flex-1 truncate">{{ c.code || c.name }}</span>
            <span v-if="!mini && (c.open_regrades || c.pending_accommodations)" class="rounded-full bg-orange-100 px-1.5 text-[10px] font-semibold text-orange-700">{{ (c.open_regrades || 0) + (c.pending_accommodations || 0) }}</span>
          </RouterLink>

          <!-- Sub-navigation for the class being viewed -->
          <div v-if="activeId === c.id && !mini" class="mt-0.5 mb-2 ml-[22px] space-y-0.5 border-l border-slate-200 pl-3">
            <RouterLink
              v-for="l in courseLinks(c)"
              :key="l.to"
              :to="l.to"
              class="flex items-center gap-2 rounded-md px-2 py-1.5 text-[13px] transition"
              :class="isActive(l.to, l.exact) ? 'bg-indigo-50 font-medium text-indigo-700' : 'text-slate-500 hover:bg-slate-50 hover:text-slate-900'"
            >
              <Icon :name="l.icon" :size="14" />
              <span class="flex-1">{{ l.label }}</span>
              <span v-if="l.badge" class="rounded-full bg-orange-100 px-1.5 text-[10px] font-semibold text-orange-700">{{ l.badge }}</span>
            </RouterLink>
          </div>
        </div>
      </div>
    </nav>

    <!-- Account -->
    <div ref="menuRoot" class="relative shrink-0 border-t border-slate-100 p-3">
      <Transition name="pop">
        <div v-if="menuOpen" class="absolute right-3 bottom-full left-3 mb-2 rounded-xl border border-slate-200 bg-white p-1.5 shadow-xl" :class="mini && 'right-auto w-56'">
          <div class="px-2.5 py-2">
            <div class="truncate text-sm font-medium">{{ auth.user?.name }}</div>
            <div class="truncate text-xs text-slate-500">{{ auth.user?.email }}</div>
          </div>
          <div class="my-1 h-px bg-slate-100"></div>
          <button class="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-sm text-slate-700 hover:bg-slate-100" @click="signOut">
            <Icon name="log-out" /> Sign out
          </button>
        </div>
      </Transition>
      <button
        class="flex w-full items-center gap-3 rounded-lg p-1.5 text-left transition hover:bg-slate-100"
        :class="mini && 'justify-center'"
        :aria-expanded="menuOpen"
        @click="menuOpen = !menuOpen"
      >
        <span class="grid size-8 shrink-0 place-items-center rounded-full bg-slate-900 text-xs font-semibold text-white">{{ initials(auth.user?.name) }}</span>
        <span v-if="!mini" class="min-w-0 flex-1">
          <span class="block truncate text-sm font-medium">{{ auth.user?.name }}</span>
          <span class="block text-xs text-slate-500 capitalize">{{ auth.user?.role }}</span>
        </span>
        <Icon v-if="!mini" name="sort" :size="14" class="text-slate-400" />
      </button>
    </div>
  </aside>
</template>
