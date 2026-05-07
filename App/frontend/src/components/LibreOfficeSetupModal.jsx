/**
 * LibreOfficeSetupModal
 *
 * ?? ? /api/setup/check ? ??? LibreOffice ??? ???
 * ?? ?? ?? ??? ????. ?? ?? ? ???? ????.
 *
 * ??? Electron IPC(install-libreoffice)? ?? ?????? ?????.
 * ?? ?????? ???? UAC ?? ?? ?? ?? ?????.
 */
import { useEffect, useState } from 'react'
import { API_BASE } from '../api'

export default function LibreOfficeSetupModal() {
  // null: ?? ?, true: ???(?? ??), false: ???(?? ??)
  const [loInstalled, setLoInstalled] = useState(null)
  const [hasMsi, setHasMsi] = useState(false)
  const [installing, setInstalling] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [done, setDone] = useState(false)

  useEffect(() => {
    fetch(`${API_BASE}/api/setup/check`)
      .then((r) => r.json())
      .then((d) => {
        setLoInstalled(!!d.libreoffice?.installed)
        setHasMsi(!!d.local_msi?.exists)
      })
      .catch(() => setLoInstalled(true)) // ??? ?? ? ??? ??? ??
  }, [])

  useEffect(() => {
    if (!done) return
    const t = setTimeout(() => setLoInstalled(true), 800)
    return () => clearTimeout(t)
  }, [done])

  const startInstall = async () => {
    setError('')
    setInstalling(true)
    setMessage('UAC ?? ?? ?... ??? ??? ??? ???.')

    try {
      // Electron ??: ?? ?????? msiexec /passive ??
      if (window.electronAPI?.installLibreOffice) {
        const result = await window.electronAPI.installLibreOffice()
        if (result.success) setDone(true)
        else setError(result.error || `?? ?? (??: ${result.code})`)
      } else {
        // ???? fallback: Flask API ??
        await fetch(`${API_BASE}/api/setup/install-lo`, { method: 'POST' })
        setMessage('?? ?...')

        await new Promise((resolve) => {
          const t = setInterval(async () => {
            try {
              const r = await fetch(`${API_BASE}/api/setup/install-status`)
              const d = await r.json()
              setMessage(d.message || '')
              if (d.state === 'done') {
                clearInterval(t)
                setDone(true)
                resolve()
              }
              if (d.state === 'error') {
                clearInterval(t)
                setError(d.error || '?? ??')
                resolve()
              }
            } catch (_) {}
          }, 1000)
        })
      }
    } catch (e) {
      setError(`?? ??: ${e?.message || String(e)}`)
    }

    setInstalling(false)
  }

  if (loInstalled === null || loInstalled === true) return null

  if (done) {
    return (
      <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/70 backdrop-blur-sm">
        <div className="mx-4 flex w-full max-w-sm flex-col items-center gap-5 rounded-3xl border border-white/10 bg-[#0d1526] p-8 shadow-2xl">
          <div className="flex h-16 w-16 items-center justify-center rounded-full border border-emerald-500/30 bg-emerald-500/20">
            <span
              className="material-symbols-outlined text-3xl text-emerald-400"
              style={{ fontVariationSettings: '"FILL" 1' }}
            >
              check_circle
            </span>
          </div>
          <div className="text-center">
            <p className="mb-1 text-lg font-bold text-white">?? ??</p>
            <p className="text-sm text-white/50">?? ?? ??? ? ????.</p>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/70 backdrop-blur-sm">
      <div className="mx-4 flex w-full max-w-md flex-col gap-6 rounded-3xl border border-white/10 bg-[#0d1526] p-8 shadow-2xl">
        <div className="flex items-start gap-4">
          <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl border border-[#85adff]/20 bg-[#1e3a8a]/40">
            <span className="material-symbols-outlined text-2xl text-[#85adff]">description</span>
          </div>
          <div>
            <h2 className="text-xl font-bold text-white">LibreOffice ?? ??</h2>
            <p className="mt-0.5 text-sm text-white/50">
              ??(.docx, .hwp, .pptx, .xlsx) ??? ?? ?? ???????.
            </p>
          </div>
        </div>

        <div className="space-y-2 rounded-2xl border border-white/[0.07] bg-white/[0.04] p-4">
          <div className="flex items-center gap-2">
            <span className={`h-2 w-2 shrink-0 rounded-full ${hasMsi ? 'bg-emerald-400' : 'bg-amber-400'}`} />
            <span className="font-mono text-xs text-white/60">
              {hasMsi
                ? 'C:\\Honey\\DB_insight\\LibreOffice_26.2.2_Win_x86-64.msi'
                : '?? MSI ?? (winget/??? ???? ??)'}
            </span>
          </div>
          <p className="pl-4 text-sm text-white/35">
            {hasMsi
              ? '?? ?? ??? ???? ???? ?? ?????.'
              : '??? ??? ?????.'}
          </p>
        </div>

        {installing && (
          <div className="flex items-center gap-3 rounded-xl bg-white/[0.04] px-4 py-3">
            <span className="material-symbols-outlined shrink-0 animate-spin text-lg text-[#85adff]">
              progress_activity
            </span>
            <p className="truncate text-xs text-white/50">{message || '?? ?...'}</p>
          </div>
        )}

        {error && (
          <div className="rounded-xl border border-red-500/20 bg-red-500/10 px-4 py-3">
            <p className="truncate text-xs text-red-400">{error}</p>
          </div>
        )}

        {!installing && !error && (
          <ul className="space-y-1.5 text-sm text-white/40">
            {[
              '??? ??? ??? ? ????.',
              'pdf/???/??/?? ??? LibreOffice ??? ?????.',
              '?? ??: C:\\Honey\\DB_insight\\Data\\LibreOffice',
            ].map((t, i) => (
              <li key={i} className="flex items-start gap-1.5">
                <span className="material-symbols-outlined mt-px shrink-0 text-base text-[#85adff]/50">
                  info
                </span>
                {t}
              </li>
            ))}
          </ul>
        )}

        <button
          onClick={installing ? undefined : startInstall}
          disabled={installing}
          className="flex w-full items-center justify-center gap-2 rounded-2xl bg-gradient-to-r from-[#85adff] to-[#ac8aff] py-3.5 text-lg font-bold text-[#070d1f] transition-all hover:brightness-110 active:scale-95 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {installing ? (
            <>
              <span className="material-symbols-outlined animate-spin text-lg">progress_activity</span>
              ?? ?...
            </>
          ) : (
            <>
              <span className="material-symbols-outlined text-lg">download</span>
              ???? ? ??
            </>
          )}
        </button>

        {error && (
          <p className="-mt-2 text-center text-xs text-red-400/70">
            ?? ?? ?? ? MSI? ?? ?????{' '}
            <a
              href="https://www.libreoffice.org/download/"
              target="_blank"
              rel="noreferrer"
              className="underline"
            >
              libreoffice.org
            </a>
            ?? ?? ??? ???.
          </p>
        )}
      </div>
    </div>
  )
}
