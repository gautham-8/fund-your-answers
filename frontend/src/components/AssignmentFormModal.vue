<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { api } from '../lib/api'
import { fmtPts, fromLocalInput, toLocalInput, tzAbbr } from '../lib/format'
import Icon from './Icon.vue'
import Modal from './Modal.vue'

/** Create an assignment in `courseId`, or edit `assignment` (dates, title, description, grading, handout). */
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
const brief = ref(null) // the handout PDF chosen in this dialog
const extracting = ref(false)
const extracted = ref(false)

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
      // { text, points }; when editing, the text is fixed and only the points can change
      parts: (a?.parts || []).map((text, i) => ({ text, points: a.part_points?.[i] ?? '' })),
      max_points: a?.max_points ?? 100,
      viva_pct: Math.round((a?.viva_weight ?? 0.3) * 100),
    })
    brief.value = null
    extracted.value = false
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

/** Read the handout with AI and fill in the questions and a draft rubric (all still editable). */
async function pickBrief(f) {
  if (!f) return
  if (f.type && f.type !== 'application/pdf') {
    error.value = 'The handout must be a PDF'
    return
  }
  brief.value = f
  if (props.assignment) return // editing: the PDF is just attached on save
  extracting.value = true
  error.value = ''
  try {
    const fd = new FormData()
    fd.append('file', f)
    const d = await api('/api/assignments/brief/extract', { method: 'POST', form: fd })
    if (!form.title.trim()) form.title = d.title
    if (!form.description.trim()) form.description = d.description
    if (d.parts.length) form.parts = d.parts.map((text, i) => ({ text, points: d.part_points[i] ?? '' }))
    if (d.rubric.length) form.rubric = d.rubric
    extracted.value = true
  } catch (e) {
    error.value = `${e.message}. You can still fill in the questions by hand; the PDF will be attached.`
  } finally {
    extracting.value = false
  }
}

const filledParts = computed(() => form.parts.filter((q) => q.text.trim()))
const pointsTotal = computed(() => filledParts.value.reduce((t, q) => t + (Number(q.points) || 0), 0))
const missingPoints = computed(() => filledParts.value.filter((q) => !(Number(q.points) > 0)).length)

async function submit() {
  error.value = ''
  if (missingPoints.value) {
    error.value = `Give points to every question (${missingPoints.value} missing). They're what the grader marks out of.`
    return
  }
  busy.value = true
  const body = {
    title: form.title,
    description: form.description,
    release_date: fromLocalInput(form.release_date),
    due_date: fromLocalInput(form.due_date),
    late_due_date: fromLocalInput(form.late_due_date),
    viva_weight: Number(form.viva_pct) / 100,
  }
  if (filledParts.value.length) body.part_points = filledParts.value.map((q) => Number(q.points))
  else body.max_points = Number(form.max_points)
  try {
    const saved = props.assignment
      ? await api(`/api/assignments/${props.assignment.id}`, { method: 'PATCH', body })
      : await api(`/api/courses/${props.courseId}/assignments`, {
          method: 'POST',
          body: { ...body, rubric: form.rubric.filter((r) => r.name.trim()), parts: filledParts.value.map((q) => q.text) },
        })
    if (brief.value) {
      const fd = new FormData()
      fd.append('file', brief.value)
      await api(`/api/assignments/${saved.id}/brief`, { method: 'PUT', form: fd })
    }
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
      <label
        class="flex cursor-pointer items-center gap-3 rounded-xl border-2 border-dashed p-4 transition"
        :class="brief ? 'border-emerald-300 bg-emerald-50/50' : 'border-slate-200 hover:border-indigo-300 hover:bg-slate-50'"
      >
        <input type="file" accept="application/pdf" class="sr-only" :disabled="extracting" @change="pickBrief($event.target.files[0])" />
        <span class="grid size-10 shrink-0 place-items-center rounded-lg" :class="brief ? 'bg-emerald-100 text-emerald-600' : 'bg-indigo-50 text-indigo-600'">
          <span v-if="extracting" class="size-4 animate-spin rounded-full border-2 border-indigo-200 border-t-indigo-600"></span>
          <Icon v-else :name="brief ? 'check' : 'upload'" :size="18" />
        </span>
        <span class="min-w-0 text-sm">
          <span class="block font-medium text-slate-800">
            <template v-if="extracting">Reading {{ brief.name }}…</template>
            <template v-else-if="brief">{{ brief.name }}</template>
            <template v-else-if="assignment?.has_brief">Replace the assignment handout <span class="font-normal text-slate-500">({{ assignment.brief_filename }})</span></template>
            <template v-else>Upload the assignment handout (PDF)</template>
          </span>
          <span class="block text-xs text-slate-500">
            <template v-if="extracted">Questions and a draft rubric were filled in below. Check and edit them.</template>
            <template v-else-if="assignment">The AI reads it next to each submission to check it actually answers the assignment.</template>
            <template v-else>The AI pulls out the questions and drafts a rubric. It also checks each submission actually answers them.</template>
          </span>
        </span>
      </label>

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
        <span class="label">Questions <span class="font-normal text-slate-400">(recommended)</span></span>
        <p class="hint mb-2">
          <template v-if="extracting">Filling these in from the handout…</template>
          <template v-else-if="extracted">Filled in from the handout. Check them, edit or remove any that aren't real questions, and add points where the handout didn't give any (highlighted).</template>
          <template v-else>Upload the handout above to fill these in automatically, or add them by hand.</template>
          They're used to check each submission answers the assignment and to aim the viva at the student's answers.
        </p>
        <div class="space-y-2">
          <div v-for="(q, i) in form.parts" :key="i" class="flex gap-2">
            <span class="w-8 shrink-0 pt-2 text-sm text-slate-500">Q{{ i + 1 }}</span>
            <textarea v-model="q.text" class="input" rows="1" placeholder="Question text" :aria-label="`Question ${i + 1}`"></textarea>
            <div class="relative w-24 shrink-0">
              <input
                v-model="q.points"
                type="number"
                min="0"
                step="any"
                class="input pr-8 font-mono"
                :class="q.text.trim() && !(Number(q.points) > 0) && 'border-orange-300 bg-orange-50/50'"
                placeholder="pts"
                :aria-label="`Points for question ${i + 1}`"
              />
              <span class="pointer-events-none absolute top-1/2 right-2.5 -translate-y-1/2 text-xs text-slate-400">pts</span>
            </div>
            <button type="button" class="icon-btn size-9 shrink-0" title="Remove" @click="form.parts.splice(i, 1)"><Icon name="trash" :size="15" /></button>
          </div>
        </div>
        <div class="mt-2 flex flex-wrap items-center justify-between gap-2">
          <button type="button" class="btn-ghost btn-sm -ml-1" @click="form.parts.push({ text: '', points: '' })"><Icon name="plus" :size="14" />Add question</button>
          <span v-if="filledParts.length" class="text-xs text-slate-500">
            Total {{ fmtPts(pointsTotal) }} pts<span v-if="missingPoints" class="text-orange-600"> · {{ missingPoints }} without points</span>
          </span>
        </div>
      </div>

      <div v-else-if="form.parts.length">
        <span class="label">Question points</span>
        <p class="hint mb-2">The questions are fixed, but you can change what each is worth. Existing grades keep their points.</p>
        <div class="space-y-1.5">
          <div v-for="(q, i) in form.parts" :key="i" class="flex items-center gap-2">
            <span class="w-8 shrink-0 text-sm text-slate-500">Q{{ i + 1 }}</span>
            <span class="min-w-0 flex-1 truncate text-sm text-slate-700" :title="q.text">{{ q.text }}</span>
            <input v-model="q.points" type="number" min="0" step="any" class="input w-24 py-1.5 font-mono" :aria-label="`Points for question ${i + 1}`" />
          </div>
        </div>
        <p class="mt-2 text-right text-xs text-slate-500">Total {{ fmtPts(pointsTotal) }} pts</p>
      </div>

      <fieldset class="rounded-xl border border-slate-200 p-4">
        <legend class="px-1 text-sm font-medium text-slate-700">Final grade</legend>
        <div class="grid gap-4 sm:grid-cols-[8rem_minmax(0,1fr)]">
          <div>
            <label class="label" for="a-pts">Graded out of</label>
            <template v-if="filledParts.length">
              <div id="a-pts" class="input bg-slate-50 font-mono">{{ fmtPts(pointsTotal) }}</div>
              <p class="hint">Sum of the question points</p>
            </template>
            <template v-else>
              <input id="a-pts" v-model="form.max_points" type="number" min="1" step="any" class="input" required />
              <p class="hint">Points for the written solution</p>
            </template>
          </div>
          <div>
            <label class="label" for="a-w">Viva weight <span class="font-normal text-slate-400">· {{ form.viva_pct }}%</span></label>
            <input id="a-w" v-model.number="form.viva_pct" type="range" min="0" max="100" step="5" class="mt-2 w-full accent-indigo-600" />
            <p class="hint">Final = {{ 100 - form.viva_pct }}% × grader's mark + {{ form.viva_pct }}% × viva score</p>
          </div>
        </div>
      </fieldset>

      <div v-if="!assignment">
        <span class="label">Viva rubric <span class="font-normal text-slate-400">· each dimension is scored 0–5 for understanding</span></span>
        <div class="space-y-2">
          <div v-for="(r, i) in form.rubric" :key="i" class="flex gap-2">
            <input v-model="r.name" class="input w-36 shrink-0 sm:w-44" placeholder="Dimension" aria-label="Dimension name" />
            <input v-model="r.description" class="input" placeholder="What it measures" aria-label="Dimension description" />
            <button type="button" class="icon-btn size-9 shrink-0" title="Remove" @click="form.rubric.splice(i, 1)"><Icon name="trash" :size="15" /></button>
          </div>
        </div>
        <button type="button" class="btn-ghost btn-sm mt-2 -ml-1" @click="form.rubric.push({ name: '', description: '' })"><Icon name="plus" :size="14" />Add dimension</button>
      </div>
      <p v-else class="flex items-center gap-2 text-xs text-slate-500"><Icon name="lock" :size="13" />The rubric and questions are fixed once an assignment is created, so scores and page matches stay comparable.</p>

      <p v-if="error" class="error-box">{{ error }}</p>
    </form>
    <template #footer>
      <button type="button" class="btn-secondary" @click="emit('close')">Cancel</button>
      <button form="assignment-form" class="btn-primary" :disabled="busy || extracting">{{ assignment ? 'Save changes' : 'Create assignment' }}</button>
    </template>
  </Modal>
</template>
