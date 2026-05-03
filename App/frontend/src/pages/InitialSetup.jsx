import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import WindowControls from '../components/WindowControls'
import AnimatedOrb from '../components/AnimatedOrb'
import { API_BASE } from '../api'

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
      const response = await fetch(`${API_BASE}/api/auth/setup`, {
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
              {/* 좌측: 메인 UI와 동일 Orb + 카피 (보안 인증 카드 톤) */}
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

              {/* 우측: 폼 (보안 인증 입력 스타일 정렬) */}
              <section className="relative flex flex-col justify-center px-8 py-10 lg:px-10 lg:py-12">
                <div className="mx-auto w-full max-w-md">
                  <div className="mb-10 flex items-center justify-between">
                    <div className="flex gap-2">
                      <div className="h-1 w-10 rounded-full bg-gradient-to-r from-sky-300/90 to-[#2563eb]" />
                      <div className="h-1 w-10 rounded-full bg-white/15" />
                      <div className="h-1 w-10 rounded-full bg-white/15" />
                    </div>
                    <span className="text-[10px] font-bold uppercase tracking-widest text-white/50">초기 설정</span>
                  </div>

                  <form onSubmit={handleSubmit} className="space-y-8">
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
                          {
                            label: '대문자 및 특수문자',
                            met: /[A-Z]/.test(password) && /[^a-zA-Z0-9]/.test(password),
                          },
                          { label: '고유한 문구', met: password.length > 0 },
                          { label: '사전 단어 미포함', met: false },
                        ].map((item) => (
                          <div key={item.label} className="flex items-center gap-2 text-xs text-white/55">
                            <span
                              className="material-symbols-outlined text-sm"
                              style={
                                item.met
                                  ? { fontVariationSettings: '"FILL" 1', color: '#93c5fd' }
                                  : { color: 'rgba(255,255,255,0.35)' }
                              }
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
                      <span className="material-symbols-outlined transition-transform group-hover:translate-x-1">
                        arrow_forward
                      </span>
                    </button>
                  </form>

                  <div className="mt-10 flex items-center justify-between border-t border-white/10 pt-8">
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
                </div>

                {done && (
                  <div className="absolute inset-0 z-20 flex flex-col items-center justify-center bg-[rgba(3,10,28,0.92)] p-10 text-center backdrop-blur-xl">
                    <div className="mb-8 flex h-24 w-24 items-center justify-center rounded-full bg-gradient-to-br from-[#132a4a] to-[#2563eb] shadow-[0_0_40px_rgba(37,99,235,0.45)]">
                      <span
                        className="material-symbols-outlined text-4xl text-white"
                        style={{ fontVariationSettings: '"FILL" 1' }}
                      >
                        verified
                      </span>
                    </div>
                    <h2 className="mb-4 text-3xl font-bold text-white md:text-4xl">환영합니다!</h2>
                    <p className="mb-10 max-w-sm text-sm text-white/65">
                      개인 인텔리전스 보관소가 초기화되어 심층 인덱싱 준비가 완료되었습니다.
                    </p>
                    <button
                      type="button"
                      onClick={() => navigate('/search')}
                      className="flex items-center gap-3 rounded-full border-2 border-sky-300/50 px-10 py-4 font-bold text-sky-100 transition-all hover:border-sky-200 hover:bg-white/[0.06]"
                    >
                      인덱스 구축 시작
                      <span className="material-symbols-outlined">database</span>
                    </button>
                  </div>
                )}
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
