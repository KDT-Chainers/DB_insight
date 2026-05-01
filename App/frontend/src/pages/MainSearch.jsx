import { useState, useRef, useEffect, useCallback } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import SearchSidebar from '../components/SearchSidebar'
import { useSidebar } from '../context/SidebarContext'
import { API_BASE } from '../api'

// ── 파일 타입 메타 ───────────────────────────────────────
const TYPE_META = {
  doc:   { icon: 'description', color: 'text-[#85adff]',   label: '문서',   grad: 'from-[#1e3a8a] to-[#1e40af]' },
  video: { icon: 'movie',       color: 'text-[#ac8aff]',   label: '동영상', grad: 'from-[#4c1d95] to-[#5b21b6]' },
  image: { icon: 'image',       color: 'text-emerald-400', label: '이미지', grad: 'from-[#064e3b] to-[#065f46]' },
  audio: { icon: 'volume_up',   color: 'text-amber-400',   label: '음성',   grad: 'from-[#78350f] to-[#92400e]' },
  movie: { icon: 'movie',       color: 'text-[#ac8aff]',   label: '동영상', grad: 'from-[#4c1d95] to-[#5b21b6]' },
  music: { icon: 'volume_up',   color: 'text-amber-400',   label: '음성',   grad: 'from-[#78350f] to-[#92400e]' },
}
const getTypeMeta = (t) =>
  TYPE_META[t] ?? { icon: 'insert_drive_file', color: 'text-on-surface-variant', label: t ?? '파일', grad: 'from-[#1c253e] to-[#263354]' }

// ── 유틸 ─────────────────────────────────────────────────
function fmtTime(sec) {
  if (!sec && sec !== 0) return '0:00'
  const s = Math.floor(sec)
  const m = Math.floor(s / 60)
  const ss = String(s % 60).padStart(2, '0')
  return `${m}:${ss}`
}

// ── STT 훅 ───────────────────────────────────────────────
function useSpeechRecognition({ onFinal }) {
  const [listening, setListening] = useState(false)
  const [interim, setInterim] = useState('')
  const recognitionRef = useRef(null)
  const latestRef = useRef('')

  const start = useCallback(() => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition
    if (!SR) { alert('이 환경에서는 음성 인식이 지원되지 않습니다.'); return }
    const r = new SR()
    r.lang = 'ko-KR'; r.continuous = false; r.interimResults = true
    r.onstart  = () => { setListening(true); setInterim(''); latestRef.current = '' }
    r.onresult = (e) => {
      let fin = '', tmp = ''
      for (let i = e.resultIndex; i < e.results.length; i++) {
        if (e.results[i].isFinal) fin += e.results[i][0].transcript
        else tmp += e.results[i][0].transcript
      }
      if (tmp) { setInterim(tmp); latestRef.current = tmp }
      if (fin) { setInterim(''); latestRef.current = fin }
    }
    r.onend    = () => { setListening(false); setInterim(''); const t = latestRef.current.trim(); latestRef.current = ''; if (t) onFinal(t) }
    r.onerror  = () => { setListening(false); setInterim('') }
    recognitionRef.current = r; r.start()
  }, [onFinal])

  const stop   = useCallback(() => recognitionRef.current?.stop(), [])
  const toggle = useCallback(() => listening ? stop() : start(), [listening, start, stop])
  return { listening, interim, toggle }
}

// ── 텍스트 검색 API (/api/trichef/search — per-query 적응형 confidence) ──
async function searchFiles(query, topK = 30) {
  const res = await fetch(`${API_BASE}/api/trichef/search`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      query,
      topk: topK,
      domains: ['image', 'doc_page', 'movie', 'music'],
      use_lexical: true,
      use_asf: true,
      pool: 300,
    }),
  })
  if (!res.ok) throw new Error(`검색 실패 HTTP ${res.status}`)
  const data = await res.json()
  if (data.error) throw new Error(data.error)

  return (data.top ?? []).map(item => {
    const isAV = item.domain === 'movie' || item.domain === 'music'
    return {
      file_path:      item.id,
      file_name:      item.file_name || (item.id || '').split(/[/\\]/).pop(),
      file_type:      item.domain === 'image' ? 'image'
                    : item.domain === 'doc_page' ? 'doc'
                    : item.domain === 'movie' ? 'video' : 'audio',
      confidence:     item.confidence ?? 0,
      similarity:     item.confidence ?? 0,
      dense:          item.dense ?? 0,
      lexical:        item.lexical ?? null,
      asf:            item.asf ?? null,
      snippet:        '',
      preview_url:    item.preview_url ?? null,
      segments:       item.segments ?? [],
      low_confidence: item.low_confidence ?? false,
      trichef_domain: item.domain,
    }
  })
}

// ── 이미지 파일 → 이미지 검색 ──────────────────────────
async function searchByImage(file, topK = 20) {
  const formData = new FormData()
  formData.append('image', file)
  formData.append('domain', 'image')
  formData.append('topk', String(topK))
  const res = await fetch(`${API_BASE}/api/trichef/search_by_image`, {
    method: 'POST',
    body: formData,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.error || `HTTP ${res.status}`)
  }
  const data = await res.json()
  return (data.top ?? []).map(r => ({
    file_path:   r.id,
    file_name:   (r.id || '').split('/').pop(),
    file_type:   'image',
    confidence:  r.confidence ?? 0,
    similarity:  r.confidence ?? 0,
    dense:       r.dense ?? 0,
    snippet:     r.caption ? `캡션: ${r.caption}` : '',
    preview_url: r.preview_url ?? null,
    segments:    [],
  }))
}

async function openFile(filePath) {
  await fetch(`${API_BASE}/api/files/open`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ file_path: filePath }),
  })
}

async function openFolder(filePath) {
  await fetch(`${API_BASE}/api/files/open-folder`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ file_path: filePath }),
  })
}

// ── AV 플레이어 스트림 URL 생성 ──────────────────────────
function avStreamUrl(result) {
  const domain = result.trichef_domain ?? (result.file_type === 'video' ? 'movie' : 'music')
  return `${API_BASE}/api/admin/file?domain=${domain}&id=${encodeURIComponent(result.file_path)}`
}

// ── 결과 카드 (admin.html card / avCard 구조 대응) ────────
function ResultCard({ result, rank, onClick, securityMode = false }) {
  const isAV       = result.file_type === 'video' || result.file_type === 'audio'
  const hasPreview = (result.file_type === 'image' || result.file_type === 'doc') && result.preview_url
  const [imgError, setImgError] = useState(false)

  // 보안 모드: 마스킹 상태
  const [secState, setSecState] = useState('idle')   // 'idle' | 'loading' | 'done' | 'clean' | 'error'
  const [maskedSrc, setMaskedSrc] = useState(null)   // base64 masked image
  const [piiTypes, setPiiTypes]   = useState([])

  // 보안 모드 ON + 이미지 결과 → 마스킹 요청
  useEffect(() => {
    if (!securityMode || !hasPreview || isAV) return
    if (secState !== 'idle') return

    setSecState('loading')
    const rel    = result.trichef_id || result.file_path
    const domain = result.trichef_domain || 'image'
    fetch(`${API_BASE}/api/security/mask_image?path=${encodeURIComponent(rel)}&domain=${domain}`)
      .then(r => r.json())
      .then(d => {
        if (d.error) { setSecState('error'); return }
        setPiiTypes(d.pii_types ?? [])
        setMaskedSrc('data:image/png;base64,' + d.masked_b64)
        setSecState(d.pii_found ? 'done' : 'clean')
      })
      .catch(() => setSecState('error'))
  }, [securityMode, hasPreview, isAV, result.file_path, secState])

  // 보안 모드 OFF → 상태 초기화
  useEffect(() => {
    if (!securityMode) {
      setSecState('idle')
      setMaskedSrc(null)
      setPiiTypes([])
    }
  }, [securityMode])
  const playerRef  = useRef(null)

  // 점수 계산 (admin.html 동일)
  const conf    = result.confidence ?? result.similarity ?? 0
  const confPct = (conf * 100).toFixed(1)
  const dense   = result.dense ?? null
  const rerank  = result.rerank ?? null
  const zScore  = result.z_score ?? null

  const clamp01 = x => (x == null || isNaN(x)) ? null : Math.max(0, Math.min(1, x))
  const sigm    = x => 1 / (1 + Math.exp(-x))
  const sim     = clamp01(dense) != null ? clamp01(dense).toFixed(3) : '—'
  const acc     = rerank != null
    ? sigm(rerank).toFixed(3)
    : Math.max(0, Math.min(1, ((zScore ?? 0) + 3) / 6)).toFixed(3)

  const streamUrl  = isAV ? avStreamUrl(result) : null
  const domainLabel = result.trichef_domain ?? result.file_type ?? 'unknown'
  const segments   = result.segments ?? []

  const DOMAIN_CLS = {
    image:    'bg-[#065f46] text-[#d1fae5] border-[#10b981]',
    doc_page: 'bg-[#5b21b6] text-[#ede9fe] border-[#8b5cf6]',
    movie:    'bg-[#7c2d12] text-[#ffedd5] border-[#ea580c]',
    music:    'bg-[#1e40af] text-[#dbeafe] border-[#3b82f6]',
  }

  const seekTo = (t) => {
    const p = playerRef.current
    if (!p) return
    p.currentTime = t
    p.play().catch(() => {})
  }

  return (
    <div
      onClick={isAV ? undefined : onClick}
      className={`bg-[#1e293b] border border-[#334155] rounded-[10px] overflow-hidden flex flex-col relative transition-transform duration-150
        ${isAV ? '' : 'cursor-pointer hover:-translate-y-0.5 hover:border-[#059669]'}`}
    >
      {/* 랭크 배지 */}
      <div className="absolute top-2 left-2 z-20 bg-[#059669] text-white min-w-[32px] h-7 px-2 rounded-full flex items-center justify-center font-bold text-xs">
        #{rank}
      </div>

      {/* AV: 플레이어 */}
      {isAV && (
        <div className="px-3 py-2 bg-[#0b1220] border-b border-[#334155]" onClick={e => e.stopPropagation()}>
          {result.file_type === 'video' ? (
            <video ref={playerRef} src={streamUrl} controls preload="metadata"
              className="w-full block outline-none bg-black" style={{ maxHeight: '200px' }} />
          ) : (
            <audio ref={playerRef} src={streamUrl} controls preload="metadata"
              className="w-full block outline-none" />
          )}
        </div>
      )}

      {/* 이미지·문서: 썸네일 */}
      {!isAV && (
        <div className="relative h-[200px] bg-[#0b1220] flex items-center justify-center overflow-hidden">
          {hasPreview && !imgError ? (
            <>
              {/* 보안 모드 로딩 스피너 */}
              {securityMode && secState === 'loading' && (
                <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-2 bg-[#0b1220]/80">
                  <span className="material-symbols-outlined text-amber-400 text-3xl animate-spin">progress_activity</span>
                  <span className="text-xs text-amber-400/80">PII 스캔 중...</span>
                </div>
              )}
              <img
                src={securityMode && maskedSrc ? maskedSrc : `${API_BASE}${result.preview_url}`}
                alt={result.file_name}
                className="max-w-full max-h-full object-contain cursor-zoom-in"
                onError={() => setImgError(true)}
              />
              {/* PII 탐지 배지 */}
              {secState === 'done' && piiTypes.length > 0 && (
                <div className="absolute bottom-2 left-2 right-2 flex flex-wrap gap-1">
                  {piiTypes.slice(0, 3).map(t => (
                    <span key={t} className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-amber-500/90 text-black">
                      {t.replace('KR_', '')}
                    </span>
                  ))}
                  <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-amber-500/90 text-black flex items-center gap-0.5">
                    <span className="material-symbols-outlined text-[10px]" style={{ fontVariationSettings: '"FILL" 1' }}>lock</span>
                    마스킹됨
                  </span>
                </div>
              )}
              {/* 안전 배지 */}
              {secState === 'clean' && (
                <div className="absolute bottom-2 left-2">
                  <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-emerald-500/90 text-black flex items-center gap-0.5">
                    <span className="material-symbols-outlined text-[10px]" style={{ fontVariationSettings: '"FILL" 1' }}>verified</span>
                    PII 없음
                  </span>
                </div>
              )}
            </>
          ) : (
            <span className="text-[#64748b] text-xs">{domainLabel}</span>
          )}
        </div>
      )}

      {/* 바디 */}
      <div className="p-3 flex flex-col gap-2 flex-1 text-[#e2e8f0]">

        {/* 배지 */}
        <div className="flex gap-1 flex-wrap">
          <span className={`text-[10px] px-2 py-0.5 rounded-full border ${DOMAIN_CLS[domainLabel] ?? 'bg-[#0b1220] text-[#64748b] border-[#334155]'}`}>
            {domainLabel}
          </span>
          {isAV && (
            <span className="text-[10px] px-2 py-0.5 rounded-full border border-[#334155] bg-[#0b1220] text-[#64748b]">
              세그 {segments.length}
            </span>
          )}
        </div>

        {/* 파일명 */}
        <div className="font-semibold text-[13px] text-[#f1f5f9] break-all">{result.file_name}</div>

        {/* 경로 */}
        <div className="text-[11px] text-[#64748b] break-all font-mono">{result.file_path}</div>

        {/* 핵심 3지표 */}
        <div className="grid grid-cols-3 gap-1.5">
          {[
            { label: '신뢰도', value: `${confPct}%`, cls: 'text-[#10b981]' },
            { label: '정확도', value: acc,            cls: 'text-[#60a5fa]' },
            { label: '유사도', value: sim,            cls: 'text-[#a78bfa]' },
          ].map(({ label, value, cls }) => (
            <div key={label} className="bg-[#0b1220] rounded-md p-1.5 text-center border border-[#334155]">
              <div className="text-[10px] text-[#64748b] uppercase tracking-wide">{label}</div>
              <div className={`text-[15px] font-bold mt-0.5 ${cls}`}>{value}</div>
            </div>
          ))}
        </div>

        {/* AV: 상위 구간 재생 + 구간 목록 */}
        {isAV && segments.length > 0 && (() => {
          const topStart = segments[0]?.start ?? segments[0]?.start_sec ?? null
          return (
            <div onClick={e => e.stopPropagation()}>
              {topStart != null && (
                <button
                  onClick={() => seekTo(topStart)}
                  className="text-[11px] px-3 py-1 bg-[#059669] text-white rounded font-semibold hover:bg-[#047857] mb-1.5"
                >
                  상위 구간 재생 ▶
                </button>
              )}
              <div className="flex flex-col gap-[3px]">
                {segments.slice(0, 10).map((s, i) => {
                  const t0 = s.start ?? s.start_sec ?? 0
                  const t1 = s.end   ?? s.end_sec   ?? 0
                  const sc = s.score ?? 0
                  const preview = (s.text || s.stt_text || s.caption || '').slice(0, 80)
                  return (
                    <button key={i} onClick={() => seekTo(t0)}
                      className="flex items-center gap-2 px-2 py-1 bg-[#0b1220] border border-[#334155] rounded text-[11px] overflow-hidden hover:border-[#059669] hover:bg-[#0f2040] text-left w-full">
                      <span className="text-[#7dd3fc] font-mono font-semibold whitespace-nowrap min-w-[112px]">{fmtTime(t0)} ~ {fmtTime(t1)}</span>
                      <span className="text-[#10b981] font-mono whitespace-nowrap">s={sc.toFixed(3)}</span>
                      <span className="text-[#94a3b8] flex-1 overflow-hidden text-ellipsis whitespace-nowrap">{preview}</span>
                    </button>
                  )
                })}
              </div>
            </div>
          )
        })()}

        {/* 이미지·문서: 스니펫 */}
        {!isAV && result.snippet && (
          <div className="text-[12px] text-[#cbd5e1] bg-[#0b1220] px-2 py-2 rounded border border-[#334155] max-h-[120px] overflow-auto whitespace-pre-wrap">
            {result.snippet}
          </div>
        )}
      </div>
    </div>
  )
}

// ── 상세 페이지 이미지 미리보기 (보안 마스킹 지원) ─────────
function DetailImagePreview({ file, securityMode }) {
  const hasPreview = (file.file_type === 'image' || file.file_type === 'doc') && file.preview_url
  const [secState,  setSecState]  = useState('idle')   // idle|loading|done|clean|error
  const [maskedSrc, setMaskedSrc] = useState(null)
  const [piiTypes,  setPiiTypes]  = useState([])

  // 보안 모드 ON → mask_image 호출
  useEffect(() => {
    if (!securityMode || !hasPreview) return
    if (secState !== 'idle') return
    setSecState('loading')
    const rel    = file.trichef_id || file.file_path
    const domain = file.trichef_domain || 'image'
    fetch(`${API_BASE}/api/security/mask_image?path=${encodeURIComponent(rel)}&domain=${domain}`)
      .then(r => r.json())
      .then(d => {
        if (d.error) { setSecState('error'); return }
        setPiiTypes(d.pii_types ?? [])
        setMaskedSrc('data:image/png;base64,' + d.masked_b64)
        setSecState(d.pii_found ? 'done' : 'clean')
      })
      .catch(() => setSecState('error'))
  }, [securityMode, hasPreview, file.file_path, secState])

  // 보안 모드 OFF → 초기화
  useEffect(() => {
    if (!securityMode) { setSecState('idle'); setMaskedSrc(null); setPiiTypes([]) }
  }, [securityMode])

  if (!hasPreview) return null

  const imgSrc = securityMode && maskedSrc ? maskedSrc : `${API_BASE}${file.preview_url}`

  return (
    <div className="w-full flex-1 flex items-center justify-center min-h-0 relative">
      {/* PII 스캔 중 오버레이 */}
      {secState === 'loading' && (
        <div className="absolute inset-0 z-10 flex items-center justify-center bg-black/50 rounded-xl">
          <div className="flex flex-col items-center gap-2">
            <span className="material-symbols-outlined text-amber-400 text-4xl animate-spin"
              style={{ fontVariationSettings: '"FILL" 1' }}>shield</span>
            <span className="text-amber-300 text-sm font-bold tracking-widest uppercase">PII 스캔 중...</span>
          </div>
        </div>
      )}

      <img
        src={imgSrc}
        alt={file.file_name}
        className="max-w-full max-h-full object-contain rounded-xl shadow-2xl border border-outline-variant/10"
        style={{ maxHeight: '380px' }}
      />

      {/* PII 탐지 배지 */}
      {secState === 'done' && (
        <div className="absolute top-3 right-3 flex flex-col items-end gap-1.5 z-10">
          <div className="flex items-center gap-1.5 bg-red-950/90 border border-red-500/60 px-2.5 py-1.5 rounded-full text-xs text-red-300 font-bold backdrop-blur-sm shadow-lg">
            <span className="material-symbols-outlined text-sm" style={{ fontVariationSettings: '"FILL" 1' }}>warning</span>
            개인정보 마스킹됨
          </div>
          {piiTypes.map(t => (
            <span key={t} className="bg-amber-900/70 border border-amber-500/40 px-2 py-0.5 rounded-full text-[11px] text-amber-200 font-bold backdrop-blur-sm">
              {t.replace('KR_', '').replace('_', ' ')}
            </span>
          ))}
        </div>
      )}
      {secState === 'clean' && (
        <div className="absolute top-3 right-3 z-10">
          <div className="flex items-center gap-1.5 bg-emerald-950/80 border border-emerald-500/40 px-2.5 py-1.5 rounded-full text-xs text-emerald-300 font-bold backdrop-blur-sm">
            <span className="material-symbols-outlined text-sm" style={{ fontVariationSettings: '"FILL" 1' }}>verified</span>
            개인정보 없음
          </div>
        </div>
      )}
      {secState === 'error' && (
        <div className="absolute top-3 right-3 z-10">
          <div className="flex items-center gap-1 bg-slate-800/80 border border-slate-500/30 px-2 py-1 rounded-full text-xs text-slate-400 backdrop-blur-sm">
            <span className="material-symbols-outlined text-sm">error</span>
            스캔 실패
          </div>
        </div>
      )}
    </div>
  )
}

// ── AV 상세: 플레이어 + 세그먼트 타임라인 ────────────────
function AVDetailContent({ result }) {
  const isVideo   = result.file_type === 'video'
  const playerRef = useRef(null)
  const streamUrl = avStreamUrl(result)
  const segments  = result.segments ?? []

  const seekTo = (startSec) => {
    const p = playerRef.current
    if (!p) return
    p.currentTime = startSec
    p.play().catch(() => {})
  }

  return (
    <div className="flex-1 flex flex-col">
      {/* 플레이어 */}
      <div className="px-8 pt-6 pb-4">
        <div className="rounded-xl overflow-hidden bg-black/60 border border-outline-variant/10">
          {isVideo ? (
            <video
              ref={playerRef}
              src={streamUrl}
              controls
              preload="metadata"
              className="w-full max-h-[280px] object-contain"
              onError={() => {}}
            />
          ) : (
            <div className="flex flex-col items-center justify-center p-6 gap-3">
              <span className="material-symbols-outlined text-amber-400 text-4xl" style={{ fontVariationSettings: '"FILL" 1' }}>volume_up</span>
              <audio
                ref={playerRef}
                src={streamUrl}
                controls
                preload="metadata"
                className="w-full"
                onError={() => {}}
              />
            </div>
          )}
        </div>
      </div>

      {/* 세그먼트 타임라인 */}
      {segments.length > 0 && (
        <div className="px-8 pb-4 flex-1 overflow-y-auto">
          <p className="text-sm font-bold text-on-surface-variant/50 uppercase tracking-widest mb-3 flex items-center gap-1">
            <span className="material-symbols-outlined text-base">timeline</span>
            매칭 구간 ({segments.length}개)
          </p>
          <div className="space-y-2">
            {segments.map((seg, i) => {
              const t0   = seg.start ?? seg.start_sec ?? 0
              const t1   = seg.end   ?? seg.end_sec   ?? 0
              const sc   = seg.score ?? 0
              const text = seg.text || seg.caption || ''
              const pct  = Math.round(sc * 100)
              return (
                <button
                  key={i}
                  onClick={() => seekTo(t0)}
                  className="w-full text-left p-3 rounded-xl bg-surface-container-highest/60 hover:bg-primary/10 border border-outline-variant/10 hover:border-primary/20 transition-all group/seg"
                >
                  <div className="flex items-center justify-between mb-1.5">
                    <div className="flex items-center gap-2">
                      <span className="material-symbols-outlined text-base text-primary group-hover/seg:scale-110 transition-transform">play_circle</span>
                      <span className="font-mono text-lg text-primary font-bold">{fmtTime(t0)}</span>
                      <span className="text-sm text-on-surface-variant/40">→</span>
                      <span className="font-mono text-lg text-on-surface-variant/60">{fmtTime(t1)}</span>
                    </div>
                    <div className="flex items-center gap-1.5">
                      {/* 점수 바 */}
                      <div className="w-16 h-1 bg-surface-container-highest rounded-full overflow-hidden">
                        <div
                          className="h-full bg-gradient-to-r from-amber-500 to-primary rounded-full"
                          style={{ width: `${Math.min(pct * 2, 100)}%` }}
                        />
                      </div>
                      <span className="text-sm text-on-surface-variant/60 font-mono tabular-nums">{sc.toFixed(3)}</span>
                    </div>
                  </div>
                  {text && (
                    <p className="text-xs text-on-surface-variant/70 leading-relaxed line-clamp-2 pl-5">
                      {text}
                    </p>
                  )}
                </button>
              )
            })}
          </div>
        </div>
      )}

      {segments.length === 0 && (
        <div className="flex-1 flex items-center justify-center text-on-surface-variant/30 text-lg px-8">
          세그먼트 정보 없음
        </div>
      )}
    </div>
  )
}

// ── 라디얼 메뉴 아이템 ──────────────────────────────────
const RADIAL_ITEMS = [
  { icon: 'image_search', label: '이미지 검색', action: 'img_search',    color: 'from-emerald-500 to-teal-500' },
  { icon: 'audiotrack',   label: 'BGM 검색',    action: 'bgm_search',    color: 'from-pink-500 to-rose-500' },
  { icon: 'description',  label: '문서',         action: 'filter_doc',    color: 'from-blue-500 to-indigo-500' },
  { icon: 'movie',        label: '동영상',       action: 'filter_video',  color: 'from-purple-500 to-violet-500' },
  { icon: 'image',        label: '이미지',       action: 'filter_image',  color: 'from-green-500 to-emerald-500' },
  { icon: 'volume_up',    label: '음성',         action: 'filter_audio',  color: 'from-amber-500 to-orange-500' },
]

// 6개를 부채꼴로 배치 (위쪽 반원, ±75° 범위)
const RADIAL_POSITIONS = (() => {
  const R = 115
  const angles = [-75, -45, -15, 15, 45, 75]
  return angles.map(a => {
    const rad = (a * Math.PI) / 180
    return { x: R * Math.sin(rad), y: -R * Math.cos(rad) }
  })
})()

// ── 메인 컴포넌트 ────────────────────────────────────────
export default function MainSearch() {
  const navigate  = useNavigate()
  const location  = useLocation()
  const { open }  = useSidebar()

  // view: 'home' | 'results' | 'detail'
  const [view, setView] = useState('home')
  const [query, setQuery] = useState('')
  const [inputValue, setInputValue] = useState('')
  const [selectedFile, setSelectedFile] = useState(null)
  const [fileDetail, setFileDetail] = useState(null)
  const [detailLoading, setDetailLoading] = useState(false)

  // 검색 결과
  const [results, setResults] = useState([])
  const [searching, setSearching] = useState(false)
  const [searchError, setSearchError] = useState('')
  const [topK, setTopK] = useState(30)

  // 라디얼 메뉴
  const [radialOpen, setRadialOpen] = useState(false)
  const [typeFilter, setTypeFilter] = useState(null)   // null | 'doc' | 'video' | 'image' | 'audio'
  const radialRef   = useRef(null)
  const imgInputRef = useRef(null)
  const bgmInputRef = useRef(null)

  // 이미지 업로드 모달
  const [imgModalOpen, setImgModalOpen] = useState(false)
  const [imgPreview,   setImgPreview]   = useState(null)   // base64 미리보기
  const [imgFile,      setImgFile]      = useState(null)   // File 객체
  const [dragOver,     setDragOver]     = useState(false)

  // 이미지 쿼리 상태 (텍스트 쿼리와 분리)
  const [imgQuery, setImgQuery] = useState(null)   // { file, preview } | null

  // 보안 모드
  const [securityMode, setSecurityMode] = useState(false)

  // 요약
  const [summary, setSummary]               = useState(null)
  const [summaryLoading, setSummaryLoading] = useState(false)


  // home → results 애니메이션
  const [flyStyle, setFlyStyle] = useState(null)
  const [homeExiting, setHomeExiting] = useState(false)
  const [resultsReady, setResultsReady] = useState(false)

  // results → detail 슬라이드
  const [detailVisible, setDetailVisible] = useState(false)

  // AI 포털 전환
  const [aiTransitioning, setAiTransitioning] = useState(false)
  const [ripplePos, setRipplePos] = useState({ x: '50%', y: '50%' })

  const btnRef  = useRef(null)
  const formRef = useRef(null)

  // STT
  const doSearchRef = useRef(null)
  const { listening, interim, toggle: toggleMic } = useSpeechRecognition({
    onFinal: useCallback((text) => {
      setInputValue(text)
      setTimeout(() => doSearchRef.current?.(text), 80)
    }, []),
  })

  const ml        = open ? 'ml-64' : 'ml-0'
  const leftEdge  = open ? 'left-64' : 'left-0'
  const sidebarPx = open ? 256 : 0

  // 라디얼 메뉴 외부 클릭 닫기
  useEffect(() => {
    if (!radialOpen) return
    const handleClick = (e) => {
      if (radialRef.current && !radialRef.current.contains(e.target)) {
        setRadialOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [radialOpen])

  // 라디얼 메뉴 액션 핸들러
  const handleRadialAction = (action) => {
    setRadialOpen(false)
    if (action === 'img_search') {
      setImgFile(null)
      setImgPreview(null)
      setImgModalOpen(true)
      return
    }
    if (action === 'bgm_search') {
      bgmInputRef.current?.click()
      return
    }
    const filterMap = {
      filter_doc:   'doc',
      filter_video: 'video',
      filter_image: 'image',
      filter_audio: 'audio',
    }
    const ft = filterMap[action]
    setTypeFilter(prev => (prev === ft ? null : ft))  // 같은 필터 재클릭 시 해제
  }

  // 이미지 파일 → 미리보기 세팅 (모달용)
  const applyImgFile = (file) => {
    if (!file || !file.type.startsWith('image/')) return
    setImgFile(file)
    const reader = new FileReader()
    reader.onload = (e) => setImgPreview(e.target.result)
    reader.readAsDataURL(file)
  }

  // 모달 드래그앤드롭
  const handleModalDrop = (e) => {
    e.preventDefault()
    setDragOver(false)
    const file = e.dataTransfer.files?.[0]
    if (file) applyImgFile(file)
  }

  // hidden input 변경 (모달 내부 클릭 선택)
  const handleImgFile = (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    e.target.value = ''
    applyImgFile(file)
  }

  // 모달 "검색" 버튼 → 실제 검색 실행
  const runImgSearch = async () => {
    if (!imgFile) return
    setImgModalOpen(false)

    // 텍스트 쿼리 초기화, 이미지 쿼리로 전환
    setImgQuery({ file: imgFile, preview: imgPreview })
    setQuery('')
    setInputValue('')
    setSearching(true)
    setSearchError('')
    setTypeFilter('image')

    // home → results 전환
    if (view === 'home') {
      setHomeExiting(true)
      setTimeout(() => { setView('results'); setHomeExiting(false); setResultsReady(true) }, 320)
    }

    try {
      const data = await searchByImage(imgFile, topK)
      setResults(data)
      fetch(`${API_BASE}/api/history`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: `[이미지] ${imgFile.name}`, method: 'image_search', result_count: data.length }),
      }).catch(() => {})
    } catch (err) {
      setSearchError(err.message)
      setResults([])
    } finally {
      setSearching(false)
    }
  }

  // BGM 파일 선택 핸들러
  const handleBgmFile = (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    e.target.value = ''
    alert(`BGM 검색: ${file.name}\n(백엔드 오디오 쿼리 API 연동 예정)`)
  }

  // 사이드바 검색 기록 클릭 시 자동 검색 (location.state.query)
  useEffect(() => {
    const q = location.state?.query
    if (q) {
      window.history.replaceState({}, '')   // state 소비
      setImgQuery(null)
      setTypeFilter(null)
      doSearchRef.current?.(q)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.state])

  // 뒤로가기
  useEffect(() => {
    const handlePopState = () => {
      setDetailVisible(false)
      if (view === 'detail')        setTimeout(() => setView('results'), 320)
      else if (view === 'results')  { setResultsReady(false); setView('home') }
    }
    window.addEventListener('popstate', handlePopState)
    return () => window.removeEventListener('popstate', handlePopState)
  }, [view])

  // ── 검색 실행 ──────────────────────────────────────────
  const fetchResults = useCallback(async (q) => {
    setSearching(true)
    setSearchError('')
    try {
      const data = await searchFiles(q, topK)
      setResults(data)
      // 검색 기록 저장
      fetch(`${API_BASE}/api/history`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: q, method: 'trichef', result_count: data.length }),
      }).catch(() => {})
    } catch (e) {
      setSearchError(e.message)
      setResults([])
    } finally {
      setSearching(false)
    }
  }, [topK])

  const doSearch = (q) => {
    if (!q.trim() || aiTransitioning) return
    setImgQuery(null)     // 텍스트 검색 시 이미지 쿼리 해제
    setTypeFilter(null)   // 텍스트 검색 시 타입 필터 초기화
    setQuery(q)
    setInputValue(q)

    if (view === 'home') {
      const rect = formRef.current?.getBoundingClientRect()
      if (rect) {
        setFlyStyle({ position: 'fixed', top: rect.top, left: rect.left, width: rect.width, transition: 'none', zIndex: 9998 })
        setHomeExiting(true)
        requestAnimationFrame(() => requestAnimationFrame(() => {
          setFlyStyle({
            position: 'fixed', top: 10,
            left: sidebarPx + 180,
            width: `calc(100vw - ${sidebarPx + 460}px)`,
            transition: 'all 0.45s cubic-bezier(0.4,0,0.2,1)',
            zIndex: 9998,
          })
        }))
      }
      setTimeout(() => {
        setFlyStyle(null); setHomeExiting(false)
        setResultsReady(false)
        setView('results')
        window.history.pushState({ view: 'results' }, '')
        requestAnimationFrame(() => setResultsReady(true))
        fetchResults(q)
      }, 480)
    } else {
      setView('results')
      fetchResults(q)
    }
  }

  useEffect(() => { doSearchRef.current = doSearch })

  const handleSearch = (e) => { e?.preventDefault(); doSearch(inputValue) }

  const handleSelectFile = (file) => {
    setSelectedFile(file)
    setFileDetail(null)
    setDetailVisible(false)
    setSummary(null)          // 파일 바뀌면 요약 초기화
    setView('detail')
    window.history.pushState({ view: 'detail' }, '')
    requestAnimationFrame(() => requestAnimationFrame(() => setDetailVisible(true)))

    // AV 타입은 fileDetail fetch 불필요 (segments 이미 포함)
    const isAV = file.file_type === 'video' || file.file_type === 'audio'
    if (!isAV) {
      setDetailLoading(true)
      fetch(`${API_BASE}/api/files/detail?path=${encodeURIComponent(file.file_path)}`)
        .then(r => r.json())
        .then(d => { setFileDetail(d); setDetailLoading(false) })
        .catch(() => setDetailLoading(false))
    }
  }

  const handleSummarize = async (file) => {
    if (summaryLoading) return
    setSummaryLoading(true)
    setSummary(null)
    try {
      const res  = await fetch(`${API_BASE}/api/files/summarize?path=${encodeURIComponent(file.file_path)}`)
      const data = await res.json()
      setSummary(data)
    } catch (e) {
      setSummary({ error: e.message })
    } finally {
      setSummaryLoading(false)
    }
  }

  const handleBackToResults = () => { setDetailVisible(false); setTimeout(() => setView('results'), 320) }

  const handleGoToAI = () => {
    const rect = btnRef.current?.getBoundingClientRect()
    if (rect) setRipplePos({ x: `${rect.left + rect.width / 2}px`, y: `${rect.top + rect.height / 2}px` })
    setAiTransitioning(true)
    setTimeout(() => navigate('/ai'), 900)
  }

  // 타입 필터 적용된 결과
  const filteredResults = typeFilter
    ? results.filter(r => {
        if (typeFilter === 'video') return r.file_type === 'video' || r.file_type === 'movie'
        if (typeFilter === 'audio') return r.file_type === 'audio' || r.file_type === 'music'
        return r.file_type === typeFilter
      })
    : results

  return (
    <div className={view === 'home' ? 'overflow-hidden h-screen grid-bg relative' : 'min-h-screen relative bg-background text-on-surface'}
      style={view !== 'home' ? { backgroundImage: 'radial-gradient(circle at 2px 2px, rgba(65,71,91,0.15) 1px, transparent 0)', backgroundSize: '32px 32px' } : {}}>
      {/* 숨김 파일 입력 (이미지·BGM 검색용) */}
      <input ref={imgInputRef} type="file" accept="image/*" className="hidden" onChange={handleImgFile} />
      <input ref={bgmInputRef} type="file" accept="audio/*" className="hidden" onChange={handleBgmFile} />

      {/* ── 이미지 업로드 모달 ── */}
      {imgModalOpen && (
        <div
          className="fixed inset-0 z-[9999] flex items-center justify-center"
          style={{ background: 'rgba(4,8,20,0.85)', backdropFilter: 'blur(12px)' }}
          onClick={() => setImgModalOpen(false)}
        >
          <div
            className="relative w-[480px] max-w-[92vw] rounded-2xl border border-outline-variant/20 bg-[#0c1326] shadow-[0_0_80px_rgba(133,173,255,0.12)] flex flex-col overflow-hidden"
            onClick={e => e.stopPropagation()}
          >
            {/* 헤더 */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-outline-variant/15">
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-emerald-500 to-teal-600 flex items-center justify-center">
                  <span className="material-symbols-outlined text-white text-base" style={{ fontVariationSettings: '"FILL" 1' }}>image_search</span>
                </div>
                <span className="font-bold text-on-surface">이미지 검색</span>
              </div>
              <button
                onClick={() => setImgModalOpen(false)}
                className="w-7 h-7 rounded-lg flex items-center justify-center text-on-surface-variant hover:text-on-surface hover:bg-surface-container-high transition-all"
              >
                <span className="material-symbols-outlined text-lg">close</span>
              </button>
            </div>

            {/* 본문 */}
            <div className="p-6 flex flex-col gap-4">
              {/* 드래그앤드롭 존 */}
              <div
                onDragOver={e => { e.preventDefault(); setDragOver(true) }}
                onDragLeave={() => setDragOver(false)}
                onDrop={handleModalDrop}
                onClick={() => imgInputRef.current?.click()}
                className={`relative flex flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed transition-all duration-200 cursor-pointer select-none overflow-hidden
                  ${dragOver
                    ? 'border-primary bg-primary/10 scale-[1.01]'
                    : 'border-outline-variant/30 hover:border-primary/50 hover:bg-primary/5'
                  }`}
                style={{ minHeight: imgPreview ? 'auto' : '220px' }}
              >
                {imgPreview ? (
                  /* 미리보기 */
                  <>
                    <img
                      src={imgPreview}
                      alt="미리보기"
                      className="max-h-[260px] max-w-full object-contain rounded-lg"
                    />
                    <div className="absolute inset-0 flex items-center justify-center opacity-0 hover:opacity-100 transition-opacity bg-black/50 rounded-xl">
                      <span className="text-white text-sm font-semibold flex items-center gap-2">
                        <span className="material-symbols-outlined text-lg">swap_horiz</span>
                        이미지 변경
                      </span>
                    </div>
                  </>
                ) : (
                  /* 빈 상태 */
                  <>
                    <div className={`w-16 h-16 rounded-full flex items-center justify-center transition-all
                      ${dragOver ? 'bg-primary/20' : 'bg-surface-container-high'}`}>
                      <span className={`material-symbols-outlined text-4xl transition-colors
                        ${dragOver ? 'text-primary' : 'text-on-surface-variant/50'}`}
                        style={{ fontVariationSettings: '"FILL" 0' }}>
                        upload_file
                      </span>
                    </div>
                    <p className="text-on-surface font-semibold text-sm">
                      이미지를 업로드하세요
                    </p>
                    <p className="text-on-surface-variant text-xs text-center leading-relaxed">
                      이미지를 끌어다 놓거나<br />
                      <span className="text-primary underline underline-offset-2">클릭하여 이미지 선택</span>
                    </p>
                    <p className="text-on-surface-variant/40 text-[10px]">
                      JPG · PNG · WEBP · HEIC 지원
                    </p>
                  </>
                )}
              </div>

              {/* 파일명 표시 */}
              {imgFile && (
                <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-surface-container-high">
                  <span className="material-symbols-outlined text-emerald-400 text-base">check_circle</span>
                  <span className="text-sm text-on-surface truncate flex-1">{imgFile.name}</span>
                  <button
                    onClick={() => { setImgFile(null); setImgPreview(null) }}
                    className="text-on-surface-variant/40 hover:text-red-400 transition-colors shrink-0"
                  >
                    <span className="material-symbols-outlined text-base">close</span>
                  </button>
                </div>
              )}

              {/* 검색 버튼 */}
              <button
                onClick={runImgSearch}
                disabled={!imgFile}
                className={`w-full py-3 rounded-xl font-bold text-sm tracking-wide flex items-center justify-center gap-2 transition-all duration-200
                  ${imgFile
                    ? 'bg-gradient-to-r from-emerald-600 to-teal-600 text-white hover:from-emerald-500 hover:to-teal-500 shadow-[0_4px_20px_rgba(16,185,129,0.25)]'
                    : 'bg-surface-container-high text-on-surface-variant/40 cursor-not-allowed'
                  }`}
              >
                <span className="material-symbols-outlined text-base" style={{ fontVariationSettings: '"FILL" 1' }}>image_search</span>
                이미지로 검색
              </button>
            </div>
          </div>
        </div>
      )}

      {/* AI 포털 전환 오버레이 */}
      {aiTransitioning && (
        <div className="fixed inset-0 z-[9999] pointer-events-none overflow-hidden">
          <div className="portal-overlay absolute rounded-full"
            style={{ width: '80px', height: '80px', left: ripplePos.x, top: ripplePos.y, transform: 'translate(-50%, -50%)',
              background: 'radial-gradient(circle, #1c253e 0%, #0c1326 60%, #070d1f 100%)', boxShadow: '0 0 30px 10px rgba(172,138,255,0.15)' }} />
          {[0, 200].map((delay, i) => (
            <div key={i} className="portal-ring absolute rounded-full border border-[#ac8aff]/25"
              style={{ width: '160px', height: '160px', left: ripplePos.x, top: ripplePos.y, transform: 'translate(-50%, -50%)', animationDelay: `${delay}ms` }} />
          ))}
          <div className="portal-text absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 flex flex-col items-center gap-2">
            <span className="material-symbols-outlined text-[#a5aac2] text-4xl" style={{ fontVariationSettings: '"FILL" 1' }}>psychology</span>
            <span className="font-manrope uppercase tracking-[0.25em] text-base text-[#a5aac2]">AI 모드</span>
          </div>
        </div>
      )}

      {/* 사이드바 */}
      <SearchSidebar />

      {/* ════ HOME ════ */}
      {view === 'home' && (
        <>
          <main className={`${ml} h-full flex flex-col items-center justify-center p-8 pt-16 relative transition-[margin] duration-300`}>
            <div className="absolute top-1/4 left-1/4 w-96 h-96 bg-primary/10 rounded-full blur-[120px] pointer-events-none" />
            <div className="absolute bottom-1/4 right-1/4 w-[500px] h-[500px] bg-secondary/5 rounded-full blur-[150px] pointer-events-none" />

            <div className="w-full max-w-4xl flex flex-col items-center z-10">
              <div className={`mb-12 text-center transition-all duration-300 ${homeExiting ? 'opacity-0 -translate-y-6' : 'opacity-100 translate-y-0'}`}>
                <h2 className="text-5xl md:text-6xl font-black tracking-tighter text-on-surface mb-4">
                  로컬 인텔리전스<span className="text-primary">.</span>
                </h2>
                <p className="text-on-surface-variant text-lg max-w-xl mx-auto font-light">
                  개인 신경망 엔진이 파일을 인덱싱하고 분석합니다.
                </p>
              </div>

              <form ref={formRef} onSubmit={handleSearch} className="w-full relative group"
                style={homeExiting ? { visibility: 'hidden' } : {}}>
                <div className={`glass-effect rounded-full p-2 flex items-center gap-4 shadow-[0_0_50px_rgba(133,173,255,0.1)] transition-all duration-300
                  ${listening ? 'border border-red-400/60 shadow-[0_0_30px_rgba(248,113,113,0.2)]' : 'border border-outline-variant/20 hover:border-primary/40'}`}>
                  {/* ── + 버튼 + 라디얼 메뉴 ── */}
                  <div ref={radialRef} className="relative shrink-0">
                    {/* 부채꼴 메뉴 아이템 */}
                    {RADIAL_ITEMS.map((item, i) => {
                      const { x, y } = RADIAL_POSITIONS[i]
                      const isActive = item.action.startsWith('filter_') &&
                        typeFilter === item.action.replace('filter_', '')
                      return (
                        <div
                          key={item.action}
                          onClick={() => handleRadialAction(item.action)}
                          className="absolute z-50 flex flex-col items-center gap-1 cursor-pointer"
                          style={{
                            left: '50%',
                            top:  '50%',
                            transform: radialOpen
                              ? `translate(calc(-50% + ${x}px), calc(-50% + ${y}px)) scale(1)`
                              : `translate(-50%, -50%) scale(0.4)`,
                            opacity:    radialOpen ? 1 : 0,
                            pointerEvents: radialOpen ? 'auto' : 'none',
                            transition: `transform 0.28s cubic-bezier(0.34,1.56,0.64,1) ${i * 30}ms,
                                         opacity   0.2s ease ${i * 20}ms`,
                          }}
                        >
                          <div className={`w-11 h-11 rounded-full bg-gradient-to-br ${item.color}
                            flex items-center justify-center shadow-lg
                            hover:scale-110 active:scale-95 transition-transform duration-150
                            ${isActive ? 'ring-2 ring-white/70' : ''}`}>
                            <span className="material-symbols-outlined text-white text-lg">{item.icon}</span>
                          </div>
                          <span className="text-[9px] font-bold text-white/90 bg-slate-900/80 px-1.5 py-0.5 rounded-full whitespace-nowrap shadow">
                            {item.label}
                          </span>
                        </div>
                      )
                    })}
                    {/* + 버튼 */}
                    <button
                      type="button"
                      onClick={() => setRadialOpen(o => !o)}
                      className={`w-12 h-12 rounded-full bg-gradient-to-r from-primary to-secondary flex items-center justify-center text-on-primary-fixed shadow-lg transition-all duration-300
                        ${radialOpen ? 'rotate-45 scale-110 shadow-primary/40' : 'active:scale-90'}`}
                    >
                      <span className="material-symbols-outlined font-bold">add</span>
                    </button>
                    {/* 활성 필터 배지 */}
                    {typeFilter && (
                      <span className="absolute -top-1 -right-1 w-3 h-3 rounded-full bg-primary border border-surface-container-low" />
                    )}
                  </div>
                  <div className="flex-1 relative">
                    <input
                      type="text"
                      value={listening ? '' : inputValue}
                      onChange={(e) => !listening && setInputValue(e.target.value)}
                      placeholder={listening ? '' : '로컬 파일에 대해 무엇이든 물어보세요...'}
                      className="w-full bg-transparent border-none focus:ring-0 text-on-surface placeholder:text-on-surface-variant/40 font-manrope text-lg py-4 outline-none"
                      readOnly={listening}
                    />
                    {listening && (
                      <div className="absolute inset-0 flex items-center gap-3 py-4 pointer-events-none">
                        <span className="text-red-400 font-manrope text-lg truncate">{interim || <span className="text-on-surface-variant/50">듣는 중...</span>}</span>
                        <div className="flex items-center gap-[3px] shrink-0">
                          {[0, 0.15, 0.3, 0.15, 0].map((delay, i) => (
                            <div key={i} className="w-[3px] bg-red-400 rounded-full animate-bounce"
                              style={{ height: `${[12,20,28,20,12][i]}px`, animationDelay: `${delay}s`, animationDuration: '0.8s' }} />
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                  <button type="button" onClick={toggleMic}
                    className={`w-12 h-12 rounded-full flex items-center justify-center transition-all duration-200 shrink-0
                      ${listening ? 'bg-red-500/20 text-red-400 animate-pulse' : 'text-on-surface-variant hover:text-primary hover:bg-primary/10'}`}>
                    <span className="material-symbols-outlined" style={listening ? { fontVariationSettings: '"FILL" 1' } : {}}>mic</span>
                  </button>
                </div>
              </form>

              {/* ── 결과 수 선택 + 보안 모드 ── */}
              <div className="mt-4 flex items-center justify-center gap-3 text-xs text-on-surface-variant flex-wrap"
                style={homeExiting ? { visibility: 'hidden' } : {}}>
                <span className="opacity-50">결과 수</span>
                {[10, 20, 30, 50].map(n => (
                  <button key={n} type="button" onClick={() => setTopK(n)}
                    className={`px-3 py-1 rounded-full border transition-colors
                      ${topK === n
                        ? 'border-primary text-primary bg-primary/10'
                        : 'border-outline-variant/20 hover:border-primary/40 hover:text-on-surface'
                      }`}>
                    {n}
                  </button>
                ))}
                <div className="w-px h-4 bg-outline-variant/20 mx-1" />
                {/* 보안 모드 토글 */}
                <button
                  type="button"
                  onClick={() => setSecurityMode(m => !m)}
                  title={securityMode ? '보안 모드 ON — 클릭하여 해제' : '보안 모드: 검색 결과에서 개인정보 자동 마스킹'}
                  className={`flex items-center gap-1.5 px-3 py-1 rounded-full border font-bold transition-all duration-200
                    ${securityMode
                      ? 'bg-amber-500/20 border-amber-400/70 text-amber-400 shadow-[0_0_14px_rgba(251,191,36,0.25)]'
                      : 'border-outline-variant/20 text-on-surface-variant hover:border-amber-400/40 hover:text-amber-400'
                    }`}
                >
                  <span className="material-symbols-outlined text-sm leading-none"
                    style={{ fontVariationSettings: securityMode ? '"FILL" 1' : '"FILL" 0' }}>
                    {securityMode ? 'security' : 'lock_open'}
                  </span>
                  <span>{securityMode ? '보안 ON' : '보안 모드'}</span>
                </button>
              </div>

              <div className="mt-8 flex justify-center" style={homeExiting ? { visibility: 'hidden' } : {}}>
                <button ref={btnRef} onClick={handleGoToAI} disabled={aiTransitioning}
                  className="px-8 py-3 rounded-full bg-surface-container-high border border-outline-variant/20 flex items-center gap-3 text-lg font-bold tracking-widest uppercase text-on-surface-variant hover:text-on-surface hover:bg-surface-container-highest transition-all duration-300 group glow-primary disabled:pointer-events-none">
                  <span className="w-2 h-2 rounded-full bg-primary animate-pulse" />
                  AI 모드로 전환
                  <span className="material-symbols-outlined text-lg group-hover:translate-x-1 transition-transform">arrow_forward</span>
                </button>
              </div>

              {/* fly 클론 */}
              {flyStyle && (
                <div style={{ ...flyStyle }}>
                  <div className="glass-effect rounded-full p-2 border border-primary/40 shadow-[0_0_30px_rgba(133,173,255,0.15)] flex items-center gap-3 px-4 py-3">
                    <span className="material-symbols-outlined text-primary">search</span>
                    <span className="flex-1 text-on-surface font-manrope text-lg truncate">{inputValue}</span>
                  </div>
                </div>
              )}

              <div className={`grid grid-cols-1 md:grid-cols-3 gap-4 mt-24 w-full transition-all duration-300 ${homeExiting ? 'opacity-0 translate-y-4' : 'opacity-100 translate-y-0'}`}>
                {[
                  { icon: 'summarize',      color: 'text-primary',   title: 'PDF 요약',     sub: '신경망 처리' },
                  { icon: 'search_insights',color: 'text-secondary', title: '심층 메타데이터',sub: '속성 분석' },
                  { icon: 'auto_awesome',   color: 'text-primary',   title: '비주얼 검색',  sub: '비전 엔진' },
                ].map((card) => (
                  <div key={card.title} className="glass-effect p-6 rounded-xl border border-outline-variant/15 hover:border-primary/20 transition-all group cursor-pointer">
                    <span className={`material-symbols-outlined ${card.color} mb-4 block`}>{card.icon}</span>
                    <h3 className="text-on-surface font-bold mb-1">{card.title}</h3>
                    <p className="text-on-surface-variant text-base uppercase tracking-tighter">{card.sub}</p>
                  </div>
                ))}
              </div>
            </div>

            <div className="absolute bottom-0 left-0 w-full h-32 bg-gradient-to-t from-surface-container-low/80 to-transparent pointer-events-none" />
          </main>
          <div className="fixed top-0 right-0 w-1/3 h-screen bg-gradient-to-l from-primary/5 to-transparent pointer-events-none" />
        </>
      )}

      {/* ════ RESULTS / DETAIL 공통 헤더 ════ */}
      {view !== 'home' && (
        <header className={`fixed top-8 ${leftEdge} right-0 z-40 bg-slate-950/60 backdrop-blur-xl flex items-center px-6 py-3 gap-4 border-b border-outline-variant/10 shadow-[0_0_20px_rgba(133,173,255,0.1)] transition-[left] duration-300`}>
          <button onClick={() => { setView('home'); setInputValue(''); setResults([]); setImgQuery(null) }}
            className={`text-lg font-bold tracking-tighter bg-gradient-to-r from-blue-300 to-purple-400 bg-clip-text text-transparent shrink-0 hover:opacity-70 transition-opacity ${!open ? 'ml-10' : ''}`}>
            DB_insight
          </button>

          <form onSubmit={handleSearch} className="flex-1">
            <div className={`flex items-center rounded-full border px-4 py-2 gap-3 transition-all
              ${listening
                ? 'bg-red-500/5 border-red-400/50 shadow-[0_0_15px_rgba(248,113,113,0.15)]'
                : imgQuery
                  ? 'bg-surface-container-high border-emerald-500/40'
                  : 'bg-surface-container-high border-outline-variant/20 focus-within:border-primary/50'
              }`}>

              {imgQuery ? (
                /* ── 이미지 쿼리 칩 ── */
                <>
                  <img
                    src={imgQuery.preview}
                    alt="쿼리 이미지"
                    className="w-7 h-7 rounded-md object-cover shrink-0 ring-1 ring-emerald-500/50"
                  />
                  <span className="text-emerald-400 text-xs font-bold uppercase tracking-wider shrink-0">이미지 검색</span>
                  <span className="text-on-surface-variant text-sm truncate flex-1">{imgQuery.file.name}</span>
                  <button
                    type="button"
                    onClick={() => { setImgQuery(null); setResults([]); setView('home') }}
                    className="shrink-0 text-on-surface-variant/40 hover:text-red-400 transition-colors"
                    title="이미지 쿼리 해제"
                  >
                    <span className="material-symbols-outlined text-lg">close</span>
                  </button>
                </>
              ) : (
                /* ── 텍스트 입력 ── */
                <>
                  <span className={`material-symbols-outlined text-lg ${listening ? 'text-red-400' : 'text-primary'}`}>
                    {listening ? 'mic' : 'search'}
                  </span>
                  <div className="flex-1 relative">
                    <input
                      className="bg-transparent border-none focus:ring-0 w-full text-on-surface placeholder-on-surface-variant text-lg outline-none"
                      placeholder={listening ? '' : '인텔리전스에 질문하세요...'}
                      value={listening ? '' : inputValue}
                      onChange={(e) => !listening && setInputValue(e.target.value)}
                      readOnly={listening}
                    />
                    {listening && (
                      <div className="absolute inset-0 flex items-center gap-2 pointer-events-none">
                        <span className="text-red-400 text-lg truncate">{interim || '듣는 중...'}</span>
                        <div className="flex items-center gap-[2px] shrink-0">
                          {[0,0.1,0.2,0.1,0].map((d,i) => (
                            <div key={i} className="w-[2px] bg-red-400 rounded-full animate-bounce"
                              style={{ height: `${[6,10,14,10,6][i]}px`, animationDelay: `${d}s`, animationDuration: '0.7s' }} />
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                  <button type="button" onClick={toggleMic}
                    className={`shrink-0 transition-all duration-200 ${listening ? 'text-red-400 animate-pulse' : 'text-on-surface-variant hover:text-primary'}`}>
                    <span className="material-symbols-outlined text-lg" style={listening ? { fontVariationSettings: '"FILL" 1' } : {}}>mic</span>
                  </button>
                </>
              )}
            </div>
          </form>

          {/* 보안 모드 토글 */}
          <button
            onClick={() => setSecurityMode(m => !m)}
            title={securityMode ? '보안 모드 ON — 클릭하여 해제' : '보안 모드 OFF — 클릭하여 활성화'}
            className={`shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-full border text-xs font-bold transition-all duration-200
              ${securityMode
                ? 'bg-amber-500/15 border-amber-400/60 text-amber-400 shadow-[0_0_12px_rgba(251,191,36,0.2)]'
                : 'bg-surface-container-high border-outline-variant/20 text-on-surface-variant hover:border-amber-400/40 hover:text-amber-400'
              }`}
          >
            <span className="material-symbols-outlined text-base"
              style={{ fontVariationSettings: securityMode ? '"FILL" 1' : '"FILL" 0' }}>
              {securityMode ? 'security' : 'lock_open'}
            </span>
            <span className="hidden sm:inline">{securityMode ? '보안 ON' : '보안'}</span>
          </button>

          {view === 'detail' && (
            <button onClick={handleBackToResults}
              className="flex items-center gap-2 px-4 py-2 rounded-full bg-surface-container-high border border-outline-variant/20 text-base font-bold text-on-surface-variant hover:text-primary hover:border-primary/30 transition-all shrink-0">
              <span className="material-symbols-outlined text-lg">arrow_back</span>결과로
            </button>
          )}
        </header>
      )}

      {/* ════ RESULTS VIEW ════ */}
      {view === 'results' && (
        <main className={`${ml} pt-24 min-h-screen transition-[margin] duration-300`}
          style={{ opacity: resultsReady ? 1 : 0, transform: resultsReady ? 'translateY(0)' : 'translateY(24px)', transition: 'opacity 0.38s ease, transform 0.38s ease, margin 0.3s' }}>
          <div className="p-8 max-w-[1400px] mx-auto">

            {/* 헤더 */}
            <div className="flex justify-between items-end mb-10">
              <div className="space-y-2">
                <span className={`px-2 py-0.5 rounded text-lg font-bold uppercase tracking-widest border
                  ${imgQuery ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' : 'bg-primary/10 text-primary border-primary/20'}`}>
                  {imgQuery ? '이미지 쿼리' : '현재 쿼리'}
                </span>
                {imgQuery ? (
                  <div className="flex items-center gap-4">
                    <img
                      src={imgQuery.preview}
                      alt="쿼리 이미지"
                      className="h-14 rounded-xl object-cover ring-2 ring-emerald-500/30 shadow-lg"
                    />
                    <div>
                      <p className="text-2xl font-extrabold tracking-tighter text-on-surface">{imgQuery.file.name}</p>
                      <p className="text-xs text-on-surface-variant/60 mt-0.5">
                        {(imgQuery.file.size / 1024).toFixed(0)} KB · {imgQuery.file.type}
                      </p>
                    </div>
                  </div>
                ) : (
                  <h1 className="text-4xl font-extrabold tracking-tighter text-on-surface">{query}</h1>
                )}
                {searching
                  ? <p className="text-on-surface-variant flex items-center gap-2">
                      <span className="material-symbols-outlined text-primary text-lg animate-spin">progress_activity</span>검색 중...
                    </p>
                  : searchError
                    ? <p className="text-red-400 text-lg">{searchError}</p>
                    : <p className="text-on-surface-variant">
                      로컬 보관소에서 <span className="text-primary font-bold">{results.length}건</span>을 찾았습니다.
                      {typeFilter && <span className="ml-2 text-xs text-on-surface-variant/60">(필터 적용: {filteredResults.length}건 표시)</span>}
                    </p>
                }
              </div>
              <div className="flex gap-3 flex-wrap items-center">
                {/* 타입 필터 칩 */}
                {typeFilter && (
                  <button onClick={() => setTypeFilter(null)}
                    className="px-3 py-1.5 rounded-full text-xs font-bold bg-primary/20 text-primary border border-primary/40 flex items-center gap-1 hover:bg-primary/30 transition-all">
                    <span className="material-symbols-outlined text-sm">{getTypeMeta(typeFilter).icon}</span>
                    {getTypeMeta(typeFilter).label}
                    <span className="material-symbols-outlined text-sm">close</span>
                  </button>
                )}
                <button className="px-4 py-2 rounded-full glass-panel border border-outline-variant/20 text-base font-bold hover:bg-primary/5 transition-all flex items-center gap-2">
                  <span className="material-symbols-outlined text-lg">filter_list</span>관련도
                </button>
              </div>
            </div>

            {/* 로딩 */}
            {searching && (
              <div className="flex flex-col items-center justify-center py-32 gap-4">
                <span className="material-symbols-outlined text-primary text-5xl animate-spin">progress_activity</span>
                <p className="text-on-surface-variant">벡터 유사도 계산 중...</p>
              </div>
            )}

            {/* 결과 없음 */}
            {!searching && !searchError && results.length === 0 && (
              <div className="flex flex-col items-center justify-center py-32 gap-4">
                <span className="material-symbols-outlined text-on-surface-variant/20 text-6xl">search_off</span>
                <p className="text-on-surface-variant">일치하는 파일을 찾지 못했습니다.</p>
                <p className="text-xs text-on-surface-variant/40">데이터 페이지에서 먼저 파일을 인덱싱하세요.</p>
              </div>
            )}

            {/* 필터 결과 없음 */}
            {!searching && results.length > 0 && filteredResults.length === 0 && (
              <div className="flex flex-col items-center justify-center py-24 gap-4">
                <span className="material-symbols-outlined text-on-surface-variant/20 text-5xl">filter_list_off</span>
                <p className="text-on-surface-variant">"{getTypeMeta(typeFilter).label}" 타입 결과가 없습니다.</p>
                <button onClick={() => setTypeFilter(null)} className="text-primary text-sm underline">필터 해제</button>
              </div>
            )}

            {/* 결과 카드 */}
            {!searching && filteredResults.length > 0 && (
              <div className="grid gap-4" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))' }}>
                {filteredResults.map((r, i) => (
                  <ResultCard key={r.file_path + i} result={r} rank={i + 1} onClick={() => handleSelectFile(r)} securityMode={securityMode} />
                ))}
              </div>
            )}

            {/* 하단 통계 */}
            {!searching && results.length > 0 && (
              <div className="mt-12 glass-panel rounded-[1.5rem] p-6 border border-outline-variant/10 relative overflow-hidden">
                <div className="absolute -right-20 -top-20 w-64 h-64 bg-primary/10 rounded-full blur-[80px]" />
                <div className="relative z-10">
                  <h3 className="text-sm font-bold text-primary mb-4 flex items-center gap-2 uppercase tracking-widest">
                    <span className="material-symbols-outlined text-lg">analytics</span>검색 요약
                  </h3>
                  <p className="text-on-surface leading-relaxed mb-6">
                    <span className="text-primary font-bold">"{query}"</span>에 대해 TRI-CHEF 엔진이 신뢰도 기준으로 정렬한 결과입니다.
                  </p>
                  <div className="grid grid-cols-4 gap-4">
                    {[
                      ['총 결과', `${results.length}건`],
                      ['최고 신뢰도', `${Math.round((results[0]?.confidence ?? 0) * 100)}%`],
                      ['문서·이미지', `${results.filter(r => r.file_type === 'doc' || r.file_type === 'image').length}건`],
                      ['영상·음성', `${results.filter(r => r.file_type === 'video' || r.file_type === 'audio').length}건`],
                    ].map(([label, val]) => (
                      <div key={label} className="p-4 rounded-2xl bg-slate-900/40 border border-outline-variant/5">
                        <p className="text-sm text-slate-500 uppercase tracking-widest mb-1">{label}</p>
                        <p className="text-xl font-bold text-on-surface">{val}</p>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}
          </div>
        </main>
      )}

      {/* ════ DETAIL VIEW ════ */}
      {view === 'detail' && selectedFile && (() => {
        const meta    = getTypeMeta(selectedFile.file_type)
        const confPct = Math.round((selectedFile.confidence ?? selectedFile.similarity ?? 0) * 100)
        const isAV    = selectedFile.file_type === 'video' || selectedFile.file_type === 'audio'

        return (
          <main className={`${ml} min-h-screen relative transition-[margin] duration-300`}
            style={{ backgroundImage: 'radial-gradient(rgba(133,173,255,0.05) 1px, transparent 1px)', backgroundSize: '32px 32px',
              opacity: detailVisible ? 1 : 0, transform: detailVisible ? 'translateX(0)' : 'translateX(36px)',
              transition: 'opacity 0.35s ease, transform 0.35s ease, margin 0.3s' }}>

            {/* 파일 정보 바 */}
            <div className={`fixed top-[88px] ${leftEdge} right-0 z-30 bg-[#070d1f]/60 backdrop-blur-xl flex items-center justify-between px-8 py-3 border-b border-outline-variant/10 transition-[left] duration-300`}>
              <div className="flex items-center gap-3 min-w-0 flex-1 mr-4">
                <span className={`material-symbols-outlined ${meta.color} shrink-0`}>{meta.icon}</span>
                <span className="font-manrope text-lg tracking-wide text-[#dfe4fe] font-bold truncate">{selectedFile.file_name}</span>
                <span className="px-2 py-0.5 rounded-full bg-primary/10 text-primary text-lg font-bold border border-primary/20 shrink-0">{confPct}%</span>
                <span className={`px-2 py-0.5 rounded-full text-lg font-bold border shrink-0 ${meta.color} bg-white/5 border-white/10`}>{meta.label}</span>
              </div>
              <div className="flex items-center gap-3 shrink-0">
                {/* 보안 모드 표시 (상세 페이지) */}
                {securityMode && (
                  <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-amber-500/15 border border-amber-400/50 text-amber-300 text-xs font-bold">
                    <span className="material-symbols-outlined text-sm" style={{ fontVariationSettings: '"FILL" 1' }}>security</span>
                    보안 ON
                  </div>
                )}
                <button
                  onClick={() => handleSummarize(selectedFile)}
                  disabled={summaryLoading}
                  className="px-5 py-2 text-base font-bold uppercase tracking-widest flex items-center gap-2
                    text-secondary bg-secondary/10 border border-secondary/30 rounded-full
                    hover:bg-secondary/20 transition-all active:scale-95 disabled:opacity-60 disabled:cursor-not-allowed">
                  {summaryLoading
                    ? <span className="material-symbols-outlined text-lg animate-spin">progress_activity</span>
                    : <span className="material-symbols-outlined text-lg">auto_awesome</span>
                  }
                  요약
                </button>
                <button
                  onClick={() => openFolder(selectedFile.file_path)}
                  className="px-5 py-2 text-base font-bold uppercase tracking-widest text-primary bg-surface-container-high border border-outline-variant/15 rounded-full hover:bg-surface-variant transition-colors active:scale-95">
                  경로 열기
                </button>
                <button
                  onClick={() => openFile(selectedFile.file_path)}
                  className="px-5 py-2 text-base font-bold uppercase tracking-widest text-on-primary bg-primary rounded-full hover:brightness-110 transition-all active:scale-95">
                  파일 열기
                </button>
              </div>
            </div>

            <section className="pt-44 pb-12 px-8 max-w-7xl mx-auto space-y-8">
              <div className="grid grid-cols-12 gap-6">

                {/* 메인 컨텐츠 */}
                <div className="col-span-8 space-y-6">
                  <div className="bg-surface-container-low rounded-xl glass-panel glow-primary min-h-[400px] flex flex-col"
                    style={{ border: '1px solid rgba(65,71,91,0.15)' }}>
                    <div className="flex items-center justify-between px-8 pt-7 pb-5 border-b border-outline-variant/10">
                      <span className="text-sm font-bold tracking-[0.2em] text-primary uppercase">
                        {isAV ? '미디어 플레이어 · 세그먼트 타임라인' : '추출된 콘텐츠 스트림'}
                      </span>
                      <div className="flex gap-2 items-center">
                        {detailLoading && <span className="material-symbols-outlined text-primary text-lg animate-spin">progress_activity</span>}
                        <span className="h-2 w-2 rounded-full bg-primary animate-pulse" />
                        <span className="h-2 w-2 rounded-full bg-secondary/50" />
                      </div>
                    </div>

                    {/* AV: 플레이어 + 세그먼트 타임라인 */}
                    {isAV ? (
                      <AVDetailContent result={selectedFile} />
                    ) : (selectedFile.file_type === 'image' || selectedFile.file_type === 'doc') && selectedFile.preview_url ? (
                      /* 이미지/문서: 실제 미리보기 (보안 마스킹 지원) */
                      <div className="flex-1 flex flex-col items-center justify-center px-8 py-6 gap-4 overflow-hidden">
                        <DetailImagePreview file={selectedFile} securityMode={securityMode} />
                        {selectedFile.snippet && (
                          <p className="w-full text-lg text-on-surface-variant/70 leading-relaxed line-clamp-3 text-center">
                            {selectedFile.snippet}
                          </p>
                        )}
                      </div>
                    ) : (
                      <div className="flex-1 px-8 py-6">
                        {detailLoading ? (
                          <div className="flex items-center gap-2 text-on-surface-variant/40">
                            <span className="material-symbols-outlined animate-spin text-lg">progress_activity</span>
                            <span className="text-sm">콘텐츠 불러오는 중...</span>
                          </div>
                        ) : fileDetail?.full_text ? (
                          <p className="text-on-surface-variant/90 leading-relaxed text-lg whitespace-pre-wrap">{fileDetail.full_text}</p>
                        ) : selectedFile.snippet ? (
                          <p className="text-on-surface-variant/90 leading-relaxed text-lg whitespace-pre-wrap">{selectedFile.snippet}</p>
                        ) : (
                          <div className="flex flex-col items-center justify-center h-48 gap-3 text-on-surface-variant/30">
                            <span className={`material-symbols-outlined text-5xl ${meta.color}/30`} style={{ fontVariationSettings: '"FILL" 1' }}>{meta.icon}</span>
                            <p className="text-sm">미리보기를 사용할 수 없습니다.</p>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                </div>

                {/* 메타데이터 패널 */}
                <div className="col-span-4 space-y-5">

                  {/* 신뢰도 카드 */}
                  <div className="bg-surface-container-high rounded-xl p-6 border border-outline-variant/10 relative overflow-hidden group">
                    <div className="absolute -right-4 -top-4 w-24 h-24 bg-primary/10 blur-3xl group-hover:bg-primary/20 transition-all" />
                    <h4 className="text-sm font-bold tracking-[0.15em] text-primary mb-4 uppercase">신뢰도 분석</h4>
                    <div className="space-y-3">
                      <div className="flex items-center gap-3">
                        <div className="flex-1 h-1.5 bg-surface-container-highest rounded-full overflow-hidden">
                          <div className="h-full bg-gradient-to-r from-primary to-secondary shadow-[0_0_8px_rgba(133,173,255,0.5)] transition-all duration-700"
                            style={{ width: `${confPct}%` }} />
                        </div>
                        <span className="text-sm font-bold text-on-surface tabular-nums">{confPct}%</span>
                      </div>
                      <p className="text-xs text-on-surface-variant/60">
                        {isAV ? 'BGE-M3 세그먼트 집계 + Calibration' : 'TRI-CHEF Hermitian 유사도 · Calibration'}
                      </p>
                    </div>
                  </div>

                  {/* 요약 결과 카드 */}
                  {(summary || summaryLoading) && (
                    <div className="bg-surface-container-low rounded-xl p-5 border border-secondary/20 relative overflow-hidden">
                      <div className="absolute -right-6 -top-6 w-20 h-20 bg-secondary/10 blur-2xl" />
                      <h4 className="text-sm font-bold tracking-[0.15em] text-secondary mb-3 uppercase flex items-center gap-2">
                        <span className="material-symbols-outlined text-base">auto_awesome</span>AI 요약
                      </h4>
                      {summaryLoading && (
                        <div className="flex items-center gap-2 text-on-surface-variant/50 text-sm">
                          <span className="material-symbols-outlined text-base animate-spin">progress_activity</span>
                          요약 생성 중...
                        </div>
                      )}
                      {summary?.error && (
                        <p className="text-red-400 text-sm">{summary.error}</p>
                      )}
                      {summary && !summary.error && (
                        <>
                          {/* 키워드 태그 */}
                          {summary.keywords?.length > 0 && (
                            <div className="flex flex-wrap gap-1 mb-3">
                              {summary.keywords.map((kw, i) => (
                                <span key={i} className="px-2 py-0.5 rounded-full text-[10px] font-bold
                                  bg-secondary/15 text-secondary border border-secondary/20">
                                  {kw}
                                </span>
                              ))}
                            </div>
                          )}
                          {/* 요약 문장 */}
                          <div className="space-y-2">
                            {(summary.sentences ?? [summary.summary]).map((s, i) => (
                              <p key={i} className="text-xs text-on-surface-variant/80 leading-relaxed
                                border-l-2 border-secondary/30 pl-2">
                                {s}
                              </p>
                            ))}
                          </div>
                          {summary.char_total && (
                            <p className="text-[10px] text-on-surface-variant/30 mt-2 text-right">
                              전체 {summary.char_total.toLocaleString()}자 → 요약
                            </p>
                          )}
                        </>
                      )}
                    </div>
                  )}

                  {/* AV: 세그먼트 요약 */}
                  {isAV && selectedFile.segments?.length > 0 && (
                    <div className="bg-surface-container-low rounded-xl p-5 border border-outline-variant/5">
                      <h4 className="text-sm font-bold tracking-[0.15em] text-amber-400 mb-3 uppercase">매칭 세그먼트</h4>
                      <div className="space-y-2">
                        {selectedFile.segments.slice(0, 5).map((s, i) => {
                          const t0 = s.start ?? s.start_sec ?? 0
                          const sc = s.score ?? 0
                          return (
                            <div key={i} className="flex items-center gap-2">
                              <span className="font-mono text-lg text-amber-400/80 shrink-0">{fmtTime(t0)}</span>
                              <div className="flex-1 h-1 bg-surface-container-highest rounded-full overflow-hidden">
                                <div className="h-full bg-amber-500/60 rounded-full" style={{ width: `${Math.min(sc * 200, 100)}%` }} />
                              </div>
                              <span className="text-sm text-on-surface-variant/50 font-mono shrink-0">{sc.toFixed(2)}</span>
                            </div>
                          )
                        })}
                      </div>
                    </div>
                  )}

                  {/* 파일 메타데이터 */}
                  <div className="bg-surface-container-low rounded-xl p-6 border border-outline-variant/5">
                    <h4 className="text-sm font-bold tracking-[0.15em] text-secondary mb-4 uppercase">파일 정보</h4>
                    <div className="space-y-0">
                      {[
                        ['파일명', selectedFile.file_name],
                        ['유형',   meta.label],
                        ['신뢰도', `${confPct}%`],
                        ...(isAV
                          ? [['세그먼트', `${selectedFile.segments?.length ?? 0}개`]]
                          : [['청크 수', fileDetail ? `${fileDetail.chunks?.length ?? '-'}개` : '-']]
                        ),
                        ['경로',   selectedFile.file_path],
                      ].map(([k, v]) => (
                        <div key={k} className="flex justify-between items-start py-2 border-b border-outline-variant/10 last:border-0 gap-2">
                          <span className="text-xs text-on-surface-variant shrink-0">{k}</span>
                          <span className="text-xs font-bold text-on-surface truncate max-w-[70%] text-right break-all">{v}</span>
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* 액션 */}
                  <div className="space-y-2">
                    <button
                      onClick={() => openFile(selectedFile.file_path)}
                      className="w-full group flex items-center justify-between p-4 rounded-xl bg-primary/10 hover:bg-primary/20 transition-colors border border-primary/20">
                      <div className="flex items-center gap-3">
                        <span className={`material-symbols-outlined ${meta.color}`}>{meta.icon}</span>
                        <span className="text-sm font-semibold text-on-surface">기본 앱으로 열기</span>
                      </div>
                      <span className="material-symbols-outlined text-base text-on-surface-variant">open_in_new</span>
                    </button>
                    <button
                      onClick={() => openFolder(selectedFile.file_path)}
                      className="w-full group flex items-center justify-between p-4 rounded-xl bg-surface-container-highest hover:bg-primary/10 transition-colors border border-transparent hover:border-primary/20">
                      <div className="flex items-center gap-3">
                        <span className="material-symbols-outlined text-on-surface-variant group-hover:text-primary">folder_open</span>
                        <span className="text-sm font-semibold">탐색기에서 보기</span>
                      </div>
                      <span className="material-symbols-outlined text-base text-on-surface-variant">chevron_right</span>
                    </button>
                  </div>
                </div>
              </div>
            </section>

            <div className="fixed bottom-[-10%] left-[20%] w-[40%] h-[40%] bg-primary/5 blur-[120px] pointer-events-none rounded-full" />
            <div className="fixed top-[10%] right-[-5%] w-[30%] h-[30%] bg-secondary/5 blur-[100px] pointer-events-none rounded-full" />
          </main>
        )
      })()}
    </div>
  )
}
