<script setup>
import { computed, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../lib/api'
import { setAuth } from '../lib/auth'
import Icon from '../components/Icon.vue'
import LogoMark from '../components/LogoMark.vue'

const props = defineProps({ mode: { type: String, default: 'login' } })
const router = useRouter()
const route = useRoute()
const isRegister = computed(() => props.mode === 'register')
// An invite link (/join/CODE) means a student is signing up.
const fromInvite = computed(() => String(route.query.redirect || '').startsWith('/join/'))

const form = reactive({ name: '', email: '', password: '', role: 'student' })
const error = ref('')
const busy = ref(false)
const showPw = ref(false)

async function submit() {
  error.value = ''
  busy.value = true
  try {
    const data = isRegister.value
      ? await api('/api/auth/register', { method: 'POST', body: form })
      : await api('/api/auth/login', { method: 'POST', body: { email: form.email, password: form.password } })
    setAuth(data)
    const redirect = String(route.query.redirect || '')
    router.push(redirect.startsWith('/') && !redirect.startsWith('//') ? redirect : '/')
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = false
  }
}

const FEATURES = [
  ['sparkles', 'Questions written from each student’s own submission'],
  ['mic', 'Short spoken vivas with transcripts and audio'],
  ['chart', 'Rubric scores with quoted evidence you can override'],
]
</script>

<template>
  <div class="grid min-h-screen lg:grid-cols-[1.1fr_1fr]">
    <!-- Brand panel -->
    <section class="relative hidden overflow-hidden bg-slate-950 p-12 text-white lg:flex lg:flex-col lg:justify-between">
      <div class="pointer-events-none absolute -top-40 -left-40 size-[36rem] rounded-full bg-indigo-600/30 blur-3xl"></div>
      <div class="pointer-events-none absolute -right-32 -bottom-48 size-[32rem] rounded-full bg-violet-600/25 blur-3xl"></div>
      <div class="relative flex items-center gap-2.5">
        <span class="grid size-9 place-items-center rounded-xl bg-linear-to-br from-indigo-400 to-violet-500"><LogoMark class="size-7" /></span>
        <span class="text-lg font-semibold tracking-tight">Fund your answers</span>
      </div>
      <div class="relative max-w-md">
        <h1 class="text-4xl leading-tight font-semibold tracking-tight">Check that students understand the work they hand in.</h1>
        <ul class="mt-8 space-y-4">
          <li v-for="[icon, text] in FEATURES" :key="text" class="flex items-center gap-3 text-slate-300">
            <span class="grid size-9 place-items-center rounded-lg bg-white/10 ring-1 ring-white/10"><Icon :name="icon" class="text-indigo-300" /></span>
            {{ text }}
          </li>
        </ul>
      </div>
      <p class="relative text-xs text-slate-500">Not an AI detector — an understanding check your instructor reviews.</p>
    </section>

    <!-- Form -->
    <section class="flex items-center justify-center px-5 py-12">
      <div class="w-full max-w-sm animate-fade-up">
        <div class="mb-8 flex items-center gap-2 lg:hidden">
          <span class="grid size-8 place-items-center rounded-lg bg-linear-to-br from-indigo-500 to-violet-600"><LogoMark class="size-6" /></span>
          <span class="font-semibold tracking-tight">Fund your answers</span>
        </div>
        <h2 class="text-2xl font-semibold tracking-tight">{{ isRegister ? 'Create your account' : 'Welcome back' }}</h2>
        <p class="mt-1 text-sm text-slate-500">
          {{ fromInvite ? 'Sign in or create an account to join the class.' : isRegister ? 'It takes less than a minute.' : 'Sign in to continue to Fund your answers.' }}
        </p>

        <form class="mt-8 space-y-4" @submit.prevent="submit">
          <div v-if="isRegister">
            <span class="label">I am a…</span>
            <div class="grid grid-cols-2 gap-1 rounded-xl bg-slate-100 p-1">
              <button
                v-for="r in ['student', 'instructor']"
                :key="r"
                type="button"
                class="flex items-center justify-center gap-2 rounded-lg py-2 text-sm font-medium capitalize transition"
                :class="form.role === r ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-700'"
                @click="form.role = r"
              >
                <Icon :name="r === 'student' ? 'cap' : 'book'" :size="15" />{{ r }}
              </button>
            </div>
          </div>
          <div v-if="isRegister">
            <label class="label" for="name">Full name</label>
            <input id="name" v-model="form.name" class="input" autocomplete="name" required />
          </div>
          <div>
            <label class="label" for="email">Email</label>
            <input id="email" v-model="form.email" type="email" class="input" autocomplete="email" placeholder="you@school.edu" required />
          </div>
          <div>
            <label class="label" for="password">Password</label>
            <div class="relative">
              <input
                id="password"
                v-model="form.password"
                :type="showPw ? 'text' : 'password'"
                class="input pr-10"
                minlength="6"
                :autocomplete="isRegister ? 'new-password' : 'current-password'"
                required
              />
              <button type="button" class="absolute inset-y-0 right-0 grid w-10 place-items-center text-slate-400 hover:text-slate-700" :aria-label="showPw ? 'Hide password' : 'Show password'" @click="showPw = !showPw">
                <Icon :name="showPw ? 'eye-off' : 'eye'" />
              </button>
            </div>
            <p v-if="isRegister" class="hint">At least 6 characters.</p>
          </div>
          <p v-if="error" class="error-box">{{ error }}</p>
          <button class="btn-primary w-full py-2.5" :disabled="busy">
            <span v-if="busy" class="size-4 animate-spin rounded-full border-2 border-white/40 border-t-white"></span>
            {{ isRegister ? 'Create account' : 'Sign in' }}
          </button>
        </form>

        <p class="mt-6 text-center text-sm text-slate-500">
          <template v-if="isRegister">
            Already have an account?
            <RouterLink :to="{ path: '/login', query: route.query }" class="font-medium text-indigo-600 hover:text-indigo-500">Sign in</RouterLink>
          </template>
          <template v-else>
            New here?
            <RouterLink :to="{ path: '/register', query: route.query }" class="font-medium text-indigo-600 hover:text-indigo-500">Create an account</RouterLink>
          </template>
        </p>
      </div>
    </section>
  </div>
</template>
