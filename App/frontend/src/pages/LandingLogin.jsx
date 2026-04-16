import { useNavigate } from 'react-router-dom'
import { useState } from 'react'

export default function LandingLogin() {
  const navigate = useNavigate()
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')

  const handleLogin = async (e) => {
    e.preventDefault()

    try {
      const response = await fetch('http://localhost:5001/api/auth/verify', {
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
    <div className="bg-surface-dim text-on-surface font-body overflow-hidden min-h-screen">
      {/* Background */}
      <div className="fixed inset-0 grid-pattern pointer-events-none"></div>
      <div className="fixed inset-0 nebula-glow pointer-events-none"></div>
      <div className="fixed -top-40 -left-40 w-96 h-96 bg-primary/20 blur-[120px] rounded-full"></div>
      <div className="fixed -bottom-40 -right-40 w-96 h-96 bg-secondary/10 blur-[120px] rounded-full"></div>

      <main className="relative z-10 min-h-screen flex flex-col items-center justify-center p-6">
        {/* Brand header */}
        <div className="absolute top-12 flex flex-col items-center">
          <h1 className="text-3xl font-black tracking-tighter text-blue-100 font-headline">DB_insight</h1>
          <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-primary mt-2">로컬 인텔리전스 프로토콜</p>
        </div>

        {/* Login card */}
        <div className="glass-panel w-full max-w-md rounded-xl p-10 shadow-[0_0_50px_rgba(0,0,0,0.3)] flex flex-col items-center gap-8 border border-white/5">
          {/* Avatar */}
          <div className="relative">
            <div className="w-24 h-24 rounded-full p-1 bg-gradient-to-tr from-primary to-secondary overflow-hidden">
              <div className="w-full h-full rounded-full bg-surface-container overflow-hidden flex items-center justify-center">
                <span className="material-symbols-outlined text-primary text-5xl" style={{ fontVariationSettings: '"FILL" 1' }}>account_circle</span>
              </div>
            </div>
            <div className="absolute bottom-0 right-0 bg-primary text-on-primary-fixed w-7 h-7 rounded-full flex items-center justify-center shadow-lg border-2 border-surface-container-highest">
              <span className="material-symbols-outlined text-sm font-bold" style={{ fontVariationSettings: '"FILL" 1' }}>verified</span>
            </div>
          </div>

          <div className="text-center">
            <h2 className="text-xl font-bold text-on-surface tracking-tight">보안 인증이 필요합니다</h2>
            <p className="text-sm text-on-surface-variant mt-1">신경망 탐색기 접근 인증</p>
          </div>

          {/* Form */}
          <form onSubmit={handleLogin} className="w-full space-y-6">
            {error && <p className="text-red-400 text-sm text-center">{error}</p>}
            <div className="relative group">
              <label className="text-[10px] uppercase font-bold tracking-widest text-primary mb-2 block ml-1">접근 토큰</label>
              <div className="relative">
                <span className="material-symbols-outlined absolute left-0 top-1/2 -translate-y-1/2 text-on-surface-variant group-focus-within:text-primary transition-colors">key</span>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••••••"
                  className="w-full bg-transparent border-b border-outline-variant py-3 pl-8 text-on-surface focus:outline-none focus:border-primary transition-all placeholder:text-outline/40"
                />
                <div className="absolute bottom-0 left-0 w-0 h-[2px] bg-primary transition-all duration-500 group-focus-within:w-full"></div>
              </div>
            </div>
            <button
              type="submit"
              className="w-full h-14 rounded-full bg-gradient-to-r from-primary to-secondary text-on-primary-fixed font-bold tracking-tight shadow-[0_4px_20px_rgba(133,173,255,0.3)] hover:shadow-[0_4px_30px_rgba(172,138,255,0.5)] transition-all active:scale-95 flex items-center justify-center gap-2 group"
            >
              시스템 시작
              <span className="material-symbols-outlined transition-transform group-hover:translate-x-1">arrow_forward</span>
            </button>
          </form>

          {/* Secondary actions */}
          <div className="flex justify-between w-full px-1">
            <button
              onClick={() => navigate('/setup')}
              className="text-xs text-on-surface-variant hover:text-primary transition-colors font-medium"
            >
              인증 정보 초기화
            </button>
            <button className="text-xs text-on-surface-variant hover:text-primary transition-colors font-medium">
              프로토콜 문서
            </button>
          </div>
        </div>

        {/* Status footer */}
        <div className="mt-12 flex items-center gap-4">
          <div className="glass-panel px-4 py-2 rounded-full border border-white/5 flex items-center gap-2">
            <div className="w-2 h-2 rounded-full bg-primary animate-pulse"></div>
            <span className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">
              노드 상태: <span className="text-primary">정상</span>
            </span>
          </div>
          <div className="glass-panel px-4 py-2 rounded-full border border-white/5 flex items-center gap-2">
            <span className="material-symbols-outlined text-xs text-secondary" style={{ fontVariationSettings: '"FILL" 1' }}>verified_user</span>
            <span className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">암호화됨</span>
          </div>
        </div>
      </main>

      {/* Side status */}
      <div className="fixed right-6 top-1/2 -translate-y-1/2 flex flex-col gap-8 opacity-20 hover:opacity-50 transition-opacity">
        <div className="flex flex-col items-center gap-1">
          <div className="w-[1px] h-12 bg-outline-variant"></div>
          <span className="text-[10px] font-mono text-primary">04ms</span>
        </div>
        <div className="flex flex-col items-center gap-1">
          <div className="w-[1px] h-12 bg-outline-variant"></div>
          <span className="text-[10px] font-mono text-primary">99.9%</span>
        </div>
      </div>

      {/* Corner accent */}
      <div className="fixed bottom-0 left-0 p-8">
        <div className="flex items-center gap-4">
          <div className="w-8 h-8 rounded-lg bg-surface-container-highest border border-white/5 flex items-center justify-center">
            <span className="material-symbols-outlined text-sm text-primary">terminal</span>
          </div>
          <div className="hidden md:block">
            <p className="text-[8px] font-bold text-outline uppercase tracking-widest">활성 시퀀스</p>
            <p className="text-[10px] font-mono text-on-surface-variant">LOG_AUTH_INIT_PRIME</p>
          </div>
        </div>
      </div>
    </div>
  )
}
