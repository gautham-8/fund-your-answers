<script setup>
import { computed, ref } from 'vue'
import { api } from '../lib/api'
import { copyText } from '../lib/clipboard'
import { confirmDialog } from '../lib/confirm'
import { initials } from '../lib/format'
import { loadCourses } from '../lib/store'
import { toast } from '../lib/toast'
import CopyChip from '../components/CopyChip.vue'
import Icon from '../components/Icon.vue'

const props = defineProps({ course: { type: Object, required: true } })
const emit = defineEmits(['changed'])
const q = ref('')

const inviteLink = computed(() => `${location.origin}/join/${props.course.join_code}`)
const students = computed(() => {
  const term = q.value.trim().toLowerCase()
  return props.course.students.filter((s) => !term || s.name.toLowerCase().includes(term) || s.email.toLowerCase().includes(term))
})
const total = computed(() => props.course.assignments.length)

async function remove(s) {
  const ok = await confirmDialog({
    title: `Remove ${s.name}?`,
    message: 'They will lose access to this class. Their submissions are kept, and they can rejoin with the code.',
    confirmText: 'Remove student',
    danger: true,
  })
  if (!ok) return
  try {
    await api(`/api/courses/${props.course.id}/students/${s.id}`, { method: 'DELETE' })
    emit('changed')
    loadCourses()
    toast(`${s.name} removed`)
  } catch (e) {
    toast(e.message, { type: 'error' })
  }
}
</script>

<template>
  <div class="space-y-6">
    <!-- Invite -->
    <div class="card flex flex-wrap items-center justify-between gap-4 bg-linear-to-br from-indigo-50/80 to-white">
      <div>
        <h2 class="font-semibold">Invite students</h2>
        <p class="mt-0.5 text-sm text-slate-500">Share the code, or send the link — it joins them in one click.</p>
      </div>
      <div class="flex flex-wrap items-center gap-2">
        <CopyChip :value="course.join_code" size="lg" :message="`Join code ${course.join_code} copied`" />
        <button class="btn-secondary" @click="copyText(inviteLink, 'Invite link copied')"><Icon name="link" />Copy invite link</button>
      </div>
    </div>

    <div>
      <div class="mb-4 flex flex-wrap items-center gap-3">
        <div class="relative min-w-0 flex-1 sm:max-w-xs">
          <Icon name="search" class="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-slate-400" />
          <input v-model="q" class="input pl-9" placeholder="Search students" aria-label="Search students" />
        </div>
        <button v-if="course.students.length" class="btn-ghost ml-auto" @click="copyText(course.students.map((s) => s.email).join(', '), `${course.students.length} emails copied`)">
          <Icon name="mail" />Copy all emails
        </button>
      </div>

      <div v-if="!course.students.length" class="rounded-2xl border border-dashed border-slate-300 bg-white px-6 py-14 text-center">
        <div class="mx-auto grid size-11 place-items-center rounded-xl bg-slate-100 text-slate-500"><Icon name="users" :size="20" /></div>
        <p class="mt-3 font-medium">No students yet</p>
        <p class="mt-1 text-sm text-slate-500">Share the join code above with your class.</p>
      </div>

      <div v-else class="overflow-hidden rounded-2xl border border-slate-200/80 bg-white shadow-xs">
        <table class="w-full text-sm">
          <thead class="border-b border-slate-100 bg-slate-50/60">
            <tr>
              <th class="th">Student</th>
              <th class="th hidden sm:table-cell">Submissions</th>
              <th class="th w-12"></th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-100">
            <tr v-for="s in students" :key="s.id" class="group">
              <td class="td">
                <div class="flex items-center gap-3">
                  <span class="grid size-8 shrink-0 place-items-center rounded-full bg-slate-100 text-xs font-semibold text-slate-600">{{ initials(s.name) }}</span>
                  <div class="min-w-0">
                    <div class="truncate font-medium">{{ s.name }}</div>
                    <button class="truncate text-xs text-slate-500 hover:text-indigo-600" title="Copy email" @click="copyText(s.email, 'Email copied')">{{ s.email }}</button>
                  </div>
                </div>
              </td>
              <td class="td hidden sm:table-cell">
                <span class="font-medium">{{ s.submission_count }}</span><span class="text-slate-400"> / {{ total }}</span>
              </td>
              <td class="td text-right">
                <button class="icon-btn opacity-60 group-hover:opacity-100 hover:bg-rose-50 hover:text-rose-600" :title="`Remove ${s.name}`" @click="remove(s)">
                  <Icon name="user-minus" />
                </button>
              </td>
            </tr>
            <tr v-if="!students.length">
              <td colspan="3" class="px-4 py-10 text-center text-sm text-slate-500">No students match “{{ q }}”.</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>
