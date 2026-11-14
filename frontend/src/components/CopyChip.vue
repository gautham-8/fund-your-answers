<script setup>
import { ref } from 'vue'
import { copyText } from '../lib/clipboard'
import Icon from './Icon.vue'

const props = defineProps({
  value: { type: String, required: true },
  text: String, // what to copy, if different from what's shown
  message: String,
  size: { type: String, default: 'sm' },
})
const copied = ref(false)
let timer

async function copy() {
  await copyText(props.text ?? props.value, props.message || `Copied “${props.value}”`)
  copied.value = true
  clearTimeout(timer)
  timer = setTimeout(() => (copied.value = false), 1600)
}
</script>

<template>
  <button
    type="button"
    class="group inline-flex items-center gap-1.5 rounded-lg border font-mono font-semibold tracking-wider transition"
    :class="[
      copied ? 'border-emerald-300 bg-emerald-50 text-emerald-700' : 'border-dashed border-slate-300 bg-white text-slate-700 hover:border-indigo-400 hover:bg-indigo-50 hover:text-indigo-700',
      size === 'lg' ? 'px-3.5 py-2 text-lg' : 'px-2 py-0.5 text-xs',
    ]"
    :title="`Click to copy ${value}`"
    :aria-label="`Copy ${value}`"
    @click.stop.prevent="copy"
  >
    {{ value }}
    <Icon :name="copied ? 'check' : 'copy'" :size="size === 'lg' ? 16 : 12" :class="copied ? '' : 'opacity-40 group-hover:opacity-100'" />
  </button>
</template>
