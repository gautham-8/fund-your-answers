<script setup>
import { computed, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../lib/api'
import { setAuth } from '../lib/auth'

const props = defineProps({ mode: { type: String, default: 'login' } })
const router = useRouter()
const isRegister = computed(() => props.mode === 'register')

const form = reactive({ name: '', email: '', password: '', role: 'student' })
const error = ref('')
const busy = ref(false)

async function submit() {
  error.value = ''
  busy.value = true
  try {
    const data = isRegister.value
      ? await api('/api/auth/register', { method: 'POST', body: form })
      : await api('/api/auth/login', { method: 'POST', body: { email: form.email, password: form.password } })
    setAuth(data)
    router.push('/')
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="mx-auto mt-10 max-w-sm">
    <h1 class="mb-1 text-2xl font-bold">{{ isRegister ? 'Create an account' : 'Sign in' }}</h1>
    <p class="mb-6 text-sm text-slate-600">Short voice vivas that check understanding of submitted work.</p>

    <form class="card space-y-4" @submit.prevent="submit">
      <div v-if="isRegister">
        <label class="label">Name</label>
        <input v-model="form.name" class="input" required />
      </div>
      <div>
        <label class="label">Email</label>
        <input v-model="form.email" type="email" class="input" required />
      </div>
      <div>
        <label class="label">Password</label>
        <input v-model="form.password" type="password" class="input" minlength="6" required />
      </div>
      <div v-if="isRegister">
        <label class="label">I am a…</label>
        <div class="flex gap-4 text-sm">
          <label class="flex items-center gap-2"><input v-model="form.role" type="radio" value="student" /> Student</label>
          <label class="flex items-center gap-2"><input v-model="form.role" type="radio" value="instructor" /> Instructor</label>
        </div>
      </div>
      <p v-if="error" class="error-box">{{ error }}</p>
      <button class="btn-primary w-full" :disabled="busy">{{ isRegister ? 'Create account' : 'Sign in' }}</button>
    </form>

    <p class="mt-4 text-center text-sm text-slate-600">
      <template v-if="isRegister">Already have an account? <RouterLink to="/login" class="text-indigo-600 hover:underline">Sign in</RouterLink></template>
      <template v-else>New here? <RouterLink to="/register" class="text-indigo-600 hover:underline">Create an account</RouterLink></template>
    </p>
  </div>
</template>
