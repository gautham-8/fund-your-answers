<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { getDocument, GlobalWorkerOptions } from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import { api, blobUrl } from '../lib/api'
import { toast } from '../lib/toast'
import Icon from '../components/Icon.vue'

GlobalWorkerOptions.workerSrc = workerUrl

const props = defineProps({ id: String })
const router = useRouter()
const RENDER_WIDTH = 1400 // px; sharp enough for the single-page view, reused for thumbnails

const sub = ref(null)
const error = ref('')
const pages = ref([]) // per question: selected page numbers
const images = ref([]) // object URL per rendered page, index = page - 1
const pageCount = ref(0)
const active = ref(0) // question being assigned
const viewing = ref(null) // page number shown large, null = grid
const saving = ref(false)
let pdfUrl = null

const parts = computed(() => sub.value?.parts || [])
const owners = (p) => pages.value.flatMap((list, i) => (list.includes(p) ? [i] : []))
const missing = computed(() => pages.value.filter((l) => !l.length).length)

async function load() {
  try {
    sub.value = await api(`/api/submissions/${props.id}`)
    if (!sub.value.page_map) return router.replace(`/assignments/${sub.value.assignment.id}`)
    pages.value = sub.value.page_map.map((l) => [...l])
    pdfUrl = await blobUrl(`/api/submissions/${props.id}/pdf`)
    const pdf = await getDocument({ url: pdfUrl }).promise
    pageCount.value = pdf.numPages
    for (let n = 1; n <= pdf.numPages; n++) {
      const page = await pdf.getPage(n)
      const base = page.getViewport({ scale: 1 })
      const viewport = page.getViewport({ scale: RENDER_WIDTH / base.width })
      const canvas = document.createElement('canvas')
      canvas.width = viewport.width
      canvas.height = viewport.height
      await page.render({ canvas, viewport }).promise
      const blob = await new Promise((r) => canvas.toBlob(r, 'image/jpeg', 0.85))
      images.value[n - 1] = URL.createObjectURL(blob)
    }
  } catch (e) {
    error.value = e.message
  }
}

function toggle(p) {
  const list = pages.value[active.value]
  const at = list.indexOf(p)
  if (at >= 0) list.splice(at, 1)
  else list.push(p), list.sort((a, b) => a - b)
}

function step(d) {
  viewing.value = Math.min(pageCount.value, Math.max(1, viewing.value + d))
}

function onKey(e) {
  if (viewing.value == null || e.target.closest('input, textarea')) return
  if (e.key === 'ArrowLeft') step(-1)
  else if (e.key === 'ArrowRight') step(1)
  else if (e.key === 'Escape') viewing.value = null
}

async function confirm() {
  saving.value = true
  try {
    await api(`/api/submissions/${props.id}/pages`, { method: 'PUT', body: { pages: pages.value } })
    toast('Pages confirmed. Your viva is ready')
    router.push(`/assignments/${sub.value.assignment.id}`)
  } catch (e) {
    toast(e.message, { type: 'error' })
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  load()
  window.addEventListener('keydown', onKey)
})
onUnmounted(() => {
  window.removeEventListener('keydown', onKey)
  images.value.forEach((u) => u && URL.revokeObjectURL(u))
  if (pdfUrl) URL.revokeObjectURL(pdfUrl)
})
</script>

<template>
  <div class="animate-fade-up">
    <p v-if="error" class="error-box mb-4">{{ error }}</p>
    <div v-if="!sub && !error" class="skeleton h-96 w-full rounded-2xl"></div>

    <template v-if="sub">
      <div class="mb-5 flex flex-wrap items-end justify-between gap-3">
        <div>
          <RouterLink :to="`/assignments/${sub.assignment.id}`" class="inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-900">
            <Icon name="chevron-left" :size="14" />{{ sub.assignment.title }}
          </RouterLink>
          <h1 class="mt-1 text-2xl font-semibold tracking-tight">Select answer pages</h1>
          <p class="mt-1 text-sm text-slate-500">Pick a question on the right, then click every page that answers it. We pre-selected our best guess.</p>
        </div>
      </div>

      <div class="grid gap-6 lg:grid-cols-[1fr_20rem]">
        <!-- Pages -->
        <section class="min-w-0 rounded-2xl border border-slate-200/80 bg-slate-100/70 p-4">
          <div class="mb-3 flex flex-wrap items-center justify-between gap-2">
            <div class="text-sm text-slate-600">
              Assigning to <span class="font-semibold text-indigo-700">Q{{ active + 1 }}</span>
              <span class="text-slate-400"> · {{ pages[active].length }} page{{ pages[active].length === 1 ? '' : 's' }} selected</span>
            </div>
            <div v-if="viewing != null" class="flex items-center gap-2">
              <span class="text-sm text-slate-500">Page {{ viewing }} of {{ pageCount }}</span>
              <button :class="pages[active].includes(viewing) ? 'btn-secondary' : 'btn-primary'" class="btn-sm" @click="toggle(viewing)">
                <Icon :name="pages[active].includes(viewing) ? 'x' : 'check'" :size="14" />
                {{ pages[active].includes(viewing) ? `Remove from Q${active + 1}` : `Add to Q${active + 1}` }}
              </button>
              <button class="btn-secondary btn-sm" @click="viewing = null"><Icon name="panel" :size="14" />All pages</button>
            </div>
          </div>

          <!-- Grid of all pages -->
          <div v-if="viewing == null" class="grid grid-cols-2 gap-4 sm:grid-cols-3">
            <div v-for="p in pageCount || sub.page_count" :key="p" class="group relative">
              <button
                type="button"
                class="relative block w-full overflow-hidden rounded-lg border-2 bg-white shadow-xs transition"
                :class="pages[active].includes(p) ? 'border-indigo-600 ring-4 ring-indigo-600/15' : 'border-transparent hover:border-indigo-300'"
                :aria-pressed="pages[active].includes(p)"
                :title="pages[active].includes(p) ? `Remove page ${p} from Q${active + 1}` : `Add page ${p} to Q${active + 1}`"
                @click="toggle(p)"
              >
                <img v-if="images[p - 1]" :src="images[p - 1]" :alt="`Page ${p}`" class="block w-full" />
                <div v-else class="skeleton aspect-[8.5/11] w-full rounded-none"></div>
                <span
                  v-if="pages[active].includes(p)"
                  class="absolute top-2 right-2 grid size-7 place-items-center rounded-full bg-indigo-600 text-white shadow"
                ><Icon name="check" :size="16" /></span>
              </button>
              <div class="mt-1.5 flex items-center justify-between gap-1">
                <div class="flex flex-wrap items-center gap-1">
                  <span class="text-xs font-medium text-slate-500">Page {{ p }}</span>
                  <span
                    v-for="i in owners(p)"
                    :key="i"
                    class="rounded px-1.5 py-0.5 text-[11px] font-semibold"
                    :class="i === active ? 'bg-indigo-600 text-white' : 'bg-slate-200 text-slate-600'"
                  >Q{{ i + 1 }}</span>
                </div>
                <button class="icon-btn size-6 opacity-0 group-hover:opacity-100 focus:opacity-100" :title="`View page ${p}`" @click="viewing = p">
                  <Icon name="eye" :size="14" />
                </button>
              </div>
            </div>
          </div>

          <!-- Single page view -->
          <div v-else>
            <div class="relative mx-auto max-w-3xl">
              <img v-if="images[viewing - 1]" :src="images[viewing - 1]" :alt="`Page ${viewing}`" class="block w-full rounded-lg bg-white shadow-sm" />
              <div v-else class="skeleton aspect-[8.5/11] w-full"></div>
              <button class="absolute top-1/2 -left-3 grid size-10 -translate-y-1/2 place-items-center rounded-full border border-slate-200 bg-white shadow disabled:opacity-40" :disabled="viewing <= 1" title="Previous page" @click="step(-1)">
                <Icon name="chevron-left" />
              </button>
              <button class="absolute top-1/2 -right-3 grid size-10 -translate-y-1/2 place-items-center rounded-full border border-slate-200 bg-white shadow disabled:opacity-40" :disabled="viewing >= pageCount" title="Next page" @click="step(1)">
                <Icon name="chevron-right" />
              </button>
            </div>
          </div>
        </section>

        <!-- Questions -->
        <aside class="lg:sticky lg:top-6 lg:self-start">
          <div class="card p-0">
            <div class="border-b border-slate-100 px-4 py-3">
              <div class="eyebrow">Questions</div>
            </div>
            <ol class="divide-y divide-slate-100">
              <li v-for="(q, i) in parts" :key="i">
                <button
                  type="button"
                  class="w-full px-4 py-3 text-left transition"
                  :class="i === active ? 'bg-indigo-50 shadow-[inset_3px_0_0] shadow-indigo-600' : 'hover:bg-slate-50'"
                  @click="active = i"
                >
                  <div class="flex items-start gap-2">
                    <span class="mt-0.5 text-sm font-semibold" :class="i === active ? 'text-indigo-700' : 'text-slate-900'">Q{{ i + 1 }}</span>
                    <span class="line-clamp-2 text-sm text-slate-600">{{ q }}</span>
                  </div>
                  <div class="mt-2 flex flex-wrap gap-1 pl-7">
                    <span v-for="p in pages[i]" :key="p" class="rounded bg-white px-1.5 py-0.5 text-xs font-medium text-slate-700 ring-1 ring-slate-200">p. {{ p }}</span>
                    <span v-if="!pages[i].length" class="text-xs text-orange-600">No pages</span>
                  </div>
                </button>
              </li>
            </ol>
            <div class="space-y-2 border-t border-slate-100 p-4">
              <p v-if="missing" class="text-xs text-orange-600">{{ missing }} question{{ missing === 1 ? ' has' : 's have' }} no pages. Leave it empty only if you didn't answer it.</p>
              <button class="btn-primary w-full" :disabled="saving" @click="confirm"><Icon name="check" />{{ saving ? 'Confirming…' : 'Confirm pages' }}</button>
            </div>
          </div>
        </aside>
      </div>
    </template>
  </div>
</template>
