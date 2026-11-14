<script setup>
import { reactive, ref, watch } from 'vue'
import { api } from '../lib/api'
import { currentTerm, termOptions } from '../lib/format'
import Modal from './Modal.vue'

/** Create a class, or edit one when `course` is passed. */
const props = defineProps({ open: Boolean, course: Object })
const emit = defineEmits(['close', 'saved'])

const form = reactive({ code: '', name: '', term: '' })
const error = ref('')
const busy = ref(false)
const terms = ref(termOptions())

watch(
  () => props.open,
  (open) => {
    if (!open) return
    error.value = ''
    Object.assign(form, props.course ? { code: props.course.code, name: props.course.name, term: props.course.term } : { code: '', name: '', term: currentTerm() })
    if (form.term && !terms.value.includes(form.term)) terms.value = [form.term, ...termOptions()]
  },
  { immediate: true },
)

async function submit() {
  busy.value = true
  error.value = ''
  try {
    const saved = props.course
      ? await api(`/api/courses/${props.course.id}`, { method: 'PATCH', body: form })
      : await api('/api/courses', { method: 'POST', body: form })
    emit('saved', saved)
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <Modal :open="open" :title="course ? 'Class settings' : 'Create a class'" :description="course ? '' : 'Students join with a code you can share.'" @close="emit('close')">
    <form id="course-form" class="space-y-4" @submit.prevent="submit">
      <div class="grid gap-4 sm:grid-cols-[10rem_1fr]">
        <div>
          <label class="label" for="c-code">Course code</label>
          <input id="c-code" v-model="form.code" class="input" placeholder="CS 682" maxlength="40" />
        </div>
        <div>
          <label class="label" for="c-name">Class name</label>
          <input id="c-name" v-model="form.name" class="input" placeholder="Neural Networks: A Modern Intro" maxlength="120" required />
        </div>
      </div>
      <div>
        <span class="label">Term</span>
        <div class="flex flex-wrap gap-2">
          <button
            v-for="t in terms"
            :key="t"
            type="button"
            class="rounded-full px-3 py-1.5 text-sm font-medium ring-1 transition ring-inset"
            :class="form.term === t ? 'bg-indigo-600 text-white ring-indigo-600' : 'bg-white text-slate-600 ring-slate-200 hover:ring-slate-300'"
            @click="form.term = t"
          >
            {{ t }}
          </button>
        </div>
      </div>
      <p v-if="error" class="error-box">{{ error }}</p>
    </form>
    <template #footer>
      <button type="button" class="btn-secondary" @click="emit('close')">Cancel</button>
      <button form="course-form" class="btn-primary" :disabled="busy">{{ course ? 'Save changes' : 'Create class' }}</button>
    </template>
  </Modal>
</template>
