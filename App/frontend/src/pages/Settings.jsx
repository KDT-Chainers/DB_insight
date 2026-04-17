import { useNavigate } from 'react-router-dom'
import { useState } from 'react'
import { useSidebar } from '../context/SidebarContext'

export default function Settings() {
  const navigate = useNavigate()
  const [cloudSync, setCloudSync] = useState(true)
  const [neuralFeedback, setNeuralFeedback] = useState(false)
  const { open } = useSidebar()

  const [modalOpen, setModalOpen] = useState(false)
  const [currentPw, setCurrentPw] = useState('')
  const [newPw, setNewPw] = useState('')
  const [confirmPw, setConfirmPw] = useState('')
  const [modalError, setModalError] = useState('')
  const [modalSuccess, setModalSuccess] = useState(false)
  const [loading, setLoading] = useState(false)

  const openModal = () => {
    setCurrentPw('')
    setNewPw('')
    setConfirmPw('')
    setModalError('')
    setModalSuccess(false)
    setModalOpen(true)
  }

  const closeModal = () => {
    if (loading) return
    setModalOpen(false)
  }

  const handlePasswordChange = async (e) => {
    e.preventDefault()
    setModalError('')

    if (newPw !== confirmPw) {
      setModalError('새 비밀번호가 일치하지 않습니다.')
      return
    }
    if (newPw.length < 1) {
      setModalError('새 비밀번호를 입력하세요.')
      return
    }

    setLoading(true)
    try {
      const res = await fetch('http://localhost:5001/api/auth/reset', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ current_password: currentPw, new_password: newPw }),
      })
      const data = await res.json()
      if (!res.ok) {
        setModalError(data.error || '변경에 실패했습니다.')
      } else {
        setModalSuccess(true)
        setTimeout(() => setModalOpen(false), 1200)
      }
    } catch {
      setModalError('서버에 연결할 수 없습니다.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="bg-surface text-on-surface antialiased min-h-screen">
      {/* Sidebar */}
      <aside className="h-screen w-64 fixed left-0 border-r border-outline-variant/15 bg-[#070d1f] flex flex-col py-8 px-4 gap-4 z-50">
        <div className="mb-8 px-4">
          <h1 className="text-[#85adff] font-bold text-xl tracking-tighter">Obsidian 인텔리전스</h1>
          <p className="font-manrope uppercase tracking-widest text-[0.7rem] text-on-surface-variant mt-1">DB_insight v.2.0.4</p>
        </div>
        <nav className="flex flex-col gap-2">
          <button
            onClick={() => navigate('/search')}
            className="text-[#a5aac2] px-4 py-3 hover:text-[#dfe4fe] hover:bg-[#1c253e]/20 transition-all duration-200 cursor-pointer flex items-center gap-3 rounded-xl group hover:translate-x-1"
          >
            <span className="material-symbols-outlined text-lg">psychology</span>
            <span className="font-manrope uppercase tracking-widest text-[0.75rem]">인텔리전스</span>
          </button>
          <button className="text-[#a5aac2] px-4 py-3 hover:text-[#dfe4fe] hover:bg-[#1c253e]/20 transition-all duration-200 cursor-pointer flex items-center gap-3 rounded-xl group hover:translate-x-1">
            <span className="material-symbols-outlined text-lg">folder_open</span>
            <span className="font-manrope uppercase tracking-widest text-[0.75rem]">파일</span>
          </button>
          <div className="text-[#85adff] bg-[#1c253e]/40 rounded-xl px-4 py-3 border-l-2 border-[#ac8aff] flex items-center gap-3 translate-x-1">
            <span className="material-symbols-outlined text-lg" style={{ fontVariationSettings: '"FILL" 1' }}>tune</span>
            <span className="font-manrope uppercase tracking-widest text-[0.75rem] font-semibold">설정</span>
          </div>
          <button className="text-[#a5aac2] px-4 py-3 hover:text-[#dfe4fe] hover:bg-[#1c253e]/20 transition-all duration-200 cursor-pointer flex items-center gap-3 rounded-xl group hover:translate-x-1">
            <span className="material-symbols-outlined text-lg">help_outline</span>
            <span className="font-manrope uppercase tracking-widest text-[0.75rem]">지원</span>
          </button>
        </nav>
        <div className="mt-auto px-4 py-6 border-t border-outline-variant/10">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-full overflow-hidden border border-primary/30 bg-surface-container-highest flex items-center justify-center">
              <span className="material-symbols-outlined text-primary">account_circle</span>
            </div>
            <div>
              <p className="text-sm font-bold text-on-surface leading-tight">Alex Thorne</p>
              <p className="text-[0.7rem] text-on-surface-variant font-mono">NODE-7721-B</p>
            </div>
          </div>
        </div>
      </aside>

      {/* Main */}
      <main className={`${open ? 'ml-64' : 'ml-0'} min-h-screen p-12 relative overflow-hidden transition-[margin] duration-300`}>
        <div className="absolute top-[-10%] right-[-10%] w-[500px] h-[500px] bg-primary/10 rounded-full blur-[120px] pointer-events-none"></div>
        <div className="absolute bottom-[-5%] left-[5%] w-[400px] h-[400px] bg-secondary/5 rounded-full blur-[100px] pointer-events-none"></div>

        <div className="max-w-4xl mx-auto relative z-10">
          <header className="mb-12">
            <h2 className="text-4xl font-extrabold tracking-tight text-on-surface mb-2">시스템 설정</h2>
            <p className="text-on-surface-variant max-w-xl">
              DB_insight의 로컬 인텔리전스 노드 파라미터를 구성하고 보안 프로토콜을 관리합니다.
            </p>
          </header>

          <div className="grid grid-cols-1 gap-8">
            {/* Security */}
            <section className="glass-panel p-8 rounded-xl border border-outline-variant/15 shadow-[0_0_40px_rgba(133,173,255,0.05)]">
              <div className="flex items-center gap-2 mb-6">
                <span className="text-[0.75rem] font-manrope uppercase tracking-[0.2em] text-primary font-bold">보안 프로토콜</span>
                <div className="h-[1px] flex-grow bg-outline-variant/20"></div>
              </div>
              <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-6">
                <div>
                  <h3 className="text-xl font-semibold text-on-surface mb-2">마스터 인증</h3>
                  <p className="text-on-surface-variant text-sm">마스터 비밀번호는 로컬 데이터베이스를 복호화합니다. 초기화하면 로컬 암호화 키가 업데이트됩니다.</p>
                </div>
                <button
                  onClick={openModal}
                  className="bg-gradient-to-tr from-primary to-secondary text-on-primary font-bold py-3 px-8 rounded-full shadow-lg shadow-primary/20 hover:scale-105 active:scale-95 transition-all duration-300 whitespace-nowrap"
                >
                  마스터 비밀번호 변경
                </button>
              </div>
            </section>

            {/* Preferences */}
            <section className="glass-panel p-8 rounded-xl border border-outline-variant/15">
              <div className="flex items-center gap-2 mb-6">
                <span className="text-[0.75rem] font-manrope uppercase tracking-[0.2em] text-primary font-bold">환경 설정</span>
                <div className="h-[1px] flex-grow bg-outline-variant/20"></div>
              </div>
              <div className="space-y-8">
                <div>
                  <label className="block text-[0.7rem] uppercase tracking-widest text-on-surface-variant font-bold mb-3">자주 사용하는 이메일</label>
                  <div className="relative max-w-md">
                    <input
                      className="w-full bg-transparent border-0 border-b border-outline-variant py-3 px-0 text-on-surface focus:ring-0 focus:border-primary transition-colors duration-300 placeholder-outline outline-none"
                      placeholder="archivist@obsidian.io"
                      type="email"
                      defaultValue="a.thorne@obsidian-intel.local"
                    />
                  </div>
                  <p className="mt-3 text-xs text-on-surface-variant/70 italic">자동 보고서 발송 및 긴급 노드 복구 알림에 사용됩니다.</p>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  {/* Toggle: Cloud Sync */}
                  <div className="p-4 rounded-xl bg-surface-container-low border border-outline-variant/10 flex items-center justify-between">
                    <div>
                      <p className="text-sm font-semibold text-on-surface">클라우드 동기화</p>
                      <p className="text-xs text-on-surface-variant">로컬 로그를 암호화된 클라우드에 동기화</p>
                    </div>
                    <button
                      onClick={() => setCloudSync(!cloudSync)}
                      className={`w-10 h-5 rounded-full relative cursor-pointer p-1 transition-colors duration-300 ${cloudSync ? 'bg-primary/30' : 'bg-surface-container-highest'}`}
                    >
                      <div className={`w-3 h-3 bg-primary rounded-full absolute top-1 transition-all ${cloudSync ? 'right-1' : 'left-1'}`}></div>
                    </button>
                  </div>
                  {/* Toggle: Neural Feedback */}
                  <div className="p-4 rounded-xl bg-surface-container-low border border-outline-variant/10 flex items-center justify-between">
                    <div>
                      <p className="text-sm font-semibold text-on-surface">신경망 피드백</p>
                      <p className="text-xs text-on-surface-variant">햅틱 처리 신호 활성화</p>
                    </div>
                    <button
                      onClick={() => setNeuralFeedback(!neuralFeedback)}
                      className={`w-10 h-5 rounded-full relative cursor-pointer p-1 transition-colors duration-300 ${neuralFeedback ? 'bg-primary/30' : 'bg-surface-container-highest'}`}
                    >
                      <div className={`w-3 h-3 rounded-full absolute top-1 transition-all ${neuralFeedback ? 'bg-primary right-1' : 'bg-outline left-1'}`}></div>
                    </button>
                  </div>
                </div>
              </div>
            </section>

            {/* Danger zone */}
            <section className="glass-panel p-8 rounded-xl border border-error-dim/20 bg-error-dim/5 relative overflow-hidden">
              <div className="absolute -right-20 -bottom-20 w-64 h-64 bg-error-dim/10 blur-[80px] rounded-full"></div>
              <div className="flex items-center gap-2 mb-6">
                <span className="text-[0.75rem] font-manrope uppercase tracking-[0.2em] text-error-dim font-bold">위험 구역</span>
                <div className="h-[1px] flex-grow bg-error-dim/20"></div>
              </div>
              <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-6 relative z-10">
                <div className="max-w-xl">
                  <h3 className="text-xl font-semibold text-error-dim mb-2">공장 초기화 및 데이터 삭제</h3>
                  <p className="text-on-surface-variant text-sm">
                    모든 인텔리전스 노드, 로컬 파일, 시스템 환경 설정을 영구적으로 삭제합니다. 이 작업은 되돌릴 수 없으며 할당된 모든 저장 섹터를 초기화합니다.
                  </p>
                </div>
                <button className="whitespace-nowrap border border-error-dim/40 text-error-dim font-bold py-3 px-8 rounded-full hover:bg-error-dim hover:text-white transition-all duration-300 active:scale-95 shadow-[0_0_20px_rgba(215,56,59,0.1)]">
                  앱 및 데이터 삭제
                </button>
              </div>
            </section>
          </div>

          {/* Footer */}
          <footer className="mt-16 flex flex-col items-center justify-center text-on-surface-variant/40 space-y-4">
            <div className="flex items-center gap-8">
              {[['저장소', '1.2TB / 4.0TB'], ['지연', '14ms'], ['가동시간', '1,402h']].map(([label, val]) => (
                <div key={label} className="text-center">
                  <p className="text-[0.6rem] uppercase tracking-widest font-bold">{label}</p>
                  <p className="text-xs font-mono">{val}</p>
                </div>
              ))}
            </div>
            <p className="text-[0.6rem] uppercase tracking-widest">© 2024 Obsidian Intelligence Systems. 모든 권리 보유.</p>
          </footer>
        </div>
      </main>
      {/* 비밀번호 변경 모달 */}
      {modalOpen && (
        <div className="fixed inset-0 z-[9999] flex items-center justify-center">
          <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={closeModal} />
          <div className="relative w-full max-w-md mx-4 bg-[#0c1326] border border-outline-variant/20 rounded-2xl shadow-[0_0_60px_rgba(133,173,255,0.15)] p-8">
            <button
              onClick={closeModal}
              disabled={loading}
              className="absolute top-4 right-4 text-on-surface-variant hover:text-on-surface transition-colors"
            >
              <span className="material-symbols-outlined">close</span>
            </button>

            <h3 className="text-xl font-bold text-on-surface mb-1">마스터 비밀번호 변경</h3>
            <p className="text-xs text-on-surface-variant mb-8">현재 비밀번호를 확인한 후 새 비밀번호로 변경합니다.</p>

            {modalSuccess ? (
              <div className="flex flex-col items-center gap-3 py-6">
                <span className="material-symbols-outlined text-4xl text-primary">check_circle</span>
                <p className="text-sm font-bold text-on-surface">비밀번호가 변경되었습니다.</p>
              </div>
            ) : (
              <form onSubmit={handlePasswordChange} className="flex flex-col gap-5">
                <div className="flex flex-col gap-1.5">
                  <label className="text-[10px] uppercase tracking-widest text-on-surface-variant font-bold">현재 비밀번호</label>
                  <input
                    type="password"
                    value={currentPw}
                    onChange={(e) => setCurrentPw(e.target.value)}
                    required
                    disabled={loading}
                    className="bg-surface-container-high border border-outline-variant/30 rounded-xl px-4 py-3 text-sm text-on-surface focus:outline-none focus:border-primary/60 transition-colors disabled:opacity-50"
                    placeholder="현재 비밀번호 입력"
                  />
                </div>

                <div className="flex flex-col gap-1.5">
                  <label className="text-[10px] uppercase tracking-widest text-on-surface-variant font-bold">새 비밀번호</label>
                  <input
                    type="password"
                    value={newPw}
                    onChange={(e) => setNewPw(e.target.value)}
                    required
                    disabled={loading}
                    className="bg-surface-container-high border border-outline-variant/30 rounded-xl px-4 py-3 text-sm text-on-surface focus:outline-none focus:border-primary/60 transition-colors disabled:opacity-50"
                    placeholder="새 비밀번호 입력"
                  />
                </div>

                <div className="flex flex-col gap-1.5">
                  <label className="text-[10px] uppercase tracking-widest text-on-surface-variant font-bold">새 비밀번호 확인</label>
                  <input
                    type="password"
                    value={confirmPw}
                    onChange={(e) => setConfirmPw(e.target.value)}
                    required
                    disabled={loading}
                    className="bg-surface-container-high border border-outline-variant/30 rounded-xl px-4 py-3 text-sm text-on-surface focus:outline-none focus:border-primary/60 transition-colors disabled:opacity-50"
                    placeholder="새 비밀번호 다시 입력"
                  />
                </div>

                {modalError && (
                  <p className="text-xs text-red-400 font-medium">{modalError}</p>
                )}

                <div className="flex gap-3 pt-2">
                  <button
                    type="button"
                    onClick={closeModal}
                    disabled={loading}
                    className="flex-1 py-3 rounded-full border border-outline-variant/30 text-sm font-bold text-on-surface-variant hover:text-on-surface hover:border-outline-variant/60 transition-all disabled:opacity-50"
                  >
                    취소
                  </button>
                  <button
                    type="submit"
                    disabled={loading}
                    className="flex-1 py-3 rounded-full bg-gradient-to-tr from-primary to-secondary text-on-primary text-sm font-bold hover:brightness-110 active:scale-95 transition-all disabled:opacity-50"
                  >
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
