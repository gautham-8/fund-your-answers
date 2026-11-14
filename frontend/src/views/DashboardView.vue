<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../lib/api'
import { auth } from '../lib/auth'

const courses = ref([])
const loading = ref(true)
const input = ref('')
const error = ref('')
const busy = ref(false)
const isInstructor = auth.user?.role === 'instructor'

async function load() {
  loading.value = true
  try {
    courses.value = await api('/api/courses')
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

async function submit() {
  error.value = ''
  busy.value = true
  try {
    if (isInstructor) await api('/api/courses', { method: 'POST', body: { name: input.value } })
    else await api('/api/courses/join', { method: 'POST', body: { code: input.value } })
    input.value = ''
    await load()
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = false
  }
}

onMounted(load)
</script>

<template>
  <h1 class="mb-6 text-2xl font-bold">Your classes</h1>

  <form class="card mb-6 flex flex-col gap-3 sm:flex-row sm:items-end" @submit.prevent="submit">
    <div class="flex-1">
      <label class="label">{{ isInstructor ? 'New class name' : 'Join a class with a code' }}</label>
      <input
        v-model="input"
        class="input"
        :placeholder="isInstructor ? 'e.g. CS 101: Intro to Algorithms' : 'e.g. K7P2QX'"
        :class="{ 'uppercase tracking-widest': !isInstructor }"
        required
      />
    </div>
    <button class="btn-primary" :disabled="busy">{{ isInstructor ? 'Create class' : 'Join class' }}</button>
  </form>
  <p v-if="error" class="error-box mb-4">{{ error }}</p>

  <p v-if="loading" class="text-slate-500">Loading…</p>
  <p v-else-if="!courses.length" class="text-slate-500">
    {{ isInstructor ? 'No classes yet. Create one above.' : 'You have not joined any classes yet.' }}
  </p>
  <div v-else class="grid gap-4 sm:grid-cols-2">
    <RouterLink v-for="c in courses" :key="c.id" :to="`/courses/${c.id}`" class="card transition hover:border-indigo-300 hover:shadow">
      <h2 class="font-semibold">{{ c.name }}</h2>
      <p class="mt-1 text-sm text-slate-500">
        {{ c.student_count }} student{{ c.student_count === 1 ? '' : 's' }}
        <template v-if="c.join_code"> · Join code <span class="font-mono font-semibold text-slate-700">{{ c.join_code }}</span></template>
      </p>
    </RouterLink>
  </div>
</template>
