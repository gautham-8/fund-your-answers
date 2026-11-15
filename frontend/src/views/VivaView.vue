<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { api, blobUrl } from '../lib/api'
import { startRecording } from '../lib/recorder'
import Icon from '../components/Icon.vue'

const props = defineProps({ id: String })
const MAX_SECONDS = 180
// Time to think before recording starts by itself. A real viva doesn't leave room to look an answer up, and
// follow-ups (where bluffing falls apart) get only a moment.
const PREP_SECONDS = { main: 20, followup: 5 }
const AWAY_MIN_MS = 1500 // ignore blips such as a permission prompt taking focus

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
const prepTotal = ref(PREP_SECONDS.main)

// Integrity signals for the open question: leaving the page and pasting. Sent with the answer and shown to the
// instructor as context only; they never change a score.
let away = { count: 0, ms: 0, since: null }
let pasted = 0
function resetSignals() {
  away = { count: 0, ms: 0, since: isAway() ? Date.now() : null }
  pasted = 0
}
function isAway() {
  return document.hidden || !document.hasFocus()
}
function onFocusChange() {
  if (!questionKey.value) return
  if (isAway() && away.since == null) away.since = Date.now()
  else if (!isAway() && away.since != null) closeAway()
}
function closeAway() {
  const ms = Date.now() - away.since
  away.since = null
  if (ms >= AWAY_MIN_MS) {
    away.count++
    away.ms += ms
  }
}
function signals() {
  if (away.since != null) closeAway()
  return { left_page_count: away.count, left_page_seconds: Math.round(away.ms / 1000), pasted_chars: pasted }
}
function onPaste(e) {
  pasted += (e.clipboardData?.getData('text') || '').length
}

const current = computed(() => state.value?.current)
const done = computed(() => state.value && !current.value && ['scoring', 'completed', 'scoring_failed'].includes(state.value.status))
const progress = computed(() => {
  if (!state.value) return 0
  return Math.round((state.value.answered_questions / Math.max(1, state.value.total_questions)) * 100)
})
const fmt = (s) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
const clock = computed(() => fmt(seconds.value))
const prepClock = computed(() => fmt(prepLeft.value))
// Typing is an accessibility accommodation: only offered once an instructor approves a request for this viva.
const accommodation = computed(() => state.value?.accommodation)
const canType = computed(() => accommodation.value?.status === 'approved')
const micSupported = typeof navigator !== 'undefined' && !!navigator.mediaDevices?.getUserMedia && typeof MediaRecorder !== 'undefined'

async function load() {
  try {
    state.value = await api(`/api/submissions/${props.id}/viva`)
  } catch (e) {
    error.value = e.message
  }
}

async function consent() {
  error.value = ''
  try {
    state.value = await api(`/api/submissions/${props.id}/viva/consent`, { method: 'POST' })
  } catch (e) {
    error.value = e.message
  }
}

const requestOpen = ref(false)
const reason = ref('')
const requesting = ref(false)

async function requestTyped() {
  requesting.value = true
  error.value = ''
  try {
    state.value.accommodation = await api(`/api/submissions/${props.id}/accommodation`, { method: 'POST', body: { reason: reason.value } })
    requestOpen.value = false
    reason.value = ''
  } catch (e) {
    error.value = e.message
  } finally {
    requesting.value = false
  }
}

async function withdrawRequest() {
  try {
    await api(`/api/submissions/${props.id}/accommodation`, { method: 'DELETE' })
    state.value.accommodation = null
  } catch (e) {
    error.value = e.message
  }
}

// While a request waits for the instructor, check back so the page updates on its own.
let pollTimer = null
watch(
  () => accommodation.value?.status === 'pending' && !state.value?.consent_given,
  (waiting) => {
    clearInterval(pollTimer)
    if (waiting) pollTimer = setInterval(load, 20000)
  },
)
watch(canType, (ok) => (typing.value = ok), { immediate: true })

// "Read aloud": a natural Gemini voice from the backend, falling back to the best voice the browser has.
const speaking = ref('') // '' | loading | playing
let player = null
let spokenKey = null
let spokenUrl = null

function stopSpeaking() {
  player?.pause()
  window.speechSynthesis?.cancel()
  speaking.value = ''
}

function browserVoice() {
  const voices = window.speechSynthesis.getVoices().filter((v) => v.lang.startsWith('en'))
  return (
    voices.find((v) => /natural|neural|online|premium|enhanced/i.test(v.name)) ??
    voices.find((v) => /google/i.test(v.name)) ??
    voices.find((v) => v.default) ??
    voices[0]
  )
}

function browserSpeak(text) {
  if (!window.speechSynthesis) return (speaking.value = '')
  const u = new SpeechSynthesisUtterance(text)
  const voice = browserVoice()
  if (voice) u.voice = voice
  u.rate = 0.95
  u.onend = u.onerror = () => (speaking.value = '')
  speaking.value = 'playing'
  window.speechSynthesis.speak(u)
}

async function speak() {
  if (!current.value) return
  if (speaking.value) return stopSpeaking()
  const key = questionKey.value
  const text = current.value.question
  if (spokenKey !== key) {
    if (spokenUrl) URL.revokeObjectURL(spokenUrl)
    spokenUrl = null
    spokenKey = key
    speaking.value = 'loading'
    try {
      spokenUrl = await blobUrl(`/api/submissions/${props.id}/viva/speech`)
    } catch {
      spokenKey = null
    }
    if (questionKey.value !== key || speaking.value !== 'loading') return // moved on or cancelled meanwhile
  }
  if (!spokenUrl) return browserSpeak(text)
  player ??= new Audio()
  player.src = spokenUrl
  player.onended = player.onerror = () => (speaking.value = '')
  speaking.value = 'playing'
  player.play().catch(() => browserSpeak(text))
}

function stopPrep() {
  clearInterval(prepTimer)
  prepTimer = null
  prepLeft.value = 0
}

// Each new question gets a prep countdown; recording starts by itself when it runs out.
function startPrep() {
  stopPrep()
  if (!micSupported || typing.value || canType.value) return
  prepTotal.value = PREP_SECONDS[current.value?.kind] ?? PREP_SECONDS.main
  prepLeft.value = prepTotal.value
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
watch(questionKey, (key) => {
  stopSpeaking()
  resetSignals()
  key ? startPrep() : stopPrep()
})
watch(typing, (t) => t && stopPrep())

async function startRec() {
  stopPrep()
  if (phase.value !== 'idle') return
  stopSpeaking() // don't record the question being read out
  error.value = ''
  phase.value = 'starting'
  try {
    rec = await startRecording({ video: true })
  } catch {
    phase.value = 'idle'
    error.value = canType.value
      ? 'Could not access your microphone. Allow mic access in your browser, or type your answer instead.'
      : 'Could not access your microphone. Allow mic access in your browser and try again.'
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
  for (const [k, v] of Object.entries(signals())) form.append(k, v)
  try {
    const res = await api(`/api/submissions/${props.id}/viva/answer`, { method: 'POST', form })
    lastTranscript.value = res.last_transcript
    state.value = res
    typed.value = ''
    typing.value = canType.value
  } catch (e) {
    error.value = e.message
    if (e.message.includes('already been answered')) await load()
  } finally {
    phase.value = 'idle'
  }
}

onMounted(() => {
  load()
  document.addEventListener('visibilitychange', onFocusChange)
  window.addEventListener('blur', onFocusChange)
  window.addEventListener('focus', onFocusChange)
})
onUnmounted(() => {
  document.removeEventListener('visibilitychange', onFocusChange)
  window.removeEventListener('blur', onFocusChange)
  window.removeEventListener('focus', onFocusChange)
  clearInterval(pollTimer)
  cancelRec()
  stopSpeaking()
  if (spokenUrl) URL.revokeObjectURL(spokenUrl)
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
          <li v-if="canType" class="flex gap-3"><Icon name="keyboard" class="mt-0.5 text-indigo-500" /><span><b>Typed answers:</b> your accommodation is approved, so you'll type your answers. They're assessed by an AI service (Google Gemini) and stored so your instructor can read them. You can still record an answer if you prefer. Stay on this page while a question is open: your instructor sees if you leave it or paste text in. This alone doesn't affect your score.</span></li>
          <li v-else class="flex gap-3"><Icon name="mic" class="mt-0.5 text-indigo-500" /><span><b>Recording notice:</b> you get 20 seconds to think about each question and a few seconds for follow-ups, then recording starts automatically (you can start sooner). Stay on this page while a question is open: your instructor sees if you leave it or paste text in. This alone doesn't affect your score. Your camera is on while you answer; the video stays on your device and is not uploaded. Your spoken answers are recorded, transcribed by an AI service (Google Gemini), and stored so your instructor can listen and read the transcript.</span></li>
          <li class="flex gap-3"><Icon name="chart" class="mt-0.5 text-indigo-500" /><span>The AI produces an <b>understanding score</b> your instructor reviews and can change. It's one part of your grade, next to a human grader's mark for your written solution. It doesn't judge accent, pauses, or phrasing — only content.</span></li>
        </ul>

        <!-- Accessibility accommodation: typed answers for the whole viva, decided before it starts -->
        <div class="rounded-xl border border-slate-200 p-4 text-sm">
          <template v-if="accommodation?.status === 'pending'">
            <div class="flex flex-wrap items-start justify-between gap-3">
              <div class="flex gap-3">
                <span class="mt-1.5 size-2 shrink-0 animate-pulse rounded-full bg-amber-500"></span>
                <div>
                  <p class="font-medium text-slate-800">Typed-answer request sent — waiting for your instructor</p>
                  <p class="mt-0.5 text-slate-500">You can start once they decide. This page updates by itself.</p>
                </div>
              </div>
              <button class="btn-ghost btn-sm" @click="withdrawRequest">Withdraw &amp; answer by voice</button>
            </div>
          </template>
          <template v-else-if="accommodation?.status === 'approved'">
            <p class="flex items-center gap-2 font-medium text-emerald-700"><Icon name="check-circle" :size="16" />Typed answers approved for this viva</p>
            <p v-if="accommodation.response" class="mt-1 text-slate-600">{{ accommodation.decided_by }}: “{{ accommodation.response }}”</p>
          </template>
          <template v-else>
            <div v-if="accommodation?.status === 'denied'" class="mb-3 rounded-lg bg-rose-50 p-3 text-rose-800">
              <p class="font-medium">Your typed-answer request wasn't approved, so this viva is by voice.</p>
              <p v-if="accommodation.response" class="mt-1">{{ accommodation.decided_by }}: “{{ accommodation.response }}”</p>
            </div>
            <div v-if="!requestOpen" class="flex flex-wrap items-center justify-between gap-3">
              <p class="flex gap-3 text-slate-600">
                <Icon name="keyboard" class="mt-0.5 shrink-0 text-slate-400" />
                <span>Have an accommodation that makes speaking difficult? Ask to <b>type your answers</b> for this whole viva. You need to ask before you start.</span>
              </p>
              <button class="btn-secondary btn-sm" @click="requestOpen = true">{{ accommodation?.status === 'denied' ? 'Ask again' : 'Request typed answers' }}</button>
            </div>
            <form v-else class="space-y-3" @submit.prevent="requestTyped">
              <label class="label" for="acc-reason">Why do you need typed answers?</label>
              <textarea id="acc-reason" v-model="reason" class="input" rows="3" maxlength="2000" placeholder="e.g. Registered with disability services for a speech impairment"></textarea>
              <p class="text-xs text-slate-500">Only your instructor sees this. You can't start the viva until they decide.</p>
              <div class="flex justify-end gap-2">
                <button type="button" class="btn-secondary btn-sm" @click="requestOpen = false">Cancel</button>
                <button class="btn-primary btn-sm" :disabled="!reason.trim() || requesting">{{ requesting ? 'Sending…' : 'Send request' }}</button>
              </div>
            </form>
          </template>
        </div>

        <p v-if="!micSupported && !canType" class="text-sm text-rose-700">This browser can't record audio. Open the viva in an up-to-date Chrome, Edge, Firefox or Safari.</p>
        <button class="btn-primary w-full py-2.5 sm:w-auto" :disabled="accommodation?.status === 'pending' || requestOpen || (!micSupported && !canType)" @click="consent">
          I understand — start<Icon name="arrow-right" />
        </button>
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
          <span><span class="font-medium text-slate-800">{{ canType ? 'We got:' : 'We heard:' }}</span> “{{ lastTranscript }}”</span>
        </div>

        <div class="card space-y-8 p-7">
          <div>
            <div class="mb-3 flex items-center justify-between">
              <span class="inline-flex items-center gap-1.5 rounded-full bg-indigo-50 px-2.5 py-1 text-xs font-semibold text-indigo-700">
                <Icon name="sparkles" :size="12" />{{ current.kind === 'followup' ? 'Follow-up' : 'Question' }}
              </span>
              <button class="btn-ghost btn-sm" :disabled="phase !== 'idle'" @click="speak">
                <span v-if="speaking === 'loading'" class="size-3.5 animate-spin rounded-full border-2 border-slate-200 border-t-slate-600"></span>
                <Icon v-else :name="speaking === 'playing' ? 'stop' : 'volume'" :size="14" />{{ speaking ? 'Stop' : 'Read aloud' }}
              </button>
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
                    <div class="h-full bg-indigo-500 transition-[width] duration-1000 ease-linear" :style="{ width: `${(prepLeft / prepTotal) * 100}%` }"></div>
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
              <button v-if="phase === 'idle' && canType" class="btn-ghost btn-sm" @click="typing = true"><Icon name="keyboard" :size="14" />Type instead</button>
            </div>
          </template>

          <div v-else class="space-y-3">
            <textarea v-model="typed" class="input text-base" rows="6" placeholder="Type your answer…" @paste="onPaste"></textarea>
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
