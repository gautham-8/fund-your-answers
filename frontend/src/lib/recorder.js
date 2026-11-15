/**
 * Record the answer with MediaRecorder, then convert the audio to 16 kHz mono WAV.
 * WAV is accepted by Gemini and plays in every browser, unlike WebM/Opus.
 *
 * With `video: true` the camera is captured too (falls back to audio-only if the
 * camera is unavailable). Only the audio is returned for upload; the video stays
 * in the browser — `stop()` hands it back as `video` for local use only.
 */
export async function startRecording({ video = false } = {}) {
  let stream
  let hasVideo = false
  if (video) {
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: { width: 640, height: 480, facingMode: 'user' } })
      hasVideo = true
    } catch {
      // No camera / camera denied: still let the student answer by voice.
    }
  }
  stream ??= await navigator.mediaDevices.getUserMedia({ audio: true })

  const audioRec = new MediaRecorder(new MediaStream(stream.getAudioTracks()))
  const audioChunks = []
  audioRec.ondataavailable = (e) => e.data.size && audioChunks.push(e.data)
  audioRec.start()

  let videoRec = null
  const videoChunks = []
  if (hasVideo) {
    videoRec = new MediaRecorder(stream)
    videoRec.ondataavailable = (e) => e.data.size && videoChunks.push(e.data)
    videoRec.start()
  }

  const stopTracks = () => stream.getTracks().forEach((t) => t.stop())
  const finish = (r) =>
    !r || r.state === 'inactive'
      ? Promise.resolve()
      : new Promise((resolve) => {
          r.onstop = resolve
          r.stop()
        })

  return {
    stream,
    hasVideo,
    async stop() {
      await Promise.all([finish(audioRec), finish(videoRec)])
      stopTracks()
      const raw = new Blob(audioChunks, { type: audioRec.mimeType })
      const videoBlob = videoRec ? new Blob(videoChunks, { type: videoRec.mimeType }) : null
      return { audio: await toWav(raw), video: videoBlob }
    },
    cancel() {
      if (audioRec.state !== 'inactive') audioRec.stop()
      if (videoRec && videoRec.state !== 'inactive') videoRec.stop()
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
