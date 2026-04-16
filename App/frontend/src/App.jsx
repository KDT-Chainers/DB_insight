import { useEffect, useState } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { SidebarProvider } from './context/SidebarContext'
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
        const response = await fetch('http://localhost:5001/api/auth/status')
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

export default function App() {
  return (
    <BrowserRouter>
      <SidebarProvider>
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
      </SidebarProvider>
    </BrowserRouter>
  )
}
