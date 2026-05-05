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
import SplashOrb from './pages/SplashOrb'
import teamLogoSrc from './assets/teamlogo.png'

function AuthGate() {
  const [loading, setLoading] = useState(true);
  const [initialized, setInitialized] = useState(null);

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
      <div className="relative min-h-screen overflow-hidden bg-[#070d1f]">
        <div className="studio-bridge-bg pointer-events-none absolute inset-0" />
        <div className="pointer-events-none absolute inset-0 grid-bg opacity-[0.22]" />
        <div className="auth-loading-aurora pointer-events-none absolute inset-0">
          <span className="aurora-band aurora-band-a" />
          <span className="aurora-band aurora-band-b" />
          <span className="aurora-band aurora-band-c" />
        </div>
        <div className="auth-loading-halo pointer-events-none absolute left-1/2 top-1/2 h-[420px] w-[420px] -translate-x-1/2 -translate-y-1/2 rounded-full" />
        <div className="auth-loading-sweep pointer-events-none absolute inset-0" />

        <div className="relative z-10 flex min-h-screen flex-col items-center justify-center gap-4">
          <img
            src={teamLogoSrc}
            alt=""
            width={44}
            height={44}
            draggable={false}
            className="auth-loading-logo h-11 w-11 rounded-xl object-contain"
          />
          <p className="text-on-surface-variant text-lg tracking-[0.08em]">
            Loading ...
          </p>
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
        <Route path="/splash" element={<SplashOrb />} />
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
