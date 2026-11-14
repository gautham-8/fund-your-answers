<script setup>
import { computed } from 'vue'

const props = defineProps({ value: Number, size: { type: Number, default: 96 }, label: String })
const R = 42
const C = 2 * Math.PI * R
const pct = computed(() => Math.max(0, Math.min(100, props.value ?? 0)))
const color = computed(() => (pct.value >= 80 ? 'text-emerald-500' : pct.value >= 60 ? 'text-amber-500' : 'text-rose-500'))
</script>

<template>
  <div class="relative inline-grid place-items-center" :style="{ width: size + 'px', height: size + 'px' }">
    <svg viewBox="0 0 100 100" class="absolute inset-0 -rotate-90">
      <circle cx="50" cy="50" :r="R" fill="none" stroke-width="8" class="stroke-slate-100" />
      <circle
        cx="50" cy="50" :r="R" fill="none" stroke-width="8" stroke-linecap="round" stroke="currentColor"
        :class="color" :stroke-dasharray="C" :stroke-dashoffset="C * (1 - pct / 100)"
        style="transition: stroke-dashoffset 0.8s cubic-bezier(0.2, 0.8, 0.2, 1)"
      />
    </svg>
    <div class="text-center leading-none">
      <div class="font-bold tracking-tight text-slate-900" :style="{ fontSize: size * 0.24 + 'px' }">
        {{ value != null ? Math.round(value) : '—' }}<span class="text-slate-400" :style="{ fontSize: size * 0.13 + 'px' }">%</span>
      </div>
      <div v-if="label" class="mt-1 text-[10px] font-medium tracking-wide text-slate-500 uppercase">{{ label }}</div>
    </div>
  </div>
</template>
