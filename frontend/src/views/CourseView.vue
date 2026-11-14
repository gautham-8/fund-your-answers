<script setup>
import { onMounted, reactive, ref } from 'vue'
import { api } from '../lib/api'
import { auth } from '../lib/auth'
import StatusBadge from '../components/StatusBadge.vue'

const props = defineProps({ id: String })
const isInstructor = auth.user?.role === 'instructor'

const DEFAULT_RUBRIC = [
  { name: 'Accuracy', description: "Are the student's explanations technically correct?" },
  { name: 'Reasoning depth', description: 'Does the student explain why they made their choices, not just what they did?' },
  { name: 'Specificity', description: 'Does the student refer to concrete details of their own work?' },
  { name: 'Clarity', description: 'Is the explanation coherent and easy to follow? (Judge content, not accent or fluency.)' },
]

const course = ref(null)
const error = ref('')
const showForm = ref(false)
const busy = ref(false)
const form = reactive(blankForm())

function blankForm() {
  return { title: '', description: '', due_date: '', rubric: DEFAULT_RUBRIC.map((r) => ({ ...r })) }
}

async function load() {
  try {
    course.value = await api(`/api/courses/${props.id}`)
  } catch (e) {
    error.value = e.message
  }
}

async function createAssignment() {
  busy.value = true
  error.value = ''
  try {
    await api(`/api/courses/${props.id}/assignments`, {
      method: 'POST',
      body: {
        title: form.title,
        description: form.description,
        due_date: form.due_date ? new Date(form.due_date).toISOString() : null,
        rubric: form.rubric.filter((r) => r.name.trim()),
      },
    })
    Object.assign(form, blankForm())
    showForm.value = false
    await load()
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = false
  }
}

const fmt = (d) => (d ? new Date(d).toLocaleString() : 'No due date')

onMounted(load)
</script>

<template>
  <p v-if="error" class="error-box mb-4">{{ error }}</p>
  <template v-if="course">
    <RouterLink to="/" class="text-sm text-indigo-600 hover:underline">← All classes</RouterLink>
    <div class="mt-2 mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 class="text-2xl font-bold">{{ course.name }}</h1>
        <p class="text-sm text-slate-500">{{ course.student_count }} student{{ course.student_count === 1 ? '' : 's' }}</p>
      </div>
      <div v-if="isInstructor" class="card py-3 text-center">
        <div class="text-xs text-slate-500">Join code</div>
        <div class="font-mono text-2xl font-bold tracking-widest text-indigo-700">{{ course.join_code }}</div>
      </div>
    </div>

    <div class="mb-3 flex items-center justify-between">
      <h2 class="text-lg font-semibold">Assignments</h2>
      <button v-if="isInstructor && !showForm" class="btn-primary" @click="showForm = true">New assignment</button>
    </div>

    <form v-if="showForm" class="card mb-6 space-y-4" @submit.prevent="createAssignment">
      <div>
        <label class="label">Title</label>
        <input v-model="form.title" class="input" required />
      </div>
      <div>
        <label class="label">Description</label>
        <textarea v-model="form.description" class="input" rows="3" placeholder="What students need to do. This also helps the AI ask relevant questions."></textarea>
      </div>
      <div>
        <label class="label">Due date</label>
        <input v-model="form.due_date" type="datetime-local" class="input sm:w-auto" />
      </div>
      <div>
        <label class="label">Rubric (each dimension is scored 1–5)</label>
        <div v-for="(r, i) in form.rubric" :key="i" class="mb-2 flex gap-2">
          <input v-model="r.name" class="input w-40 shrink-0" placeholder="Dimension" />
          <input v-model="r.description" class="input" placeholder="What it measures" />
          <button type="button" class="btn-secondary px-3" title="Remove" @click="form.rubric.splice(i, 1)">✕</button>
        </div>
        <button type="button" class="text-sm text-indigo-600 hover:underline" @click="form.rubric.push({ name: '', description: '' })">
          + Add dimension
        </button>
      </div>
      <div class="flex gap-2">
        <button class="btn-primary" :disabled="busy">Create assignment</button>
        <button type="button" class="btn-secondary" @click="showForm = false">Cancel</button>
      </div>
    </form>

    <p v-if="!course.assignments.length" class="text-slate-500">No assignments yet.</p>
    <div class="space-y-3">
      <RouterLink
        v-for="a in course.assignments"
        :key="a.id"
        :to="`/assignments/${a.id}`"
        class="card flex items-center justify-between transition hover:border-indigo-300"
      >
        <div>
          <div class="font-medium">{{ a.title }}</div>
          <div class="text-sm text-slate-500">Due: {{ fmt(a.due_date) }}</div>
        </div>
        <StatusBadge v-if="!isInstructor" :status="a.my_status" />
      </RouterLink>
    </div>
  </template>
</template>
