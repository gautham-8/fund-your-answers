<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { api } from '../lib/api'
import { auth } from '../lib/auth'
import { confirmDialog } from '../lib/confirm'
import { initials, relative } from '../lib/format'
import { loadCourses } from '../lib/store'
import { toast } from '../lib/toast'
import Icon from '../components/Icon.vue'

const props = defineProps({ course: { type: Object, required: true } })
const emit = defineEmits(['changed'])
const isInstructor = auth.user?.role === 'instructor'

const items = ref(null)
const error = ref('')
const tab = ref('open')
const expanded = ref(null)
const draft = reactive({ response: '', score: null })
const saving = ref(false)

const counts = computed(() => ({
  open: items.value?.filter((r) => r.status === 'open').length ?? 0,
  resolved: items.value?.filter((r) => r.status === 'resolved').length ?? 0,
  all: items.value?.length ?? 0,
}))
const shown = computed(() => (items.value || []).filter((r) => tab.value === 'all' || r.status === tab.value))

async function load() {
  try {
    items.value = await api(`/api/courses/${props.course.id}/regrade-requests`)
  } catch (e) {
    error.value = e.message
  }
}

function toggle(r) {
  expanded.value = expanded.value === r.id ? null : r.id
  Object.assign(draft, { response: r.response || '', score: null })
}

async function resolve(r, status = 'resolved') {
  saving.value = true
  try {
    const body = { status, response: draft.response }
    if (status === 'resolved' && draft.score) body.override_score = draft.score
    const updated = await api(`/api/regrade-requests/${r.id}`, { method: 'PATCH', body })
    Object.assign(r, updated)
    expanded.value = null
    emit('changed')
    loadCourses()
    toast(status === 'resolved' ? 'Regrade request resolved' : 'Request reopened')
  } catch (e) {
    toast(e.message, { type: 'error' })
  } finally {
    saving.value = false
  }
}

async function withdraw(r) {
  const ok = await confirmDialog({ title: 'Withdraw this request?', message: `Your regrade request for “${r.dimension}” will be removed.`, confirmText: 'Withdraw', danger: true })
  if (!ok) return
  try {
    await api(`/api/regrade-requests/${r.id}`, { method: 'DELETE' })
    items.value = items.value.filter((x) => x.id !== r.id)
    emit('changed')
    toast('Request withdrawn')
  } catch (e) {
    toast(e.message, { type: 'error' })
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
          v-for="k in ['open', 'resolved', 'all']"
          :key="k"
          class="inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium capitalize transition"
          :class="tab === k ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-800'"
          @click="tab = k"
        >
          {{ k }} <span class="rounded-full bg-slate-200/70 px-1.5 text-[10px]">{{ counts[k] }}</span>
        </button>
      </div>
      <p class="text-xs text-slate-500">
        {{ isInstructor ? 'Students can ask for a rubric item to be re-checked after grades are published.' : 'Request a regrade from an assignment page once its grade is published.' }}
      </p>
    </div>

    <div v-if="!items" class="space-y-3">
      <div v-for="i in 3" :key="i" class="skeleton h-24 rounded-2xl"></div>
    </div>

    <div v-else-if="!shown.length" class="rounded-2xl border border-dashed border-slate-300 bg-white px-6 py-14 text-center">
      <div class="mx-auto grid size-11 place-items-center rounded-xl bg-slate-100 text-slate-500"><Icon name="inbox" :size="20" /></div>
      <p class="mt-3 font-medium">{{ tab === 'open' ? 'No open requests' : 'Nothing here yet' }}</p>
      <p class="mt-1 text-sm text-slate-500">{{ tab === 'open' ? 'You’re all caught up.' : 'Regrade requests will show up here.' }}</p>
    </div>

    <ul v-else class="space-y-3">
      <li v-for="r in shown" :key="r.id" class="card p-0">
        <div class="flex flex-wrap items-start gap-4 p-5">
          <span v-if="isInstructor" class="grid size-9 shrink-0 place-items-center rounded-full bg-slate-100 text-xs font-semibold text-slate-600">{{ initials(r.student?.name) }}</span>
          <div class="min-w-0 flex-1">
            <div class="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
              <span v-if="isInstructor" class="font-semibold text-slate-900">{{ r.student?.name }}</span>
              <span v-if="isInstructor" class="text-slate-300">·</span>
              <RouterLink :to="`/assignments/${r.assignment.id}`" class="font-medium text-slate-700 hover:text-indigo-700">{{ r.assignment.title }}</RouterLink>
              <span class="rounded-md bg-slate-100 px-1.5 py-0.5 text-xs font-medium text-slate-600">{{ r.dimension }}</span>
            </div>
            <p class="mt-2 text-sm whitespace-pre-line text-slate-700">{{ r.message }}</p>
            <div class="mt-2 flex flex-wrap items-center gap-3 text-xs text-slate-500">
              <span>{{ relative(r.created_at) }}</span>
              <span>Score at request: <b class="text-slate-700">{{ r.score_before }}/5</b></span>
              <span v-if="r.status === 'resolved' && r.score_after != null">
                Now: <b :class="r.score_after > r.score_before ? 'text-emerald-600' : 'text-slate-700'">{{ r.score_after }}/5</b>
              </span>
            </div>
            <div v-if="r.status === 'resolved' && (r.response || r.resolved_by)" class="mt-3 rounded-xl bg-slate-50 p-3 text-sm">
              <div class="mb-1 text-xs font-medium text-slate-500">{{ r.resolved_by }} replied {{ relative(r.resolved_at) }}</div>
              <p class="whitespace-pre-line text-slate-700">{{ r.response || 'Resolved without a comment.' }}</p>
            </div>
          </div>
          <div class="flex items-center gap-2">
            <span
              class="inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset"
              :class="r.status === 'open' ? 'bg-orange-50 text-orange-700 ring-orange-200' : 'bg-emerald-50 text-emerald-700 ring-emerald-200'"
            >
              <span class="size-1.5 rounded-full" :class="r.status === 'open' ? 'bg-orange-500' : 'bg-emerald-500'"></span>{{ r.status === 'open' ? 'Open' : 'Resolved' }}
            </span>
            <template v-if="isInstructor">
              <RouterLink :to="`/submissions/${r.submission_id}/report`" class="btn-ghost btn-sm">Report<Icon name="arrow-right" :size="13" /></RouterLink>
              <button v-if="r.status === 'open'" class="btn-primary btn-sm" @click="toggle(r)">Respond</button>
              <button v-else class="btn-ghost btn-sm" @click="resolve(r, 'open')">Reopen</button>
            </template>
            <button v-else-if="r.status === 'open'" class="btn-ghost btn-sm text-rose-600 hover:bg-rose-50 hover:text-rose-700" @click="withdraw(r)">Withdraw</button>
          </div>
        </div>

        <!-- Instructor response -->
        <div v-if="expanded === r.id" class="space-y-3 border-t border-slate-100 bg-slate-50/60 p-5">
          <div>
            <span class="label">New score for {{ r.dimension }} <span class="font-normal text-slate-400">(optional — currently {{ r.score_before }}/5)</span></span>
            <div class="flex gap-1.5">
              <button
                v-for="n in 5"
                :key="n"
                type="button"
                class="size-9 rounded-lg text-sm font-semibold ring-1 transition ring-inset"
                :class="draft.score === n ? 'bg-indigo-600 text-white ring-indigo-600' : 'bg-white text-slate-700 ring-slate-200 hover:ring-indigo-300'"
                @click="draft.score = draft.score === n ? null : n"
              >
                {{ n }}
              </button>
            </div>
          </div>
          <div>
            <label class="label" :for="`resp-${r.id}`">Reply to student</label>
            <textarea :id="`resp-${r.id}`" v-model="draft.response" class="input" rows="3" placeholder="Explain your decision"></textarea>
          </div>
          <div class="flex justify-end gap-2">
            <button class="btn-secondary" @click="expanded = null">Cancel</button>
            <button class="btn-primary" :disabled="saving" @click="resolve(r)">
              <Icon name="check" />{{ draft.score ? `Resolve & set ${draft.score}/5` : 'Resolve, keep score' }}
            </button>
          </div>
        </div>
      </li>
    </ul>
  </div>
</template>
