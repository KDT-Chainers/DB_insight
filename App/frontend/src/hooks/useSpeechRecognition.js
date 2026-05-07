import { useState, useRef, useCallback } from 'react'

/**
 * Web Speech API (webkit) — ko-KR, interim 결과.
 * @param {{ onFinal: (text: string) => void }} opts
 */
export function useSpeechRecognition({ onFinal }) {
  const [listening, setListening] = useState(false)
  const [interim, setInterim] = useState('')
  const recognitionRef = useRef(null)
  const latestRef = useRef('')
  const onFinalRef = useRef(onFinal)
  onFinalRef.current = onFinal

  const flushFinal = useCallback((fromError = false) => {
    const t = latestRef.current.trim()
    latestRef.current = ''
    setInterim('')
    setListening(false)
    if (t) onFinalRef.current(t)
    else if (fromError) {
      /* 묵음·중단 등으로 비었을 때는 콜백 없음 */
    }
  }, [])

  const start = useCallback(() => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition
    if (!SR) {
      alert('이 환경에서는 음성 인식이 지원되지 않습니다.')
      return
    }
    const r = new SR()
    r.lang = 'ko-KR'
    r.continuous = false
    r.interimResults = true
    r.maxAlternatives = 1
    r.onstart = () => {
      setListening(true)
      setInterim('')
      latestRef.current = ''
    }
    r.onresult = (e) => {
      let fin = ''
      let tmp = ''
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const seg = e.results[i]
        if (seg.isFinal) fin += seg[0].transcript
        else tmp += seg[0].transcript
      }
      if (tmp) {
        setInterim(tmp)
        latestRef.current = tmp
      }
      if (fin) {
        setInterim('')
        latestRef.current = fin
      }
    }
    r.onend = () => {
      flushFinal(false)
    }
    r.onerror = (ev) => {
      const partial = latestRef.current.trim()
      setListening(false)
      setInterim('')
      latestRef.current = ''
      if (partial) onFinalRef.current(partial)
      else if (ev?.error === 'not-allowed' || ev?.error === 'service-not-allowed') {
        alert('마이크 또는 음성 인식 권한이 필요합니다.')
      }
    }
    recognitionRef.current = r
    r.start()
  }, [flushFinal])

  const stop = useCallback(() => recognitionRef.current?.stop(), [])
  const toggle = useCallback(() => (listening ? stop() : start()), [listening, start, stop])
  return { listening, interim, toggle, stop }
}
