import { createContext, useContext, useState, useEffect } from 'react'

const ScaleContext = createContext(null)

const STORAGE_KEY = 'ui-scale'
const DEFAULT_SCALE = 0.8
const MIN_SCALE = 0.6
const MAX_SCALE = 1.2
const STEP = 0.05

export function ScaleProvider({ children }) {
  const [scale, setScaleRaw] = useState(() => {
    const stored = localStorage.getItem(STORAGE_KEY)
    const parsed = stored ? parseFloat(stored) : DEFAULT_SCALE
    return isNaN(parsed) ? DEFAULT_SCALE : Math.min(MAX_SCALE, Math.max(MIN_SCALE, parsed))
  })

  const setScale = (val) => {
    const clamped = Math.min(MAX_SCALE, Math.max(MIN_SCALE, parseFloat(val.toFixed(2))))
    setScaleRaw(clamped)
    localStorage.setItem(STORAGE_KEY, String(clamped))
    window.electronAPI?.setZoom(clamped)
  }

  return (
    <ScaleContext.Provider value={{ scale, setScale, MIN_SCALE, MAX_SCALE, STEP }}>
      {children}
    </ScaleContext.Provider>
  )
}

export function useScale() {
  return useContext(ScaleContext)
}
