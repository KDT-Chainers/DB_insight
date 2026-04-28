/**
 * LibreOfficeSetupModal
 *
 * 앱 시작 시 /api/setup/check 를 호출해 LibreOffice 미설치 상태이면
 * 전체 화면을 덮는 모달을 표시합니다. 설치 완료 후 자동으로 닫힙니다.
 *
 * 설치는 Electron IPC(install-libreoffice)를 통해 메인 프로세스에서 직접
 * msiexec /passive 로 실행합니다. 메인 프로세스(GUI)에서 호출해야 UAC 팝업이
 * 정상적으로 표시됩니다.
 */
import { useEffect, useState } from 'react'
import { API_BASE } from '../api'

export default function LibreOfficeSetupModal() {
  // null = 확인 중, true = 설치됨(모달 불필요), false = 미설치(모달 표시)
  const [loInstalled, setLoInstalled] = useState(null)
  const [hasMsi, setHasMsi]           = useState(false)
  const [installing, setInstalling]   = useState(false)
  const [message, setMessage]         = useState('')
  const [error, setError]             = useState('')
  const [done, setDone]               = useState(false)

  // ── 최초 설치 여부 확인 ─────────────────────────────────────────
  useEffect(() => {
    fetch(`${API_BASE}/api/setup/check`)
      .then(r => r.json())
      .then(d => {
        setLoInstalled(!!(d.libreoffice?.installed))
        setHasMsi(!!(d.local_msi?.exists))
      })
      .catch(() => setLoInstalled(true)) // 백엔드 오류 → 모달 숨김(방해 안 함)
  }, [])

  // ── 설치 시작 (Electron IPC → 메인 프로세스에서 msiexec 실행) ──
  const startInstall = async () => {
    setError('')
    setInstalling(true)
    setMessage('UAC 권한 요청 중 — 관리자 권한을 허용해 주세요...')
    try {
      // Electron 환경: IPC로 메인 프로세스에서 msiexec /passive 실행
      if (window.electronAPI?.installLibreOffice) {
        const result = await window.electronAPI.installLibreOffice()
        if (result.success) {
          setDone(true)
        } else {
          setError(result.error || `설치 실패 (코드: ${result.code})`)
        }
      } else {
        // 브라우저 환경 fallback: Flask API 사용
        await fetch(`${API_BASE}/api/setup/install-lo`, { method: 'POST' })
        setMessage('설치 중...')
        // 상태 폴링
        await new Promise((resolve) => {
          const t = setInterval(async () => {
            try {
              const r = await fetch(`${API_BASE}/api/setup/install-status`)
              const d = await r.json()
              setMessage(d.message || '')
              if (d.state === 'done')  { clearInterval(t); setDone(true); resolve() }
              if (d.state === 'error') { clearInterval(t); setError(d.error || '설치 실패'); resolve() }
            } catch (_) {}
          }, 1000)
        })
      }
    } catch (e) {
      setError('설치 오류: ' + (e?.message || String(e)))
    }
    setInstalling(false)
  }

  // 확인 중이거나 이미 설치된 경우 → 모달 미표시
  if (loInstalled === null || loInstalled === true) return null

  // 설치 완료 → 0.8초 후 모달 닫기
  if (done) {
    setTimeout(() => setLoInstalled(true), 800)
    return (
      <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/70 backdrop-blur-sm">
        <div className="bg-[#0d1526] border border-white/10 rounded-3xl p-8 w-full max-w-sm mx-4 flex flex-col items-center gap-5 shadow-2xl">
          <div className="w-16 h-16 rounded-full bg-emerald-500/20 border border-emerald-500/30 flex items-center justify-center">
            <span className="material-symbols-outlined text-emerald-400 text-3xl" style={{ fontVariationSettings: '"FILL" 1' }}>
              check_circle
            </span>
          </div>
          <div className="text-center">
            <p className="text-lg font-bold text-white mb-1">설치 완료</p>
            <p className="text-sm text-white/50">앱을 계속 사용하실 수 있습니다.</p>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/70 backdrop-blur-sm">
      <div className="bg-[#0d1526] border border-white/10 rounded-3xl p-8 w-full max-w-md mx-4 flex flex-col gap-6 shadow-2xl">

        {/* 헤더 */}
        <div className="flex items-start gap-4">
          <div className="w-12 h-12 rounded-xl bg-[#1e3a8a]/40 border border-[#85adff]/20 flex items-center justify-center shrink-0">
            <span className="material-symbols-outlined text-[#85adff] text-2xl">description</span>
          </div>
          <div>
            <h2 className="text-xl font-bold text-white">LibreOffice 필요</h2>
            <p className="text-sm text-white/50 mt-0.5">
              문서(.docx · .hwp · .pptx · .xlsx) 검색을 위한 필수 구성요소입니다.
            </p>
          </div>
        </div>

        {/* MSI 경로 안내 */}
        <div className="bg-white/[0.04] border border-white/[0.07] rounded-2xl p-4 space-y-2">
          <div className="flex items-center gap-2">
            <span className={`w-2 h-2 rounded-full shrink-0 ${hasMsi ? 'bg-emerald-400' : 'bg-amber-400'}`} />
            <span className="text-xs text-white/60 font-mono">
              {hasMsi
                ? 'C:\\Honey\\DB_insight\\LibreOffice_26.2.2_Win_x86-64.msi'
                : '번들 MSI 없음 — winget / 인터넷 다운로드 사용'}
            </span>
          </div>
          <p className="text-[11px] text-white/35 pl-4">
            {hasMsi
              ? '로컬 설치 파일이 확인되었습니다. 네트워크 없이 설치됩니다.'
              : '인터넷 연결이 필요합니다.'}
          </p>
        </div>

        {/* 설치 상태 */}
        {installing && (
          <div className="flex items-center gap-3 bg-white/[0.04] rounded-xl px-4 py-3">
            <span className="material-symbols-outlined text-[#85adff] text-lg animate-spin shrink-0">progress_activity</span>
            <p className="text-xs text-white/50 truncate">{message || '설치 중...'}</p>
          </div>
        )}
        {error && (
          <div className="bg-red-500/10 border border-red-500/20 rounded-xl px-4 py-3">
            <p className="text-xs text-red-400 truncate">{error}</p>
          </div>
        )}

        {/* 안내 */}
        {!installing && !error && (
          <ul className="space-y-1.5 text-[11px] text-white/40">
            {[
              '관리자 권한이 필요할 수 있습니다.',
              '.pdf · 이미지 · 동영상 · 음성 파일은 LibreOffice 없이 동작합니다.',
              '설치 위치: C:\\Honey\\DB_insight\\Data\\LibreOffice',
            ].map((t, i) => (
              <li key={i} className="flex items-start gap-1.5">
                <span className="material-symbols-outlined text-[11px] text-[#85adff]/50 mt-px shrink-0">info</span>
                {t}
              </li>
            ))}
          </ul>
        )}

        {/* 버튼 */}
        <button
          onClick={installing ? undefined : startInstall}
          disabled={installing}
          className="w-full py-3.5 rounded-2xl font-bold text-sm flex items-center justify-center gap-2 transition-all active:scale-95
            bg-gradient-to-r from-[#85adff] to-[#ac8aff] text-[#070d1f]
            hover:brightness-110 disabled:opacity-60 disabled:cursor-not-allowed"
        >
          {installing ? (
            <>
              <span className="material-symbols-outlined text-sm animate-spin">progress_activity</span>
              설치 중...
            </>
          ) : (
            <>
              <span className="material-symbols-outlined text-sm">download</span>
              다운로드 및 설치
            </>
          )}
        </button>

        {error && (
          <p className="text-xs text-center text-red-400/70 -mt-2">
            자동 설치 실패 시 MSI를 직접 실행하거나{' '}
            <a
              href="https://www.libreoffice.org/download/"
              target="_blank"
              rel="noreferrer"
              className="underline"
            >
              libreoffice.org
            </a>
            에서 수동 설치하세요.
          </p>
        )}
      </div>
    </div>
  )
}
