<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { api } from '../lib/api'
import { startRecording } from '../lib/recorder'
import Icon from '../components/Icon.vue'

const props = defineProps({ id: String })
const MAX_SECONDS = 180
const PREP_SECONDS = 60

const state = ref(null)
const error = ref('')
const phase = ref('idle') // idle | starting | recording | processing
const seconds = ref(0)
const typing = ref(false)
const typed = ref('')
const lastTranscript = ref('')
const prepLeft = ref(0) // seconds of preparation left before recording auto-starts; 0 = no countdown
const hasVideo = ref(false)
const preview = ref(null) // <video> element for the live camera preview
let rec = null
let tick = null
let prepTimer = null

const current = computed(() => state.value?.current)
const done = computed(() => state.value && !current.value && ['scoring', 'completed', 'scoring_failed'].includes(state.value.status))
const progress = computed(() => {
  if (!state.value) return 0
  return Math.round((state.value.answered_questions / Math.max(1, state.value.total_questions)) * 100)
})
const fmt = (s) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
const clock = computed(() => fmt(seconds.value))
const prepClock = computed(() => fmt(prepLeft.value))
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

function stopPrep() {
  clearInterval(prepTimer)
  prepTimer = null
  prepLeft.value = 0
}

// Each new question gets a prep countdown; recording starts by itself when it runs out.
function startPrep() {
  stopPrep()
  if (!micSupported || typing.value) return
  prepLeft.value = PREP_SECONDS
  prepTimer = setInterval(() => {
    prepLeft.value--
    if (prepLeft.value <= 0) {
      stopPrep()
      if (phase.value === 'idle' && !typing.value) startRec()
    }
  }, 1000)
}

const questionKey = computed(() =>
  state.value?.consent_given && current.value ? `${current.value.question_index}-${current.value.kind}` : null,
)
watch(questionKey, (key) => (key ? startPrep() : stopPrep()))
watch(typing, (t) => t && stopPrep())

async function startRec() {
  stopPrep()
  if (phase.value !== 'idle') return
  error.value = ''
  phase.value = 'starting'
  try {
    rec = await startRecording({ video: true })
  } catch {
    phase.value = 'idle'
    error.value = 'Could not access your microphone. Allow mic access in your browser, or type your answer instead.'
    return
  }
  hasVideo.value = rec.hasVideo
  phase.value = 'recording'
  await nextTick()
  if (preview.value && rec?.hasVideo) preview.value.srcObject = rec.stream
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
    // The video is only captured locally — we upload the audio and let the video go.
    const { audio } = await rec.stop()
    rec = null
    await send({ audio })
  } catch (e) {
    error.value = e.message
    phase.value = 'idle'
  }
}

function cancelRec() {
  stopPrep()
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
  <div class="mx-auto max-w-2xl animate-fade-up">
    <p v-if="error" class="error-box mb-4">{{ error }}</p>
    <div v-if="!state && !error" class="space-y-4">
      <div class="skeleton h-3 w-full"></div>
      <div class="skeleton h-64 w-full rounded-2xl"></div>
    </div>

    <template v-if="state">
      <!-- Not ready -->
      <div v-if="state.status === 'analyzing'" class="card flex items-center gap-3 text-slate-600">
        <span class="size-4 animate-spin rounded-full border-2 border-indigo-200 border-t-indigo-600"></span>
        Your PDF is still being analyzed. Please check back in a minute.
      </div>
      <div v-else-if="state.status === 'analysis_failed'" class="card text-slate-600">
        We couldn't analyze your PDF. Go back to the assignment to retry or upload again.
      </div>
      <div v-else-if="state.status === 'off_topic'" class="card space-y-1 text-slate-600">
        <p class="font-medium text-slate-800">Your PDF doesn't seem to answer this assignment's questions.</p>
        <p v-if="state.relevance_note" class="text-sm">{{ state.relevance_note }}</p>
        <p class="text-sm">Go back to the assignment and upload the right file. If you think this is a mistake, your instructor can let it through.</p>
      </div>

      <div v-else-if="state.pages_pending" class="card text-slate-600">
        First confirm which pages answer each question on the assignment page, then come back to start the viva.
      </div>

      <!-- Consent -->
      <div v-else-if="!state.consent_given && current" class="card space-y-6 p-7">
        <div class="grid size-12 place-items-center rounded-2xl bg-linear-to-br from-indigo-500 to-violet-600 text-white shadow-sm shadow-indigo-500/30">
          <Icon name="mic" :size="22" />
        </div>
        <div>
          <h1 class="text-2xl font-semibold tracking-tight">Before you start</h1>
          <p class="mt-1 text-slate-500">{{ state.total_questions }} questions about the methods and decisions in your own submission. Some may have one follow-up.</p>
        </div>
        <ul class="space-y-3 text-sm text-slate-700">
          <li class="flex gap-3"><Icon name="mic" class="mt-0.5 text-indigo-500" /><span><b>Recording notice:</b> you get 1 minute to prepare for each question, then recording starts automatically (you can start sooner). Your camera is on while you answer; the video stays on your device and is not uploaded. Your spoken answers are recorded, transcribed by an AI service (Google Gemini), and stored so your instructor can listen and read the transcript.</span></li>
          <li class="flex gap-3"><Icon name="chart" class="mt-0.5 text-indigo-500" /><span>The AI produces an <b>understanding score</b> your instructor reviews and can change. It's one part of your grade, next to a human grader's mark for your written solution. It doesn't judge accent, pauses, or phrasing — only content.</span></li>
          <li class="flex gap-3"><Icon name="keyboard" class="mt-0.5 text-indigo-500" /><span>Prefer not to be recorded? You can type your answers instead.</span></li>
        </ul>
        <button class="btn-primary w-full py-2.5 sm:w-auto" @click="consent">I understand — start<Icon name="arrow-right" /></button>
      </div>

      <!-- Done -->
      <div v-else-if="done" class="card space-y-4 py-12 text-center">
        <div class="mx-auto grid size-16 place-items-center rounded-full bg-emerald-50 text-emerald-600 ring-8 ring-emerald-50/50"><Icon name="check" :size="30" :stroke="2.5" /></div>
        <h1 class="text-2xl font-semibold tracking-tight">Viva complete</h1>
        <p class="mx-auto max-w-sm text-slate-500">Thanks! Your answers have been submitted. You'll see your grade once your instructor publishes it.</p>
        <RouterLink to="/" class="btn-secondary">Back to dashboard</RouterLink>
      </div>

      <!-- Question -->
      <div v-else-if="current" class="space-y-5">
        <div>
          <div class="mb-2 flex justify-between text-xs font-medium text-slate-500">
            <span>Question {{ current.question_index + 1 }} of {{ state.total_questions }}</span>
            <span>{{ progress }}% done</span>
          </div>
          <div class="flex gap-1.5">
            <span
              v-for="n in state.total_questions"
              :key="n"
              class="h-1.5 flex-1 rounded-full transition-colors"
              :class="n <= state.answered_questions ? 'bg-indigo-500' : n === current.question_index + 1 ? 'bg-indigo-200' : 'bg-slate-200'"
            ></span>
          </div>
        </div>

        <div v-if="lastTranscript" class="flex gap-2.5 rounded-xl bg-white p-3.5 text-sm text-slate-600 ring-1 ring-slate-200">
          <Icon name="check-circle" class="mt-0.5 text-emerald-500" />
          <span><span class="font-medium text-slate-800">We heard:</span> “{{ lastTranscript }}”</span>
        </div>

        <div class="card space-y-8 p-7">
          <div>
            <div class="mb-3 flex items-center justify-between">
              <span class="inline-flex items-center gap-1.5 rounded-full bg-indigo-50 px-2.5 py-1 text-xs font-semibold text-indigo-700">
                <Icon name="sparkles" :size="12" />{{ current.kind === 'followup' ? 'Follow-up' : 'Question' }}
              </span>
              <button class="btn-ghost btn-sm" @click="speak"><Icon name="volume" :size="14" />Read aloud</button>
            </div>
            <p class="text-xl leading-relaxed font-medium tracking-tight text-slate-900">{{ current.question }}</p>
          </div>

          <div v-if="phase === 'processing'" class="flex flex-col items-center gap-3 py-6 text-slate-600">
            <span class="size-8 animate-spin rounded-full border-[3px] border-indigo-100 border-t-indigo-600"></span>
            Processing your answer…
          </div>

          <template v-else-if="!typing">
            <div class="flex flex-col items-center gap-4 py-2">
              <template v-if="phase === 'idle'">
                <button
                  class="group relative grid size-20 place-items-center rounded-full bg-linear-to-br from-indigo-500 to-violet-600 text-white shadow-lg shadow-indigo-500/30 transition hover:scale-105 active:scale-95 disabled:opacity-50"
                  :disabled="!micSupported"
                  aria-label="Record answer"
                  @click="startRec"
                >
                  <Icon name="mic" :size="30" />
                </button>
                <template v-if="prepLeft > 0">
                  <span class="text-sm font-medium text-slate-700">
                    Recording starts in <span class="font-mono font-semibold text-indigo-600">{{ prepClock }}</span>
                  </span>
                  <div class="h-1 w-48 overflow-hidden rounded-full bg-slate-200">
                    <div class="h-full bg-indigo-500 transition-[width] duration-1000 ease-linear" :style="{ width: `${(prepLeft / PREP_SECONDS) * 100}%` }"></div>
                  </div>
                  <button class="btn-secondary btn-sm" @click="startRec">I'm ready — start now</button>
                </template>
                <span v-else class="text-sm font-medium text-slate-700">Tap to record your answer</span>
              </template>
              <div v-else-if="phase === 'starting'" class="flex items-center gap-2 py-6 text-sm text-slate-600">
                <span class="size-4 animate-spin rounded-full border-2 border-indigo-200 border-t-indigo-600"></span>
                Turning on your camera and microphone…
              </div>
              <template v-else-if="phase === 'recording'">
                <div v-if="hasVideo" class="relative w-full max-w-sm overflow-hidden rounded-2xl bg-slate-900 ring-1 ring-slate-200">
                  <video ref="preview" autoplay muted playsinline class="aspect-[4/3] w-full -scale-x-100 object-cover"></video>
                  <span class="absolute top-2 left-2 rounded-full bg-black/50 px-2 py-0.5 text-[11px] font-medium text-white">Not uploaded</span>
                </div>
                <p v-else class="text-xs text-slate-500">Camera unavailable — recording audio only.</p>
                <button class="relative grid size-20 place-items-center rounded-full bg-rose-600 text-white shadow-lg shadow-rose-500/30 transition hover:bg-rose-500" aria-label="Stop and submit" @click="stopRec">
                  <span class="absolute inset-0 animate-ping rounded-full bg-rose-500/40"></span>
                  <Icon name="stop" :size="26" class="relative" />
                </button>
                <span class="flex items-center gap-2 font-mono text-lg font-semibold text-rose-600">
                  <span class="size-2 animate-pulse rounded-full bg-rose-600"></span>{{ clock }}
                </span>
                <div class="flex gap-2">
                  <button class="btn-danger" @click="stopRec">Stop &amp; submit</button>
                  <button class="btn-secondary" @click="cancelRec">Cancel</button>
                </div>
              </template>
            </div>
            <div class="flex flex-col items-center gap-2 border-t border-slate-100 pt-5 text-center">
              <p class="text-xs text-slate-500">Use the minute to think it through, then speak naturally — up to 3 minutes per answer.</p>
              <button v-if="phase === 'idle'" class="btn-ghost btn-sm" @click="typing = true"><Icon name="keyboard" :size="14" />Type instead</button>
            </div>
          </template>

          <div v-else class="space-y-3">
            <textarea v-model="typed" class="input text-base" rows="6" placeholder="Type your answer…"></textarea>
            <div class="flex items-center justify-between gap-3">
              <button v-if="micSupported" class="btn-ghost btn-sm" @click="typing = false"><Icon name="mic" :size="14" />Record instead</button>
              <button class="btn-primary ml-auto" :disabled="!typed.trim()" @click="sendTyped"><Icon name="send" />Submit answer</button>
            </div>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>
