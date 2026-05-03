import { useNavigate } from 'react-router-dom'
import { useState } from 'react'
import WindowControls from '../components/WindowControls'
import AmbientPageBackdrop from '../components/AmbientPageBackdrop'
import { API_BASE } from '../api'

export default function LandingLogin() {
  const navigate = useNavigate()
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')

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
        navigate('/search')
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
    <div className="relative min-h-screen overflow-hidden font-body text-on-surface">
      <AmbientPageBackdrop />

      {/* 드래그 가능한 타이틀바 */}
      <div
        className="titlebar-chrome fixed left-0 right-0 top-0 z-[9999] flex h-8 items-center justify-end px-2"
        style={{ WebkitAppRegion: 'drag' }}
      >
        <div style={{ WebkitAppRegion: 'no-drag' }}>
          <WindowControls />
        </div>
      </div>

      <main className="relative z-10 flex min-h-screen flex-col items-center justify-center p-6">
        {/* Brand header */}
        <div className="absolute top-12 flex flex-col items-center">
          <button
            type="button"
            onClick={() => navigate('/welcome')}
            className="font-headline text-3xl font-black tracking-tighter text-blue-100 transition-opacity hover:opacity-80"
          >
            DB_insight
          </button>
          <p className="mt-2 text-[10px] font-semibold uppercase tracking-[0.2em] text-primary">로컬 인텔리전스 프로토콜</p>
        </div>

        {/* Login card */}
        <div className="glass-panel flex w-full max-w-md flex-col items-center gap-8 rounded-xl border border-white/5 p-10 shadow-[0_0_50px_rgba(0,0,0,0.3)]">
          {/* Avatar */}
          <div className="relative">
            <div className="h-24 w-24 overflow-hidden rounded-full bg-gradient-to-tr from-primary to-secondary p-1">
              <div className="flex h-full w-full items-center justify-center overflow-hidden rounded-full bg-surface-container">
                <span className="material-symbols-outlined text-5xl text-primary" style={{ fontVariationSettings: '"FILL" 1' }}>
                  account_circle
                </span>
              </div>
            </div>
            <div className="absolute bottom-0 right-0 flex h-7 w-7 items-center justify-center rounded-full border-2 border-surface-container-highest bg-primary text-on-primary-fixed shadow-lg">
              <span className="material-symbols-outlined text-sm font-bold" style={{ fontVariationSettings: '"FILL" 1' }}>
                verified
              </span>
            </div>
          </div>

          <div className="text-center">
            <h2 className="text-xl font-bold tracking-tight text-on-surface">보안 인증이 필요합니다</h2>
            <p className="mt-1 text-sm text-on-surface-variant">신경망 탐색기 접근 인증</p>
          </div>

          {/* Form */}
          <form onSubmit={handleLogin} className="w-full space-y-6">
            {error && <p className="text-center text-sm text-red-400">{error}</p>}
            <div className="group relative">
              <label className="mb-2 ml-1 block text-[10px] font-bold uppercase tracking-widest text-primary">접근 토큰</label>
              <div className="relative">
                <span className="material-symbols-outlined absolute left-0 top-1/2 -translate-y-1/2 text-on-surface-variant transition-colors group-focus-within:text-primary">
                  key
                </span>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••••••"
                  className="w-full border-b border-outline-variant bg-transparent py-3 pl-8 text-on-surface placeholder:text-outline/40 transition-all focus:border-primary focus:outline-none"
                />
                <div className="absolute bottom-0 left-0 h-[2px] w-0 bg-primary transition-all duration-500 group-focus-within:w-full" />
              </div>
            </div>
            <button
              type="submit"
              className="group flex h-14 w-full items-center justify-center gap-2 rounded-full bg-gradient-to-r from-primary to-secondary font-bold tracking-tight text-on-primary-fixed shadow-[0_4px_20px_rgba(133,173,255,0.3)] transition-all hover:shadow-[0_4px_30px_rgba(172,138,255,0.5)] active:scale-95"
            >
              시스템 시작
              <span className="material-symbols-outlined transition-transform group-hover:translate-x-1">arrow_forward</span>
            </button>
          </form>

          {/* Secondary actions */}
          <div className="flex w-full justify-between px-1">
            <button
              type="button"
              onClick={() => navigate('/setup')}
              className="text-xs font-medium text-on-surface-variant transition-colors hover:text-primary"
            >
              인증 정보 초기화
            </button>
            <button
              type="button"
              onClick={() => navigate('/welcome')}
              className="text-xs font-medium text-on-surface-variant transition-colors hover:text-primary"
            >
              소개 화면
            </button>
          </div>
        </div>

        {/* Status footer */}
        <div className="mt-12 flex items-center gap-4">
          <div className="glass-panel flex items-center gap-2 rounded-full border border-white/5 px-4 py-2">
            <div className="h-2 w-2 animate-pulse rounded-full bg-primary" />
            <span className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">
              노드 상태: <span className="text-primary">정상</span>
            </span>
          </div>
          <div className="glass-panel flex items-center gap-2 rounded-full border border-white/5 px-4 py-2">
            <span className="material-symbols-outlined text-xs text-secondary" style={{ fontVariationSettings: '"FILL" 1' }}>
              verified_user
            </span>
            <span className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">암호화됨</span>
          </div>
        </div>
      </main>

      {/* Side status */}
      <div className="fixed right-6 top-1/2 z-10 flex -translate-y-1/2 flex-col gap-8 opacity-20 transition-opacity hover:opacity-50">
        <div className="flex flex-col items-center gap-1">
          <div className="h-12 w-[1px] bg-outline-variant" />
          <span className="font-mono text-[10px] text-primary">04ms</span>
        </div>
        <div className="flex flex-col items-center gap-1">
          <div className="h-12 w-[1px] bg-outline-variant" />
          <span className="font-mono text-[10px] text-primary">99.9%</span>
        </div>
      </div>

      {/* Corner accent */}
      <div className="fixed bottom-0 left-0 z-10 p-8">
        <div className="flex items-center gap-4">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg border border-white/5 bg-surface-container-highest">
            <span className="material-symbols-outlined text-sm text-primary">terminal</span>
          </div>
          <div className="hidden md:block">
            <p className="text-[8px] font-bold uppercase tracking-widest text-outline">활성 시퀀스</p>
            <p className="font-mono text-[10px] text-on-surface-variant">LOG_AUTH_INIT_PRIME</p>
          </div>
        </div>
      </div>
    </div>
  )
}
