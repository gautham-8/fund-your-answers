<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { api } from '../lib/api'
import { startRecording } from '../lib/recorder'

const props = defineProps({ id: String })
const MAX_SECONDS = 180

const state = ref(null)
const error = ref('')
const phase = ref('idle') // idle | recording | processing
const seconds = ref(0)
const typing = ref(false)
const typed = ref('')
const lastTranscript = ref('')
let rec = null
let tick = null

const current = computed(() => state.value?.current)
const done = computed(() => state.value && !current.value && ['scoring', 'completed', 'scoring_failed'].includes(state.value.status))
const progress = computed(() => {
  if (!state.value) return 0
  return Math.round((state.value.answered_questions / Math.max(1, state.value.total_questions)) * 100)
})
const clock = computed(() => `${Math.floor(seconds.value / 60)}:${String(seconds.value % 60).padStart(2, '0')}`)
const micSupported = typeof navigator !== 'undefined' && !!navigator.mediaDevices?.getUserMedia && typeof MediaRecorder !== 'undefined'

async function load() {
  try {
    state.value = await api(`/api/submissions/${props.id}/viva`)
  } catch (e) {
    error.value = e.message
  }
}

async function consent() {
  state.value = await api(`/api/submissions/${props.id}/viva/consent`, { method: 'POST' })
}

function speak() {
  if (!current.value || !window.speechSynthesis) return
  window.speechSynthesis.cancel()
  window.speechSynthesis.speak(new SpeechSynthesisUtterance(current.value.question))
}

async function startRec() {
  error.value = ''
  try {
    rec = await startRecording()
  } catch {
    error.value = 'Could not access your microphone. Allow mic access in your browser, or type your answer instead.'
    return
  }
  phase.value = 'recording'
  seconds.value = 0
  tick = setInterval(() => {
    seconds.value++
    if (seconds.value >= MAX_SECONDS) stopRec()
  }, 1000)
}

async function stopRec() {
  clearInterval(tick)
  if (!rec) return
  phase.value = 'processing'
  try {
    const wav = await rec.stop()
    rec = null
    await send({ audio: wav })
  } catch (e) {
    error.value = e.message
    phase.value = 'idle'
  }
}

function cancelRec() {
  clearInterval(tick)
  rec?.cancel()
  rec = null
  phase.value = 'idle'
}

async function sendTyped() {
  if (!typed.value.trim()) return
  phase.value = 'processing'
  await send({ text: typed.value })
}

async function send({ audio, text }) {
  error.value = ''
  const form = new FormData()
  form.append('question_index', current.value.question_index)
  form.append('kind', current.value.kind)
  if (audio) form.append('audio', audio, 'answer.wav')
  if (text) form.append('text', text)
  try {
    const res = await api(`/api/submissions/${props.id}/viva/answer`, { method: 'POST', form })
    lastTranscript.value = res.last_transcript
    state.value = res
    typed.value = ''
    typing.value = false
  } catch (e) {
    error.value = e.message
    if (e.message.includes('already been answered')) await load()
  } finally {
    phase.value = 'idle'
  }
}

onMounted(load)
onUnmounted(() => {
  cancelRec()
  window.speechSynthesis?.cancel()
})
</script>

<template>
  <div class="mx-auto max-w-2xl">
    <p v-if="error" class="error-box mb-4">{{ error }}</p>
    <p v-if="!state && !error" class="text-slate-500">Loading…</p>

    <template v-if="state">
      <!-- Not ready -->
      <div v-if="state.status === 'analyzing'" class="card">Your PDF is still being analyzed. Please check back in a minute.</div>
      <div v-else-if="state.status === 'analysis_failed'" class="card">
        We couldn't analyze your PDF. Go back to the assignment to retry or upload again.
      </div>

      <!-- Consent -->
      <div v-else-if="!state.consent_given && current" class="card space-y-4">
        <h1 class="text-xl font-bold">Before you start</h1>
        <div class="space-y-2 text-sm text-slate-700">
          <p>You'll be asked <b>{{ state.total_questions }} questions</b> about the methods and decisions in your own submission. Some may have one follow-up.</p>
          <p><b>Recording notice:</b> your spoken answers will be recorded, transcribed by an AI service (Google Gemini), and stored so your instructor can listen to them and read the transcript.</p>
          <p>The AI produces an <b>understanding score</b> that your instructor reviews and can change. It does not judge accent, pauses, or phrasing — only the content of your answers.</p>
          <p>If you'd rather not be recorded, you can type your answers instead.</p>
        </div>
        <button class="btn-primary" @click="consent">I understand — start</button>
      </div>

      <!-- Done -->
      <div v-else-if="done" class="card space-y-3 text-center">
        <div class="text-4xl">✓</div>
        <h1 class="text-xl font-bold">Viva complete</h1>
        <p class="text-slate-600">Thanks! Your answers have been submitted. Your instructor will review the results.</p>
        <RouterLink to="/" class="btn-secondary">Back to classes</RouterLink>
      </div>

      <!-- Question -->
      <div v-else-if="current" class="space-y-4">
        <div>
          <div class="mb-1 flex justify-between text-xs text-slate-500">
            <span>Question {{ current.question_index + 1 }} of {{ state.total_questions }}</span>
            <span>{{ progress }}%</span>
          </div>
          <div class="h-2 rounded-full bg-slate-200">
            <div class="h-2 rounded-full bg-indigo-600 transition-all" :style="{ width: progress + '%' }"></div>
          </div>
        </div>

        <div v-if="lastTranscript" class="rounded-lg bg-slate-100 p-3 text-sm text-slate-600">
          <span class="font-medium">We heard:</span> “{{ lastTranscript }}”
        </div>

        <div class="card space-y-5">
          <div>
            <div class="mb-2 text-xs font-semibold uppercase tracking-wide text-indigo-600">
              {{ current.kind === 'followup' ? 'Follow-up' : 'Question' }}
            </div>
            <p class="text-lg leading-relaxed">{{ current.question }}</p>
            <button class="mt-2 text-sm text-indigo-600 hover:underline" @click="speak">🔊 Read aloud</button>
          </div>

          <div v-if="phase === 'processing'" class="flex items-center gap-3 text-slate-600">
            <span class="h-4 w-4 animate-spin rounded-full border-2 border-indigo-600 border-t-transparent"></span>
            Processing your answer…
          </div>

          <template v-else-if="!typing">
            <div v-if="phase === 'idle'" class="flex flex-wrap items-center gap-3">
              <button class="btn-primary" :disabled="!micSupported" @click="startRec">🎙 Record answer</button>
              <button class="text-sm text-slate-600 hover:underline" @click="typing = true">Type instead</button>
            </div>
            <div v-else-if="phase === 'recording'" class="flex flex-wrap items-center gap-3">
              <span class="flex items-center gap-2 font-mono text-rose-600">
                <span class="h-3 w-3 animate-pulse rounded-full bg-rose-600"></span>{{ clock }}
              </span>
              <button class="btn-danger" @click="stopRec">Stop &amp; submit</button>
              <button class="btn-secondary" @click="cancelRec">Cancel</button>
            </div>
            <p class="text-xs text-slate-500">Take your time. Speak naturally — up to 3 minutes per answer.</p>
          </template>

          <div v-else class="space-y-3">
            <textarea v-model="typed" class="input" rows="5" placeholder="Type your answer…"></textarea>
            <div class="flex gap-3">
              <button class="btn-primary" :disabled="!typed.trim()" @click="sendTyped">Submit answer</button>
              <button v-if="micSupported" class="text-sm text-slate-600 hover:underline" @click="typing = false">Record instead</button>
            </div>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>
