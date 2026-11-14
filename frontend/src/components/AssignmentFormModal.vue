<script setup>
import { reactive, ref, watch } from 'vue'
import { api } from '../lib/api'
import { fromLocalInput, toLocalInput, tzAbbr } from '../lib/format'
import Icon from './Icon.vue'
import Modal from './Modal.vue'

/** Create an assignment in `courseId`, or edit `assignment` (dates, title, description). */
const props = defineProps({ open: Boolean, courseId: String, assignment: Object })
const emit = defineEmits(['close', 'saved'])

const DEFAULT_RUBRIC = [
  { name: 'Accuracy', description: "Are the student's explanations technically correct?" },
  { name: 'Reasoning depth', description: 'Does the student explain why they made their choices, not just what they did?' },
  { name: 'Specificity', description: 'Does the student refer to concrete details of their own work?' },
  { name: 'Clarity', description: 'Is the explanation coherent and easy to follow? (Judge content, not accent or fluency.)' },
]

const form = reactive({})
const error = ref('')
const busy = ref(false)

watch(
  () => props.open,
  (open) => {
    if (!open) return
    error.value = ''
    const a = props.assignment
    Object.assign(form, {
      title: a?.title || '',
      description: a?.description || '',
      release_date: toLocalInput(a?.release_date),
      due_date: toLocalInput(a?.due_date),
      late_due_date: toLocalInput(a?.late_due_date),
      rubric: DEFAULT_RUBRIC.map((r) => ({ ...r })),
    })
  },
  { immediate: true },
)

/** Quick picks: N days from now at 11:59 PM. */
function inDays(n) {
  const d = new Date()
  d.setDate(d.getDate() + n)
  d.setHours(23, 59, 0, 0)
  return toLocalInput(d.toISOString())
}
const PRESETS = [
  ['Tomorrow', 1],
  ['In 1 week', 7],
  ['In 2 weeks', 14],
]
function addLateWindow(days) {
  if (!form.due_date) return
  const d = new Date(form.due_date)
  d.setDate(d.getDate() + days)
  form.late_due_date = toLocalInput(d.toISOString())
}

async function submit() {
  busy.value = true
  error.value = ''
  const body = {
    title: form.title,
    description: form.description,
    release_date: fromLocalInput(form.release_date),
    due_date: fromLocalInput(form.due_date),
    late_due_date: fromLocalInput(form.late_due_date),
  }
  try {
    const saved = props.assignment
      ? await api(`/api/assignments/${props.assignment.id}`, { method: 'PATCH', body })
      : await api(`/api/courses/${props.courseId}/assignments`, {
          method: 'POST',
          body: { ...body, rubric: form.rubric.filter((r) => r.name.trim()) },
        })
    emit('saved', saved)
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <Modal :open="open" :title="assignment ? 'Edit assignment' : 'New assignment'" size="lg" @close="emit('close')">
    <form id="assignment-form" class="space-y-5" @submit.prevent="submit">
      <div>
        <label class="label" for="a-title">Title</label>
        <input id="a-title" v-model="form.title" class="input" placeholder="Assignment 3: Transformers" required />
      </div>
      <div>
        <label class="label" for="a-desc">Instructions</label>
        <textarea id="a-desc" v-model="form.description" class="input" rows="3" placeholder="What students need to do. This also helps the AI ask relevant questions."></textarea>
      </div>

      <fieldset class="rounded-xl border border-slate-200 p-4">
        <legend class="px-1 text-sm font-medium text-slate-700">Schedule <span class="font-normal text-slate-400">· {{ tzAbbr }}</span></legend>
        <div class="grid gap-4 sm:grid-cols-3">
          <div>
            <label class="label" for="a-rel">Release</label>
            <input id="a-rel" v-model="form.release_date" type="datetime-local" class="input" />
            <p class="hint">Hidden from students until then. Empty = now.</p>
          </div>
          <div>
            <label class="label" for="a-due">Due</label>
            <input id="a-due" v-model="form.due_date" type="datetime-local" class="input" />
            <div class="mt-1.5 flex flex-wrap gap-1">
              <button v-for="[l, n] in PRESETS" :key="l" type="button" class="rounded-md bg-slate-100 px-1.5 py-0.5 text-[11px] font-medium text-slate-600 hover:bg-indigo-50 hover:text-indigo-700" @click="form.due_date = inDays(n)">
                {{ l }}
              </button>
            </div>
          </div>
          <div>
            <label class="label" for="a-late">Late due <span class="font-normal text-slate-400">(optional)</span></label>
            <input id="a-late" v-model="form.late_due_date" type="datetime-local" class="input" :disabled="!form.due_date" />
            <div v-if="form.due_date" class="mt-1.5 flex flex-wrap gap-1">
              <button v-for="n in [1, 3]" :key="n" type="button" class="rounded-md bg-slate-100 px-1.5 py-0.5 text-[11px] font-medium text-slate-600 hover:bg-indigo-50 hover:text-indigo-700" @click="addLateWindow(n)">
                +{{ n }} day{{ n > 1 ? 's' : '' }}
              </button>
            </div>
          </div>
        </div>
        <p class="mt-3 text-xs text-slate-500">Submissions after the due date but before the late due date are accepted and marked <b>Late</b>.</p>
      </fieldset>

      <div v-if="!assignment">
        <span class="label">Rubric <span class="font-normal text-slate-400">· each dimension is scored 1–5</span></span>
        <div class="space-y-2">
          <div v-for="(r, i) in form.rubric" :key="i" class="flex gap-2">
            <input v-model="r.name" class="input w-36 shrink-0 sm:w-44" placeholder="Dimension" aria-label="Dimension name" />
            <input v-model="r.description" class="input" placeholder="What it measures" aria-label="Dimension description" />
            <button type="button" class="icon-btn size-9 shrink-0" title="Remove" @click="form.rubric.splice(i, 1)"><Icon name="trash" :size="15" /></button>
          </div>
        </div>
        <button type="button" class="btn-ghost btn-sm mt-2 -ml-1" @click="form.rubric.push({ name: '', description: '' })"><Icon name="plus" :size="14" />Add dimension</button>
      </div>
      <p v-else class="flex items-center gap-2 text-xs text-slate-500"><Icon name="lock" :size="13" />The rubric is fixed once an assignment is created, so scores stay comparable.</p>

      <p v-if="error" class="error-box">{{ error }}</p>
    </form>
    <template #footer>
      <button type="button" class="btn-secondary" @click="emit('close')">Cancel</button>
      <button form="assignment-form" class="btn-primary" :disabled="busy">{{ assignment ? 'Save changes' : 'Create assignment' }}</button>
    </template>
  </Modal>
</template>
