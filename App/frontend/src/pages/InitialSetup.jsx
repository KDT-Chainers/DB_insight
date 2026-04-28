import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import WindowControls from '../components/WindowControls'
import { API_BASE } from '../api'

// ── LibreOffice 의존성 설치 스텝 ─────────────────────────────────
function DepsStep({ onDone }) {
  const [loStatus, setLoStatus] = useState(null)   // null | {installed, path}
  const [installing, setInstalling] = useState(false)
  const [progress, setProgress] = useState(0)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [done, setDone] = useState(false)
  const pollRef = useRef(null)

  // 최초 확인
  useEffect(() => {
    fetch(`${API_BASE}/api/setup/check`)
      .then(r => r.json())
      .then(d => setLoStatus(d.libreoffice))
      .catch(() => setLoStatus({ installed: false, path: null }))
  }, [])

  // 설치 진행 폴링
  useEffect(() => {
    if (!installing) return
    pollRef.current = setInterval(async () => {
      try {
        const r = await fetch(`${API_BASE}/api/setup/install-status`)
        const d = await r.json()
        setProgress(d.progress ?? 0)
        setMessage(d.message ?? '')
        if (d.state === 'done') {
          clearInterval(pollRef.current)
          setInstalling(false)
          setDone(true)
          setLoStatus({ installed: true, path: null })
        } else if (d.state === 'error') {
          clearInterval(pollRef.current)
          setInstalling(false)
          setError(d.error || '설치 실패')
        }
      } catch (_) {}
    }, 1000)
    return () => clearInterval(pollRef.current)
  }, [installing])

  const startInstall = async () => {
    setError('')
    setInstalling(true)
    setProgress(0)
    setMessage('설치 시작 중...')
    try {
      await fetch(`${API_BASE}/api/setup/install-lo`, { method: 'POST' })
    } catch (e) {
      setInstalling(false)
      setError('서버 연결 실패')
    }
  }

  const skip = () => onDone()

  if (loStatus === null) {
    return (
      <div className="flex flex-col items-center justify-center flex-1 gap-4">
        <span className="material-symbols-outlined text-primary text-4xl animate-spin">progress_activity</span>
        <p className="text-on-surface-variant text-sm">의존성 확인 중...</p>
      </div>
    )
  }

  if (loStatus.installed || done) {
    return (
      <div className="flex flex-col items-center justify-center flex-1 gap-6 text-center">
        <div className="w-16 h-16 rounded-full bg-emerald-500/20 border border-emerald-500/30 flex items-center justify-center">
          <span className="material-symbols-outlined text-emerald-400 text-3xl" style={{ fontVariationSettings: '"FILL" 1' }}>check_circle</span>
        </div>
        <div>
          <h3 className="text-xl font-bold text-on-surface mb-1">LibreOffice 준비 완료</h3>
          <p className="text-sm text-on-surface-variant">문서·오피스 파일 처리가 활성화되었습니다.</p>
        </div>
        <button
          onClick={onDone}
          className="px-8 py-3 rounded-full kinetic-gradient text-on-primary-container font-bold flex items-center gap-2 hover:brightness-110 transition-all active:scale-95"
        >
          시작하기
          <span className="material-symbols-outlined">arrow_forward</span>
        </button>
      </div>
    )
  }

  return (
    <div className="flex flex-col flex-1 gap-6">
      {/* 헤더 */}
      <div>
        <h3 className="text-2xl font-bold text-on-surface mb-1">의존성 설치</h3>
        <p className="text-sm text-on-surface-variant">
          .docx · .hwp · .pptx · .xlsx 파일 처리를 위해 LibreOffice가 필요합니다.
        </p>
      </div>

      {/* LibreOffice 카드 */}
      <div className="p-5 rounded-2xl bg-surface-container-high border border-outline-variant/15">
        <div className="flex items-center gap-4 mb-4">
          <div className="w-12 h-12 rounded-xl bg-[#1e3a8a]/40 border border-primary/20 flex items-center justify-center shrink-0">
            <span className="material-symbols-outlined text-primary text-2xl">description</span>
          </div>
          <div className="flex-1 min-w-0">
            <p className="font-bold text-on-surface">LibreOffice</p>
            <p className="text-xs text-on-surface-variant">오피스 · 한글 문서 변환 엔진 (약 400 MB)</p>
          </div>
          {!installing && !error && (
            <span className="px-2 py-0.5 rounded-full bg-amber-500/15 text-amber-400 text-[10px] font-bold border border-amber-500/20 shrink-0">
              미설치
            </span>
          )}
        </div>

        {/* 진행 바 */}
        {(installing || error) && (
          <div className="space-y-2">
            <div className="w-full h-1.5 bg-surface-container-highest rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full transition-all duration-500 ${error ? 'bg-red-500' : 'bg-gradient-to-r from-primary to-secondary'}`}
                style={{ width: `${progress}%` }}
              />
            </div>
            <p className={`text-xs ${error ? 'text-red-400' : 'text-on-surface-variant'} truncate`}>
              {error || message || '설치 중...'}
            </p>
          </div>
        )}
      </div>

      {/* 설명 */}
      <div className="space-y-2 text-xs text-on-surface-variant/70">
        {[
          'winget(Windows 내장) 또는 공식 MSI를 통해 자동 설치됩니다.',
          '관리자 권한이 필요할 수 있습니다.',
          '.pdf · 이미지 파일은 LibreOffice 없이도 정상 동작합니다.',
        ].map((t, i) => (
          <div key={i} className="flex items-start gap-2">
            <span className="material-symbols-outlined text-xs text-primary/60 mt-0.5 shrink-0">info</span>
            <span>{t}</span>
          </div>
        ))}
      </div>

      {/* 버튼 */}
      <div className="flex gap-3 mt-auto">
        <button
          onClick={skip}
          disabled={installing}
          className="flex-1 py-3 rounded-full border border-outline-variant/30 text-on-surface-variant text-sm font-bold hover:bg-white/5 transition-all disabled:opacity-40"
        >
          나중에 설치
        </button>
        <button
          onClick={installing ? undefined : startInstall}
          disabled={installing}
          className="flex-2 px-6 py-3 rounded-full kinetic-gradient text-on-primary-container font-bold flex items-center justify-center gap-2 hover:brightness-110 transition-all active:scale-95 disabled:opacity-60"
        >
          {installing ? (
            <>
              <span className="material-symbols-outlined text-sm animate-spin">progress_activity</span>
              설치 중... {progress}%
            </>
          ) : (
            <>
              <span className="material-symbols-outlined text-sm">download</span>
              자동 설치
            </>
          )}
        </button>
      </div>

      {error && (
        <p className="text-xs text-center text-red-400/80">
          자동 설치 실패 시{' '}
          <span className="underline cursor-pointer" onClick={() => window.open?.('https://www.libreoffice.org/download/')}>
            libreoffice.org
          </span>
          에서 수동 설치하세요.
        </p>
      )}
    </div>
  )
}

// ── 메인 컴포넌트 ─────────────────────────────────────────────────
export default function InitialSetup() {
  const navigate = useNavigate()
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [step, setStep] = useState('password')  // 'password' | 'deps'
  const [error, setError] = useState('')

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (password !== confirm) { setError('비밀번호가 일치하지 않습니다'); return }
    try {
      const response = await fetch(`${API_BASE}/api/auth/setup`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password }),
      })
      const data = await response.json()
      if (response.ok && data?.success === true) { setError(''); setStep('deps'); return }
      if (data?.error === 'Already initialized') { setError('이미 설정된 비밀번호가 있습니다'); setTimeout(() => navigate('/'), 1000); return }
      setError(data?.error || '설정에 실패했습니다')
    } catch { setError('서버에 연결할 수 없습니다') }
  }

  const stepIndex = step === 'password' ? 0 : 1

  return (
    <div className="flex items-center justify-center min-h-screen p-4 bg-void">
      {/* 드래그 가능한 타이틀바 */}
      <div className="fixed top-0 left-0 right-0 h-8 bg-[#070d1f] z-[9999] flex items-center justify-end px-2" style={{ WebkitAppRegion: 'drag' }}>
        <div style={{ WebkitAppRegion: 'no-drag' }}><WindowControls /></div>
      </div>

      {/* Background */}
      <div className="fixed top-[-10%] left-[-10%] w-[60%] h-[60%] orb-glow rounded-full blur-[100px] opacity-40 pointer-events-none" />
      <div className="fixed bottom-[-10%] right-[-10%] w-[50%] h-[50%] bg-secondary/10 rounded-full blur-[120px] opacity-30 pointer-events-none" />

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
              <span style={{ background: 'linear-gradient(45deg, #85adff, #ac8aff)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent', backgroundClip: 'text' }}>
                DB_insight
              </span>에{' '}오신 것을 환영합니다.
            </h1>
            <p className="text-on-surface-variant text-lg leading-relaxed max-w-sm">
              신경망 수준의 마스터 비밀번호로 개인 인덱스를 보호하세요. 모든 처리는 기기에서 이루어집니다.
            </p>
          </div>
          <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
            <div className="w-96 h-96 rounded-full orb-glow animate-pulse" />
            <div className="absolute w-64 h-64 border border-primary/20 rounded-full animate-reverse-spin" />
            <div className="absolute w-80 h-80 border border-secondary/10 rounded-full animate-spin-slow" />
          </div>
          <div className="relative z-10 flex items-center gap-4">
            <div className="flex -space-x-3">
              <div className="w-8 h-8 rounded-full border-2 border-surface-container bg-surface-variant flex items-center justify-center text-[10px] font-bold">AI</div>
              <div className="w-8 h-8 rounded-full border-2 border-surface-container bg-surface-variant flex items-center justify-center text-[10px] font-bold">DB</div>
            </div>
            <span className="text-[10px] uppercase tracking-widest text-on-surface-variant font-semibold">코어 v2.4 활성화</span>
          </div>
        </section>

        {/* Right form */}
        <section className="flex-1 flex flex-col p-12 lg:p-20 bg-surface/80 glass-panel relative">
          <div className="max-w-md mx-auto w-full flex flex-col h-full">
            {/* 진행 바 */}
            <div className="flex justify-between items-center mb-12">
              <div className="flex gap-2">
                {['마스터 키', '의존성'].map((label, i) => (
                  <div key={i} className="flex items-center gap-1.5">
                    <div className={`h-1 w-12 rounded-full transition-all duration-500 ${i <= stepIndex ? 'kinetic-gradient' : 'bg-surface-container-highest'}`} />
                    <span className={`text-[9px] uppercase tracking-widest font-bold transition-colors ${i === stepIndex ? 'text-primary' : 'text-on-surface-variant/30'}`}>{label}</span>
                  </div>
                ))}
              </div>
              <span className="text-[10px] uppercase tracking-widest text-primary font-bold">초기 설정</span>
            </div>

            {/* ── STEP 1: 비밀번호 ── */}
            {step === 'password' && (
              <form onSubmit={handleSubmit} className="space-y-8 flex-1">
                <div>
                  <h2 className="text-3xl font-bold mb-2">마스터 키 생성</h2>
                  <p className="text-on-surface-variant text-sm">마스터 키는 모든 로컬 데이터 저장소를 암호화합니다.</p>
                </div>
                {error && <p className="text-red-400 text-sm text-center">{error}</p>}
                <div className="space-y-6">
                  <div className="group">
                    <label className="block text-[10px] uppercase tracking-widest font-bold text-on-surface-variant mb-2 group-focus-within:text-primary transition-colors">마스터 비밀번호</label>
                    <input type="password" value={password} onChange={e => setPassword(e.target.value)} placeholder="••••••••••••"
                      className="w-full bg-transparent border-b border-outline-variant focus:border-primary focus:ring-0 px-0 py-3 text-xl transition-all placeholder:text-outline-variant/30 outline-none" />
                  </div>
                  <div className="grid grid-cols-2 gap-4">
                    {[
                      { label: '8자 이상', met: password.length >= 8 },
                      { label: '대문자 및 특수문자', met: /[A-Z]/.test(password) && /[^a-zA-Z0-9]/.test(password) },
                      { label: '고유한 문구', met: password.length > 0 },
                      { label: '사전 단어 미포함', met: false },
                    ].map(item => (
                      <div key={item.label} className="flex items-center gap-2 text-xs text-on-surface-variant">
                        <span className="material-symbols-outlined text-sm" style={item.met ? { fontVariationSettings: '"FILL" 1', color: '#85adff' } : {}}>
                          {item.met ? 'check_circle' : 'circle'}
                        </span>
                        <span>{item.label}</span>
                      </div>
                    ))}
                  </div>
                  <div className="group">
                    <label className="block text-[10px] uppercase tracking-widest font-bold text-on-surface-variant mb-2 group-focus-within:text-primary transition-colors">비밀번호 확인</label>
                    <input type="password" value={confirm} onChange={e => setConfirm(e.target.value)} placeholder="••••••••••••"
                      className="w-full bg-transparent border-b border-outline-variant focus:border-primary focus:ring-0 px-0 py-3 text-xl transition-all placeholder:text-outline-variant/30 outline-none" />
                  </div>
                </div>
                <button type="submit" className="w-full kinetic-gradient text-on-primary-container font-bold py-4 rounded-full flex items-center justify-center gap-2 shadow-[0_10px_20px_rgba(133,173,255,0.2)] hover:shadow-[0_15px_30px_rgba(133,173,255,0.3)] transition-all group active:scale-95">
                  코어 초기화
                  <span className="material-symbols-outlined group-hover:translate-x-1 transition-transform">arrow_forward</span>
                </button>
              </form>
            )}

            {/* ── STEP 2: 의존성 ── */}
            {step === 'deps' && (
              <DepsStep onDone={() => navigate('/search')} />
            )}

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
        </section>
      </main>
    </div>
  )
}
