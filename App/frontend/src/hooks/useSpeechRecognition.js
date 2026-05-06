import { useState, useRef, useCallback, useEffect } from 'react'
import { API_BASE } from '../api'

/**
 * 백엔드 faster-whisper 기반 STT 훅.
 *
 * 기존 webkitSpeechRecognition 은 Electron 에서 동작 불가 → MediaRecorder 로 교체.
 *
 * 동작:
 *   - MediaRecorder timeslice 1500ms 로 청크 녹음
 *   - 매 청크마다 누적 blob 을 POST /api/stt/transcribe?partial=true → setInterim
 *   - Web Audio API 로 RMS 측정 → 1.5초 침묵 감지 시 자동 정지
 *   - 정지 시 최종 transcribe 후 onFinal(text)
 *
 * @param {{ onFinal: (text: string) => void, silenceMs?: number, chunkMs?: number }} opts
 * @returns {{ listening: boolean, interim: string, toggle: () => void, stop: () => void }}
 */
export function useSpeechRecognition({ onFinal, silenceMs = 1500, chunkMs = 1500 }) {
  const [listening, setListening] = useState(false)
  const [interim, setInterim] = useState('')

  // mutable refs (re-render 회피)
  const mediaStreamRef = useRef(null)        // MediaStream from getUserMedia
  const recorderRef    = useRef(null)        // MediaRecorder
  const chunksRef      = useRef([])          // Blob[]  — 누적
  const audioCtxRef    = useRef(null)        // AudioContext
  const analyserRef    = useRef(null)        // AnalyserNode (VAD)
  const vadRafRef      = useRef(null)        // RAF id for VAD loop
  const lastVoiceAtRef = useRef(0)           // 마지막으로 음성 감지된 시각 (ms)
  const inflightRef    = useRef(false)       // partial transcribe in-flight
  const stoppedRef     = useRef(false)       // 사용자 정지 / VAD 정지 마크
  const onFinalRef     = useRef(onFinal)
  const mimeRef        = useRef('audio/webm')
  onFinalRef.current = onFinal

  // ── 실제 STT POST ───────────────────────────────────────────────────────
  const postTranscribe = useCallback(async (blob, partial) => {
    if (!blob || blob.size === 0) return null
    try {
      const url = `${API_BASE}/api/stt/transcribe?partial=${partial ? 'true' : 'false'}`
      const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': blob.type || 'audio/webm' },
        body: blob,
      })
      if (!res.ok) return null
      const j = await res.json()
      return (j.text || '').trim()
    } catch {
      return null
    }
  }, [])

  // ── 정리(자원 해제) ─────────────────────────────────────────────────────
  const cleanup = useCallback(() => {
    if (vadRafRef.current) {
      cancelAnimationFrame(vadRafRef.current)
      vadRafRef.current = null
    }
    if (analyserRef.current) {
      try { analyserRef.current.disconnect() } catch {}
      analyserRef.current = null
    }
    if (audioCtxRef.current) {
      try { audioCtxRef.current.close() } catch {}
      audioCtxRef.current = null
    }
    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach(t => { try { t.stop() } catch {} })
      mediaStreamRef.current = null
    }
    recorderRef.current = null
  }, [])

  // ── stop (수동 또는 VAD 트리거) ─────────────────────────────────────────
  const stop = useCallback(() => {
    if (stoppedRef.current) return
    stoppedRef.current = true
    const rec = recorderRef.current
    if (rec && rec.state !== 'inactive') {
      try { rec.stop() } catch {}
    } else {
      // recorder 없거나 이미 정지 — 강제 cleanup
      cleanup()
      setListening(false)
      setInterim('')
    }
  }, [cleanup])

  // ── start ───────────────────────────────────────────────────────────────
  const start = useCallback(async () => {
    if (listening) return

    // 1) getUserMedia
    let stream
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      })
    } catch (e) {
      alert('마이크 권한이 필요합니다.')
      return
    }
    mediaStreamRef.current = stream

    // 2) MediaRecorder (브라우저별 mime 협상)
    const candidates = [
      'audio/webm;codecs=opus',
      'audio/webm',
      'audio/ogg;codecs=opus',
      'audio/mp4',
    ]
    let mime = ''
    for (const m of candidates) {
      if (window.MediaRecorder && MediaRecorder.isTypeSupported(m)) { mime = m; break }
    }
    mimeRef.current = mime || 'audio/webm'
    let rec
    try {
      rec = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream)
    } catch (e) {
      cleanup()
      alert('이 환경에서는 녹음을 지원하지 않습니다.')
      return
    }
    recorderRef.current = rec
    chunksRef.current = []
    stoppedRef.current = false
    setInterim('')

    rec.ondataavailable = async (ev) => {
      if (ev.data && ev.data.size > 0) chunksRef.current.push(ev.data)
      // 정지 후의 dataavailable 은 onstop 에서 처리
      if (stoppedRef.current) return
      // partial transcribe (이미 in-flight 면 스킵 — 다음 청크 때 재시도)
      if (inflightRef.current) return
      inflightRef.current = true
      const blob = new Blob(chunksRef.current, { type: mimeRef.current })
      const text = await postTranscribe(blob, true)
      inflightRef.current = false
      if (text != null && !stoppedRef.current) setInterim(text)
    }

    rec.onstop = async () => {
      // 마지막 청크 변환 후 onFinal
      const blob = new Blob(chunksRef.current, { type: mimeRef.current })
      chunksRef.current = []
      const finalText = (await postTranscribe(blob, false)) || ''
      cleanup()
      setListening(false)
      setInterim('')
      const trimmed = finalText.trim()
      if (trimmed) onFinalRef.current(trimmed)
    }

    rec.onerror = (e) => {
      console.warn('[stt] MediaRecorder error', e)
    }

    // 3) VAD (Web Audio API + RMS)
    try {
      const AC = window.AudioContext || window.webkitAudioContext
      const ctx = new AC()
      const src = ctx.createMediaStreamSource(stream)
      const analyser = ctx.createAnalyser()
      analyser.fftSize = 1024
      src.connect(analyser)
      audioCtxRef.current = ctx
      analyserRef.current = analyser

      const buf = new Uint8Array(analyser.fftSize)
      const VOICE_THRESHOLD = 0.012   // RMS 정규화 (0~1)
      const startedAt = performance.now()
      lastVoiceAtRef.current = startedAt
      const MIN_RECORD_MS = 600       // 시작 직후 잠깐은 침묵으로 보지 않음

      const tick = () => {
        if (stoppedRef.current) return
        analyser.getByteTimeDomainData(buf)
        // RMS
        let sumSq = 0
        for (let i = 0; i < buf.length; i++) {
          const v = (buf[i] - 128) / 128
          sumSq += v * v
        }
        const rms = Math.sqrt(sumSq / buf.length)
        const now = performance.now()
        if (rms > VOICE_THRESHOLD) {
          lastVoiceAtRef.current = now
        } else if (now - startedAt > MIN_RECORD_MS &&
                   now - lastVoiceAtRef.current > silenceMs) {
          // 침묵 감지 → 자동 정지
          stop()
          return
        }
        vadRafRef.current = requestAnimationFrame(tick)
      }
      vadRafRef.current = requestAnimationFrame(tick)
    } catch (e) {
      console.warn('[stt] VAD 초기화 실패 (수동 정지 필요)', e)
    }

    // 4) 시작
    try {
      rec.start(chunkMs)
      setListening(true)
    } catch (e) {
      cleanup()
      alert('녹음 시작 실패: ' + e.message)
    }
  }, [listening, chunkMs, silenceMs, postTranscribe, cleanup, stop])

  // ── unmount 시 자원 정리 ────────────────────────────────────────────────
  useEffect(() => () => {
    stoppedRef.current = true
    cleanup()
  }, [cleanup])

  const toggle = useCallback(() => (listening ? stop() : start()), [listening, start, stop])

  return { listening, interim, toggle, stop }
}
