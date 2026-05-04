import { useEffect, useState } from 'react'
import { HashRouter, Routes, Route, Navigate } from 'react-router-dom'
import { SidebarProvider } from './context/SidebarContext'
import { ScaleProvider, useScale } from './context/ScaleContext'
import { API_BASE } from './api'
import LandingHome from './pages/LandingHome'
import LandingLogin from './pages/LandingLogin'
import InitialSetup from './pages/InitialSetup'
import MainSearch from './pages/MainSearch'
import MainAI from './pages/MainAI'
import Settings from './pages/Settings'
import DataIndexing from './pages/DataIndexing'

function AuthGate() {
  const [loading, setLoading] = useState(true);
  const [initialized, setInitialized] = useState(null);
  const [retryCount, setRetryCount] = useState(0);

  useEffect(() => {
    let active = true;
    let timer = null;

    const checkStatus = async () => {
      try {
        const response = await fetch(`${API_BASE}/api/auth/status`);
        const data = await response.json();
        if (!response.ok) throw new Error(data?.error || "Failed");
        if (active) {
          setInitialized(Boolean(data?.initialized));
          setLoading(false);
        }
      } catch {
        // 백엔드 아직 기동 중 — 1.5초 후 재시도 (최대 60회 = 90초)
        if (active) {
          setRetryCount(c => c + 1);
          timer = setTimeout(checkStatus, 1500);
        }
      }
    };

    checkStatus();

    return () => {
      active = false;
      if (timer) clearTimeout(timer);
    };
  }, []);

  if (loading) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center gap-4 bg-[#070d1f]">
        <div className="w-10 h-10 bg-gradient-to-br from-primary to-secondary rounded-xl flex items-center justify-center animate-pulse">
          <span className="material-symbols-outlined text-white text-xl" style={{ fontVariationSettings: '"FILL" 1' }}>dataset</span>
        </div>
        <p className="text-on-surface-variant text-lg">
          {retryCount < 3 ? '서버에 연결하는 중...' : `백엔드 준비 중... (${retryCount})`}
        </p>
        <div className="w-32 h-0.5 bg-surface-container-high rounded-full overflow-hidden">
          <div className="h-full bg-gradient-to-r from-primary to-secondary animate-[slide_1.4s_ease-in-out_infinite] rounded-full" />
        </div>
      </div>
    );
  }

  if (initialized === false) {
    return <Navigate to="/setup" replace />;
  }

  return <LandingLogin />;
}

// 경로에 따라 애니메이션 클래스 결정
function getEnterClass(pathname) {
  if (pathname === "/data") return "page-enter-right";
  return "page-enter";
}

/** v0 스타일 인트로(히어로+오브) — 선택 진입용 #/welcome */
function WelcomeGate() {
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
      <div className="flex min-h-screen items-center justify-center bg-void p-4">
        <p className="text-center text-sm text-red-400">{error}</p>
      </div>
    )
  }

  if (initialized === false) {
    return <Navigate to="/setup" replace />
  }

  return <LandingHome />
}

function ScaledApp() {
  const { scale } = useScale();

  // Electron webFrame.setZoomFactor() 사용 — CSS zoom과 달리 레이아웃에 영향 없이
  // 렌더링 레벨에서만 확대/축소하므로 h-screen, fixed 등이 모두 정상 동작한다.
  useEffect(() => {
    window.electronAPI?.setZoom(scale);
  }, [scale]);

  return (
    <SidebarProvider>
      <Routes>
        <Route path="/" element={<AuthGate />} />
        <Route path="/welcome" element={<WelcomeGate />} />
        <Route path="/login" element={<Navigate to="/" replace />} />
        <Route path="/setup" element={<InitialSetup />} />
        <Route path="/search" element={<MainSearch />} />
        <Route
          path="/search/results"
          element={<Navigate to="/search" replace />}
        />
        <Route
          path="/search/results/:id"
          element={<Navigate to="/search" replace />}
        />
        <Route path="/ai" element={<MainAI />} />
        <Route path="/ai/results" element={<Navigate to="/ai" replace />} />
        <Route path="/ai/results/:id" element={<Navigate to="/ai" replace />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="/data" element={<DataIndexing />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </SidebarProvider>
  );
}

export default function App() {
  return (
    <HashRouter>
      <ScaleProvider>
        <ScaledApp />
      </ScaleProvider>
    </HashRouter>
  );
}
