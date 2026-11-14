<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { api } from '../lib/api'
import { auth } from '../lib/auth'
import StatusBadge from '../components/StatusBadge.vue'
import ClassInsights from '../components/ClassInsights.vue'

const props = defineProps({ id: String })
const isInstructor = auth.user?.role === 'instructor'

const a = ref(null)
const error = ref('')
const file = ref(null)
const uploading = ref(false)
let timer = null

const mySub = computed(() => a.value?.my_submission)
const pending = (s) => s === 'analyzing' || s === 'scoring'

async function load() {
  try {
    a.value = await api(`/api/assignments/${props.id}`)
  } catch (e) {
    error.value = e.message
  }
  // Poll while something is processing in the background.
  const list = isInstructor ? a.value?.submissions || [] : mySub.value ? [mySub.value] : []
  clearTimeout(timer)
  if (list.some((s) => pending(s.status))) timer = setTimeout(load, 3000)
}

async function upload() {
  if (!file.value) return
  uploading.value = true
  error.value = ''
  try {
    const form = new FormData()
    form.append('file', file.value)
    await api(`/api/assignments/${props.id}/submissions`, { method: 'POST', form })
    file.value = null
    await load()
  } catch (e) {
    error.value = e.message
  } finally {
    uploading.value = false
  }
}

async function retry(subId) {
  try {
    await api(`/api/submissions/${subId}/retry`, { method: 'POST' })
    await load()
  } catch (e) {
    error.value = e.message
  }
}

const pastDue = computed(() => !!a.value?.due_date && new Date(a.value.due_date) < new Date())
const canUpload = computed(
  () => !pastDue.value && (!mySub.value || ['analyzing', 'analysis_failed', 'ready'].includes(mySub.value.status)),
)
const fmt = (d) => (d ? new Date(d).toLocaleString() : 'No due date')

onMounted(load)
onUnmounted(() => clearTimeout(timer))
</script>

<template>
  <p v-if="error" class="error-box mb-4">{{ error }}</p>
  <template v-if="a">
    <RouterLink :to="`/courses/${a.course.id}`" class="text-sm text-indigo-600 hover:underline">← {{ a.course.name }}</RouterLink>
    <h1 class="mt-2 text-2xl font-bold">{{ a.title }}</h1>
    <p class="text-sm text-slate-500">
      Due: {{ fmt(a.due_date) }}
      <span v-if="pastDue" class="ml-1 rounded bg-slate-200 px-1.5 py-0.5 text-xs text-slate-700">Closed</span>
    </p>
    <p v-if="a.description" class="mt-3 whitespace-pre-line text-slate-700">{{ a.description }}</p>

    <details class="mt-3 text-sm text-slate-600">
      <summary class="cursor-pointer">Rubric</summary>
      <ul class="mt-2 list-disc pl-5">
        <li v-for="r in a.rubric" :key="r.name"><b>{{ r.name }}</b> — {{ r.description }}</li>
      </ul>
    </details>

    <!-- Student -->
    <section v-if="!isInstructor" class="card mt-6 space-y-4">
      <div class="flex items-center justify-between">
        <h2 class="font-semibold">Your submission</h2>
        <StatusBadge :status="mySub?.status" />
      </div>

      <p v-if="mySub" class="text-sm text-slate-600">File: {{ mySub.filename }}</p>

      <div v-if="mySub?.status === 'analyzing'" class="text-sm text-slate-600">
        Reading your PDF and preparing questions. This usually takes under a minute…
      </div>
      <div v-if="mySub?.status === 'analysis_failed'" class="error-box">
        We couldn't analyze your PDF. <button class="underline" @click="retry(mySub.id)">Try again</button>
        or upload a different file.
        <div v-if="mySub.error" class="mt-1 text-xs opacity-80">{{ mySub.error }}</div>
      </div>
      <div v-if="mySub?.status === 'ready' || mySub?.status === 'viva_in_progress'" class="rounded-lg bg-indigo-50 p-4">
        <p class="mb-3 text-sm text-indigo-900">
          Your viva is ready: {{ mySub.status === 'ready' ? 'a few' : 'the remaining' }} short spoken questions about your own work.
          Find a quiet spot; it takes about 5–10 minutes.
        </p>
        <RouterLink :to="`/submissions/${mySub.id}/viva`" class="btn-primary">
          {{ mySub.status === 'ready' ? 'Start viva' : 'Continue viva' }}
        </RouterLink>
      </div>
      <div v-if="mySub?.status === 'scoring' || mySub?.status === 'completed'" class="rounded-lg bg-emerald-50 p-4 text-sm text-emerald-900">
        Viva complete — thanks! Your instructor will review the results.
      </div>
      <div v-if="mySub?.status === 'scoring_failed'" class="error-box">
        Viva complete, but scoring hit an error. <button class="underline" @click="retry(mySub.id)">Retry scoring</button>
      </div>

      <p v-if="pastDue && !mySub" class="text-sm text-slate-500">The due date has passed, so submissions are closed.</p>
      <form v-if="canUpload" class="flex flex-col gap-3 border-t border-slate-100 pt-4 sm:flex-row sm:items-center" @submit.prevent="upload">
        <input type="file" accept="application/pdf" class="text-sm" @change="file = $event.target.files[0]" />
        <button class="btn-primary" :disabled="!file || uploading">{{ uploading ? 'Uploading…' : mySub ? 'Replace PDF' : 'Submit PDF' }}</button>
      </form>
    </section>

    <!-- Instructor -->
    <section v-else class="mt-6">
      <h2 class="mb-3 text-lg font-semibold">
        Submissions <span class="text-sm font-normal text-slate-500">({{ a.submissions.length }} of {{ a.student_count }} students)</span>
      </h2>
      <p v-if="!a.submissions.length" class="text-slate-500">No submissions yet.</p>
      <div v-else class="card overflow-x-auto p-0">
        <table class="w-full text-left text-sm">
          <thead class="border-b border-slate-200 bg-slate-50 text-slate-600">
            <tr>
              <th class="px-4 py-2 font-medium">Student</th>
              <th class="px-4 py-2 font-medium">Submitted</th>
              <th class="px-4 py-2 font-medium">Status</th>
              <th class="px-4 py-2 font-medium">Understanding score</th>
              <th class="px-4 py-2"></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="s in a.submissions" :key="s.id" class="border-b border-slate-100 last:border-0">
              <td class="px-4 py-2">
                <div class="font-medium">{{ s.student?.name }}</div>
                <div class="text-xs text-slate-500">{{ s.student?.email }}</div>
              </td>
              <td class="px-4 py-2 text-slate-600">{{ new Date(s.created_at).toLocaleString() }}</td>
              <td class="px-4 py-2"><StatusBadge :status="s.status" :needs-review="s.needs_review" /></td>
              <td class="px-4 py-2 font-semibold">{{ s.overall != null ? `${s.overall}%` : '—' }}</td>
              <td class="px-4 py-2 text-right">
                <RouterLink :to="`/submissions/${s.id}/report`" class="text-indigo-600 hover:underline">Report</RouterLink>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <ClassInsights :assignment-id="id" />
    </section>
  </template>
</template>
