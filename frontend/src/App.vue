<script setup>
import { useRouter } from 'vue-router'
import { auth, logout } from './lib/auth'

const router = useRouter()
function signOut() {
  logout()
  router.push('/login')
}
</script>

<template>
  <header class="border-b border-slate-200 bg-white">
    <div class="mx-auto flex max-w-5xl items-center justify-between px-4 py-3">
      <RouterLink to="/" class="text-lg font-bold text-indigo-700">Viva</RouterLink>
      <div v-if="auth.user" class="flex items-center gap-3 text-sm">
        <span class="text-slate-600">
          {{ auth.user.name }}
          <span class="ml-1 rounded bg-slate-100 px-1.5 py-0.5 text-xs capitalize">{{ auth.user.role }}</span>
        </span>
        <button class="btn-secondary px-3 py-1" @click="signOut">Sign out</button>
      </div>
    </div>
  </header>
  <main class="mx-auto max-w-5xl px-4 py-6">
    <RouterView />
  </main>
</template>
