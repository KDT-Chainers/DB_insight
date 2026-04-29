/**
 * LibreOfficeSetupModal
 *
 * ???œì‘ ??/api/setup/check ë¥??¸ì¶œ??LibreOffice ë¯¸ì„¤ì¹??íƒœ?´ë©´
 * ?„ì²´ ?”ë©´????Š” ëª¨ë‹¬???œì‹œ?©ë‹ˆ?? ?¤ì¹˜ ?„ë£Œ ???ë™?¼ë¡œ ?«í™?ˆë‹¤.
 *
 * ?¤ì¹˜??Electron IPC(install-libreoffice)ë¥??µí•´ ë©”ì¸ ?„ë¡œ?¸ìŠ¤?ì„œ ì§ì ‘
 * msiexec /passive ë¡??¤í–‰?©ë‹ˆ?? ë©”ì¸ ?„ë¡œ?¸ìŠ¤(GUI)?ì„œ ?¸ì¶œ?´ì•¼ UAC ?ì—…?? * ?•ìƒ?ìœ¼ë¡??œì‹œ?©ë‹ˆ??
 */
import { useEffect, useState } from 'react'
import { API_BASE } from '../api'

export default function LibreOfficeSetupModal() {
  // null = ?•ì¸ ì¤? true = ?¤ì¹˜??ëª¨ë‹¬ ë¶ˆí•„??, false = ë¯¸ì„¤ì¹?ëª¨ë‹¬ ?œì‹œ)
  const [loInstalled, setLoInstalled] = useState(null)
  const [hasMsi, setHasMsi]           = useState(false)
  const [installing, setInstalling]   = useState(false)
  const [message, setMessage]         = useState('')
  const [error, setError]             = useState('')
  const [done, setDone]               = useState(false)

  // ?€?€ ìµœì´ˆ ?¤ì¹˜ ?¬ë? ?•ì¸ ?€?€?€?€?€?€?€?€?€?€?€?€?€?€?€?€?€?€?€?€?€?€?€?€?€?€?€?€?€?€?€?€?€?€?€?€?€?€?€?€?€
  useEffect(() => {
    fetch(`${API_BASE}/api/setup/check`)
      .then(r => r.json())
      .then(d => {
        setLoInstalled(!!(d.libreoffice?.installed))
        setHasMsi(!!(d.local_msi?.exists))
      })
      .catch(() => setLoInstalled(true)) // ë°±ì—”???¤ë¥˜ ??ëª¨ë‹¬ ?¨ê?(ë°©í•´ ????
  }, [])

  // ?€?€ ?¤ì¹˜ ?œì‘ (Electron IPC ??ë©”ì¸ ?„ë¡œ?¸ìŠ¤?ì„œ msiexec ?¤í–‰) ?€?€
  const startInstall = async () => {
    setError('')
    setInstalling(true)
    setMessage('UAC ê¶Œí•œ ?”ì²­ ì¤???ê´€ë¦¬ì ê¶Œí•œ???ˆìš©??ì£¼ì„¸??..')
    try {
      // Electron ?˜ê²½: IPCë¡?ë©”ì¸ ?„ë¡œ?¸ìŠ¤?ì„œ msiexec /passive ?¤í–‰
      if (window.electronAPI?.installLibreOffice) {
        const result = await window.electronAPI.installLibreOffice()
        if (result.success) {
          setDone(true)
        } else {
          setError(result.error || `?¤ì¹˜ ?¤íŒ¨ (ì½”ë“œ: ${result.code})`)
        }
      } else {
        // ë¸Œë¼?°ì? ?˜ê²½ fallback: Flask API ?¬ìš©
        await fetch(`${API_BASE}/api/setup/install-lo`, { method: 'POST' })
        setMessage('?¤ì¹˜ ì¤?..')
        // ?íƒœ ?´ë§
        await new Promise((resolve) => {
          const t = setInterval(async () => {
            try {
              const r = await fetch(`${API_BASE}/api/setup/install-status`)
              const d = await r.json()
              setMessage(d.message || '')
              if (d.state === 'done')  { clearInterval(t); setDone(true); resolve() }
              if (d.state === 'error') { clearInterval(t); setError(d.error || '?¤ì¹˜ ?¤íŒ¨'); resolve() }
            } catch (_) {}
          }, 1000)
        })
      }
    } catch (e) {
      setError('?¤ì¹˜ ?¤ë¥˜: ' + (e?.message || String(e)))
    }
    setInstalling(false)
  }

  // ?•ì¸ ì¤‘ì´ê±°ë‚˜ ?´ë? ?¤ì¹˜??ê²½ìš° ??ëª¨ë‹¬ ë¯¸í‘œ??  if (loInstalled === null || loInstalled === true) return null

  // ?¤ì¹˜ ?„ë£Œ ??0.8ì´???ëª¨ë‹¬ ?«ê¸°
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
            <p className="text-lg font-bold text-white mb-1">?¤ì¹˜ ?„ë£Œ</p>
            <p className="text-sm text-white/50">?±ì„ ê³„ì† ?¬ìš©?˜ì‹¤ ???ˆìŠµ?ˆë‹¤.</p>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/70 backdrop-blur-sm">
      <div className="bg-[#0d1526] border border-white/10 rounded-3xl p-8 w-full max-w-md mx-4 flex flex-col gap-6 shadow-2xl">

        {/* ?¤ë” */}
        <div className="flex items-start gap-4">
          <div className="w-12 h-12 rounded-xl bg-[#1e3a8a]/40 border border-[#85adff]/20 flex items-center justify-center shrink-0">
            <span className="material-symbols-outlined text-[#85adff] text-2xl">description</span>
          </div>
          <div>
            <h2 className="text-xl font-bold text-white">LibreOffice ?„ìš”</h2>
            <p className="text-sm text-white/50 mt-0.5">
              ë¬¸ì„œ(.docx Â· .hwp Â· .pptx Â· .xlsx) ê²€?‰ì„ ?„í•œ ?„ìˆ˜ êµ¬ì„±?”ì†Œ?…ë‹ˆ??
            </p>
          </div>
        </div>

        {/* MSI ê²½ë¡œ ?ˆë‚´ */}
        <div className="bg-white/[0.04] border border-white/[0.07] rounded-2xl p-4 space-y-2">
          <div className="flex items-center gap-2">
            <span className={`w-2 h-2 rounded-full shrink-0 ${hasMsi ? 'bg-emerald-400' : 'bg-amber-400'}`} />
            <span className="text-xs text-white/60 font-mono">
              {hasMsi
                ? 'C:\\Honey\\DB_insight\\LibreOffice_26.2.2_Win_x86-64.msi'
                : 'ë²ˆë“¤ MSI ?†ìŒ ??winget / ?¸í„°???¤ìš´ë¡œë“œ ?¬ìš©'}
            </span>
          </div>
          <p className="text-sm text-white/35 pl-4">
            {hasMsi
              ? 'ë¡œì»¬ ?¤ì¹˜ ?Œì¼???•ì¸?˜ì—ˆ?µë‹ˆ?? ?¤íŠ¸?Œí¬ ?†ì´ ?¤ì¹˜?©ë‹ˆ??'
              : '?¸í„°???°ê²°???„ìš”?©ë‹ˆ??'}
          </p>
        </div>

        {/* ?¤ì¹˜ ?íƒœ */}
        {installing && (
          <div className="flex items-center gap-3 bg-white/[0.04] rounded-xl px-4 py-3">
            <span className="material-symbols-outlined text-[#85adff] text-lg animate-spin shrink-0">progress_activity</span>
            <p className="text-xs text-white/50 truncate">{message || '?¤ì¹˜ ì¤?..'}</p>
          </div>
        )}
        {error && (
          <div className="bg-red-500/10 border border-red-500/20 rounded-xl px-4 py-3">
            <p className="text-xs text-red-400 truncate">{error}</p>
          </div>
        )}

        {/* ?ˆë‚´ */}
        {!installing && !error && (
          <ul className="space-y-1.5 text-lg text-white/40">
            {[
              'ê´€ë¦¬ì ê¶Œí•œ???„ìš”?????ˆìŠµ?ˆë‹¤.',
              '.pdf Â· ?´ë?ì§€ Â· ?™ì˜??Â· ?Œì„± ?Œì¼?€ LibreOffice ?†ì´ ?™ì‘?©ë‹ˆ??',
              '?¤ì¹˜ ?„ì¹˜: C:\\Honey\\DB_insight\\Data\\LibreOffice',
            ].map((t, i) => (
              <li key={i} className="flex items-start gap-1.5">
                <span className="material-symbols-outlined text-lg text-[#85adff]/50 mt-px shrink-0">info</span>
                {t}
              </li>
            ))}
          </ul>
        )}

        {/* ë²„íŠ¼ */}
        <button
          onClick={installing ? undefined : startInstall}
          disabled={installing}
          className="w-full py-3.5 rounded-2xl font-bold text-lg flex items-center justify-center gap-2 transition-all active:scale-95
            bg-gradient-to-r from-[#85adff] to-[#ac8aff] text-[#070d1f]
            hover:brightness-110 disabled:opacity-60 disabled:cursor-not-allowed"
        >
          {installing ? (
            <>
              <span className="material-symbols-outlined text-lg animate-spin">progress_activity</span>
              ?¤ì¹˜ ì¤?..
            </>
          ) : (
            <>
              <span className="material-symbols-outlined text-lg">download</span>
              ?¤ìš´ë¡œë“œ ë°??¤ì¹˜
            </>
          )}
        </button>

        {error && (
          <p className="text-xs text-center text-red-400/70 -mt-2">
            ?ë™ ?¤ì¹˜ ?¤íŒ¨ ??MSIë¥?ì§ì ‘ ?¤í–‰?˜ê±°??' '}
            <a
              href="https://www.libreoffice.org/download/"
              target="_blank"
              rel="noreferrer"
              className="underline"
            >
              libreoffice.org
            </a>
            ?ì„œ ?˜ë™ ?¤ì¹˜?˜ì„¸??
          </p>
        )}
      </div>
    </div>
  )
}
