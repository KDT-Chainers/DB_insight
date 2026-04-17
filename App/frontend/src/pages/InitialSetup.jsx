import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import WindowControls from '../components/WindowControls'

export default function InitialSetup() {
  const navigate = useNavigate()
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [done, setDone] = useState(false)
  const [error, setError] = useState('')

  const handleSubmit = async (e) => {
    e.preventDefault()

    if (password !== confirm) {
      setError('비밀번호가 일치하지 않습니다')
      return
    }

    try {
      const response = await fetch('http://localhost:5001/api/auth/setup', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password }),
      })
      const data = await response.json()

      if (response.ok && data?.success === true) {
        setError('')
        setDone(true)
        return
      }

      if (data?.error === 'Already initialized') {
        setError('이미 설정된 비밀번호가 있습니다')
        setTimeout(() => navigate('/'), 1000)
        return
      }

      setError(data?.error || '설정에 실패했습니다')
    } catch {
      setError('서버에 연결할 수 없습니다')
    }
  }

  return (
    <div className="flex items-center justify-center min-h-screen p-4 bg-void">
      {/* 윈도우 컨트롤 버튼 */}
      <div className="fixed top-2 right-2 z-[9999]">
        <WindowControls />
      </div>

      {/* Background */}
      <div className="fixed top-[-10%] left-[-10%] w-[60%] h-[60%] orb-glow rounded-full blur-[100px] opacity-40 pointer-events-none"></div>
      <div className="fixed bottom-[-10%] right-[-10%] w-[50%] h-[50%] bg-secondary/10 rounded-full blur-[120px] opacity-30 pointer-events-none"></div>

      <main className="relative w-full max-w-6xl h-[800px] flex overflow-hidden rounded-xl shadow-2xl border border-white/5 animate-fade-in">
        {/* Left branding */}
        <section className="hidden lg:flex w-5/12 flex-col justify-between p-12 bg-surface-container relative overflow-hidden">
          <div className="relative z-10">
            <div className="flex items-center gap-3 mb-12">
              <div className="w-10 h-10 rounded-lg kinetic-gradient flex items-center justify-center shadow-[0_0_20px_rgba(133,173,255,0.4)]">
                <span className="material-symbols-outlined text-on-primary-container" style={{ fontVariationSettings: '"FILL" 1' }}>dataset</span>
              </div>
              <span className="text-2xl font-black tracking-tighter text-on-surface">DB_insight</span>
            </div>
            <h1 className="text-5xl font-extrabold tracking-tight leading-[1.1] mb-6">
              <span style={{
                background: 'linear-gradient(45deg, #85adff, #ac8aff)',
                WebkitBackgroundClip: 'text',
                WebkitTextFillColor: 'transparent',
                backgroundClip: 'text',
              }}>DB_insight</span>에{' '}
              오신 것을 환영합니다.
            </h1>
            <p className="text-on-surface-variant text-lg leading-relaxed max-w-sm">
              신경망 수준의 마스터 비밀번호로 개인 인덱스를 보호하세요. 모든 처리는 기기에서 이루어집니다.
            </p>
          </div>

          {/* AI Orb */}
          <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
            <div className="w-96 h-96 rounded-full orb-glow animate-pulse"></div>
            <div className="absolute w-64 h-64 border border-primary/20 rounded-full animate-reverse-spin"></div>
            <div className="absolute w-80 h-80 border border-secondary/10 rounded-full animate-spin-slow"></div>
          </div>

          <div className="relative z-10 flex items-center gap-4">
            <div className="flex -space-x-3">
              <div className="w-8 h-8 rounded-full border-2 border-surface-container bg-surface-variant flex items-center justify-center text-[10px] font-bold">AI</div>
              <div className="w-8 h-8 rounded-full border-2 border-surface-container bg-surface-variant flex items-center justify-center text-[10px] font-bold">DB</div>
            </div>
            <span className="text-[10px] uppercase tracking-widest text-on-surface-variant font-semibold">코어 v2.4 활성화</span>
          </div>
        </section>

        {/* Right setup form */}
        <section className="flex-1 flex flex-col p-12 lg:p-20 bg-surface/80 glass-panel relative">
          <div className="max-w-md mx-auto w-full flex flex-col h-full">
            {/* Progress */}
            <div className="flex justify-between items-center mb-12">
              <div className="flex gap-2">
                <div className="h-1 w-12 rounded-full kinetic-gradient"></div>
                <div className="h-1 w-12 rounded-full bg-surface-container-highest"></div>
                <div className="h-1 w-12 rounded-full bg-surface-container-highest"></div>
              </div>
              <span className="text-[10px] uppercase tracking-widest text-primary font-bold">초기 설정</span>
            </div>

            {/* Form */}
            <form onSubmit={handleSubmit} className="space-y-8 flex-1">
              <div>
                <h2 className="text-3xl font-bold mb-2">마스터 키 생성</h2>
                <p className="text-on-surface-variant text-sm">마스터 키는 모든 로컬 데이터 저장소를 암호화합니다.</p>
              </div>
              {error && <p className="text-red-400 text-sm text-center">{error}</p>}
              <div className="space-y-6">
                <div className="group">
                  <label className="block text-[10px] uppercase tracking-widest font-bold text-on-surface-variant mb-2 group-focus-within:text-primary transition-colors">
                    마스터 비밀번호
                  </label>
                  <div className="relative">
                    <input
                      type="password"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      placeholder="••••••••••••"
                      className="w-full bg-transparent border-b border-outline-variant focus:border-primary focus:ring-0 px-0 py-3 text-xl transition-all placeholder:text-outline-variant/30 outline-none"
                    />
                  </div>
                </div>

                {/* Strength */}
                <div className="grid grid-cols-2 gap-4">
                  {[
                    { label: '8자 이상', met: password.length >= 8 },
                    { label: '대문자 및 특수문자', met: /[A-Z]/.test(password) && /[^a-zA-Z0-9]/.test(password) },
                    { label: '고유한 문구', met: password.length > 0 },
                    { label: '사전 단어 미포함', met: false },
                  ].map((item) => (
                    <div key={item.label} className="flex items-center gap-2 text-xs text-on-surface-variant">
                      <span
                        className="material-symbols-outlined text-sm"
                        style={item.met ? { fontVariationSettings: '"FILL" 1', color: '#85adff' } : {}}
                      >
                        {item.met ? 'check_circle' : 'circle'}
                      </span>
                      <span>{item.label}</span>
                    </div>
                  ))}
                </div>

                <div className="group">
                  <label className="block text-[10px] uppercase tracking-widest font-bold text-on-surface-variant mb-2 group-focus-within:text-primary transition-colors">
                    비밀번호 확인
                  </label>
                  <div className="relative">
                    <input
                      type="password"
                      value={confirm}
                      onChange={(e) => setConfirm(e.target.value)}
                      placeholder="••••••••••••"
                      className="w-full bg-transparent border-b border-outline-variant focus:border-primary focus:ring-0 px-0 py-3 text-xl transition-all placeholder:text-outline-variant/30 outline-none"
                    />
                  </div>
                </div>
              </div>

              <button
                type="submit"
                className="w-full kinetic-gradient text-on-primary-container font-bold py-4 rounded-full flex items-center justify-center gap-2 shadow-[0_10px_20px_rgba(133,173,255,0.2)] hover:shadow-[0_15px_30px_rgba(133,173,255,0.3)] transition-all group active:scale-95"
              >
                코어 초기화
                <span className="material-symbols-outlined group-hover:translate-x-1 transition-transform">arrow_forward</span>
              </button>
            </form>

            <div className="mt-auto pt-8 border-t border-outline-variant/10 flex items-center justify-between">
              <div className="flex items-center gap-2 opacity-60">
                <span className="material-symbols-outlined text-sm">lock</span>
                <span className="text-[10px] uppercase tracking-tighter">제로 지식 저장소</span>
              </div>
              <button onClick={() => navigate('/')} className="text-[10px] uppercase tracking-tighter hover:text-primary transition-colors font-bold">
                로그인으로 돌아가기
              </button>
            </div>
          </div>

          {/* Success overlay */}
          {done && (
            <div className="absolute inset-0 bg-surface z-20 flex flex-col items-center justify-center p-12 text-center">
              <div className="w-24 h-24 rounded-full kinetic-gradient flex items-center justify-center mb-8 shadow-[0_0_40px_rgba(133,173,255,0.5)]">
                <span className="material-symbols-outlined text-4xl text-on-primary-container" style={{ fontVariationSettings: '"FILL" 1' }}>verified</span>
              </div>
              <h2 className="text-4xl font-black mb-4">환영합니다!</h2>
              <p className="text-on-surface-variant max-w-sm mb-12">
                개인 인텔리전스 보관소가 초기화되어 심층 인덱싱 준비가 완료되었습니다.
              </p>
              <button
                onClick={() => navigate('/search')}
                className="px-10 py-4 rounded-full border-2 border-primary text-primary font-bold hover:bg-primary/10 transition-all flex items-center gap-3"
              >
                인덱스 구축 시작
                <span className="material-symbols-outlined">database</span>
              </button>
            </div>
          )}
        </section>
      </main>
    </div>
  )
}
