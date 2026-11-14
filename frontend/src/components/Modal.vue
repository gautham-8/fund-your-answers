<script setup>
import { nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import Icon from './Icon.vue'

const props = defineProps({
  open: Boolean,
  title: String,
  description: String,
  size: { type: String, default: 'md' },
})
const emit = defineEmits(['close'])
const panel = ref(null)
const SIZES = { sm: 'sm:max-w-sm', md: 'sm:max-w-lg', lg: 'sm:max-w-2xl' }

function onKey(e) {
  if (e.key === 'Escape' && props.open) emit('close')
}
onMounted(() => window.addEventListener('keydown', onKey))
onUnmounted(() => window.removeEventListener('keydown', onKey))

// Focus the first field when opened.
watch(
  () => props.open,
  async (open) => {
    if (!open) return
    await nextTick()
    panel.value?.querySelector('input:not([type=hidden]), textarea, select')?.focus()
  },
)
</script>

<template>
  <Teleport to="body">
    <Transition name="modal">
      <div v-if="open" class="fixed inset-0 z-50 flex items-end justify-center sm:items-center sm:p-4">
        <div class="absolute inset-0 bg-slate-900/40 backdrop-blur-[2px]" @click="emit('close')"></div>
        <div
          ref="panel"
          role="dialog"
          aria-modal="true"
          :aria-label="title"
          class="modal-panel relative flex max-h-[92vh] w-full flex-col rounded-t-2xl bg-white shadow-2xl ring-1 ring-slate-900/5 sm:rounded-2xl"
          :class="SIZES[size]"
        >
          <div class="flex items-start justify-between gap-4 px-6 pt-5 pb-3">
            <div>
              <h2 class="text-base font-semibold text-slate-900">{{ title }}</h2>
              <p v-if="description" class="mt-0.5 text-sm text-slate-500">{{ description }}</p>
            </div>
            <button type="button" class="icon-btn -mt-1 -mr-2" aria-label="Close" @click="emit('close')"><Icon name="x" /></button>
          </div>
          <div class="overflow-y-auto px-6 pt-1 pb-5"><slot /></div>
          <div v-if="$slots.footer" class="flex justify-end gap-2 rounded-b-2xl border-t border-slate-100 bg-slate-50/70 px-6 py-3">
            <slot name="footer" />
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>
