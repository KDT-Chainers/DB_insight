import { useNavigate } from 'react-router-dom'
import { useState, useEffect, useCallback } from 'react'
import { useScale } from '../context/ScaleContext'
import { API_BASE } from '../api'
import WindowControls from '../components/WindowControls'
import PageSidebar from '../components/PageSidebar'

export default function Settings() {
  const navigate = useNavigate()
  const [cloudSync, setCloudSync] = useState(true)
  const [neuralFeedback, setNeuralFeedback] = useState(false)
  const { scale, setScale, MIN_SCALE, MAX_SCALE, STEP } = useScale()

  // ── BGM API 스위치 ───────────────────────────────────────
  const [bgmStatus, setBgmStatus] = useState(null)
  const [bgmHost, setBgmHost] = useState('')
  const [bgmKey, setBgmKey] = useState('')
  const [bgmSecret, setBgmSecret] = useState('')
  const [bgmTesting, setBgmTesting] = useState(false)
  const [bgmSyncing, setBgmSyncing] = useState(false)
  const [bgmMsg, setBgmMsg] = useState('')

  const refreshBgmStatus = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/bgm/api_status`)
      if (res.ok) {
        const d = await res.json()
        setBgmStatus(d)
        setBgmHost(d.host || '')
      }
    } catch { /* 백엔드 비동작 시 무시 */ }
  }, [])
  useEffect(() => { refreshBgmStatus() }, [refreshBgmStatus])

  const updateBgmApi = async (patch) => {
    setBgmMsg('')
    try {
      const res = await fetch(`${API_BASE}/api/bgm/api_toggle`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(patch),
      })
      const d = await res.json()
      setBgmStatus(d)
      setBgmHost(d.host || '')
      // 키 입력 필드는 보안상 패치 후 비움 (마스킹 표시는 status로 확인)
      if (patch.access_key !== undefined) setBgmKey('')
      if (patch.access_secret !== undefined) setBgmSecret('')
      setBgmMsg(`설정 갱신: api_enabled=${d.api_enabled}`)
    } catch (e) {
      setBgmMsg(`갱신 실패: ${e.message}`)
    }
  }

  const handleSyncCatalog = async () => {
    setBgmSyncing(true); setBgmMsg('카탈로그 동기화 중...')
    try {
      const res = await fetch(`${API_BASE}/api/bgm/catalog_sync`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ only_missing: true }),
      })
      const d = await res.json()
      if (d.error) setBgmMsg(`실패: ${d.error}`)
      else setBgmMsg(`완료: ${d.synced}곡 메타 보강`)
    } catch (e) { setBgmMsg(`실패: ${e.message}`) }
    finally { setBgmSyncing(false) }
  }

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

      {/* ── Sidebar ── */}
      <PageSidebar subtitle="시스템 설정">
        {[
          { icon: 'database',      label: '워크스페이스', onClick: () => navigate('/search') },
          { icon: 'account_tree',  label: '인덱싱',       onClick: () => navigate('/data')   },
          { icon: 'tune',          label: '설정',         active: true },
        ].map(item => (
          <button
            key={item.label}
            onClick={item.onClick}
            className={`w-full flex items-center gap-3 rounded-xl px-4 py-2.5 text-base font-manrope uppercase tracking-widest transition-all
              ${item.active
                ? 'text-primary bg-[#1c253e]'
                : 'text-[#a5aac2] hover:bg-[#1c253e]/50 hover:text-[#dfe4fe]'}`}
          >
            <span className="material-symbols-outlined text-base">{item.icon}</span>
            {item.label}
          </button>
        ))}
      </PageSidebar>

      {/* ── Main ── */}
      <main className="flex-1 flex flex-col overflow-hidden bg-surface-dim relative">
        <div className="absolute top-0 right-0 w-96 h-96 bg-primary/10 rounded-full blur-[120px] pointer-events-none" />
        <div className="absolute bottom-0 left-0 w-72 h-72 bg-secondary/5 rounded-full blur-[100px] pointer-events-none" />

        {/* 드래그 타이틀바 */}
        <header className="shrink-0 bg-[#070d1f] flex justify-end items-center px-2 h-8 z-40"
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
                  <span className="text-sm font-manrope uppercase tracking-[0.2em] text-primary font-bold">보안 프로토콜</span>
                  <div className="h-px flex-grow bg-outline-variant/20" />
                </div>
                <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
                  <div>
                    <h3 className="text-base font-semibold text-on-surface mb-1">마스터 인증</h3>
                    <p className="text-sm text-on-surface-variant">마스터 비밀번호는 로컬 데이터베이스를 복호화합니다.</p>
                  </div>
                  <button
                    onClick={openModal}
                    className="shrink-0 bg-gradient-to-tr from-primary to-secondary text-on-primary font-bold py-2.5 px-6 rounded-full text-lg shadow-lg shadow-primary/20 hover:scale-105 active:scale-95 transition-all duration-200 whitespace-nowrap"
                  >
                    비밀번호 변경
                  </button>
                </div>
              </section>

              {/* 환경설정 */}
              <section className="glass-panel p-6 rounded-xl border border-outline-variant/15">
                <div className="flex items-center gap-2 mb-5">
                  <span className="text-sm font-manrope uppercase tracking-[0.2em] text-primary font-bold">환경 설정</span>
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
                            className={`px-2.5 py-1 rounded-lg text-lg font-bold transition-all
                              ${Math.abs(scale - v) < 0.01
                                ? 'bg-primary/20 text-primary border border-primary/30'
                                : 'bg-surface-container-high text-on-surface-variant hover:text-on-surface border border-outline-variant/20'}`}>
                            {Math.round(v * 100)}%
                          </button>
                        ))}
                      </div>
                    </div>
                    <div className="flex items-center gap-3">
                      <span className="text-sm text-on-surface-variant/50 w-8">{Math.round(MIN_SCALE * 100)}%</span>
                      <input type="range" min={MIN_SCALE} max={MAX_SCALE} step={STEP} value={scale}
                        onChange={e => setScale(parseFloat(e.target.value))}
                        className="flex-1 h-1.5 rounded-full appearance-none cursor-pointer bg-surface-container-highest
                          [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-4 [&::-webkit-slider-thumb]:h-4
                          [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-primary
                          [&::-webkit-slider-thumb]:shadow-[0_0_8px_rgba(133,173,255,0.5)] [&::-webkit-slider-thumb]:cursor-pointer"
                        style={{ background: `linear-gradient(to right, var(--md-sys-color-primary) 0%, var(--md-sys-color-primary) ${((scale - MIN_SCALE) / (MAX_SCALE - MIN_SCALE)) * 100}%, rgba(255,255,255,0.1) ${((scale - MIN_SCALE) / (MAX_SCALE - MIN_SCALE)) * 100}%, rgba(255,255,255,0.1) 100%)` }}
                      />
                      <span className="text-sm text-on-surface-variant/50 w-8 text-right">{Math.round(MAX_SCALE * 100)}%</span>
                      <span className="text-xs font-bold text-primary w-9 text-right">{Math.round(scale * 100)}%</span>
                    </div>
                    <p className="mt-2 text-base text-on-surface-variant/50">앱 전체 UI 크기를 조절합니다. 즉시 적용됩니다.</p>
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

              {/* BGM 검색 — 외부 API 스위치 */}
              <section className="glass-panel p-6 rounded-xl border border-pink-500/20 bg-pink-500/5 relative overflow-hidden">
                <div className="absolute -right-16 -bottom-16 w-48 h-48 bg-pink-500/10 blur-[60px] rounded-full" />
                <div className="flex items-center gap-2 mb-5">
                  <span className="material-symbols-outlined text-pink-400">music_note</span>
                  <span className="text-sm font-manrope uppercase tracking-[0.2em] text-pink-400 font-bold">BGM 검색</span>
                  <div className="h-px flex-grow bg-pink-500/20" />
                </div>
                <div className="space-y-4 relative z-10">
                  <p className="text-sm text-on-surface-variant">
                    기본은 로컬 모델 (Chromaprint + CLAP)로 검색합니다. 외부 ACRCloud API를 켜면 메타데이터 보강 및
                    fallback으로 이용할 수 있습니다.
                  </p>

                  {/* 마스터 토글 */}
                  <div className="p-4 rounded-xl bg-surface-container-low border border-outline-variant/10 flex items-center justify-between gap-3">
                    <div>
                      <p className="text-sm font-semibold text-on-surface">외부 음원 인식 API 사용</p>
                      <p className="text-xs text-on-surface-variant mt-0.5">
                        OFF 상태에서는 외부 호출이 0건이며 로컬 모델만 사용합니다.
                      </p>
                    </div>
                    <button
                      onClick={() => updateBgmApi({ api_enabled: !(bgmStatus?.api_enabled) })}
                      className={`shrink-0 w-10 h-5 rounded-full relative cursor-pointer p-1 transition-colors duration-300
                        ${bgmStatus?.api_enabled ? 'bg-pink-400/40' : 'bg-surface-container-highest'}`}
                    >
                      <div className={`w-3 h-3 rounded-full absolute top-1 transition-all
                        ${bgmStatus?.api_enabled ? 'bg-pink-400 right-1' : 'bg-outline left-1'}`} />
                    </button>
                  </div>

                  {/* API 활성 시 키 입력 + 액션 */}
                  {bgmStatus?.api_enabled && (
                    <div className="space-y-3 pl-3 border-l-2 border-pink-500/30">
                      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                        <input
                          type="text"
                          placeholder="ACR Host (예: identify-eu-west-1.acrcloud.com)"
                          value={bgmHost}
                          onChange={(e) => setBgmHost(e.target.value)}
                          className="bg-surface-container-high border border-outline-variant/30 rounded-lg px-3 py-2 text-sm text-on-surface focus:outline-none focus:border-pink-400/60 col-span-1 sm:col-span-3"
                        />
                        <input
                          type="text"
                          placeholder={bgmStatus?.access_key_set ? 'access_key (저장됨, 변경 시 입력)' : 'access_key'}
                          value={bgmKey}
                          onChange={(e) => setBgmKey(e.target.value)}
                          className="bg-surface-container-high border border-outline-variant/30 rounded-lg px-3 py-2 text-sm text-on-surface focus:outline-none focus:border-pink-400/60"
                        />
                        <input
                          type="password"
                          placeholder={bgmStatus?.access_secret_set ? 'access_secret (저장됨)' : 'access_secret'}
                          value={bgmSecret}
                          onChange={(e) => setBgmSecret(e.target.value)}
                          className="bg-surface-container-high border border-outline-variant/30 rounded-lg px-3 py-2 text-sm text-on-surface focus:outline-none focus:border-pink-400/60"
                        />
                        <button
                          type="button"
                          onClick={() => updateBgmApi({
                            host: bgmHost,
                            ...(bgmKey ? { access_key: bgmKey } : {}),
                            ...(bgmSecret ? { access_secret: bgmSecret } : {}),
                          })}
                          className="px-4 py-2 rounded-lg bg-pink-500/20 text-pink-300 border border-pink-400/40 text-sm font-bold hover:bg-pink-500/30 transition"
                        >
                          저장
                        </button>
                      </div>

                      <div className="flex items-center gap-2 text-xs text-on-surface-variant">
                        <span className="material-symbols-outlined text-base">
                          {bgmStatus?.api_configured ? 'check_circle' : 'error'}
                        </span>
                        {bgmStatus?.api_configured
                          ? '자격증명 등록됨'
                          : '자격증명 미등록 — 키 입력 후 저장하세요'}
                      </div>

                      <div className="flex flex-wrap gap-2">
                        <button
                          type="button"
                          disabled={!bgmStatus?.api_configured || bgmSyncing}
                          onClick={handleSyncCatalog}
                          className="px-4 py-2 rounded-full bg-gradient-to-r from-pink-500 to-rose-500 text-white text-sm font-bold disabled:opacity-40 disabled:cursor-not-allowed hover:shadow-lg hover:shadow-pink-500/30 transition"
                        >
                          {bgmSyncing ? '동기화 중...' : '음원 카탈로그 동기화 (102곡)'}
                        </button>
                        <button
                          type="button"
                          onClick={() => updateBgmApi({
                            fallback_to_local: !(bgmStatus?.fallback_to_local),
                          })}
                          className="px-4 py-2 rounded-full bg-white/5 border border-outline-variant/30 text-on-surface text-sm font-bold hover:bg-white/10 transition"
                        >
                          로컬 fallback: {bgmStatus?.fallback_to_local ? 'ON' : 'OFF'}
                        </button>
                        <button
                          type="button"
                          onClick={() => updateBgmApi({
                            auto_enrich_catalog: !(bgmStatus?.auto_enrich),
                          })}
                          className="px-4 py-2 rounded-full bg-white/5 border border-outline-variant/30 text-on-surface text-sm font-bold hover:bg-white/10 transition"
                        >
                          자동 메타 보강: {bgmStatus?.auto_enrich ? 'ON' : 'OFF'}
                        </button>
                      </div>
                    </div>
                  )}

                  {bgmMsg && (
                    <div className="text-xs text-on-surface-variant px-2 py-1 bg-white/5 rounded">
                      {bgmMsg}
                    </div>
                  )}
                </div>
              </section>

              {/* 위험 구역 */}
              <section className="glass-panel p-6 rounded-xl border border-red-500/20 bg-red-500/5 relative overflow-hidden">
                <div className="absolute -right-16 -bottom-16 w-48 h-48 bg-red-500/10 blur-[60px] rounded-full" />
                <div className="flex items-center gap-2 mb-5">
                  <span className="text-sm font-manrope uppercase tracking-[0.2em] text-red-400 font-bold">위험 구역</span>
                  <div className="h-px flex-grow bg-red-500/20" />
                </div>
                <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 relative z-10">
                  <div>
                    <h3 className="text-base font-semibold text-red-400 mb-1">공장 초기화 및 데이터 삭제</h3>
                    <p className="text-sm text-on-surface-variant">모든 인덱스, 로컬 파일, 설정을 영구적으로 삭제합니다.</p>
                  </div>
                  <button className="shrink-0 border border-red-500/40 text-red-400 font-bold py-2.5 px-6 rounded-full text-lg hover:bg-red-500 hover:text-white transition-all duration-200 active:scale-95 whitespace-nowrap">
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
                    <label className="text-sm uppercase tracking-widest text-on-surface-variant font-bold">{f.label}</label>
                    <input type="password" value={f.value} onChange={f.onChange} required disabled={loading}
                      placeholder={f.placeholder}
                      className="bg-surface-container-high border border-outline-variant/30 rounded-xl px-4 py-2.5 text-lg text-on-surface focus:outline-none focus:border-primary/60 transition-colors disabled:opacity-50" />
                  </div>
                ))}
                {modalError && <p className="text-xs text-red-400 font-medium">{modalError}</p>}
                <div className="flex gap-3 pt-1">
                  <button type="button" onClick={closeModal} disabled={loading}
                    className="flex-1 py-2.5 rounded-full border border-outline-variant/30 text-lg font-bold text-on-surface-variant hover:text-on-surface transition-all disabled:opacity-50">
                    취소
                  </button>
                  <button type="submit" disabled={loading}
                    className="flex-1 py-2.5 rounded-full bg-gradient-to-tr from-primary to-secondary text-on-primary text-lg font-bold hover:brightness-110 active:scale-95 transition-all disabled:opacity-50">
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
