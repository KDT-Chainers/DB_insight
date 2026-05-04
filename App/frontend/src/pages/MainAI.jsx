import { useState, useRef, useEffect, useCallback } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import SearchSidebar from '../components/SearchSidebar'
import AnimatedOrb from '../components/AnimatedOrb'
import { useSidebar } from '../context/SidebarContext'
import { useSpeechRecognition } from '../hooks/useSpeechRecognition'
import { useMicLevelRef } from '../hooks/useMicLevelRef'
import { API_BASE } from '../api'

// ── 상수 ─────────────────────────────────────────────────────────
const AI_ORB_ASSEMBLE_SECONDS = 8

const AI = {
  accent:      '#8b5cf6',
  accentLight: '#a78bfa',
  accentDark:  '#6d28d9',
  bg:          '#0d0718',
  card:        '#130d24',
  border:      'rgba(139,92,246,0.2)',
  borderHover: 'rgba(139,92,246,0.5)',
  rankBg:      'linear-gradient(135deg, #6d28d9, #7c3aed)',
  glow:        '0 0 20px rgba(139,92,246,0.3)',
}

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

function fmtTime(sec) {
  if (!sec && sec !== 0) return '0:00'
  const s = Math.floor(sec)
  const m = Math.floor(s / 60)
  return `${m}:${String(s % 60).padStart(2, '0')}`
}

function avStreamUrl(result) {
  const domain = result.trichef_domain ?? (result.file_type === 'video' ? 'movie' : 'music')
  return `${API_BASE}/api/admin/file?domain=${domain}&id=${encodeURIComponent(result.file_path)}`
}

// 마크다운 → 평문 (LLM 이 ignore prompt 해서 별표를 쓸 경우 대비)
function stripMarkdown(text) {
  if (!text) return text
  return text
    .replace(/\*\*(.+?)\*\*/g, '$1')
    .replace(/(?<![*\w])\*(.+?)\*(?!\*)/g, '$1')
    .replace(/^#{1,6}\s+/gm, '')
    .replace(/`([^`\n]+)`/g, '$1')
    .replace(/^>\s+/gm, '')
    .replace(/^[-*_]{3,}\s*$/gm, '')
    .replace(/^(\s*)[-*]\s+/gm, '$1• ')
}

// 답변 안의 [출처N] 강조
function renderAnswer(text) {
  if (!text) return null
  const parts = text.split(/(\[출처\d+\])/g)
  return parts.map((part, i) => {
    if (/^\[출처\d+\]$/.test(part)) {
      return (
        <span key={i} className="font-bold text-sm px-1.5 py-0.5 rounded-md mx-0.5 align-middle"
          style={{ background: 'rgba(139,92,246,0.2)', color: AI.accentLight, border: `1px solid ${AI.border}` }}>
          {part}
        </span>
      )
    }
    return <span key={i}>{part}</span>
  })
}

// ── 후보 파일 카드 (스캔 애니메이션 포함) ────────────────────────
function CandidateCard({ source, index, scanState, chunks, onClick }) {
  const [imgError, setImgError] = useState(false)
  const playerRef = useRef(null)

  const fname    = source.file_name || source.trichef_id || '?'
  const ftype    = source.file_type || ''
  const conf     = source.confidence ?? 0
  const isAV     = ftype === 'video' || ftype === 'audio' || ftype === 'movie' || ftype === 'music'
  const hasThumb = (ftype === 'image' || ftype === 'doc') && source.preview_url
  const meta     = getTypeMeta(ftype)

  // scanState: 'idle' | 'scanning' | 'found' | 'not_found'
  const isScanning = scanState === 'scanning'
  const isFound    = scanState === 'found'
  const isNotFound = scanState === 'not_found'

  const cardStyle = {
    background:   AI.card,
    border:       `1px solid ${isFound ? '#10b981' : isNotFound ? 'rgba(100,116,139,0.2)' : isScanning ? AI.accent : AI.border}`,
    boxShadow:    isFound ? '0 0 24px rgba(16,185,129,0.35)' : isScanning ? '0 0 16px rgba(139,92,246,0.4)' : 'none',
    opacity:      isNotFound ? 0.35 : 1,
    filter:       isNotFound ? 'grayscale(70%)' : 'none',
    transition:   'all 0.4s ease',
    cursor:       'pointer',
  }

  return (
    <div
      onClick={() => onClick?.(source)}
      className="rounded-2xl overflow-hidden flex flex-col relative"
      style={cardStyle}
      onMouseEnter={e => {
        if (!isNotFound) {
          e.currentTarget.style.borderColor = isFound ? '#34d399' : AI.borderHover
          e.currentTarget.style.boxShadow   = isFound ? '0 0 32px rgba(16,185,129,0.5)' : AI.glow
        }
      }}
      onMouseLeave={e => {
        e.currentTarget.style.borderColor = isFound ? '#10b981' : isNotFound ? 'rgba(100,116,139,0.2)' : isScanning ? AI.accent : AI.border
        e.currentTarget.style.boxShadow   = isFound ? '0 0 24px rgba(16,185,129,0.35)' : isScanning ? '0 0 16px rgba(139,92,246,0.4)' : 'none'
      }}
    >
      {/* 상태 배지 */}
      {scanState !== 'idle' && (
        <div className="absolute top-2 right-2 z-30 flex items-center gap-1 px-2 py-1 rounded-full text-[10px] font-bold"
          style={{
            background: isScanning ? 'rgba(139,92,246,0.85)' : isFound ? 'rgba(16,185,129,0.85)' : 'rgba(71,85,105,0.85)',
            color: '#fff',
          }}>
          {isScanning && <span className="material-symbols-outlined text-sm animate-spin">progress_activity</span>}
          {isFound    && <span className="material-symbols-outlined text-sm">check_circle</span>}
          {isNotFound && <span className="material-symbols-outlined text-sm">cancel</span>}
          <span>{isScanning ? '스캔 중' : isFound ? '발견됨' : '없음'}</span>
        </div>
      )}

      {/* 순위 배지 */}
      <div className="absolute top-2 left-2 z-20 min-w-[28px] h-6 px-1.5 rounded-full flex items-center justify-center font-bold text-[10px] text-white"
        style={{ background: AI.rankBg, boxShadow: '0 0 8px rgba(139,92,246,0.5)' }}>
        #{index + 1}
      </div>

      {/* AV 플레이어 */}
      {isAV && (
        <div className="px-3 py-2 border-b" style={{ background: '#0b0515', borderColor: AI.border }}
          onClick={e => e.stopPropagation()}>
          {ftype === 'video' || ftype === 'movie' ? (
            <video ref={playerRef} src={avStreamUrl(source)} controls preload="metadata"
              className="w-full block outline-none bg-black" style={{ maxHeight: '160px' }} />
          ) : (
            <audio ref={playerRef} src={avStreamUrl(source)} controls preload="metadata"
              className="w-full block outline-none" />
          )}
        </div>
      )}

      {/* 이미지/문서 썸네일 */}
      {!isAV && (
        <div className="relative h-[150px] flex items-center justify-center overflow-hidden"
          style={{ background: '#0b0515' }}>
          {hasThumb && !imgError ? (
            <img src={`${API_BASE}${source.preview_url}`} alt={fname}
              className="max-w-full max-h-full object-contain"
              onError={() => setImgError(true)} />
          ) : (
            <span className={`material-symbols-outlined text-4xl ${meta.color}`}
              style={{ fontVariationSettings: '"FILL" 0, "wght" 200' }}>
              {meta.icon}
            </span>
          )}
          {/* 스캔 오버레이 */}
          {isScanning && (
            <div className="absolute inset-0 flex items-center justify-center"
              style={{ background: 'rgba(109,40,217,0.15)' }}>
              <div className="absolute inset-0 overflow-hidden">
                <div className="scan-line" />
              </div>
            </div>
          )}
        </div>
      )}

      {/* 바디 */}
      <div className="p-3 flex flex-col gap-2 flex-1">
        {/* 신뢰도 + 타입 */}
        <div className="flex items-center justify-between">
          <span className="text-[10px] px-2 py-0.5 rounded-full font-bold border"
            style={{ background: 'rgba(139,92,246,0.1)', color: AI.accentLight, borderColor: AI.border }}>
            {ftype || 'file'}
          </span>
          <span className="text-[11px] font-mono font-bold" style={{ color: AI.accentLight }}>
            {(conf * 100).toFixed(0)}%
          </span>
        </div>

        {/* 파일명 */}
        <div className="text-[13px] font-semibold text-[#f1f5f9] leading-snug line-clamp-2" title={fname}>
          {fname}
        </div>

        {/* 매칭된 청크 (found 상태일 때) */}
        {isFound && chunks && chunks.length > 0 && (
          <div className="mt-1 px-2 py-1.5 rounded-lg text-[10px] text-emerald-300/80 leading-relaxed line-clamp-3"
            style={{ background: 'rgba(16,185,129,0.08)', border: '1px solid rgba(16,185,129,0.2)' }}>
            ...{chunks[0].slice(0, 120)}...
          </div>
        )}
      </div>
    </div>
  )
}

// ── 의도 메시지 박스 ──────────────────────────────────────────────
function IntentBox({ message, fileKeywords, detailKeywords, visible }) {
  return (
    <div className={`mb-5 rounded-2xl border p-4 transition-all duration-500 ${visible ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-4'}`}
      style={{ background: 'linear-gradient(135deg, rgba(109,40,217,0.12) 0%, rgba(76,29,149,0.08) 100%)', borderColor: AI.border }}>
      <div className="flex items-start gap-3">
        <div className="w-8 h-8 rounded-full flex items-center justify-center shrink-0"
          style={{ background: 'linear-gradient(135deg, #6d28d9, #7c3aed)', boxShadow: '0 0 14px rgba(139,92,246,0.4)' }}>
          <span className="material-symbols-outlined text-white text-base" style={{ fontVariationSettings: '"FILL" 1' }}>smart_toy</span>
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm text-[#e2e8f0] leading-relaxed mb-2">{message}</p>
          <div className="flex flex-wrap gap-2">
            {fileKeywords.map((kw, i) => (
              <span key={`f${i}`} className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold"
                style={{ background: 'rgba(139,92,246,0.15)', color: AI.accentLight, border: `1px solid ${AI.border}` }}>
                <span className="material-symbols-outlined text-[10px]">folder_search</span>
                {kw}
              </span>
            ))}
            {detailKeywords.map((kw, i) => (
              <span key={`d${i}`} className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold"
                style={{ background: 'rgba(16,185,129,0.1)', color: '#34d399', border: '1px solid rgba(16,185,129,0.2)' }}>
                <span className="material-symbols-outlined text-[10px]">manage_search</span>
                {kw}
              </span>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

// ── 스캔 진행 헤더 ────────────────────────────────────────────────
function ScanProgressBar({ total, scanned, found }) {
  const pct = total > 0 ? Math.round((scanned / total) * 100) : 0
  return (
    <div className="mb-4 rounded-xl border px-4 py-3"
      style={{ background: AI.card, borderColor: AI.border }}>
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2 text-sm font-bold" style={{ color: AI.accentLight }}>
          <span className="material-symbols-outlined text-base animate-pulse">radar</span>
          파일 내용 스캔 중...
        </div>
        <div className="flex items-center gap-3 text-[11px] text-on-surface-variant">
          <span className="text-emerald-400 font-bold">{found}개 발견</span>
          <span>{scanned}/{total}</span>
        </div>
      </div>
      <div className="h-1.5 rounded-full overflow-hidden" style={{ background: 'rgba(139,92,246,0.1)' }}>
        <div className="h-full rounded-full transition-all duration-300"
          style={{ width: `${pct}%`, background: 'linear-gradient(90deg, #6d28d9, #8b5cf6, #a78bfa)' }} />
      </div>
    </div>
  )
}

// ── 답변 패널 ────────────────────────────────────────────────────
function AnswerPanel({ answer, streaming, sources, done, onClickSource }) {
  const clean = stripMarkdown(answer)
  return (
    <div className="mt-6 rounded-2xl border overflow-hidden"
      style={{ background: AI.card, borderColor: AI.border }}>
      {/* 헤더 */}
      <div className="flex items-center gap-2.5 px-5 py-3"
        style={{ background: 'rgba(109,40,217,0.12)', borderBottom: `1px solid ${AI.border}` }}>
        <div className="w-6 h-6 rounded-full flex items-center justify-center"
          style={{ background: 'linear-gradient(135deg, #6d28d9, #7c3aed)' }}>
          <span className="material-symbols-outlined text-white text-sm" style={{ fontVariationSettings: '"FILL" 1' }}>smart_toy</span>
        </div>
        <span className="text-sm font-bold" style={{ color: AI.accentLight }}>AI 답변</span>
        {streaming && (
          <span className="material-symbols-outlined text-base animate-spin ml-auto" style={{ color: AI.accent }}>progress_activity</span>
        )}
        {done && !streaming && (
          <span className="material-symbols-outlined text-base ml-auto text-emerald-400">check_circle</span>
        )}
      </div>

      {/* 답변 본문 */}
      <div className="px-5 py-4 text-[14px] leading-relaxed text-[#e2e8f0] whitespace-pre-wrap">
        {renderAnswer(clean)}
        {streaming && (
          <span className="inline-block w-0.5 h-4 ml-0.5 animate-pulse align-middle"
            style={{ background: AI.accentLight }} />
        )}
      </div>

      {/* 출처 목록 */}
      {sources && sources.length > 0 && (
        <div className="px-5 pb-4 pt-1 border-t" style={{ borderColor: AI.border }}>
          <p className="text-[10px] uppercase tracking-widest font-bold mb-2" style={{ color: AI.accentLight }}>
            참고 파일
          </p>
          <div className="flex flex-col gap-1.5">
            {sources.map((src, i) => (
              <button key={i} onClick={() => onClickSource?.(src)}
                className="flex items-center gap-2 text-left text-[11px] text-on-surface-variant/70 hover:text-on-surface transition-colors group">
                <span className="text-[10px] font-bold px-1.5 py-0.5 rounded shrink-0"
                  style={{ background: 'rgba(139,92,246,0.15)', color: AI.accentLight }}>
                  출처{i + 1}
                </span>
                <span className="truncate group-hover:underline">{src.file_name || '?'}</span>
                <span className="shrink-0 text-[10px] text-on-surface-variant/40">{src.file_type}</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ── AV 상세 플레이어 ──────────────────────────────────────────────
function AVDetailContent({ result }) {
  const isVideo   = result.file_type === 'video' || result.file_type === 'movie'
  const playerRef = useRef(null)
  const streamUrl = avStreamUrl(result)
  const segments  = result.segments ?? []
  const seekTo    = (t) => { const p = playerRef.current; if (!p) return; p.currentTime = t; p.play().catch(() => {}) }

  return (
    <div className="flex-1 flex flex-col">
      <div className="px-8 pt-6 pb-4">
        <div className="rounded-xl overflow-hidden bg-black/60 border" style={{ borderColor: AI.border }}>
          {isVideo ? (
            <video ref={playerRef} src={streamUrl} controls preload="metadata"
              className="w-full max-h-[280px] object-contain" />
          ) : (
            <div className="flex flex-col items-center p-6 gap-3">
              <span className="material-symbols-outlined text-amber-400 text-4xl" style={{ fontVariationSettings: '"FILL" 1' }}>volume_up</span>
              <audio ref={playerRef} src={streamUrl} controls preload="metadata" className="w-full" />
            </div>
          )}
        </div>
      </div>
      {segments.length > 0 && (
        <div className="px-8 pb-4 flex-1 overflow-y-auto">
          <p className="text-sm font-bold uppercase tracking-widest mb-3 flex items-center gap-1" style={{ color: AI.accentLight }}>
            <span className="material-symbols-outlined text-base">timeline</span>
            매칭 구간 ({segments.length}개)
          </p>
          <div className="space-y-2">
            {segments.map((seg, i) => {
              const t0 = seg.start ?? seg.start_sec ?? 0
              const t1 = seg.end   ?? seg.end_sec   ?? 0
              const sc = seg.score ?? 0
              return (
                <button key={i} onClick={() => seekTo(t0)}
                  className="w-full text-left p-3 rounded-xl transition-all"
                  style={{ background: AI.card, border: `1px solid ${AI.border}` }}
                  onMouseEnter={e => e.currentTarget.style.borderColor = AI.accentLight}
                  onMouseLeave={e => e.currentTarget.style.borderColor = AI.border}>
                  <div className="flex items-center justify-between mb-1.5">
                    <div className="flex items-center gap-2">
                      <span className="material-symbols-outlined text-base" style={{ color: AI.accent }}>play_circle</span>
                      <span className="font-mono text-lg font-bold" style={{ color: AI.accentLight }}>{fmtTime(t0)}</span>
                      <span className="text-sm text-on-surface-variant/40">→</span>
                      <span className="font-mono text-lg text-on-surface-variant/60">{fmtTime(t1)}</span>
                    </div>
                    <span className="text-sm font-mono tabular-nums text-on-surface-variant/60">{sc.toFixed(3)}</span>
                  </div>
                  {(seg.text || seg.caption) && (
                    <p className="text-xs text-on-surface-variant/70 leading-relaxed line-clamp-2 pl-5">
                      {seg.text || seg.caption}
                    </p>
                  )}
                </button>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}

// ────────────────────────────────────────────────────────────────
// 메인 컴포넌트
// ────────────────────────────────────────────────────────────────
export default function MainAI() {
  const navigate = useNavigate()
  const location = useLocation()
  const { open } = useSidebar()

  // ── 뷰 상태 ─────────────────────────────────────────────────
  const [view,          setView]          = useState('home')
  const [query,         setQuery]         = useState('')
  const [inputValue,    setInputValue]    = useState('')
  const [selectedFile,  setSelectedFile]  = useState(null)
  const [fileDetail,    setFileDetail]    = useState(null)
  const [detailLoading, setDetailLoading] = useState(false)

  // ── RAG 파이프라인 상태 ──────────────────────────────────────
  const [streaming,       setStreaming]       = useState(false)
  const [ragPhase,        setRagPhase]        = useState('idle')  // idle|intent|candidates|scanning|selected|answering|done
  const [intentMessage,   setIntentMessage]   = useState('')
  const [fileKeywords,    setFileKeywords]    = useState([])
  const [detailKeywords,  setDetailKeywords]  = useState([])
  const [candidates,      setCandidates]      = useState([])
  // scanStates: { [file_id]: 'idle'|'scanning'|'found'|'not_found' }
  const [scanStates,      setScanStates]      = useState({})
  // scanChunks: { [file_id]: string[] }
  const [scanChunks,      setScanChunks]      = useState({})
  const [scannedCount,    setScannedCount]    = useState(0)
  const [foundCount,      setFoundCount]      = useState(0)
  const [selectedSources, setSelectedSources] = useState([])
  const [answer,          setAnswer]          = useState('')
  const [aiError,         setAiError]         = useState('')
  const [ragDone,         setRagDone]         = useState(false)

  const [topK,     setTopK]     = useState(5)
  const abortRef = useRef(null)

  // ── 애니메이션 ───────────────────────────────────────────────
  const [homeExiting,    setHomeExiting]    = useState(false)
  const [resultsReady,   setResultsReady]   = useState(false)
  const [detailVisible,  setDetailVisible]  = useState(false)
  const [aiHomeEntranceOn, setAiHomeEntranceOn] = useState(
    () => typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches
  )
  const [searchTransitioning, setSearchTransitioning] = useState(false)
  const [ripplePos, setRipplePos] = useState({ x: '50%', y: '50%' })

  const btnRef     = useRef(null)
  const inputRef   = useRef(null)
  const orbSinkRef = useRef(null)
  const orbVoiceRef = useRef(0)
  const ml        = open ? 'ml-64' : 'ml-0'
  const leftEdge  = open ? 'left-64' : 'left-0'

  // aiHomeEntranceOn 제어
  useEffect(() => {
    if (view !== 'home') { setAiHomeEntranceOn(false); return }
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) { setAiHomeEntranceOn(true); return }
    setAiHomeEntranceOn(false)
    const t = window.setTimeout(() => setAiHomeEntranceOn(true), 180)
    return () => clearTimeout(t)
  }, [view])

  useEffect(() => {
    if (view !== 'detail') {
      const t = setTimeout(() => inputRef.current?.focus(), 150)
      return () => clearTimeout(t)
    }
  }, [view])

  // STT
  const doSearchRef = useRef(null)
  const { listening, toggle: toggleMic, stop: stopMic } = useSpeechRecognition({
    onFinal: useCallback((text) => {
      setInputValue(text)
      setTimeout(() => doSearchRef.current?.(text), 80)
    }, []),
  })

  useMicLevelRef(view === 'home' && listening, orbVoiceRef, { startDelayMs: 420 })

  useEffect(() => {
    if (view !== 'home') stopMic()
  }, [view, stopMic])

  // 뒤로가기
  useEffect(() => {
    const handle = () => {
      setDetailVisible(false)
      if (view === 'detail')       setTimeout(() => setView('results'), 320)
      else if (view === 'results') { setResultsReady(false); setView('home') }
    }
    window.addEventListener('popstate', handle)
    return () => window.removeEventListener('popstate', handle)
  }, [view])

  // 사이드바 검색 기록 클릭
  useEffect(() => {
    const q = location.state?.query
    if (q) { window.history.replaceState({}, ''); doSearchRef.current?.(q) }
  }, [location.state])

  // ── RAG SSE 실행 ─────────────────────────────────────────────
  const runRAG = useCallback(async (q) => {
    if (abortRef.current) abortRef.current.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setStreaming(true)
    setRagPhase('intent')
    setIntentMessage('')
    setFileKeywords([])
    setDetailKeywords([])
    setCandidates([])
    setScanStates({})
    setScanChunks({})
    setScannedCount(0)
    setFoundCount(0)
    setSelectedSources([])
    setAnswer('')
    setAiError('')
    setRagDone(false)

    // thread_id (localStorage 영속, 24h TTL)
    let tid = null
    try {
      const raw = localStorage.getItem('aimode_thread_id')
      if (raw) {
        const obj = JSON.parse(raw)
        if (obj?.id && obj?.expires > Date.now()) tid = obj.id
      }
    } catch {}
    if (!tid) {
      tid = `t_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
      try {
        localStorage.setItem('aimode_thread_id', JSON.stringify({
          id: tid, expires: Date.now() + 24 * 3600 * 1000,
        }))
      } catch {}
    }
    window.__aimodeThreadId = tid

    try {
      const resp = await fetch(`${API_BASE}/api/aimode/chat`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ query: q, topk: topK, thread_id: tid }),
        signal:  controller.signal,
      })

      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)

      const reader  = resp.body.getReader()
      const decoder = new TextDecoder()
      let   buf     = ''

      while (true) {
        const { value, done } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        const lines = buf.split('\n')
        buf = lines.pop() ?? ''

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const raw = line.slice(6).trim()
          if (!raw) continue
          let ev
          try { ev = JSON.parse(raw) } catch { continue }

          switch (ev.type) {
            case 'info':
              // 연결 확인 — 아무것도 안 함
              break

            case 'intent':
              setIntentMessage(ev.message || '')
              setFileKeywords(ev.file_keywords || [])
              setDetailKeywords(ev.detail_keywords || [])
              setRagPhase('intent')
              break

            case 'candidates': {
              const items = ev.items || []
              setCandidates(items)
              // 초기 scanState 모두 idle
              const initStates = {}
              items.forEach(src => { initStates[src.trichef_id || src.file_name] = 'idle' })
              setScanStates(initStates)
              setScanChunks({})
              setRagPhase('candidates')
              // 검색 기록 저장
              fetch(`${API_BASE}/api/history`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ query: q, method: 'aimode', result_count: items.length }),
              }).then(() => window.dispatchEvent(new Event('history-updated'))).catch(() => {})
              break
            }

            case 'scanning':
              setScanStates(prev => ({
                ...prev,
                [ev.file_id]: 'scanning',
              }))
              setRagPhase('scanning')
              break

            case 'scan_result':
              setScanStates(prev => ({
                ...prev,
                [ev.file_id]: ev.found ? 'found' : 'not_found',
              }))
              if (ev.found && ev.chunks?.length) {
                setScanChunks(prev => ({ ...prev, [ev.file_id]: ev.chunks }))
              }
              setScannedCount(prev => prev + 1)
              if (ev.found) setFoundCount(prev => prev + 1)
              break

            case 'selected':
              setSelectedSources(ev.sources || [])
              setRagPhase('selected')
              break

            case 'token':
              setAnswer(prev => prev + (ev.text || ''))
              setRagPhase('answering')
              break

            case 'done':
              if (ev.answer) setAnswer(ev.answer)
              setRagDone(true)
              setRagPhase('done')
              break

            case 'error':
              setAiError(ev.message || '오류 발생')
              break
          }
        }
      }
    } catch (e) {
      if (e.name !== 'AbortError') {
        setAiError(e.message || '연결 오류')
      }
    } finally {
      setStreaming(false)
    }
  }, [topK])

  // ── doSearch ─────────────────────────────────────────────────
  const doSearch = (q) => {
    if (!q.trim() || searchTransitioning) return
    setQuery(q)
    setInputValue(q)

    if (view === 'home') {
      setHomeExiting(true)
      setTimeout(() => {
        setHomeExiting(false)
        setResultsReady(false)
        setView('results')
        window.history.pushState({ view: 'results' }, '')
        requestAnimationFrame(() => setResultsReady(true))
        runRAG(q)
      }, 420)
    } else {
      setView('results')
      runRAG(q)
    }
  }

  doSearchRef.current = doSearch
  useEffect(() => { doSearchRef.current = doSearch })

  const handleSearch   = (e) => { e?.preventDefault(); doSearch(inputValue) }
  const handleSelectFile = (file) => {
    setSelectedFile(file)
    setFileDetail(null)
    setDetailVisible(false)
    setView('detail')
    window.history.pushState({ view: 'detail' }, '')
    requestAnimationFrame(() => requestAnimationFrame(() => setDetailVisible(true)))
    const isAV = ['video', 'audio', 'movie', 'music'].includes(file.file_type)
    if (!isAV) {
      setDetailLoading(true)
      fetch(`${API_BASE}/api/files/detail?path=${encodeURIComponent(file.file_path)}`)
        .then(r => r.json()).then(d => { setFileDetail(d); setDetailLoading(false) })
        .catch(() => setDetailLoading(false))
    }
  }
  const handleBackToResults = () => { setDetailVisible(false); setTimeout(() => setView('results'), 320) }

  const handleNewConversation = useCallback(async () => {
    if (abortRef.current) abortRef.current.abort()
    const tid = window.__aimodeThreadId
    if (tid) {
      try { await fetch(`${API_BASE}/api/aimode/chat/${encodeURIComponent(tid)}`, { method: 'DELETE' }) } catch {}
    }
    try { localStorage.removeItem('aimode_thread_id') } catch {}
    window.__aimodeThreadId = null
    setStreaming(false)
    setRagPhase('idle')
    setIntentMessage('')
    setFileKeywords([])
    setDetailKeywords([])
    setCandidates([])
    setScanStates({})
    setScanChunks({})
    setScannedCount(0)
    setFoundCount(0)
    setSelectedSources([])
    setAnswer('')
    setAiError('')
    setRagDone(false)
    setSelectedFile(null)
    setFileDetail(null)
    setView('home')
    setInputValue('')
  }, [])

  const handleGoToSearch = () => {
    const rect = btnRef.current?.getBoundingClientRect()
    if (rect) setRipplePos({ x: `${rect.left + rect.width / 2}px`, y: `${rect.top + rect.height / 2}px` })
    setSearchTransitioning(true)
    setTimeout(() => navigate('/search'), 900)
  }

  // ── 렌더 ────────────────────────────────────────────────────
  return (
    <div className={view === 'home' ? 'overflow-hidden h-screen relative' : 'min-h-screen relative text-on-surface'}
      style={{
        background: view === 'home' ? AI.bg : '#0a0514',
        backgroundImage: view !== 'home'
          ? 'radial-gradient(circle at 2px 2px, rgba(109,40,217,0.08) 1px, transparent 0)'
          : undefined,
        backgroundSize: view !== 'home' ? '32px 32px' : undefined,
      }}>

      {/* 검색 모드 전환 오버레이 */}
      {searchTransitioning && (
        <div className="fixed inset-0 z-[9999] pointer-events-none overflow-hidden">
          <div className="portal-overlay absolute rounded-full"
            style={{ width: '80px', height: '80px', left: ripplePos.x, top: ripplePos.y,
              transform: 'translate(-50%, -50%)',
              background: 'radial-gradient(circle, #1c253e 0%, #0c1326 60%, #070d1f 100%)',
              boxShadow: '0 0 30px 10px rgba(133,173,255,0.15)' }} />
          {[0, 200].map((delay, i) => (
            <div key={i} className="portal-ring absolute rounded-full border border-[#85adff]/25"
              style={{ width: '160px', height: '160px', left: ripplePos.x, top: ripplePos.y,
                transform: 'translate(-50%, -50%)', animationDelay: `${delay}ms` }} />
          ))}
          <div className="portal-text absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 flex flex-col items-center gap-2">
            <span className="material-symbols-outlined text-[#a5aac2] text-4xl" style={{ fontVariationSettings: '"FILL" 1' }}>database</span>
            <span className="font-manrope uppercase tracking-[0.25em] text-base text-[#a5aac2]">검색 모드</span>
          </div>
        </div>
      )}

      {/* 사이드바 */}
      <SearchSidebar entranceOn={view === 'home' ? aiHomeEntranceOn : undefined} />

      {/* ════ HOME VIEW ════ */}
      {view === 'home' && (
        <main className={`${ml} relative flex h-full min-h-0 flex-col overflow-x-hidden overflow-y-auto bg-transparent transition-[margin] duration-300 pt-8`}>
          <div className="ai-home-orbit-bg pointer-events-none absolute inset-0 z-0 min-h-0"
            style={{ '--ai-orbit-assemble': `${AI_ORB_ASSEMBLE_SECONDS}s` }} aria-hidden />
          <div ref={orbSinkRef} className="absolute inset-0 z-0 min-h-0" aria-hidden>
            <AnimatedOrb
              layout="fill" colorMode="ai" hideCenterUI interactive={false}
              aiHoverFx pointScaleMul={1.45} particleCount={11000} size={720}
              assembleIntro assembleDuration={AI_ORB_ASSEMBLE_SECONDS}
              voiceLevelRef={orbVoiceRef}
            />
          </div>

          <div className={`pointer-events-none relative z-10 flex h-full min-h-0 w-full flex-col ${aiHomeEntranceOn ? 'main-search-entrance-on' : 'main-search-entrance-off'}`}>
            <div className="relative z-10 flex min-h-0 flex-1 flex-col items-center justify-center overflow-y-auto px-6 py-8 md:px-8">
              <div className="relative flex w-full max-w-lg flex-col items-center justify-center">
                <div className="relative z-10 flex w-full flex-col items-center gap-9 text-center md:gap-10">
                  <div className={`mse-hero-down pointer-events-auto max-w-lg shrink-0 transition-all duration-300 ${homeExiting ? 'opacity-0 -translate-y-6' : ''}`}>
                    <h2 className="font-headline inline-flex flex-wrap items-baseline justify-center gap-0 text-4xl font-semibold tracking-tight md:text-5xl lg:text-6xl">
                      <span className="font-headline inline-block bg-gradient-to-r from-[#5e5a52] from-[6%] via-[#b8b0a2] to-[#d4cec2] bg-clip-text text-transparent">B</span>
                      <span className="font-headline text-[#cbc4b6] drop-shadow-[0_1px_5px_rgba(18,16,14,0.18)]">eyond Smarte</span>
                      <span className="font-headline inline-block bg-gradient-to-r from-[#d4cec2] via-[#9e978a] to-[#45423c] to-[90%] bg-clip-text text-transparent">r</span>
                    </h2>
                  </div>
                  <form onSubmit={handleSearch}
                    className="mse-search-up group pointer-events-auto relative z-10 w-full max-w-[min(90vw,22rem)] shrink-0 md:max-w-[24rem]"
                    style={homeExiting ? { visibility: 'hidden' } : {}}>
                    <div className="pointer-events-none absolute -inset-[2px] rounded-full bg-gradient-to-r from-fuchsia-500/0 via-violet-400/25 to-fuchsia-500/0 opacity-0 blur-md transition-opacity duration-500 group-focus-within:opacity-100" />
                    <div className="relative flex items-center gap-2 rounded-full border border-violet-200/[0.14] bg-gradient-to-b from-violet-100/[0.09] to-violet-950/[0.28] px-1.5 py-1.5 shadow-[inset_0_1px_0_rgba(255,255,255,0.16),inset_0_-1px_0_rgba(0,0,0,0.22),0_10px_44px_rgba(32,12,58,0.5)] backdrop-blur-2xl transition-all duration-300 group-focus-within:border-violet-200/25">
                      <button type="button"
                        className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-violet-900 to-purple-600 text-violet-50 shadow-[0_0_20px_rgba(124,58,237,0.32),inset_0_1px_0_rgba(255,255,255,0.18)] transition-transform hover:from-violet-800 hover:to-purple-500 active:scale-90">
                        <span className="material-symbols-outlined text-[20px] font-bold">add</span>
                      </button>
                      <input type="text" value={inputValue} onChange={e => setInputValue(e.target.value)}
                        placeholder={listening ? '듣는 중…' : 'Anything you need'}
                        className="min-w-0 flex-1 border-none bg-transparent py-2 font-manrope text-sm text-violet-100/90 outline-none ring-0 placeholder:text-violet-300/45 md:py-2.5 md:text-base" />
                      <button type="button" onClick={toggleMic} aria-pressed={listening}
                        className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full border backdrop-blur-md transition-colors ${
                          listening
                            ? 'border-rose-400/35 bg-rose-950/40 text-rose-200 shadow-[0_0_16px_rgba(251,113,133,0.25)]'
                            : 'border-violet-300/18 bg-violet-950/35 text-violet-200/80 hover:border-violet-200/30'
                        }`}>
                        <span className="material-symbols-outlined text-[20px]">mic</span>
                      </button>
                    </div>
                  </form>
                </div>
              </div>
            </div>

            <div className="mse-search-up mse-search-up-delay-1 pointer-events-auto flex shrink-0 flex-col items-center justify-end px-6 pb-10 pt-2 md:px-8">
              <button ref={btnRef} onClick={handleGoToSearch} disabled={searchTransitioning}
                className="group flex items-center gap-3 rounded-full border border-white/10 bg-white/[0.06] px-8 py-3 text-sm font-bold uppercase tracking-widest text-neutral-400 transition-all duration-300 hover:border-white/20 hover:text-neutral-200 disabled:pointer-events-none"
                onMouseEnter={e => { e.currentTarget.style.boxShadow = '0 0 24px rgba(139, 92, 246, 0.15)' }}
                onMouseLeave={e => { e.currentTarget.style.boxShadow = 'none' }}>
                <span className="h-2 w-2 animate-pulse rounded-full bg-violet-500"
                  style={{ boxShadow: '0 0 6px rgba(139, 92, 246, 0.9)' }} />
                검색 모드로 전환
                <span className="material-symbols-outlined text-lg transition-transform group-hover:translate-x-1">arrow_forward</span>
              </button>
            </div>
          </div>
        </main>
      )}

      {/* ════ 공통 헤더 (results / detail) ════ */}
      {view !== 'home' && (
        <header className={`fixed top-8 ${leftEdge} right-0 z-40 bg-[#070d1f]/60 backdrop-blur-xl flex items-center px-8 h-16 gap-6 shadow-[0_4px_30px_rgba(172,138,255,0.1)] transition-[left] duration-300`}>
          <button onClick={() => { setView('home'); setInputValue('') }}
            className={`text-xl font-bold tracking-tighter bg-gradient-to-r from-violet-400 to-fuchsia-400 bg-clip-text text-transparent shrink-0 hover:opacity-70 transition-opacity ${!open ? 'ml-10' : ''}`}>
            Obsidian AI
          </button>

          <form onSubmit={handleSearch} className="flex-1">
            <div className="relative group flex items-center">
              <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-violet-400/50">search</span>
              <input ref={inputRef} autoFocus
                className="bg-transparent border-none focus:ring-0 w-full text-on-surface text-lg outline-none pl-9"
                style={{ caretColor: AI.accentLight }}
                placeholder="AI에게 질문하세요..."
                value={listening ? '' : inputValue}
                onChange={e => !listening && setInputValue(e.target.value)}
                readOnly={listening} />
              <button type="button" onClick={toggleMic}
                className={`shrink-0 transition-all duration-200 ${listening ? 'animate-pulse' : ''}`}
                style={{ color: listening ? AI.accentLight : 'rgba(139,92,246,0.4)' }}>
                <span className="material-symbols-outlined text-lg" style={listening ? { fontVariationSettings: '"FILL" 1' } : {}}>mic</span>
              </button>
            </div>
          </form>

          {view === 'detail' && (
            <button onClick={handleBackToResults}
              className="flex items-center gap-2 px-4 py-2 rounded-full border text-base font-bold transition-all shrink-0 text-on-surface-variant hover:text-on-surface"
              style={{ background: AI.card, borderColor: AI.border }}
              onMouseEnter={e => e.currentTarget.style.borderColor = AI.accentLight}
              onMouseLeave={e => e.currentTarget.style.borderColor = AI.border}>
              <span className="material-symbols-outlined text-lg">arrow_back</span>결과로
            </button>
          )}

          <button onClick={handleNewConversation} title="새 대화 시작"
            className="flex items-center gap-2 px-4 py-2 rounded-full border text-base font-bold transition-all shrink-0 text-on-surface-variant hover:text-on-surface"
            style={{ background: AI.card, borderColor: AI.border }}
            onMouseEnter={e => e.currentTarget.style.borderColor = AI.accentLight}
            onMouseLeave={e => e.currentTarget.style.borderColor = AI.border}>
            <span className="material-symbols-outlined text-lg">restart_alt</span>새 대화
          </button>

          <div className="absolute bottom-0 left-0 w-full h-[1px] opacity-30"
            style={{ background: `linear-gradient(to right, transparent, ${AI.accent}, transparent)` }} />
        </header>
      )}

      {/* ════ RESULTS VIEW ════ */}
      {view === 'results' && (
        <main className={`${ml} min-h-screen transition-[margin] duration-300`}
          style={{ paddingTop: '128px', opacity: resultsReady ? 1 : 0,
            transform: resultsReady ? 'translateY(0)' : 'translateY(24px)',
            transition: 'opacity 0.38s ease, transform 0.38s ease, margin 0.3s' }}>
          <div className="px-8 pb-12 pt-5 max-w-[1400px] mx-auto">

            {/* 쿼리 + 상태 */}
            <div className="mb-5">
              <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-widest border"
                style={{ background: 'rgba(109,40,217,0.1)', color: AI.accentLight, borderColor: AI.border }}>
                AI RAG
              </span>
              <h1 className="text-3xl font-extrabold tracking-tighter text-on-surface mt-1">{query}</h1>
              <div className="mt-2 flex items-center gap-2 text-sm text-on-surface-variant">
                {streaming
                  ? <>
                      <span className="material-symbols-outlined text-base animate-spin" style={{ color: AI.accent }}>progress_activity</span>
                      <span>
                        {ragPhase === 'intent'     && 'Qwen이 질문을 분석하는 중...'}
                        {ragPhase === 'candidates' && `${candidates.length}개 파일 발견 — 내용 스캔 준비 중...`}
                        {ragPhase === 'scanning'   && `파일 내용 스캔 중... (${scannedCount}/${candidates.length})`}
                        {ragPhase === 'selected'   && `${selectedSources.length}개 파일에서 관련 내용 발견 — 답변 생성 중...`}
                        {ragPhase === 'answering'  && '답변 생성 중...'}
                      </span>
                    </>
                  : aiError
                    ? <span className="text-red-400">{aiError}</span>
                    : ragDone
                      ? <span><span className="font-bold" style={{ color: AI.accentLight }}>{selectedSources.length}개</span> 파일에서 답변을 생성했습니다.</span>
                      : null
                }
              </div>
            </div>

            {/* 의도 메시지 박스 */}
            <IntentBox
              message={intentMessage}
              fileKeywords={fileKeywords}
              detailKeywords={detailKeywords}
              visible={!!intentMessage}
            />

            {/* 스캔 진행 바 */}
            {(ragPhase === 'scanning' || (candidates.length > 0 && scannedCount > 0)) && (
              <ScanProgressBar
                total={candidates.length}
                scanned={scannedCount}
                found={foundCount}
              />
            )}

            {/* 후보 파일 카드 그리드 */}
            {candidates.length > 0 && (
              <div className="grid gap-4 mb-6"
                style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))' }}>
                {candidates.map((src, i) => {
                  const fid   = src.trichef_id || src.file_name || String(i)
                  const state = scanStates[fid] || 'idle'
                  const cks   = scanChunks[fid] || []
                  return (
                    <CandidateCard
                      key={fid}
                      source={src}
                      index={i}
                      scanState={state}
                      chunks={cks}
                      onClick={handleSelectFile}
                    />
                  )
                })}
              </div>
            )}

            {/* 답변 패널 */}
            {(answer || ragPhase === 'answering' || ragPhase === 'done') && (
              <AnswerPanel
                answer={answer}
                streaming={streaming && ragPhase === 'answering'}
                sources={selectedSources}
                done={ragDone}
                onClickSource={handleSelectFile}
              />
            )}

          </div>
        </main>
      )}

      {/* ════ DETAIL VIEW ════ */}
      {view === 'detail' && selectedFile && (
        <main className={`${ml} min-h-screen transition-[margin] duration-300`}
          style={{ paddingTop: '128px' }}>
          <div className={`max-w-4xl mx-auto px-8 pb-12 transition-all duration-300 ${detailVisible ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-8'}`}>
            {/* 파일 헤더 */}
            <div className="rounded-2xl border mb-6 overflow-hidden" style={{ background: AI.card, borderColor: AI.border }}>
              <div className="px-6 py-4 flex items-center gap-4" style={{ background: 'rgba(109,40,217,0.1)' }}>
                <div className="w-12 h-12 rounded-xl flex items-center justify-center"
                  style={{ background: 'linear-gradient(135deg, #6d28d9, #7c3aed)' }}>
                  <span className="material-symbols-outlined text-white text-2xl"
                    style={{ fontVariationSettings: '"FILL" 1' }}>
                    {getTypeMeta(selectedFile.file_type).icon}
                  </span>
                </div>
                <div className="flex-1 min-w-0">
                  <h2 className="text-lg font-bold text-on-surface truncate">{selectedFile.file_name}</h2>
                  <p className="text-xs text-on-surface-variant/60 font-mono truncate mt-0.5">{selectedFile.file_path}</p>
                </div>
                <div className="text-right shrink-0">
                  <div className="text-xl font-bold" style={{ color: AI.accentLight }}>
                    {((selectedFile.confidence ?? 0) * 100).toFixed(1)}%
                  </div>
                  <div className="text-xs text-on-surface-variant">신뢰도</div>
                </div>
              </div>

              {/* AV 플레이어 */}
              {['video', 'audio', 'movie', 'music'].includes(selectedFile.file_type) && (
                <AVDetailContent result={selectedFile} />
              )}

              {/* 이미지 */}
              {selectedFile.file_type === 'image' && selectedFile.preview_url && (
                <div className="flex items-center justify-center p-6" style={{ background: '#0b0515' }}>
                  <img src={`${API_BASE}${selectedFile.preview_url}`} alt={selectedFile.file_name}
                    className="max-w-full max-h-[400px] object-contain rounded-xl" />
                </div>
              )}

              {/* Doc 정보 */}
              {selectedFile.file_type === 'doc' && (
                <div className="px-6 py-4">
                  {detailLoading ? (
                    <div className="flex items-center gap-2 text-on-surface-variant">
                      <span className="material-symbols-outlined animate-spin">progress_activity</span>
                      상세 정보 로드 중...
                    </div>
                  ) : fileDetail ? (
                    <div className="text-sm text-on-surface-variant space-y-1">
                      {Object.entries(fileDetail).slice(0, 8).map(([k, v]) => (
                        <div key={k} className="flex gap-2">
                          <span className="text-on-surface-variant/50 shrink-0 w-24">{k}</span>
                          <span className="text-on-surface/80 truncate">{String(v)}</span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-sm text-on-surface-variant/50">상세 정보 없음</p>
                  )}
                </div>
              )}
            </div>

            {/* 매칭 청크 */}
            {(() => {
              const fid = selectedFile.trichef_id || selectedFile.file_name
              const cks = scanChunks[fid]
              if (!cks || cks.length === 0) return null
              return (
                <div className="rounded-2xl border mb-6 overflow-hidden" style={{ background: AI.card, borderColor: '#10b981' }}>
                  <div className="px-5 py-3 flex items-center gap-2"
                    style={{ background: 'rgba(16,185,129,0.1)', borderBottom: '1px solid rgba(16,185,129,0.2)' }}>
                    <span className="material-symbols-outlined text-emerald-400 text-base">find_in_page</span>
                    <span className="text-sm font-bold text-emerald-400">매칭된 내용 ({cks.length}개)</span>
                  </div>
                  <div className="p-4 space-y-3">
                    {cks.map((chunk, i) => (
                      <div key={i} className="px-3 py-2 rounded-lg text-sm text-on-surface/80 leading-relaxed"
                        style={{ background: 'rgba(16,185,129,0.05)', border: '1px solid rgba(16,185,129,0.15)' }}>
                        ...{chunk}...
                      </div>
                    ))}
                  </div>
                </div>
              )
            })()}

            {/* 답변 (detail에서도 보여줌) */}
            {answer && (
              <AnswerPanel
                answer={answer}
                streaming={false}
                sources={selectedSources}
                done={ragDone}
                onClickSource={handleSelectFile}
              />
            )}
          </div>
        </main>
      )}

      {/* scan-line CSS */}
      <style>{`
        @keyframes scanLine {
          0%   { transform: translateY(-100%); opacity: 0.8; }
          100% { transform: translateY(100%);  opacity: 0.3; }
        }
        .scan-line {
          position: absolute;
          top: 0; left: 0; right: 0;
          height: 40%;
          background: linear-gradient(to bottom, transparent, rgba(139,92,246,0.4), transparent);
          animation: scanLine 1.2s ease-in-out infinite;
        }
      `}</style>
    </div>
  )
}
