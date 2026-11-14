<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../lib/api'
import { auth } from '../lib/auth'
import { loadCourses } from '../lib/store'
import { toast } from '../lib/toast'
import Icon from '../components/Icon.vue'

// Invite links: /join/K7P2QX joins the class and opens it.
const props = defineProps({ code: String })
const router = useRouter()
const error = ref('')

onMounted(async () => {
  if (auth.user?.role !== 'student') {
    error.value = 'Invite links are for students. Share this link with your class so they can join in one click.'
    return
  }
  try {
    const course = await api('/api/courses/join', { method: 'POST', body: { code: props.code } })
    await loadCourses()
    toast(`Joined ${course.code || course.name}`)
    router.replace(`/courses/${course.id}`)
  } catch (e) {
    error.value = e.message
  }
})
</script>

<template>
  <div class="mx-auto mt-16 max-w-md text-center">
    <template v-if="!error">
      <span class="mx-auto block size-8 animate-spin rounded-full border-2 border-indigo-200 border-t-indigo-600"></span>
      <p class="mt-4 text-sm text-slate-500">Joining class <span class="font-mono font-semibold">{{ code }}</span>…</p>
    </template>
    <div v-else class="card">
      <div class="mx-auto grid size-12 place-items-center rounded-full bg-amber-50 text-amber-600"><Icon name="alert" :size="22" /></div>
      <p class="mt-4 text-sm text-slate-600">{{ error }}</p>
      <RouterLink to="/" class="btn-secondary mt-5">Go to dashboard</RouterLink>
    </div>
  </div>
</template>
