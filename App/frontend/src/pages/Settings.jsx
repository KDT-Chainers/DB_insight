import { useNavigate } from 'react-router-dom'
import { useState } from 'react'
import { useScale } from '../context/ScaleContext'
import { API_BASE } from '../api'
import WindowControls from '../components/WindowControls'
import TeamLogoMark from '../components/TeamLogoMark'

export default function Settings() {
  const navigate = useNavigate()
  const [cloudSync, setCloudSync] = useState(true)
  const [neuralFeedback, setNeuralFeedback] = useState(false)
  const { scale, setScale, MIN_SCALE, MAX_SCALE, STEP } = useScale()

  const [modalOpen, setModalOpen] = useState(false)
  const [currentPw, setCurrentPw] = useState('')
  const [newPw, setNewPw] = useState('')
  const [confirmPw, setConfirmPw] = useState('')
  const [modalError, setModalError] = useState('')
  const [modalSuccess, setModalSuccess] = useState(false)
  const [loading, setLoading] = useState(false)

  const openModal = () => {
    setCurrentPw(''); setNewPw(''); setConfirmPw('')
    setModalError(''); setModalSuccess(false); setModalOpen(true)
  }
  const closeModal = () => { if (!loading) setModalOpen(false) }

  const handlePasswordChange = async (e) => {
    e.preventDefault()
    setModalError('')
    if (newPw !== confirmPw) { setModalError('새 비밀번호가 일치하지 않습니다.'); return }
    if (newPw.length < 1) { setModalError('새 비밀번호를 입력하세요.'); return }
    setLoading(true)
    try {
      const res = await fetch(`${API_BASE}/api/auth/reset`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ current_password: currentPw, new_password: newPw }),
      })
      const data = await res.json()
      if (!res.ok) setModalError(data.error || '변경에 실패했습니다.')
      else { setModalSuccess(true); setTimeout(() => setModalOpen(false), 1200) }
    } catch { setModalError('서버에 연결할 수 없습니다.') }
    finally { setLoading(false) }
  }

  return (
    <div className="bg-surface text-on-surface flex h-screen overflow-hidden">

      {/* ── Sidebar (DataIndexing과 동일 스타일) ── */}
      <aside className="w-64 shrink-0 h-screen bg-[#070d1f]/60 backdrop-blur-xl flex flex-col pt-12 pb-4 border-r border-[#41475b]/15 shadow-[20px_0_40px_rgba(133,173,255,0.05)] z-50">
        <div className="px-4 mb-8 flex items-center gap-3">
          <TeamLogoMark />
          <div>
            <h1 className="text-xl font-black text-[#dfe4fe] leading-none">DB_insight</h1>
            <p className="text-[0.65rem] uppercase tracking-widest text-[#a5aac2] mt-1">시스템 설정</p>
          </div>
        </div>

        <nav className="flex-1 px-3 space-y-1">
          {[
            { icon: 'database', label: '워크스페이스', onClick: () => navigate('/search') },
            { icon: 'account_tree', label: '인덱싱', onClick: () => navigate('/data') },
            { icon: 'tune', label: '설정', active: true },
          ].map(item => (
            <button
              key={item.label}
              onClick={item.onClick}
              className={`w-full flex items-center gap-3 rounded-xl px-4 py-2.5 text-[0.75rem] font-manrope uppercase tracking-widest transition-all
                ${item.active
                  ? 'text-primary bg-[#1c253e]'
                  : 'text-[#a5aac2] hover:bg-[#1c253e]/50 hover:text-[#dfe4fe]'}`}
            >
              <span className="material-symbols-outlined text-base">{item.icon}</span>
              {item.label}
            </button>
          ))}
        </nav>

        <div className="px-4 mt-auto pt-4 border-t border-outline-variant/10 flex items-center gap-3">
          <div className="w-10 h-10 rounded-full bg-surface-container-highest flex items-center justify-center shrink-0">
            <span className="material-symbols-outlined text-primary">account_circle</span>
          </div>
          <div className="overflow-hidden">
            <p className="text-sm font-bold text-on-surface truncate">관리자</p>
            <p className="text-[0.65rem] text-on-surface-variant">심층 분석 접근 권한</p>
          </div>
        </div>
      </aside>

      {/* ── Main ── */}
      <main className="flex-1 flex flex-col overflow-hidden bg-surface-dim relative">
        <div className="absolute top-0 right-0 w-96 h-96 bg-primary/10 rounded-full blur-[120px] pointer-events-none" />
        <div className="absolute bottom-0 left-0 w-72 h-72 bg-secondary/5 rounded-full blur-[100px] pointer-events-none" />

        {/* 드래그 타이틀바 */}
        <header className="titlebar-chrome shrink-0 flex justify-end items-center px-2 h-8 z-40"
          style={{ WebkitAppRegion: 'drag' }}>
          <div style={{ WebkitAppRegion: 'no-drag' }}><WindowControls /></div>
        </header>

        <div className="flex-1 overflow-y-auto">
          <div className="max-w-3xl mx-auto px-8 py-8 relative z-10">

            <header className="mb-8">
              <h2 className="text-2xl font-extrabold tracking-tight text-on-surface mb-1">시스템 설정</h2>
              <p className="text-sm text-on-surface-variant">DB_insight 노드 파라미터 및 보안 프로토콜을 관리합니다.</p>
            </header>

            <div className="flex flex-col gap-5">

              {/* 보안 */}
              <section className="glass-panel p-6 rounded-xl border border-outline-variant/15">
                <div className="flex items-center gap-2 mb-5">
                  <span className="text-[0.7rem] font-manrope uppercase tracking-[0.2em] text-primary font-bold">보안 프로토콜</span>
                  <div className="h-px flex-grow bg-outline-variant/20" />
                </div>
                <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
                  <div>
                    <h3 className="text-base font-semibold text-on-surface mb-1">마스터 인증</h3>
                    <p className="text-sm text-on-surface-variant">마스터 비밀번호는 로컬 데이터베이스를 복호화합니다.</p>
                  </div>
                  <button
                    onClick={openModal}
                    className="shrink-0 bg-gradient-to-tr from-primary to-secondary text-on-primary font-bold py-2.5 px-6 rounded-full text-sm shadow-lg shadow-primary/20 hover:scale-105 active:scale-95 transition-all duration-200 whitespace-nowrap"
                  >
                    비밀번호 변경
                  </button>
                </div>
              </section>

              {/* 환경설정 */}
              <section className="glass-panel p-6 rounded-xl border border-outline-variant/15">
                <div className="flex items-center gap-2 mb-5">
                  <span className="text-[0.7rem] font-manrope uppercase tracking-[0.2em] text-primary font-bold">환경 설정</span>
                  <div className="h-px flex-grow bg-outline-variant/20" />
                </div>
                <div className="space-y-6">

                  {/* 화면 크기 */}
                  <div>
                    <div className="flex items-center justify-between mb-3">
                      <label className="text-xs uppercase tracking-widest text-on-surface-variant font-bold">화면 크기</label>
                      <div className="flex items-center gap-1.5">
                        {[0.7, 0.8, 0.9, 1.0].map(v => (
                          <button key={v} onClick={() => setScale(v)}
                            className={`px-2.5 py-1 rounded-lg text-[10px] font-bold transition-all
                              ${Math.abs(scale - v) < 0.01
                                ? 'bg-primary/20 text-primary border border-primary/30'
                                : 'bg-surface-container-high text-on-surface-variant hover:text-on-surface border border-outline-variant/20'}`}>
                            {Math.round(v * 100)}%
                          </button>
                        ))}
                      </div>
                    </div>
                    <div className="flex items-center gap-3">
                      <span className="text-[10px] text-on-surface-variant/50 w-8">{Math.round(MIN_SCALE * 100)}%</span>
                      <input type="range" min={MIN_SCALE} max={MAX_SCALE} step={STEP} value={scale}
                        onChange={e => setScale(parseFloat(e.target.value))}
                        className="flex-1 h-1.5 rounded-full appearance-none cursor-pointer bg-surface-container-highest
                          [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-4 [&::-webkit-slider-thumb]:h-4
                          [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-primary
                          [&::-webkit-slider-thumb]:shadow-[0_0_8px_rgba(133,173,255,0.5)] [&::-webkit-slider-thumb]:cursor-pointer"
                        style={{ background: `linear-gradient(to right, var(--md-sys-color-primary) 0%, var(--md-sys-color-primary) ${((scale - MIN_SCALE) / (MAX_SCALE - MIN_SCALE)) * 100}%, rgba(255,255,255,0.1) ${((scale - MIN_SCALE) / (MAX_SCALE - MIN_SCALE)) * 100}%, rgba(255,255,255,0.1) 100%)` }}
                      />
                      <span className="text-[10px] text-on-surface-variant/50 w-8 text-right">{Math.round(MAX_SCALE * 100)}%</span>
                      <span className="text-xs font-bold text-primary w-9 text-right">{Math.round(scale * 100)}%</span>
                    </div>
                    <p className="mt-2 text-xs text-on-surface-variant/50">앱 전체 UI 크기를 조절합니다. 즉시 적용됩니다.</p>
                  </div>

                  {/* 토글들 */}
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    {[
                      { label: '클라우드 동기화', desc: '로컬 로그를 암호화된 클라우드에 동기화', value: cloudSync, onChange: () => setCloudSync(v => !v) },
                      { label: '신경망 피드백', desc: '햅틱 처리 신호 활성화', value: neuralFeedback, onChange: () => setNeuralFeedback(v => !v) },
                    ].map(item => (
                      <div key={item.label} className="p-4 rounded-xl bg-surface-container-low border border-outline-variant/10 flex items-center justify-between gap-3">
                        <div>
                          <p className="text-sm font-semibold text-on-surface">{item.label}</p>
                          <p className="text-xs text-on-surface-variant mt-0.5">{item.desc}</p>
                        </div>
                        <button onClick={item.onChange}
                          className={`shrink-0 w-10 h-5 rounded-full relative cursor-pointer p-1 transition-colors duration-300 ${item.value ? 'bg-primary/30' : 'bg-surface-container-highest'}`}>
                          <div className={`w-3 h-3 rounded-full absolute top-1 transition-all ${item.value ? 'bg-primary right-1' : 'bg-outline left-1'}`} />
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              </section>

              {/* 위험 구역 */}
              <section className="glass-panel p-6 rounded-xl border border-red-500/20 bg-red-500/5 relative overflow-hidden">
                <div className="absolute -right-16 -bottom-16 w-48 h-48 bg-red-500/10 blur-[60px] rounded-full" />
                <div className="flex items-center gap-2 mb-5">
                  <span className="text-[0.7rem] font-manrope uppercase tracking-[0.2em] text-red-400 font-bold">위험 구역</span>
                  <div className="h-px flex-grow bg-red-500/20" />
                </div>
                <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 relative z-10">
                  <div>
                    <h3 className="text-base font-semibold text-red-400 mb-1">공장 초기화 및 데이터 삭제</h3>
                    <p className="text-sm text-on-surface-variant">모든 인덱스, 로컬 파일, 설정을 영구적으로 삭제합니다.</p>
                  </div>
                  <button className="shrink-0 border border-red-500/40 text-red-400 font-bold py-2.5 px-6 rounded-full text-sm hover:bg-red-500 hover:text-white transition-all duration-200 active:scale-95 whitespace-nowrap">
                    앱 및 데이터 삭제
                  </button>
                </div>
              </section>
            </div>
          </div>
        </div>
      </main>

      {/* ── 비밀번호 변경 모달 ── */}
      {modalOpen && (
        <div className="fixed inset-0 z-[9999] flex items-center justify-center">
          <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={closeModal} />
          <div className="relative w-full max-w-md mx-4 bg-[#0c1326] border border-outline-variant/20 rounded-2xl shadow-[0_0_60px_rgba(133,173,255,0.15)] p-8">
            <button onClick={closeModal} disabled={loading}
              className="absolute top-4 right-4 text-on-surface-variant hover:text-on-surface transition-colors">
              <span className="material-symbols-outlined">close</span>
            </button>
            <h3 className="text-lg font-bold text-on-surface mb-1">마스터 비밀번호 변경</h3>
            <p className="text-xs text-on-surface-variant mb-6">현재 비밀번호를 확인한 후 새 비밀번호로 변경합니다.</p>
            {modalSuccess ? (
              <div className="flex flex-col items-center gap-3 py-6">
                <span className="material-symbols-outlined text-4xl text-primary">check_circle</span>
                <p className="text-sm font-bold text-on-surface">비밀번호가 변경되었습니다.</p>
              </div>
            ) : (
              <form onSubmit={handlePasswordChange} className="flex flex-col gap-4">
                {[
                  { label: '현재 비밀번호', value: currentPw, onChange: e => setCurrentPw(e.target.value), placeholder: '현재 비밀번호 입력' },
                  { label: '새 비밀번호', value: newPw, onChange: e => setNewPw(e.target.value), placeholder: '새 비밀번호 입력' },
                  { label: '새 비밀번호 확인', value: confirmPw, onChange: e => setConfirmPw(e.target.value), placeholder: '새 비밀번호 다시 입력' },
                ].map(f => (
                  <div key={f.label} className="flex flex-col gap-1.5">
                    <label className="text-[10px] uppercase tracking-widest text-on-surface-variant font-bold">{f.label}</label>
                    <input type="password" value={f.value} onChange={f.onChange} required disabled={loading}
                      placeholder={f.placeholder}
                      className="bg-surface-container-high border border-outline-variant/30 rounded-xl px-4 py-2.5 text-sm text-on-surface focus:outline-none focus:border-primary/60 transition-colors disabled:opacity-50" />
                  </div>
                ))}
                {modalError && <p className="text-xs text-red-400 font-medium">{modalError}</p>}
                <div className="flex gap-3 pt-1">
                  <button type="button" onClick={closeModal} disabled={loading}
                    className="flex-1 py-2.5 rounded-full border border-outline-variant/30 text-sm font-bold text-on-surface-variant hover:text-on-surface transition-all disabled:opacity-50">
                    취소
                  </button>
                  <button type="submit" disabled={loading}
                    className="flex-1 py-2.5 rounded-full bg-gradient-to-tr from-primary to-secondary text-on-primary text-sm font-bold hover:brightness-110 active:scale-95 transition-all disabled:opacity-50">
                    {loading ? '변경 중...' : '변경'}
                  </button>
                </div>
              </form>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
