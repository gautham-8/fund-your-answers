<script setup>
import { dismiss, toasts } from '../lib/toast'
import Icon from './Icon.vue'

const ICON = { success: 'check-circle', error: 'alert', info: 'sparkles' }
const TONE = { success: 'text-emerald-400', error: 'text-rose-400', info: 'text-indigo-300' }
</script>

<template>
  <div class="pointer-events-none fixed inset-x-0 bottom-4 z-[60] flex flex-col items-center gap-2 px-4" aria-live="polite">
    <TransitionGroup name="toast">
      <div
        v-for="t in toasts"
        :key="t.id"
        class="pointer-events-auto flex items-center gap-2.5 rounded-xl bg-slate-900 py-2.5 pr-2 pl-3.5 text-sm text-white shadow-xl shadow-slate-900/20"
      >
        <Icon :name="ICON[t.type]" :class="TONE[t.type]" />
        <span>{{ t.message }}</span>
        <button class="ml-1 rounded-md p-1 text-slate-400 hover:bg-white/10 hover:text-white" aria-label="Dismiss" @click="dismiss(t.id)">
          <Icon name="x" :size="14" />
        </button>
      </div>
    </TransitionGroup>
  </div>
</template>
