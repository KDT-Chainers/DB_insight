import { useEffect } from 'react'

/**
 * 마이크 입력 RMS를 스무딩해 `outRef.current`에 0~1 근사값으로 기록 (렌더 없음, Orb 등 rAF 소비용).
 * Web Speech와 동시에 마이크를 잡으면 STT가 묵음이 되는 경우가 있어, `startDelayMs`로 분석기 시작을 늦출 수 있음.
 *
 * @param {boolean} active
 * @param {{ current: number }} outRef
 * @param {{ startDelayMs?: number }} [opts]
 */
export function useMicLevelRef(active, outRef, opts = {}) {
  const startDelayMs = typeof opts.startDelayMs === 'number' ? opts.startDelayMs : 0

  useEffect(() => {
    if (!outRef) return
    if (!active) {
      outRef.current = 0
      return
    }

    let cancelled = false
    let raf = 0
    let stream = null
    let ctx = null
    let analyser = null
    let source = null
    const buf = new Float32Array(512)
    let delayTimer = 0

    const loop = () => {
      if (cancelled || !analyser) return
      analyser.getFloatTimeDomainData(buf)
      let sum = 0
      for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i]
      const rms = Math.sqrt(sum / buf.length)
      const raw = Math.min(1.15, rms * 9)
      const p = outRef.current
      outRef.current = p * 0.72 + raw * 0.28
      raf = requestAnimationFrame(loop)
    }

    const openMic = async () => {
      try {
        stream = await navigator.mediaDevices.getUserMedia({ audio: true })
        if (cancelled) {
          stream.getTracks().forEach((t) => t.stop())
          return
        }
        const AC = window.AudioContext || window.webkitAudioContext
        if (!AC) return
        ctx = new AC()
        await ctx.resume()
        analyser = ctx.createAnalyser()
        analyser.fftSize = 1024
        analyser.smoothingTimeConstant = 0.42
        source = ctx.createMediaStreamSource(stream)
        source.connect(analyser)
        raf = requestAnimationFrame(loop)
      } catch {
        outRef.current = 0
      }
    }

    if (startDelayMs > 0) {
      delayTimer = window.setTimeout(() => {
        delayTimer = 0
        if (!cancelled) void openMic()
      }, startDelayMs)
    } else {
      void openMic()
    }

    return () => {
      cancelled = true
      if (delayTimer) window.clearTimeout(delayTimer)
      cancelAnimationFrame(raf)
      try {
        source?.disconnect()
      } catch {
        /* ignore */
      }
      try {
        analyser?.disconnect()
      } catch {
        /* ignore */
      }
      if (ctx) ctx.close().catch(() => {})
      stream?.getTracks().forEach((t) => t.stop())
      outRef.current = 0
    }
  }, [active, outRef, startDelayMs])
}
