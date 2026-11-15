import { onUnmounted, ref } from 'vue'
import { getDocument, GlobalWorkerOptions } from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import { blobUrl } from './api'

GlobalWorkerOptions.workerSrc = workerUrl

/**
 * Render a protected PDF's pages to images with pdf.js.
 * `images[n - 1]` is an object URL for page n (null until rendered). Cleans up when the component unmounts.
 */
export function usePdfPages({ width = 1400 } = {}) {
  const images = ref([])
  const count = ref(0)
  let pdf = null
  let task = null
  let url = null
  let alive = true

  async function open(path) {
    url = await blobUrl(path)
    task = getDocument({ url })
    pdf = await task.promise
    count.value = pdf.numPages
    images.value = Array(pdf.numPages).fill(null)
    return pdf.numPages
  }

  /** Render page n (1-based), turned `rotation` degrees clockwise on top of the PDF's own rotation. */
  async function render(n, rotation = 0) {
    if (!pdf || !alive) return
    const page = await pdf.getPage(n)
    const rot = (page.rotate + rotation) % 360
    const base = page.getViewport({ scale: 1, rotation: rot })
    const viewport = page.getViewport({ scale: width / base.width, rotation: rot })
    const canvas = document.createElement('canvas')
    canvas.width = viewport.width
    canvas.height = viewport.height
    await page.render({ canvas, viewport }).promise
    const blob = await new Promise((r) => canvas.toBlob(r, 'image/jpeg', 0.85))
    if (!alive) return
    if (images.value[n - 1]) URL.revokeObjectURL(images.value[n - 1])
    images.value[n - 1] = URL.createObjectURL(blob)
  }

  /** Render pages one after another (the first ones you pass show up first). */
  async function renderAll(pages, rotationOf = () => 0) {
    for (const n of pages) if (alive) await render(n, rotationOf(n))
  }

  onUnmounted(() => {
    alive = false
    images.value.forEach((u) => u && URL.revokeObjectURL(u))
    if (url) URL.revokeObjectURL(url)
    // pdf.js v6 only has destroy() on the loading task (not the document). It also cancels a load still in
    // progress. Never let cleanup throw: an error in an unmount hook stops the next page from rendering.
    task?.destroy().catch(() => {})
  })

  return { images, count, open, render, renderAll }
}
