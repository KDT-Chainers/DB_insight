import { useNavigate } from 'react-router-dom'
import { useState, useRef } from 'react'
import WindowControls from '../components/WindowControls'
import { API_BASE } from '../api'

export default function LandingLogin() {
  const navigate = useNavigate()
  const submitBtnRef = useRef(null)
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [portalToMain, setPortalToMain] = useState(false)
  const [ripplePos, setRipplePos] = useState({ x: '50%', y: '50%' })

  const handleLogin = async (e) => {
    e.preventDefault()

    try {
      const response = await fetch(`${API_BASE}/api/auth/verify`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password }),
      })
      const data = await response.json()

      if (response.ok && data?.success === true) {
        setError('')
        const reduceMotion =
          typeof window !== 'undefined' &&
          window.matchMedia('(prefers-reduced-motion: reduce)').matches
        if (reduceMotion) {
          navigate('/search')
          return
        }
        const rect = submitBtnRef.current?.getBoundingClientRect()
        if (rect) {
          setRipplePos({ x: `${rect.left + rect.width / 2}px`, y: `${rect.top + rect.height / 2}px` })
        } else {
          setRipplePos({ x: '50%', y: '50%' })
        }
        setPortalToMain(true)
        window.setTimeout(() => navigate('/search'), 900)
        return
      }

      if (data?.error === 'Invalid password') {
        setError('비밀번호가 올바르지 않습니다')
        return
      }

      setError(data?.error || '로그인에 실패했습니다')
    } catch {
      setError('서버에 연결할 수 없습니다')
    }
  }

  return (
    <div className="relative min-h-screen min-h-dvh overflow-x-hidden overflow-y-auto bg-[var(--app-bg-top)] font-body text-on-surface">
      {/* 드래그 가능한 타이틀바 */}
      <div
        className="titlebar-chrome fixed left-0 right-0 top-0 z-[9999] flex h-8 items-center justify-end px-2"
        style={{ WebkitAppRegion: 'drag' }}
      >
        <div style={{ WebkitAppRegion: 'no-drag' }}>
          <WindowControls />
        </div>
      </div>

      <main className="relative z-10 flex min-h-screen flex-col items-center justify-center p-6 pt-10">
        <div className="relative isolate w-full max-w-sm">
          <div
            className="pointer-events-none absolute -inset-5 rounded-[1.65rem] bg-gradient-to-b from-sky-200/15 via-primary/10 to-[rgba(37,99,235,0.08)] opacity-90 blur-2xl"
            aria-hidden
          />
          <div
            className="pointer-events-none absolute -inset-2 rounded-[1.35rem] border border-white/[0.08] bg-white/[0.05] shadow-[0_8px_40px_rgba(0,0,0,0.25),inset_0_1px_0_0_rgba(255,255,255,0.12)] backdrop-blur-2xl backdrop-saturate-150"
            aria-hidden
          />
          <div className="relative min-h-[34rem] overflow-hidden rounded-2xl shadow-[0_28px_80px_rgba(0,0,0,0.55)]">
          <div className="pointer-events-none absolute inset-0 app-depth-bg" aria-hidden />

          <div className="relative z-10 flex min-h-[34rem] flex-col justify-center bg-gradient-to-b from-white/[0.07] via-white/[0.02] to-transparent px-7 py-12 backdrop-blur-[56px] backdrop-saturate-150">
            <div className="flex w-full flex-col items-center gap-6">
              <div className="relative">
                <div className="h-24 w-24 overflow-hidden rounded-full bg-gradient-to-tr from-[#060d1f] via-[#0f2847] to-[#2563eb] p-1 shadow-[0_0_28px_rgba(37,99,235,0.28)]">
                  <div className="flex h-full w-full items-center justify-center overflow-hidden rounded-full bg-surface-container">
                    <span className="material-symbols-outlined text-5xl text-[#93c5fd]" style={{ fontVariationSettings: '"FILL" 1' }}>
                      account_circle
                    </span>
                  </div>
                </div>
                <div className="absolute bottom-0 right-0 flex h-7 w-7 items-center justify-center rounded-full border-2 border-surface-container-highest bg-gradient-to-br from-[#132a4a] to-[#2563eb] text-white shadow-[0_4px_16px_rgba(37,99,235,0.4)]">
                  <span className="material-symbols-outlined text-sm font-bold" style={{ fontVariationSettings: '"FILL" 1' }}>
                    verified
                  </span>
                </div>
              </div>

              <div className="text-center">
                <h2 className="text-xl font-bold tracking-tight text-white">보안 인증이 필요합니다</h2>
                <p className="mt-1 text-sm text-white/65">신경망 탐색기 접근 인증</p>
              </div>

              <form onSubmit={handleLogin} className="w-full space-y-8">
                {error && <p className="text-center text-sm text-red-300">{error}</p>}
                <div className="group relative">
                  <label className="mb-2 ml-1 block text-[10px] font-bold uppercase tracking-[0.22em] text-white/55">
                    접근 토큰
                  </label>
                  <div className="relative">
                    <span className="material-symbols-outlined absolute left-0 top-1/2 -translate-y-1/2 text-white/45 transition-colors group-focus-within:text-sky-200">
                      key
                    </span>
                    <input
                      type="password"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      placeholder="••••••••••••"
                      className="w-full border-b border-white/20 bg-transparent py-3 pl-8 text-white placeholder:text-white/35 transition-all focus:border-sky-300/70 focus:outline-none"
                    />
                    <div className="absolute bottom-0 left-0 h-[2px] w-0 bg-gradient-to-r from-sky-300/90 to-[#2563eb] transition-all duration-500 group-focus-within:w-full" />
                  </div>
                </div>
                <button
                  ref={submitBtnRef}
                  type="submit"
                  className="group flex h-14 w-full items-center justify-center gap-2 rounded-full bg-gradient-to-r from-[#060d1f] via-[#0f2847] to-[#2563eb] font-bold tracking-tight text-white shadow-[0_4px_24px_rgba(37,99,235,0.35)] transition-all hover:shadow-[0_8px_36px_rgba(56,189,248,0.35)] hover:brightness-[1.05] active:scale-[0.98]"
                >
                  시스템 시작
                  <span className="material-symbols-outlined transition-transform group-hover:translate-x-1">arrow_forward</span>
                </button>
              </form>

              <div className="flex w-full justify-between px-0.5">
                <button
                  type="button"
                  onClick={() => navigate('/setup')}
                  className="text-xs font-medium text-white/50 transition-colors hover:text-sky-200"
                >
                  인증 정보 초기화
                </button>
                <button
                  type="button"
                  onClick={() => navigate('/welcome')}
                  className="text-xs font-medium text-white/50 transition-colors hover:text-sky-200"
                >
                  소개 화면
                </button>
              </div>
            </div>
          </div>
          </div>
        </div>

        {/* Status footer */}
        <div className="mt-12 flex flex-wrap items-center justify-center gap-3">
          <div className="flex items-center gap-2 rounded-full bg-white/[0.06] px-4 py-2 backdrop-blur-md">
            <div className="h-2 w-2 animate-pulse rounded-full bg-sky-300 shadow-[0_0_10px_rgba(125,211,252,0.75)]" />
            <span className="text-[10px] font-bold uppercase tracking-widest text-white/50">
              노드 상태: <span className="text-sky-200">정상</span>
            </span>
          </div>
          <div className="flex items-center gap-2 rounded-full bg-white/[0.06] px-4 py-2 backdrop-blur-md">
            <span className="material-symbols-outlined text-xs text-sky-200/90" style={{ fontVariationSettings: '"FILL" 1' }}>
              verified_user
            </span>
            <span className="text-[10px] font-bold uppercase tracking-widest text-white/55">암호화됨</span>
          </div>
        </div>
      </main>

      {/* 메인 검색 전환 — MainSearch AI 포털과 동일 오버레이 */}
      {portalToMain && (
        <div className="pointer-events-none fixed inset-0 z-[10000] overflow-hidden">
          <div
            className="portal-overlay absolute rounded-full"
            style={{
              width: '80px',
              height: '80px',
              left: ripplePos.x,
              top: ripplePos.y,
              transform: 'translate(-50%, -50%)',
              background: 'radial-gradient(circle, #1c253e 0%, #0c1326 60%, #070d1f 100%)',
              boxShadow: '0 0 30px 10px rgba(172,138,255,0.15)',
            }}
          />
          {[0, 200].map((delay, i) => (
            <div
              key={i}
              className="portal-ring absolute rounded-full border border-[#ac8aff]/25"
              style={{
                width: '160px',
                height: '160px',
                left: ripplePos.x,
                top: ripplePos.y,
                transform: 'translate(-50%, -50%)',
                animationDelay: `${delay}ms`,
              }}
            />
          ))}
          <div className="portal-text absolute left-1/2 top-1/2 flex -translate-x-1/2 -translate-y-1/2 flex-col items-center gap-2">
            <span className="material-symbols-outlined text-4xl text-[#a5aac2]" style={{ fontVariationSettings: '"FILL" 1' }}>
              psychology
            </span>
            <span className="font-manrope text-xs uppercase tracking-[0.25em] text-[#a5aac2]">메인 화면</span>
          </div>
        </div>
      )}
    </div>
  )
}
