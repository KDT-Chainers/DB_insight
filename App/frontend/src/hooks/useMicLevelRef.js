import { useEffect } from 'react'

/**
 * 마이크 입력 RMS를 스무딩해 `outRef.current`에 0~1 근사값으로 기록 (렌더 없음, Orb 등 rAF 소비용).
 * @param {boolean} active
 * @param {{ current: number }} outRef
 */
export function useMicLevelRef(active, outRef) {
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

    ;(async () => {
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
    })()

    return () => {
      cancelled = true
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
  }, [active, outRef])
}
