<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { api } from '../lib/api'
import { initials, relative } from '../lib/format'
import { loadCourses } from '../lib/store'
import { toast } from '../lib/toast'
import Icon from '../components/Icon.vue'

const props = defineProps({ course: { type: Object, required: true } })
const emit = defineEmits(['changed'])

const items = ref(null)
const error = ref('')
const tab = ref('pending')
const replies = reactive({}) // request id -> draft reply
const saving = ref(null)

const STATUS = {
  pending: { label: 'Pending', cls: 'bg-amber-50 text-amber-700 ring-amber-200', dot: 'bg-amber-500' },
  approved: { label: 'Approved', cls: 'bg-emerald-50 text-emerald-700 ring-emerald-200', dot: 'bg-emerald-500' },
  denied: { label: 'Denied', cls: 'bg-slate-100 text-slate-600 ring-slate-200', dot: 'bg-slate-400' },
}

const counts = computed(() => ({
  pending: items.value?.filter((r) => r.status === 'pending').length ?? 0,
  decided: items.value?.filter((r) => r.status !== 'pending').length ?? 0,
  all: items.value?.length ?? 0,
}))
const shown = computed(() =>
  (items.value || []).filter((r) => tab.value === 'all' || (tab.value === 'pending') === (r.status === 'pending')),
)

async function load() {
  try {
    items.value = await api(`/api/courses/${props.course.id}/accommodations`)
  } catch (e) {
    error.value = e.message
  }
}

async function decide(r, status) {
  saving.value = r.id
  try {
    const updated = await api(`/api/accommodations/${r.id}`, { method: 'PATCH', body: { status, response: replies[r.id] || '' } })
    Object.assign(r, updated)
    delete replies[r.id]
    emit('changed')
    loadCourses()
    toast(status === 'approved' ? 'Typed answers approved' : 'Request denied')
  } catch (e) {
    toast(e.message, { type: 'error' })
  } finally {
    saving.value = null
  }
}

onMounted(load)
</script>

<template>
  <div>
    <p v-if="error" class="error-box mb-4">{{ error }}</p>

    <div class="mb-4 flex flex-wrap items-center justify-between gap-3">
      <div class="flex rounded-lg bg-slate-100 p-0.5">
        <button
          v-for="k in ['pending', 'decided', 'all']"
          :key="k"
          class="inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium capitalize transition"
          :class="tab === k ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-800'"
          @click="tab = k"
        >
          {{ k }} <span class="rounded-full bg-slate-200/70 px-1.5 text-[10px]">{{ counts[k] }}</span>
        </button>
      </div>
      <p class="max-w-md text-xs text-slate-500">
        Vivas are spoken by default. Students with an accommodation can ask to type their answers for a whole viva, before starting it.
      </p>
    </div>

    <div v-if="!items" class="space-y-3">
      <div v-for="i in 3" :key="i" class="skeleton h-24 rounded-2xl"></div>
    </div>

    <div v-else-if="!shown.length" class="rounded-2xl border border-dashed border-slate-300 bg-white px-6 py-14 text-center">
      <div class="mx-auto grid size-11 place-items-center rounded-xl bg-slate-100 text-slate-500"><Icon name="keyboard" :size="20" /></div>
      <p class="mt-3 font-medium">{{ tab === 'pending' ? 'No requests waiting' : 'Nothing here yet' }}</p>
      <p class="mt-1 text-sm text-slate-500">Typed-answer requests will show up here.</p>
    </div>

    <ul v-else class="space-y-3">
      <li v-for="r in shown" :key="r.id" class="card p-5">
        <div class="flex flex-wrap items-start gap-4">
          <span class="grid size-9 shrink-0 place-items-center rounded-full bg-slate-100 text-xs font-semibold text-slate-600">{{ initials(r.student?.name) }}</span>
          <div class="min-w-0 flex-1">
            <div class="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
              <span class="font-semibold text-slate-900">{{ r.student?.name }}</span>
              <span class="text-slate-300">·</span>
              <RouterLink :to="`/assignments/${r.assignment.id}`" class="font-medium text-slate-700 hover:text-indigo-700">{{ r.assignment.title }}</RouterLink>
              <span class="rounded-md bg-slate-100 px-1.5 py-0.5 text-xs font-medium text-slate-600">Typed answers</span>
            </div>
            <p class="mt-2 text-sm whitespace-pre-line text-slate-700">{{ r.reason }}</p>
            <p class="mt-2 text-xs text-slate-500">
              Asked {{ relative(r.created_at) }}<template v-if="r.decided_at"> · {{ STATUS[r.status].label.toLowerCase() }} by {{ r.decided_by }} {{ relative(r.decided_at) }}</template>
            </p>
            <p v-if="r.status !== 'pending' && r.response" class="mt-2 rounded-xl bg-slate-50 p-3 text-sm whitespace-pre-line text-slate-700">{{ r.response }}</p>
          </div>
          <span class="inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset" :class="STATUS[r.status].cls">
            <span class="size-1.5 rounded-full" :class="STATUS[r.status].dot"></span>{{ STATUS[r.status].label }}
          </span>
        </div>

        <div v-if="r.status === 'pending'" class="mt-4 space-y-3 border-t border-slate-100 pt-4">
          <textarea v-model="replies[r.id]" class="input" rows="2" placeholder="Optional note to the student"></textarea>
          <div class="flex justify-end gap-2">
            <button class="btn-secondary" :disabled="saving === r.id" @click="decide(r, 'denied')">Deny</button>
            <button class="btn-primary" :disabled="saving === r.id" @click="decide(r, 'approved')"><Icon name="check" />Approve typed answers</button>
          </div>
        </div>
      </li>
    </ul>
  </div>
</template>
