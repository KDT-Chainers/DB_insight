import { useEffect, useState } from 'react'
import { HashRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom'
import { SidebarProvider } from './context/SidebarContext'
import { ScaleProvider, useScale } from './context/ScaleContext'
import { API_BASE } from './api'
import LandingLogin from './pages/LandingLogin'
import InitialSetup from './pages/InitialSetup'
import MainSearch from './pages/MainSearch'
import MainAI from './pages/MainAI'
import Settings from './pages/Settings'
import DataIndexing from './pages/DataIndexing'

function AuthGate() {
  const [loading, setLoading] = useState(true)
  const [initialized, setInitialized] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true

    const checkStatus = async () => {
      try {
        const response = await fetch(`${API_BASE}/api/auth/status`)
        const data = await response.json()
        if (!response.ok) {
          throw new Error(data?.error || 'Failed to fetch status')
        }
        if (active) {
          setInitialized(Boolean(data?.initialized))
        }
      } catch {
        if (active) {
          setError('서버에 연결할 수 없습니다')
        }
      } finally {
        if (active) {
          setLoading(false)
        }
      }
    }

    checkStatus()

    return () => {
      active = false
    }
  }, [])

  if (loading) {
    return <div />
  }

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center p-4 bg-void">
        <p className="text-red-400 text-sm text-center">{error}</p>
      </div>
    )
  }

  if (initialized === false) {
    return <Navigate to="/setup" replace />
  }

  return <LandingLogin />
}

// 경로에 따라 애니메이션 클래스 결정
function getEnterClass(pathname) {
  if (pathname === '/data') return 'page-enter-right'
  return 'page-enter'
}

function ScaledApp() {
  const { scale } = useScale()
  const location  = useLocation()

  // Electron webFrame.setZoomFactor() 사용 — CSS zoom과 달리 레이아웃에 영향 없이
  // 렌더링 레벨에서만 확대/축소하므로 h-screen, fixed 등이 모두 정상 동작한다.
  useEffect(() => {
    window.electronAPI?.setZoom(scale)
  }, [scale])

  return (
    <SidebarProvider>
      {/* key 변경 시 div 재마운트 → 애니메이션 재생 */}
      <div
        key={location.pathname}
        className={getEnterClass(location.pathname)}
        style={{ height: '100vh', overflow: 'hidden' }}
      >
        <Routes>
          <Route path="/" element={<AuthGate />} />
          <Route path="/setup" element={<InitialSetup />} />
          <Route path="/search" element={<MainSearch />} />
          <Route path="/search/results" element={<Navigate to="/search" replace />} />
          <Route path="/search/results/:id" element={<Navigate to="/search" replace />} />
          <Route path="/ai" element={<MainAI />} />
          <Route path="/ai/results" element={<Navigate to="/ai" replace />} />
          <Route path="/ai/results/:id" element={<Navigate to="/ai" replace />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/data" element={<DataIndexing />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </div>
    </SidebarProvider>
  )
}

export default function App() {
  return (
    <HashRouter>
      <ScaleProvider>
        <ScaledApp />
      </ScaleProvider>
    </HashRouter>
  )
}
