<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { auth } from './lib/auth'
import { loadCourses } from './lib/store'
import AppSidebar from './components/AppSidebar.vue'
import ConfirmHost from './components/ConfirmHost.vue'
import Icon from './components/Icon.vue'
import LogoMark from './components/LogoMark.vue'
import Toaster from './components/Toaster.vue'

const route = useRoute()
const shell = computed(() => !route.meta.guest && !!auth.token)

function readCollapsed() {
  try {
    return localStorage.getItem('viva_sidebar') === 'collapsed'
  } catch {
    return false
  }
}
const collapsed = ref(readCollapsed())
const mobileOpen = ref(false)

function toggle() {
  collapsed.value = !collapsed.value
  try {
    localStorage.setItem('viva_sidebar', collapsed.value ? 'collapsed' : 'open')
  } catch {}
}

// Load the class list once signed in (and again after signing in as someone else).
watch(
  () => auth.token,
  (token) => token && loadCourses().catch(() => {}),
  { immediate: true },
)
watch(() => route.fullPath, () => (mobileOpen.value = false))
</script>

<template>
  <div v-if="shell" class="min-h-screen lg:flex">
    <AppSidebar :collapsed="collapsed" :mobile-open="mobileOpen" @toggle="toggle" @close="mobileOpen = false" />
    <div class="min-w-0 flex-1">
      <header class="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-slate-200/80 bg-white/80 px-4 backdrop-blur lg:hidden">
        <button class="icon-btn -ml-1" aria-label="Open menu" @click="mobileOpen = true"><Icon name="menu" :size="18" /></button>
        <RouterLink to="/" class="flex items-center gap-2">
          <span class="grid size-7 place-items-center rounded-lg bg-linear-to-br from-indigo-500 to-violet-600"><LogoMark class="size-5" /></span>
          <span class="font-semibold tracking-tight">Fund your answers</span>
        </RouterLink>
      </header>
      <main :class="route.meta.wide ? 'w-full px-3 py-3 sm:px-4 lg:py-4' : 'mx-auto w-full max-w-6xl px-4 py-6 sm:px-6 lg:px-10 lg:py-10'">
        <RouterView v-slot="{ Component, route: r }">
          <component :is="Component" :key="r.meta.remount ? r.path : undefined" />
        </RouterView>
      </main>
    </div>
  </div>
  <RouterView v-else />

  <Toaster />
  <ConfirmHost />
</template>
