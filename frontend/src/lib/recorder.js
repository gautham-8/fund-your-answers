/**
 * Record audio with MediaRecorder, then convert to 16 kHz mono WAV.
 * WAV is accepted by Gemini and plays in every browser, unlike WebM/Opus.
 */
export async function startRecording() {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
  const recorder = new MediaRecorder(stream)
  const chunks = []
  recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data)
  recorder.start()

  const stopTracks = () => stream.getTracks().forEach((t) => t.stop())

  return {
    async stop() {
      await new Promise((resolve) => {
        recorder.onstop = resolve
        recorder.stop()
      })
      stopTracks()
      const raw = new Blob(chunks, { type: recorder.mimeType })
      return toWav(raw)
    },
    cancel() {
      if (recorder.state !== 'inactive') recorder.stop()
      stopTracks()
    },
  }
}

async function toWav(blob, sampleRate = 16000) {
  const buf = await blob.arrayBuffer()
  const ctx = new AudioContext()
  const decoded = await ctx.decodeAudioData(buf)
  await ctx.close()

  const length = Math.ceil(decoded.duration * sampleRate)
  const offline = new OfflineAudioContext(1, length, sampleRate)
  const src = offline.createBufferSource()
  src.buffer = decoded
  src.connect(offline.destination)
  src.start()
  const rendered = await offline.startRendering()
  return encodeWav(rendered.getChannelData(0), sampleRate)
}

function encodeWav(samples, sampleRate) {
  const buffer = new ArrayBuffer(44 + samples.length * 2)
  const view = new DataView(buffer)
  const write = (o, s) => [...s].forEach((c, i) => view.setUint8(o + i, c.charCodeAt(0)))

  write(0, 'RIFF')
  view.setUint32(4, 36 + samples.length * 2, true)
  write(8, 'WAVE')
  write(12, 'fmt ')
  view.setUint32(16, 16, true)
  view.setUint16(20, 1, true) // PCM
  view.setUint16(22, 1, true) // mono
  view.setUint32(24, sampleRate, true)
  view.setUint32(28, sampleRate * 2, true)
  view.setUint16(32, 2, true)
  view.setUint16(34, 16, true)
  write(36, 'data')
  view.setUint32(40, samples.length * 2, true)

  let o = 44
  for (let i = 0; i < samples.length; i++, o += 2) {
    const s = Math.max(-1, Math.min(1, samples[i]))
    view.setInt16(o, s < 0 ? s * 0x8000 : s * 0x7fff, true)
  }
  return new Blob([view], { type: 'audio/wav' })
}
