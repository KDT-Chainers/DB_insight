import { useState, useRef, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
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

// ── 검색 API ────────────────────────────────────────────
async function searchFiles(query, topK = 20) {
  const res = await fetch(`${API_BASE}/api/search?q=${encodeURIComponent(query)}&top_k=${topK}`)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const data = await res.json()
  if (data.error) throw new Error(data.error)
  const results = data.results ?? []
  // confidence 정규화: confidence 없으면 similarity 사용
  return results.map(r => ({
    ...r,
    confidence: r.confidence ?? r.similarity ?? 0,
    similarity:  r.similarity  ?? r.confidence ?? 0,
    segments:    r.segments    ?? [],
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

// ── 점수 바 (admin.html scoreBarsHtml 대응) ─────────────
function ScoreBar({ label, value, colorClass }) {
  const pct = value != null ? Math.min(Math.max(value * 100, 0), 100) : null
  return (
    <div className="flex items-center gap-1.5">
      <span className="w-10 shrink-0 text-[10px] text-on-surface-variant/50 font-mono">{label}</span>
      <div className="flex-1 h-[5px] bg-surface-container-highest rounded-full border border-outline-variant/15 overflow-hidden">
        {pct != null && (
          <div className={`h-full ${colorClass} rounded-full`} style={{ width: `${pct}%` }} />
        )}
      </div>
      <span className="w-8 shrink-0 text-right text-[10px] text-on-surface-variant/70 font-mono">
        {value != null ? value.toFixed(2) : '—'}
      </span>
    </div>
  )
}

// ── 결과 카드 (admin.html card / avCard 구조 대응) ────────
function ResultCard({ result, rank, onClick }) {
  const meta       = getTypeMeta(result.file_type)
  const conf       = result.confidence ?? result.similarity ?? 0
  const confPct    = Math.round(conf * 100)
  const isAV       = result.file_type === 'video' || result.file_type === 'audio'
  const hasPreview = (result.file_type === 'image' || result.file_type === 'doc') && result.preview_url
  const [imgError, setImgError] = useState(false)
  const playerRef  = useRef(null)

  // 점수 필드
  const dense   = result.dense   ?? null
  const lexical = result.lexical ?? null
  const asf     = result.asf     ?? null
  const zScore  = result.z_score ?? null
  const rerank  = result.rerank  ?? null

  // 신뢰도 색상
  const confCls = conf >= 0.8 ? 'text-emerald-400' : conf >= 0.3 ? 'text-primary' : 'text-red-400'

  // AV 스트림 URL
  const streamUrl = isAV ? avStreamUrl(result) : null

  // 세그먼트
  const segments = result.segments ?? []
  const topSegs  = segments.slice(0, 5)
  const topText  = topSegs[0]
    ? (topSegs[0].preview || topSegs[0].text || topSegs[0].caption || '')
    : ''

  const seekTo = (t) => {
    const p = playerRef.current
    if (!p) return
    p.currentTime = t
    p.play().catch(() => {})
  }

  // rerank: logit → sigmoid
  const rerankPct = rerank != null ? 1 / (1 + Math.exp(-rerank)) : null

  return (
    <div className="flex-none w-[420px] snap-start">
      <div
        onClick={isAV ? undefined : onClick}
        className={`bg-surface-container-high rounded-[1.5rem] overflow-hidden shadow-[0_20px_50px_rgba(0,0,0,0.3)] border border-outline-variant/5 relative transition-all
          ${isAV ? '' : 'cursor-pointer hover:border-primary/20 hover:shadow-primary/10'}`}
      >
        {/* 랭크 배지 */}
        <div className="absolute top-2 left-2 z-20 px-1.5 py-0.5 rounded bg-black/70 text-white text-[10px] font-bold leading-none">
          #{rank}
        </div>

        {/* ── AV: 인라인 플레이어 ── */}
        {isAV && (
          <div className="w-full bg-black/80" onClick={e => e.stopPropagation()}>
            {result.file_type === 'video' ? (
              <video
                ref={playerRef}
                src={streamUrl}
                controls
                preload="metadata"
                className="w-full max-h-[200px] object-contain"
                onError={() => {}}
              />
            ) : (
              <div className="flex flex-col items-center justify-center px-4 pt-8 pb-4 gap-3">
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
        )}

        {/* ── 이미지·문서: 썸네일 ── */}
        {!isAV && (
          <div className={`relative h-[180px] flex items-center justify-center overflow-hidden
            ${hasPreview && !imgError ? 'bg-black' : `bg-gradient-to-br ${meta.grad}`}`}>
            {hasPreview && !imgError ? (
              <img
                src={`${API_BASE}${result.preview_url}`}
                alt={result.file_name}
                className="w-full h-full object-contain"
                onError={() => setImgError(true)}
              />
            ) : (
              <span className="material-symbols-outlined text-white/20 text-[64px]" style={{ fontVariationSettings: '"FILL" 1' }}>{meta.icon}</span>
            )}
            <div className="absolute inset-0 bg-gradient-to-t from-black/70 to-transparent pointer-events-none" />
          </div>
        )}

        {/* ── 바디 ── */}
        <div className="p-4 space-y-3">

          {/* 배지 */}
          <div className="flex flex-wrap gap-1.5">
            <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase border ${meta.color} bg-white/5 border-white/10`}>
              {meta.label}
            </span>
            {isAV && (
              <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase border text-on-surface-variant/70 bg-white/5 border-white/10">
                세그 {segments.length}
              </span>
            )}
          </div>

          {/* 파일명 */}
          <div className="text-sm font-bold text-on-surface truncate" title={result.file_name}>
            {result.file_name}
          </div>

          {/* 경로 */}
          <div className="text-[10px] font-mono text-on-surface-variant/40 truncate" title={result.file_path}>
            {result.file_path}
          </div>

          {/* 메트릭 그리드 (6칸 2열) */}
          <div className="grid grid-cols-3 gap-1">
            {[
              ['신뢰도', `${confPct}%`,                    confCls],
              ['dense',   dense   != null ? dense.toFixed(3)   : '—', 'text-on-surface'],
              ['lexical', lexical != null ? lexical.toFixed(3) : '—', 'text-on-surface'],
              ['ASF',     asf     != null ? asf.toFixed(3)     : '—', 'text-on-surface'],
              ['rerank',  rerank  != null ? rerank.toFixed(2)  : '—', 'text-on-surface'],
              ['z',       zScore  != null ? zScore.toFixed(2)  : '—', 'text-on-surface'],
            ].map(([k, v, cls]) => (
              <div key={k} className="bg-surface-container-highest/40 rounded-lg px-2 py-1.5">
                <div className="text-[9px] text-on-surface-variant/40 uppercase tracking-wider mb-0.5">{k}</div>
                <div className={`text-xs font-bold font-mono ${cls}`}>{v}</div>
              </div>
            ))}
          </div>

          {/* 점수 바 */}
          <div className="space-y-1">
            <ScoreBar label="dense"  value={dense}      colorClass="bg-gradient-to-r from-emerald-600 to-emerald-400" />
            <ScoreBar label="lex"    value={lexical}    colorClass="bg-gradient-to-r from-blue-600 to-blue-400" />
            <ScoreBar label="asf"    value={asf}        colorClass="bg-gradient-to-r from-violet-600 to-violet-400" />
            <ScoreBar label="rerank" value={rerankPct}  colorClass="bg-gradient-to-r from-orange-600 to-orange-400" />
          </div>

          {/* AV: 세그먼트 버튼 + 최상위 발췌 */}
          {isAV ? (
            <>
              {topSegs.length > 0 && (
                <div className="flex flex-wrap gap-1" onClick={e => e.stopPropagation()}>
                  {topSegs.map((s, i) => {
                    const t0 = s.start ?? s.start_sec ?? 0
                    const t1 = s.end   ?? s.end_sec   ?? 0
                    const sc = s.score ?? 0
                    return (
                      <button
                        key={i}
                        onClick={() => seekTo(t0)}
                        title={s.text || s.caption || ''}
                        className="px-2 py-0.5 rounded-full text-[10px] font-mono bg-surface-container-highest border border-outline-variant/20 hover:border-primary/40 hover:bg-primary/10 text-on-surface-variant hover:text-primary transition-all"
                      >
                        {fmtTime(t0)}-{fmtTime(t1)} · {sc.toFixed(3)}
                      </button>
                    )
                  })}
                </div>
              )}
              {topText && (
                <p className="text-[11px] text-on-surface-variant/70 leading-relaxed line-clamp-2">
                  {topText}
                </p>
              )}
            </>
          ) : (
            /* 이미지·문서: 스니펫 발췌 */
            result.snippet ? (
              <p className="text-[11px] text-on-surface-variant/70 leading-relaxed line-clamp-2">
                {result.snippet}
              </p>
            ) : null
          )}

          {/* 하단 액션 (이미지·문서) */}
          {!isAV && (
            <div className="pt-2 border-t border-outline-variant/10 flex justify-end">
              <span className="text-xs font-bold text-primary flex items-center gap-1">
                열기 <span className="material-symbols-outlined text-base">arrow_forward</span>
              </span>
            </div>
          )}
        </div>
      </div>
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

// ── 메인 컴포넌트 ────────────────────────────────────────
export default function MainSearch() {
  const navigate = useNavigate()
  const { open } = useSidebar()

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
      const data = await searchFiles(q)
      setResults(data)
    } catch (e) {
      setSearchError(e.message)
      setResults([])
    } finally {
      setSearching(false)
    }
  }, [])

  const doSearch = (q) => {
    if (!q.trim() || aiTransitioning) return
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

  const handleBackToResults = () => { setDetailVisible(false); setTimeout(() => setView('results'), 320) }

  const handleGoToAI = () => {
    const rect = btnRef.current?.getBoundingClientRect()
    if (rect) setRipplePos({ x: `${rect.left + rect.width / 2}px`, y: `${rect.top + rect.height / 2}px` })
    setAiTransitioning(true)
    setTimeout(() => navigate('/ai'), 900)
  }

  return (
    <div className={view === 'home' ? 'overflow-hidden h-screen grid-bg relative' : 'min-h-screen relative bg-background text-on-surface'}
      style={view !== 'home' ? { backgroundImage: 'radial-gradient(circle at 2px 2px, rgba(65,71,91,0.15) 1px, transparent 0)', backgroundSize: '32px 32px' } : {}}>

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
                  <button type="button" className="w-12 h-12 rounded-full bg-gradient-to-r from-primary to-secondary flex items-center justify-center text-on-primary-fixed shadow-lg active:scale-90 transition-transform shrink-0">
                    <span className="material-symbols-outlined font-bold">add</span>
                  </button>
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

              <div className="mt-10 flex justify-center" style={homeExiting ? { visibility: 'hidden' } : {}}>
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
          <button onClick={() => { setView('home'); setInputValue(''); setResults([]) }}
            className={`text-lg font-bold tracking-tighter bg-gradient-to-r from-blue-300 to-purple-400 bg-clip-text text-transparent shrink-0 hover:opacity-70 transition-opacity ${!open ? 'ml-10' : ''}`}>
            DB_insight
          </button>

          <form onSubmit={handleSearch} className="flex-1">
            <div className={`flex items-center rounded-full border px-4 py-2 gap-3 transition-all
              ${listening ? 'bg-red-500/5 border-red-400/50 shadow-[0_0_15px_rgba(248,113,113,0.15)]' : 'bg-surface-container-high border-outline-variant/20 focus-within:border-primary/50'}`}>
              <span className={`material-symbols-outlined text-lg ${listening ? 'text-red-400' : 'text-primary'}`}>{listening ? 'mic' : 'search'}</span>
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
            </div>
          </form>

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
                <span className="px-2 py-0.5 rounded text-lg font-bold bg-primary/10 text-primary uppercase tracking-widest border border-primary/20">현재 쿼리</span>
                <h1 className="text-4xl font-extrabold tracking-tighter text-on-surface">{query}</h1>
                {searching
                  ? <p className="text-on-surface-variant flex items-center gap-2">
                      <span className="material-symbols-outlined text-primary text-lg animate-spin">progress_activity</span>검색 중...
                    </p>
                  : searchError
                    ? <p className="text-red-400 text-lg">{searchError}</p>
                    : <p className="text-on-surface-variant">로컬 보관소에서 <span className="text-primary font-bold">{results.length}건</span>을 찾았습니다.</p>
                }
              </div>
              <div className="flex gap-3">
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

            {/* 결과 카드 */}
            {!searching && results.length > 0 && (
              <div className="flex gap-6 overflow-x-auto no-scrollbar pb-12 snap-x snap-mandatory">
                {results.map((r, i) => (
                  <ResultCard key={r.file_path + i} result={r} rank={i + 1} onClick={() => handleSelectFile(r)} />
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
                      /* 이미지/문서: 실제 미리보기 */
                      <div className="flex-1 flex flex-col items-center justify-center px-8 py-6 gap-4 overflow-hidden">
                        <div className="w-full flex-1 flex items-center justify-center min-h-0">
                          <img
                            src={`${API_BASE}${selectedFile.preview_url}`}
                            alt={selectedFile.file_name}
                            className="max-w-full max-h-full object-contain rounded-xl shadow-2xl border border-outline-variant/10"
                            style={{ maxHeight: '340px' }}
                          />
                        </div>
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
