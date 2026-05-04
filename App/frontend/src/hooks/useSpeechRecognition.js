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
    r.onstart = () => {
      setListening(true)
      setInterim('')
      latestRef.current = ''
    }
    r.onresult = (e) => {
      let fin = ''
      let tmp = ''
      for (let i = e.resultIndex; i < e.results.length; i++) {
        if (e.results[i].isFinal) fin += e.results[i][0].transcript
        else tmp += e.results[i][0].transcript
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
      setListening(false)
      setInterim('')
      const t = latestRef.current.trim()
      latestRef.current = ''
      if (t) onFinal(t)
    }
    r.onerror = () => {
      setListening(false)
      setInterim('')
    }
    recognitionRef.current = r
    r.start()
  }, [onFinal])

  const stop = useCallback(() => recognitionRef.current?.stop(), [])
  const toggle = useCallback(() => (listening ? stop() : start()), [listening, start, stop])
  return { listening, interim, toggle, stop }
}
