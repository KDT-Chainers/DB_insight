import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import WindowControls from '../components/WindowControls'
import AnimatedOrb from '../components/AnimatedOrb'
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
        <p className="text-on-surface-variant text-lg">의존성 확인 중...</p>
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
            <span className="px-2 py-0.5 rounded-full bg-amber-500/15 text-amber-400 text-lg font-bold border border-amber-500/20 shrink-0">
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
      <div className="space-y-2 text-base text-on-surface-variant/70">
        {[
          'winget(Windows 내장) 또는 공식 MSI를 통해 자동 설치됩니다.',
          '관리자 권한이 필요할 수 있습니다.',
          '.pdf · 이미지 파일은 LibreOffice 없이도 정상 동작합니다.',
        ].map((t, i) => (
          <div key={i} className="flex items-start gap-2">
            <span className="material-symbols-outlined text-base text-primary/60 mt-0.5 shrink-0">info</span>
            <span>{t}</span>
          </div>
        ))}
      </div>

      {/* 버튼 */}
      <div className="flex gap-3 mt-auto">
        <button
          onClick={skip}
          disabled={installing}
          className="flex-1 py-3 rounded-full border border-outline-variant/30 text-on-surface-variant text-lg font-bold hover:bg-white/5 transition-all disabled:opacity-40"
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
              <span className="material-symbols-outlined text-lg animate-spin">progress_activity</span>
              설치 중... {progress}%
            </>
          ) : (
            <>
              <span className="material-symbols-outlined text-lg">download</span>
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
    <div className="relative min-h-screen min-h-dvh overflow-x-hidden overflow-y-auto bg-[var(--app-bg-top)] font-body text-on-surface">
      <div
        className="titlebar-chrome fixed left-0 right-0 top-0 z-[9999] flex h-8 items-center justify-end px-2"
        style={{ WebkitAppRegion: 'drag' }}
      >
        <div style={{ WebkitAppRegion: 'no-drag' }}>
          <WindowControls />
        </div>
      </div>

      <main className="relative z-10 flex min-h-screen flex-col items-center justify-center p-6 pt-10">
        <div className="relative isolate w-full max-w-4xl">
          <div
            className="pointer-events-none absolute -inset-5 rounded-[1.65rem] bg-gradient-to-b from-sky-200/15 via-primary/10 to-[rgba(37,99,235,0.08)] opacity-90 blur-2xl"
            aria-hidden
          />
          <div
            className="pointer-events-none absolute -inset-2 rounded-[1.35rem] border border-white/[0.08] bg-white/[0.05] shadow-[0_8px_40px_rgba(0,0,0,0.25),inset_0_1px_0_0_rgba(255,255,255,0.12)] backdrop-blur-2xl backdrop-saturate-150"
            aria-hidden
          />
          <div className="relative min-h-[36rem] overflow-hidden rounded-2xl shadow-[0_28px_80px_rgba(0,0,0,0.55)] lg:min-h-[34rem]">
            <div className="pointer-events-none absolute inset-0 app-depth-bg" aria-hidden />

            <div className="relative z-10 grid min-h-[36rem] grid-cols-1 bg-gradient-to-b from-white/[0.07] via-white/[0.02] to-transparent backdrop-blur-[56px] backdrop-saturate-150 lg:min-h-[34rem] lg:grid-cols-2">
              {/* 좌측: 메인 UI와 동일 Orb + 카피 */}
              <section className="relative flex flex-col items-center justify-center gap-8 overflow-visible border-b border-white/10 px-8 py-12 lg:border-b-0 lg:border-r lg:px-10">
                <div className="flex flex-col items-center text-center">
                  <p className="mb-3 text-xs font-semibold uppercase tracking-[0.2em] text-white/50">DB_insight</p>
                  <h1 className="max-w-sm text-2xl font-bold leading-tight tracking-tight text-white md:text-3xl">
                    DB_insight에 오신 것을 환영합니다.
                  </h1>
                  <p className="mt-3 max-w-sm text-sm leading-relaxed text-white/65">
                    신경망 수준의 마스터 비밀번호로 개인 인덱스를 보호하세요. 모든 처리는 기기에서 이루어집니다.
                  </p>
                </div>
                <div className="overflow-visible py-2">
                  <AnimatedOrb size={280} interactive={false} />
                </div>
                <div className="flex items-center gap-3 text-[10px] font-semibold uppercase tracking-widest text-white/45">
                  <div className="flex -space-x-2">
                    <div className="flex h-8 w-8 items-center justify-center rounded-full border-2 border-white/15 bg-white/[0.06] text-[9px] font-bold text-white/70">
                      AI
                    </div>
                    <div className="flex h-8 w-8 items-center justify-center rounded-full border-2 border-white/15 bg-white/[0.06] text-[9px] font-bold text-white/70">
                      DB
                    </div>
                  </div>
                  <span>AI DB 코어 v2.4 활성화</span>
                </div>
              </section>

              {/* 우측: 폼 */}
              <section className="relative flex flex-col justify-center px-8 py-10 lg:px-10 lg:py-12">
                <div className="mx-auto w-full max-w-md flex flex-col h-full">
                  {/* 진행 바 */}
                  <div className="mb-10 flex items-center justify-between">
                    <div className="flex gap-2">
                      {['마스터 키', '의존성'].map((label, i) => (
                        <div key={i} className="flex items-center gap-1.5">
                          <div className={`h-1 w-10 rounded-full transition-all duration-500 ${i <= stepIndex ? 'bg-gradient-to-r from-sky-300/90 to-[#2563eb]' : 'bg-white/15'}`} />
                          <span className={`text-[10px] font-bold uppercase tracking-widest transition-colors ${i === stepIndex ? 'text-sky-200' : 'text-white/30'}`}>{label}</span>
                        </div>
                      ))}
                    </div>
                    <span className="text-[10px] font-bold uppercase tracking-widest text-white/50">초기 설정</span>
                  </div>

                  {/* ── STEP 1: 비밀번호 ── */}
                  {step === 'password' && (
                    <form onSubmit={handleSubmit} className="space-y-8 flex-1">
                      <div>
                        <h2 className="mb-2 text-xl font-bold tracking-tight text-white md:text-2xl">마스터 키 생성</h2>
                        <p className="text-sm text-white/60">마스터 키는 모든 로컬 데이터 저장소를 암호화합니다.</p>
                      </div>
                      {error && <p className="text-center text-sm text-red-300">{error}</p>}
                      <div className="space-y-6">
                        <div className="group">
                          <label className="mb-2 ml-1 block text-[10px] font-bold uppercase tracking-[0.22em] text-white/55">
                            마스터 비밀번호
                          </label>
                          <div className="relative">
                            <input
                              type="password"
                              value={password}
                              onChange={(e) => setPassword(e.target.value)}
                              placeholder="••••••••••••"
                              className="w-full border-b border-white/20 bg-transparent py-3 text-lg text-white placeholder:text-white/35 transition-all focus:border-sky-300/70 focus:outline-none"
                            />
                            <div className="pointer-events-none absolute bottom-0 left-0 h-[2px] w-0 bg-gradient-to-r from-sky-300/90 to-[#2563eb] transition-all duration-500 group-focus-within:w-full" />
                          </div>
                        </div>
                        <div className="grid grid-cols-2 gap-3">
                          {[
                            { label: '8자 이상', met: password.length >= 8 },
                            { label: '대문자 및 특수문자', met: /[A-Z]/.test(password) && /[^a-zA-Z0-9]/.test(password) },
                            { label: '고유한 문구', met: password.length > 0 },
                            { label: '사전 단어 미포함', met: false },
                          ].map((item) => (
                            <div key={item.label} className="flex items-center gap-2 text-xs text-white/55">
                              <span
                                className="material-symbols-outlined text-sm"
                                style={item.met ? { fontVariationSettings: '"FILL" 1', color: '#93c5fd' } : { color: 'rgba(255,255,255,0.35)' }}
                              >
                                {item.met ? 'check_circle' : 'circle'}
                              </span>
                              <span>{item.label}</span>
                            </div>
                          ))}
                        </div>
                        <div className="group">
                          <label className="mb-2 ml-1 block text-[10px] font-bold uppercase tracking-[0.22em] text-white/55">
                            비밀번호 확인
                          </label>
                          <div className="relative">
                            <input
                              type="password"
                              value={confirm}
                              onChange={(e) => setConfirm(e.target.value)}
                              placeholder="••••••••••••"
                              className="w-full border-b border-white/20 bg-transparent py-3 text-lg text-white placeholder:text-white/35 transition-all focus:border-sky-300/70 focus:outline-none"
                            />
                            <div className="pointer-events-none absolute bottom-0 left-0 h-[2px] w-0 bg-gradient-to-r from-sky-300/90 to-[#2563eb] transition-all duration-500 group-focus-within:w-full" />
                          </div>
                        </div>
                      </div>
                      <button
                        type="submit"
                        className="group flex h-14 w-full items-center justify-center gap-2 rounded-full bg-gradient-to-r from-[#060d1f] via-[#0f2847] to-[#2563eb] font-bold tracking-tight text-white shadow-[0_4px_24px_rgba(37,99,235,0.35)] transition-all hover:shadow-[0_8px_36px_rgba(56,189,248,0.35)] hover:brightness-[1.05] active:scale-[0.98]"
                      >
                        코어 초기화
                        <span className="material-symbols-outlined transition-transform group-hover:translate-x-1">arrow_forward</span>
                      </button>
                      <div className="mt-auto pt-8 border-t border-white/10 flex items-center justify-between">
                        <div className="flex items-center gap-2 text-white/45">
                          <span className="material-symbols-outlined text-sm">lock</span>
                          <span className="text-[10px] font-semibold uppercase tracking-tighter">제로 지식 저장소</span>
                        </div>
                        <button
                          type="button"
                          onClick={() => navigate('/')}
                          className="text-[10px] font-bold uppercase tracking-tighter text-white/50 transition-colors hover:text-sky-200"
                        >
                          로그인으로 돌아가기
                        </button>
                      </div>
                    </form>
                  )}

                  {/* ── STEP 2: 의존성 ── */}
                  {step === 'deps' && (
                    <DepsStep onDone={() => navigate('/search')} />
                  )}
                </div>
              </section>
            </div>
          </div>
        </div>

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
    </div>
  )
}
