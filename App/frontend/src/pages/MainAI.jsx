import { useState, useRef, useEffect, useCallback } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import SearchSidebar from '../components/SearchSidebar'
import { useSidebar } from '../context/SidebarContext'
import { API_BASE } from '../api'

// ── 파일 타입 메타 (MainSearch 동일) ─────────────────────────
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

// ── AI 색상 상수 ─────────────────────────────────────────────
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

// ── 결과 카드 (AI 색상) ───────────────────────────────────────
function AiResultCard({ result, rank, onClick }) {
  const isAV       = result.file_type === 'video' || result.file_type === 'audio'
  const hasPreview = (result.file_type === 'image' || result.file_type === 'doc') && result.preview_url
  const [imgError, setImgError] = useState(false)
  const playerRef  = useRef(null)

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

  const domainLabel = result.trichef_domain ?? result.file_type ?? 'unknown'
  const segments    = result.segments ?? []
  const streamUrl   = isAV ? avStreamUrl(result) : null

  const DOMAIN_CLS = {
    image:    'bg-[#065f46] text-[#d1fae5] border-[#10b981]',
    doc_page: 'bg-[#5b21b6] text-[#ede9fe] border-[#8b5cf6]',
    movie:    'bg-[#7c2d12] text-[#ffedd5] border-[#ea580c]',
    music:    'bg-[#1e40af] text-[#dbeafe] border-[#3b82f6]',
  }

  const seekTo = (t) => { const p = playerRef.current; if (!p) return; p.currentTime = t; p.play().catch(() => {}) }

  return (
    <div
      onClick={isAV ? undefined : onClick}
      className={`rounded-[10px] overflow-hidden flex flex-col relative transition-all duration-200
        ${isAV ? '' : 'cursor-pointer hover:-translate-y-0.5'}`}
      style={{
        background: AI.card,
        border: `1px solid ${AI.border}`,
      }}
      onMouseEnter={e => { if (!isAV) e.currentTarget.style.borderColor = AI.borderHover; e.currentTarget.style.boxShadow = AI.glow }}
      onMouseLeave={e => { e.currentTarget.style.borderColor = AI.border; e.currentTarget.style.boxShadow = 'none' }}
    >
      {/* 랭크 배지 — violet */}
      <div className="absolute top-2 left-2 z-20 text-white min-w-[32px] h-7 px-2 rounded-full flex items-center justify-center font-bold text-xs"
        style={{ background: AI.rankBg, boxShadow: '0 0 10px rgba(139,92,246,0.5)' }}>
        #{rank}
      </div>

      {/* AV: 플레이어 */}
      {isAV && (
        <div className="px-3 py-2 border-b" style={{ background: '#0b0515', borderColor: AI.border }}
          onClick={e => e.stopPropagation()}>
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
        <div className="relative h-[200px] flex items-center justify-center overflow-hidden"
          style={{ background: '#0b0515' }}>
          {hasPreview && !imgError ? (
            <img
              src={`${API_BASE}${result.preview_url}`}
              alt={result.file_name}
              className="max-w-full max-h-full object-contain"
              onError={() => setImgError(true)}
            />
          ) : (
            <span className="text-[#6b21a8] text-xs">{domainLabel}</span>
          )}
        </div>
      )}

      {/* 바디 */}
      <div className="p-3 flex flex-col gap-2 flex-1 text-[#e2e8f0]">
        {/* 도메인 배지 */}
        <div className="flex gap-1 flex-wrap">
          <span className={`text-[10px] px-2 py-0.5 rounded-full border ${DOMAIN_CLS[domainLabel] ?? 'bg-[#1e1040] text-[#a78bfa] border-[#7c3aed]'}`}>
            {domainLabel}
          </span>
          {isAV && (
            <span className="text-[10px] px-2 py-0.5 rounded-full border border-[#4c1d95] bg-[#2e1065] text-[#c4b5fd]">
              세그 {segments.length}
            </span>
          )}
        </div>

        {/* 파일명 + 페이지 */}
        <div className="flex items-start gap-2 flex-wrap">
          <div className="font-semibold text-[13px] text-[#f1f5f9] break-all leading-snug flex-1 min-w-0">
            {result.file_name}
          </div>
          {result.page_num != null && (
            <span className="shrink-0 text-[10px] px-1.5 py-0.5 rounded bg-[#2e1065] text-[#c4b5fd] border border-[#7c3aed]/40 font-mono whitespace-nowrap">
              {result.page_num}p
            </span>
          )}
        </div>

        {/* 경로 */}
        <div className="text-[11px] text-[#6b7280] break-all font-mono">
          {result.file_path || result.trichef_id}
        </div>

        {/* 3지표 */}
        <div className="grid grid-cols-3 gap-1.5">
          {[
            { label: '신뢰도', value: `${confPct}%`, cls: 'text-[#a78bfa]' },
            { label: '정확도', value: acc,            cls: 'text-[#60a5fa]' },
            { label: '유사도', value: sim,            cls: 'text-[#c4b5fd]' },
          ].map(({ label, value, cls }) => (
            <div key={label} className="rounded-md p-1.5 text-center border"
              style={{ background: '#0b0515', borderColor: AI.border }}>
              <div className="text-[10px] text-[#6b7280] uppercase tracking-wide">{label}</div>
              <div className={`text-[15px] font-bold mt-0.5 ${cls}`}>{value}</div>
            </div>
          ))}
        </div>

        {/* AV: 세그먼트 */}
        {isAV && segments.length > 0 && (() => {
          const topStart = segments[0]?.start ?? segments[0]?.start_sec ?? null
          return (
            <div onClick={e => e.stopPropagation()}>
              {topStart != null && (
                <button onClick={() => seekTo(topStart)}
                  className="text-[11px] px-3 py-1 text-white rounded font-semibold mb-1.5 hover:brightness-110"
                  style={{ background: AI.accentDark }}>
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
                      className="flex items-center gap-2 px-2 py-1 rounded text-[11px] text-left w-full transition-colors"
                      style={{ background: '#0b0515', border: `1px solid ${AI.border}` }}
                      onMouseEnter={e => e.currentTarget.style.borderColor = AI.accentLight}
                      onMouseLeave={e => e.currentTarget.style.borderColor = AI.border}>
                      <span className="text-[#7dd3fc] font-mono font-semibold whitespace-nowrap min-w-[112px]">{fmtTime(t0)} ~ {fmtTime(t1)}</span>
                      <span className="text-[#a78bfa] font-mono whitespace-nowrap">s={sc.toFixed(3)}</span>
                      <span className="text-[#94a3b8] flex-1 overflow-hidden text-ellipsis whitespace-nowrap">{preview}</span>
                    </button>
                  )
                })}
              </div>
            </div>
          )
        })()}
      </div>
    </div>
  )
}

// ── AV 상세 플레이어 ─────────────────────────────────────────
function AVDetailContent({ result }) {
  const isVideo   = result.file_type === 'video'
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

// ── 도메인 색상/레이블 ─────────────────────────────────────────
const DOMAIN_META = {
  image:    { label: '이미지', icon: 'image',       bg: '#064e3b', text: '#d1fae5', border: '#10b981' },
  doc_page: { label: '문서',   icon: 'description', bg: '#4c1d95', text: '#ede9fe', border: '#8b5cf6' },
  movie:    { label: '동영상', icon: 'movie',       bg: '#7c2d12', text: '#ffedd5', border: '#ea580c' },
  music:    { label: '음성',   icon: 'volume_up',   bg: '#1e3a8a', text: '#dbeafe', border: '#3b82f6' },
  all:      { label: '전체',   icon: 'search',      bg: '#1e1b4b', text: '#c7d2fe', border: '#6366f1' },
}

// ── 미니 결과 카드 (단계별 미리보기) ──────────────────────────
function MiniResultPill({ item, rank }) {
  const fname    = item.file_name || item.id || '?'
  const conf     = item.confidence ?? 0
  const dom      = item.domain ?? 'image'
  const hasThumb = dom === 'image' && item.preview_url
  const [imgErr, setImgErr] = useState(false)
  const dc = DOMAIN_META[dom] ?? DOMAIN_META.all

  return (
    <div className="shrink-0 rounded-lg overflow-hidden flex flex-col transition-all duration-150 hover:brightness-110"
      style={{ background: '#0b0515', border: `1px solid ${AI.border}`, width: '110px' }}>
      {/* 썸네일 */}
      {hasThumb && !imgErr ? (
        <div className="h-14 flex items-center justify-center bg-black/50 overflow-hidden">
          <img src={`${API_BASE}${item.preview_url}`} alt={fname}
            className="max-w-full max-h-full object-contain"
            onError={() => setImgErr(true)} />
        </div>
      ) : (
        <div className="h-9 flex items-center justify-center" style={{ background: `${dc.bg}55` }}>
          <span className="material-symbols-outlined text-sm" style={{ color: dc.border }}>{dc.icon}</span>
        </div>
      )}
      {/* 정보 */}
      <div className="px-2 py-1.5 flex flex-col gap-0.5">
        <span className="text-[9px] font-bold" style={{ color: AI.accentLight }}>#{rank} · {(conf*100).toFixed(0)}%</span>
        <span className="text-[9px] text-on-surface-variant/60 truncate" title={fname}>{fname}</span>
      </div>
    </div>
  )
}

// ── AI 탐색 과정 패널 ─────────────────────────────────────────
function AIIterationPanel({ iterationData, domainSelection, streaming, hasLLM }) {
  const [collapsed, setCollapsed] = useState(false)

  if (!iterationData.length && !streaming) return null

  const focusedCount = iterationData.filter(it => it.iteration > 0).length

  return (
    <div className="mb-6 rounded-xl overflow-hidden" style={{ border: `1px solid ${AI.border}`, background: AI.card }}>
      {/* 패널 헤더 */}
      <button
        onClick={() => setCollapsed(c => !c)}
        className="w-full flex items-center justify-between px-5 py-3 hover:brightness-110 transition-all"
        style={{ background: 'rgba(109,40,217,0.15)' }}
      >
        <div className="flex items-center gap-2.5">
          <span className="material-symbols-outlined text-lg" style={{ color: AI.accentLight, fontVariationSettings: '"FILL" 1' }}>
            {streaming ? 'psychology' : 'auto_awesome'}
          </span>
          <span className="text-sm font-bold" style={{ color: AI.accentLight }}>AI 탐색 과정</span>
          <span className="text-[10px] px-2 py-0.5 rounded-full font-bold"
            style={{ background: 'rgba(139,92,246,0.15)', color: AI.accentLight, border: `1px solid ${AI.border}` }}>
            {iterationData.length}단계
          </span>
          {hasLLM !== undefined && (
            <span className="text-[10px] px-2 py-0.5 rounded-full font-bold"
              style={{ background: hasLLM ? 'rgba(139,92,246,0.1)' : 'rgba(100,116,139,0.1)',
                       color: hasLLM ? AI.accentLight : '#94a3b8',
                       border: `1px solid ${hasLLM ? AI.border : 'rgba(100,116,139,0.15)'}` }}>
              {hasLLM ? '🤖 LLM' : '⚙️ 휴리스틱'}
            </span>
          )}
          {streaming && <span className="material-symbols-outlined text-base animate-spin" style={{ color: AI.accent }}>progress_activity</span>}
        </div>
        <span className="material-symbols-outlined text-sm text-on-surface-variant/50">
          {collapsed ? 'expand_more' : 'expand_less'}
        </span>
      </button>

      {!collapsed && (
        <div className="p-4 space-y-3">
          {iterationData.map((step, idx) => {
            const isGlobal = step.iteration === 0
            const dc = DOMAIN_META[step.domain] ?? DOMAIN_META.all

            return (
              <div key={idx}>
                {/* 도메인 선택 안내 배너 (전체→집중 전환 시) */}
                {!isGlobal && idx > 0 && iterationData[idx - 1]?.iteration === 0 && domainSelection && (
                  <div className="flex items-start gap-2 mb-2 px-3 py-2 rounded-lg"
                    style={{ background: 'rgba(109,40,217,0.08)', border: `1px dashed ${AI.border}` }}>
                    <span className="material-symbols-outlined text-sm shrink-0 mt-0.5" style={{ color: AI.accent }}>arrow_forward</span>
                    <div>
                      <span className="text-[11px] font-bold" style={{ color: AI.accentLight }}>
                        {dc.label} 도메인으로 집중합니다
                      </span>
                      <span className="text-[11px] text-on-surface-variant/50 ml-2">{domainSelection.reason}</span>
                    </div>
                  </div>
                )}

                {/* 단계 카드 */}
                <div className="rounded-xl overflow-hidden"
                  style={{ border: `1px solid rgba(109,40,217,0.15)`, background: '#080412' }}>

                  {/* 단계 헤더 */}
                  <div className="flex items-center gap-2 px-3 py-2"
                    style={{ background: 'rgba(109,40,217,0.07)', borderBottom: '1px solid rgba(109,40,217,0.1)' }}>
                    <div className="w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold text-white shrink-0"
                      style={{ background: step.done ? 'linear-gradient(135deg,#059669,#047857)' : isGlobal ? 'rgba(99,102,241,0.7)' : AI.rankBg }}>
                      {isGlobal ? '①' : step.iteration}
                    </div>
                    <span className="text-[11px] font-mono font-bold text-on-surface/80 flex-1 truncate">
                      "{step.query}"
                    </span>
                    <span className="text-[9px] px-1.5 py-0.5 rounded-full font-bold border shrink-0"
                      style={{ background: dc.bg, color: dc.text, borderColor: dc.border }}>
                      {dc.label}
                    </span>
                    <span className="text-[10px] text-on-surface-variant/40 shrink-0">{step.count ?? step.items?.length ?? 0}건</span>
                  </div>

                  {/* 결과 미리보기 카드 (top 3) */}
                  {step.items?.length > 0 && (
                    <div className="px-3 py-2.5 flex gap-2 overflow-x-auto"
                      style={{ scrollbarWidth: 'thin', scrollbarColor: `${AI.border} transparent` }}>
                      {step.items.slice(0, 5).map((item, i) => (
                        <MiniResultPill key={i} item={item} rank={i + 1} />
                      ))}
                      {step.items.length > 5 && (
                        <div className="shrink-0 flex items-center text-[10px] text-on-surface-variant/30 pl-1 whitespace-nowrap">
                          +{step.items.length - 5}건
                        </div>
                      )}
                    </div>
                  )}

                  {/* AI 사고 */}
                  {step.thought && (
                    <div className="px-3 py-2 flex items-start gap-2"
                      style={{ borderTop: '1px solid rgba(109,40,217,0.08)' }}>
                      <span className="material-symbols-outlined text-sm shrink-0 mt-0.5"
                        style={{ color: step.done ? '#10b981' : AI.accent, fontVariationSettings: '"FILL" 1' }}>
                        {step.done ? 'check_circle' : 'psychology'}
                      </span>
                      <p className="text-[11px] text-on-surface-variant/65 leading-relaxed">{step.thought}</p>
                    </div>
                  )}
                </div>
              </div>
            )
          })}

          {/* 스트리밍 대기 표시 */}
          {streaming && (
            <div className="flex items-center gap-2 px-3 py-2 rounded-lg"
              style={{ border: `1px dashed ${AI.border}`, background: 'rgba(109,40,217,0.05)' }}>
              <span className="material-symbols-outlined text-sm animate-spin" style={{ color: AI.accentLight }}>progress_activity</span>
              <span className="text-[11px] text-on-surface-variant/40 animate-pulse">AI가 결과를 분석하는 중...</span>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── STT 훅 ───────────────────────────────────────────────────
function useSpeechRecognition({ onFinal }) {
  const [listening, setListening] = useState(false)
  const [interim,   setInterim]   = useState('')
  const recognitionRef = useRef(null)
  const latestRef      = useRef('')

  const start = useCallback(() => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition
    if (!SR) { alert('음성 인식 미지원'); return }
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
    r.onend   = () => { setListening(false); setInterim(''); const t = latestRef.current.trim(); latestRef.current = ''; if (t) onFinal(t) }
    r.onerror = () => { setListening(false); setInterim('') }
    recognitionRef.current = r; r.start()
  }, [onFinal])

  const stop   = useCallback(() => recognitionRef.current?.stop(), [])
  const toggle = useCallback(() => listening ? stop() : start(), [listening, start, stop])
  return { listening, interim, toggle }
}

// ── 메인 컴포넌트 ─────────────────────────────────────────────
export default function MainAI() {
  const navigate  = useNavigate()
  const location  = useLocation()
  const { open }  = useSidebar()

  const [view,         setView]         = useState('home')
  const [query,        setQuery]        = useState('')
  const [inputValue,   setInputValue]   = useState('')
  const [selectedFile, setSelectedFile] = useState(null)
  const [fileDetail,   setFileDetail]   = useState(null)
  const [detailLoading,setDetailLoading]= useState(false)

  // AI 에이전트 상태
  const [streaming,      setStreaming]      = useState(false)
  const [results,        setResults]        = useState([])
  const [iterationData,  setIterationData]  = useState([])   // [{iteration, query, domain, items, thought, done, count}]
  const [domainSelection,setDomainSelection]= useState(null) // {domain, reason}
  const [aiError,        setAiError]        = useState('')
  const [finalQuery,     setFinalQuery]     = useState('')
  const [hasLLM,         setHasLLM]         = useState(undefined)
  const [topK,         setTopK]         = useState(20)
  const [maxIter,      setMaxIter]      = useState(5)
  const abortRef = useRef(null)

  // 애니메이션
  const [homeExiting,  setHomeExiting]  = useState(false)
  const [resultsReady, setResultsReady] = useState(false)
  const [detailVisible,setDetailVisible]= useState(false)

  // 포털 전환
  const [searchTransitioning, setSearchTransitioning] = useState(false)
  const [ripplePos, setRipplePos] = useState({ x: '50%', y: '50%' })
  const btnRef    = useRef(null)
  const formRef   = useRef(null)
  const inputRef  = useRef(null)    // 검색창 포커스용

  // 뷰 변경 시 검색창 자동 포커스
  useEffect(() => {
    if (view === 'home' || view === 'results') {
      const t = setTimeout(() => inputRef.current?.focus(), 120)
      return () => clearTimeout(t)
    }
  }, [view])

  const ml       = open ? 'ml-64' : 'ml-0'
  const leftEdge = open ? 'left-64' : 'left-0'
  const sidebarPx= open ? 256 : 0

  // STT
  const doSearchRef = useRef(null)
  const { listening, interim, toggle: toggleMic } = useSpeechRecognition({
    onFinal: useCallback((text) => {
      setInputValue(text)
      setTimeout(() => doSearchRef.current?.(text), 80)
    }, []),
  })

  // 뒤로가기
  useEffect(() => {
    const handle = () => {
      setDetailVisible(false)
      if (view === 'detail')        setTimeout(() => setView('results'), 320)
      else if (view === 'results')  { setResultsReady(false); setView('home') }
    }
    window.addEventListener('popstate', handle)
    return () => window.removeEventListener('popstate', handle)
  }, [view])

  // 사이드바 검색 기록 클릭
  useEffect(() => {
    const q = location.state?.query
    if (q) { window.history.replaceState({}, ''); doSearchRef.current?.(q) }
  }, [location.state])

  // ── SSE 에이전트 실행 ────────────────────────────────────────
  const runAISearch = useCallback(async (q) => {
    // 이전 요청 취소
    if (abortRef.current) abortRef.current.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setStreaming(true)
    setResults([])
    setIterationData([])
    setDomainSelection(null)
    setAiError('')
    setFinalQuery(q)
    setHasLLM(undefined)

    try {
      const res = await fetch(`${API_BASE}/api/ai/search`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: q, topk: topK, max_iterations: maxIter }),
        signal: controller.signal,
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)

      const reader  = res.body.getReader()
      const decoder = new TextDecoder()
      let   buffer  = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop()

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          try {
            const ev = JSON.parse(line.slice(6))
            handleSSEEvent(ev)
          } catch {}
        }
      }
    } catch (e) {
      if (e.name !== 'AbortError') setAiError(e.message)
    } finally {
      setStreaming(false)
    }
  }, [topK, maxIter])

  const mapItem = (item) => {
    const isDocPage = item.domain === 'doc_page'
    return {
      file_path:      item.source_path || item.id,
      trichef_id:     item.id,
      file_name:      item.file_name || (item.id || '').split(/[/\\]/).pop(),
      page_num:       item.page_num ?? null,
      file_type:      item.domain === 'image' ? 'image'
                    : isDocPage ? 'doc'
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
  }

  const handleSSEEvent = (ev) => {
    switch (ev.type) {
      case 'info':
        setHasLLM(ev.has_llm)
        break

      case 'iteration_results':
        // 각 단계 결과 카드 저장/업데이트
        setIterationData(prev => {
          const idx = prev.findIndex(it => it.iteration === ev.iteration)
          const entry = {
            iteration: ev.iteration,
            query:     ev.query,
            domain:    ev.domain,
            items:     ev.items ?? [],
            count:     ev.items?.length ?? 0,
            thought:   '',
            done:      false,
          }
          if (idx >= 0) {
            const next = [...prev]
            next[idx] = { ...next[idx], ...entry }
            return next
          }
          return [...prev, entry]
        })
        break

      case 'domain_selected':
        setDomainSelection({ domain: ev.domain, reason: ev.reason })
        break

      case 'thought':
        // 마지막 focused 단계(iteration>0)의 thought 업데이트
        setIterationData(prev => {
          if (!prev.length) return prev
          const updated = [...prev]
          // 뒤에서부터 iteration>0인 항목 찾기
          for (let i = updated.length - 1; i >= 0; i--) {
            if (updated[i].iteration > 0) {
              updated[i] = { ...updated[i], thought: ev.text, done: ev.done }
              return updated
            }
          }
          return prev
        })
        break

      case 'results': {
        const mapped = (ev.items ?? []).map(mapItem)
        setResults(mapped)
        setFinalQuery(ev.final_query || ev.query)
        // 최종 history로 iterationData thought/done 동기화
        if (ev.history?.length) {
          setIterationData(prev => {
            const updated = [...prev]
            ev.history.forEach((h, hi) => {
              const idx = updated.findIndex(it => it.iteration === hi + 1)
              if (idx >= 0) {
                updated[idx] = { ...updated[idx], thought: h.thought, done: h.done, count: h.count }
              }
            })
            return updated
          })
        }
        break
      }

      case 'error':
        setAiError(ev.message || '오류 발생')
        break
    }
  }

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
        runAISearch(q)
      }, 420)
    } else {
      setView('results')
      runAISearch(q)
    }
  }

  useEffect(() => { doSearchRef.current = doSearch })

  const handleSearch  = (e) => { e?.preventDefault(); doSearch(inputValue) }

  const handleSelectFile = (file) => {
    setSelectedFile(file)
    setFileDetail(null)
    setDetailVisible(false)
    setView('detail')
    window.history.pushState({ view: 'detail' }, '')
    requestAnimationFrame(() => requestAnimationFrame(() => setDetailVisible(true)))
    const isAV = file.file_type === 'video' || file.file_type === 'audio'
    if (!isAV) {
      setDetailLoading(true)
      fetch(`${API_BASE}/api/files/detail?path=${encodeURIComponent(file.file_path)}`)
        .then(r => r.json()).then(d => { setFileDetail(d); setDetailLoading(false) })
        .catch(() => setDetailLoading(false))
    }
  }

  const handleBackToResults = () => { setDetailVisible(false); setTimeout(() => setView('results'), 320) }

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

      <SearchSidebar />

      {/* ════ HOME VIEW ════ */}
      {view === 'home' && (
        <main className={`${ml} h-full flex flex-col items-center justify-center p-8 relative transition-[margin] duration-300`}>
          {/* 배경 glow */}
          <div className="absolute top-1/4 left-1/3 w-[600px] h-[400px] rounded-full blur-[140px] pointer-events-none"
            style={{ background: 'rgba(109,40,217,0.2)' }} />
          <div className="absolute bottom-1/4 right-1/4 w-[500px] h-[400px] rounded-full blur-[120px] pointer-events-none"
            style={{ background: 'rgba(88,28,135,0.15)' }} />
          {/* 스캔라인 */}
          <div className="absolute inset-0 pointer-events-none"
            style={{ background: 'repeating-linear-gradient(0deg, transparent, transparent 3px, rgba(139,92,246,0.012) 3px, rgba(139,92,246,0.012) 4px)' }} />

          <div className="w-full max-w-4xl flex flex-col items-center z-10">
            <div className={`mb-12 text-center transition-all duration-300 ${homeExiting ? 'opacity-0 -translate-y-6' : 'opacity-100 translate-y-0'}`}>
              <h2 className="text-5xl md:text-6xl font-black tracking-tighter mb-4">
                <span className="text-on-surface">로컬 </span>
                <span style={{ background: 'linear-gradient(to right, #a78bfa, #c084fc, #e879f9)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>
                  AI 에이전트
                </span>
                <span style={{ color: AI.accentLight }}>.</span>
              </h2>
              <p className="text-on-surface-variant/70 text-lg max-w-xl mx-auto font-light">
                원하는 파일이 <span style={{ color: AI.accentLight, fontWeight: 700 }}>상위 3위</span> 안에 들 때까지 스스로 쿼리를 개선합니다.
              </p>
            </div>

            {/* 검색창 */}
            <form ref={formRef} onSubmit={handleSearch} className="w-full relative group"
              style={homeExiting ? { visibility: 'hidden' } : {}}>
              <div className="absolute -inset-[1px] rounded-full blur-sm opacity-0 group-focus-within:opacity-100 transition-opacity duration-500 pointer-events-none"
                style={{ background: 'linear-gradient(to right, rgba(109,40,217,0.6), rgba(192,38,211,0.3), rgba(109,40,217,0.6))' }} />
              <div className="relative rounded-full p-2 flex items-center gap-4 transition-all duration-300"
                style={{ background: 'rgba(5,3,12,0.75)', border: `1px solid rgba(109,40,217,0.4)`,
                  boxShadow: '0 0 40px rgba(109,40,217,0.12), inset 0 0 20px rgba(0,0,0,0.4)' }}>
                <button type="button" className="w-12 h-12 rounded-full flex items-center justify-center text-white active:scale-90 transition-transform"
                  style={{ background: AI.rankBg, boxShadow: '0 0 20px rgba(124,58,237,0.6)' }}>
                  <span className="material-symbols-outlined font-bold" style={{ fontVariationSettings: '"FILL" 1' }}>psychology</span>
                </button>
                <input
                  ref={inputRef}
                  type="text"
                  value={listening ? '' : inputValue}
                  onChange={(e) => !listening && setInputValue(e.target.value)}
                  placeholder={listening ? '' : 'AI에게 검색을 맡기세요...'}
                  className="flex-1 bg-transparent border-none focus:ring-0 text-on-surface font-manrope text-lg py-4 outline-none"
                  style={{ caretColor: AI.accentLight }}
                  readOnly={listening}
                />
                {listening && (
                  <div className="absolute left-20 right-20 flex items-center gap-3 pointer-events-none">
                    <span className="text-lg font-manrope truncate" style={{ color: AI.accentLight }}>{interim || '듣는 중...'}</span>
                    <div className="flex items-center gap-[3px] shrink-0">
                      {[0, 0.15, 0.3, 0.15, 0].map((delay, i) => (
                        <div key={i} className="w-[3px] rounded-full animate-bounce"
                          style={{ height: `${[12,20,28,20,12][i]}px`, animationDelay: `${delay}s`,
                            animationDuration: '0.8s', background: AI.accentLight }} />
                      ))}
                    </div>
                  </div>
                )}
                <button type="button" onClick={toggleMic}
                  className={`w-12 h-12 rounded-full flex items-center justify-center transition-all duration-200 shrink-0 ${listening ? 'animate-pulse' : ''}`}
                  style={{ background: listening ? 'rgba(139,92,246,0.2)' : 'rgba(139,92,246,0.05)',
                    color: listening ? AI.accentLight : 'rgba(139,92,246,0.6)' }}>
                  <span className="material-symbols-outlined" style={listening ? { fontVariationSettings: '"FILL" 1' } : {}}>mic</span>
                </button>
              </div>
            </form>

            {/* 설정 */}
            <div className="mt-4 flex items-center justify-center gap-3 text-xs flex-wrap text-on-surface-variant"
              style={homeExiting ? { visibility: 'hidden' } : {}}>
              <span className="opacity-50">결과 수</span>
              {[10, 20, 30].map(n => (
                <button key={n} type="button" onClick={() => setTopK(n)}
                  className="px-3 py-1 rounded-full border transition-colors"
                  style={topK === n
                    ? { borderColor: AI.accent, color: AI.accentLight, background: 'rgba(139,92,246,0.1)' }
                    : { borderColor: 'rgba(109,40,217,0.2)', color: 'inherit' }}>
                  {n}
                </button>
              ))}
              <div className="w-px h-4 opacity-20" style={{ background: AI.accent }} />
              <span className="opacity-50">최대 시도</span>
              {[2, 3, 5].map(n => (
                <button key={n} type="button" onClick={() => setMaxIter(n)}
                  className="px-3 py-1 rounded-full border transition-colors"
                  style={maxIter === n
                    ? { borderColor: AI.accent, color: AI.accentLight, background: 'rgba(139,92,246,0.1)' }
                    : { borderColor: 'rgba(109,40,217,0.2)', color: 'inherit' }}>
                  {n}
                </button>
              ))}
            </div>

            {/* 검색 모드 전환 버튼 */}
            <div className="mt-8 flex justify-center" style={homeExiting ? { visibility: 'hidden' } : {}}>
              <button ref={btnRef} onClick={handleGoToSearch} disabled={searchTransitioning}
                className="px-8 py-3 rounded-full flex items-center gap-3 text-lg font-bold tracking-widest uppercase transition-all duration-300 group disabled:pointer-events-none"
                style={{ background: 'rgba(10,5,25,0.6)', border: '1px solid rgba(109,40,217,0.25)',
                  color: 'rgba(167,139,250,0.5)' }}
                onMouseEnter={e => { e.currentTarget.style.color = AI.accentLight; e.currentTarget.style.boxShadow = AI.glow }}
                onMouseLeave={e => { e.currentTarget.style.color = 'rgba(167,139,250,0.5)'; e.currentTarget.style.boxShadow = 'none' }}>
                <span className="w-2 h-2 rounded-full animate-pulse" style={{ background: AI.accent, boxShadow: AI.glow }} />
                검색 모드로 전환
                <span className="material-symbols-outlined text-lg group-hover:translate-x-1 transition-transform">arrow_forward</span>
              </button>
            </div>

            {/* 기능 카드 */}
            <div className={`grid grid-cols-1 md:grid-cols-3 gap-4 mt-24 w-full transition-all duration-300 ${homeExiting ? 'opacity-0 translate-y-4' : 'opacity-100 translate-y-0'}`}>
              {[
                { icon: 'manage_search', title: '반복 검색', sub: '쿼리 자동 개선' },
                { icon: 'psychology',   title: 'AI 추론',   sub: '결과 적합성 판단' },
                { icon: 'auto_awesome', title: 'LLM 연동',  sub: 'Ollama 로컬 LLM' },
              ].map((card) => (
                <div key={card.title}
                  className="p-6 rounded-xl cursor-pointer transition-all duration-300 group"
                  style={{ background: 'rgba(5,3,15,0.65)', border: `1px solid rgba(109,40,217,0.2)` }}
                  onMouseEnter={e => { e.currentTarget.style.borderColor = 'rgba(139,92,246,0.5)'; e.currentTarget.style.boxShadow = AI.glow }}
                  onMouseLeave={e => { e.currentTarget.style.borderColor = 'rgba(109,40,217,0.2)'; e.currentTarget.style.boxShadow = 'none' }}>
                  <span className="material-symbols-outlined mb-4 block group-hover:text-violet-400 transition-colors"
                    style={{ color: AI.accentDark }}>{card.icon}</span>
                  <h3 className="text-on-surface font-bold mb-1">{card.title}</h3>
                  <p className="text-[11px] uppercase tracking-tighter" style={{ color: 'rgba(167,139,250,0.4)' }}>{card.sub}</p>
                </div>
              ))}
            </div>
          </div>
        </main>
      )}

      {/* ════ RESULTS / DETAIL 헤더 ════ */}
      {view !== 'home' && (
        <header className={`fixed top-0 ${leftEdge} right-0 z-40 h-16 backdrop-blur-xl flex items-center px-6 gap-4 border-b transition-[left] duration-300`}
          style={{ background: 'rgba(13,7,24,0.8)', borderColor: AI.border,
            boxShadow: '0 4px 30px rgba(109,40,217,0.1)' }}>

          <button onClick={() => { setView('home'); setInputValue(''); setResults([]); if (abortRef.current) abortRef.current.abort() }}
            className={`text-lg font-bold tracking-tighter shrink-0 hover:opacity-70 transition-opacity ${!open ? 'ml-10' : ''}`}
            style={{ background: 'linear-gradient(to right, #a78bfa, #e879f9)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>
            AI 에이전트
          </button>

          <form onSubmit={handleSearch} className="flex-1">
            <div className="flex items-center rounded-full border px-4 py-2 gap-3 transition-all"
              style={{ background: AI.card, borderColor: AI.border }}>
              <span className="material-symbols-outlined text-lg" style={{ color: streaming ? AI.accent : 'rgba(139,92,246,0.5)' }}>
                {streaming ? 'psychology' : 'search'}
              </span>
              <input
                ref={inputRef}
                className="bg-transparent border-none focus:ring-0 w-full text-on-surface text-lg outline-none"
                style={{ caretColor: AI.accentLight }}
                placeholder="AI에게 검색을 맡기세요..."
                value={listening ? '' : inputValue}
                onChange={(e) => !listening && setInputValue(e.target.value)}
                readOnly={listening}
              />
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

          <div className="absolute bottom-0 left-0 w-full h-[1px] opacity-30"
            style={{ background: `linear-gradient(to right, transparent, ${AI.accent}, transparent)` }} />
        </header>
      )}

      {/* ════ RESULTS VIEW ════ */}
      {view === 'results' && (
        <main className={`${ml} min-h-screen transition-[margin] duration-300`}
          style={{ paddingTop: '64px', opacity: resultsReady ? 1 : 0, transform: resultsReady ? 'translateY(0)' : 'translateY(24px)',
            transition: 'opacity 0.38s ease, transform 0.38s ease, margin 0.3s' }}>
          <div className="px-8 pb-8 pt-5 max-w-[1400px] mx-auto">

            {/* 쿼리 헤더 */}
            <div className="flex justify-between items-end mb-6">
              <div className="space-y-2">
                <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-widest border"
                  style={{ background: 'rgba(109,40,217,0.1)', color: AI.accentLight, borderColor: AI.border }}>
                  AI 쿼리
                </span>
                <h1 className="text-4xl font-extrabold tracking-tighter text-on-surface">{query}</h1>
                {finalQuery && finalQuery !== query && (
                  <p className="text-xs flex items-center gap-1.5" style={{ color: 'rgba(167,139,250,0.6)' }}>
                    <span className="material-symbols-outlined text-sm">arrow_forward</span>
                    최종 쿼리: <span className="font-mono font-bold" style={{ color: AI.accentLight }}>"{finalQuery}"</span>
                  </p>
                )}
                {streaming
                  ? <p className="text-on-surface-variant flex items-center gap-2">
                      <span className="material-symbols-outlined text-lg animate-spin" style={{ color: AI.accent }}>progress_activity</span>
                      AI 에이전트 검색 중...
                    </p>
                  : aiError
                    ? <p className="text-red-400 text-sm">{aiError}</p>
                    : <p className="text-on-surface-variant">
                        <span className="font-bold" style={{ color: AI.accentLight }}>{results.length}건</span>을 찾았습니다.
                        {iterationData.filter(it=>it.iteration>0).length > 0 && (<span className="ml-2 text-xs opacity-50">({iterationData.filter(it=>it.iteration>0).length}회 시도)</span>
                        )}
                      </p>
                }
              </div>
            </div>

            {/* AI 탐색 과정 패널 */}
            <AIIterationPanel iterationData={iterationData} domainSelection={domainSelection} streaming={streaming} hasLLM={hasLLM} />

            {/* 로딩 */}
            {streaming && results.length === 0 && (
              <div className="flex flex-col items-center justify-center py-32 gap-4">
                <span className="material-symbols-outlined text-5xl animate-spin" style={{ color: AI.accent }}>psychology</span>
                <p className="text-on-surface-variant">AI 에이전트가 <span style={{ color: AI.accentLight }}>탑 3</span> 목표로 쿼리 최적화 중...</p>
              </div>
            )}

            {/* 결과 없음 */}
            {!streaming && !aiError && results.length === 0 && (
              <div className="flex flex-col items-center justify-center py-32 gap-4">
                <span className="material-symbols-outlined text-on-surface-variant/20 text-6xl">search_off</span>
                <p className="text-on-surface-variant">일치하는 파일을 찾지 못했습니다.</p>
              </div>
            )}

            {/* 결과 카드 (스트리밍 중에도 표시) */}
            {results.length > 0 && (
              <div className="grid gap-4" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))' }}>
                {results.map((r, i) => (
                  <AiResultCard key={r.file_path + i} result={r} rank={i + 1} onClick={() => handleSelectFile(r)} />
                ))}
              </div>
            )}

            {/* 요약 통계 */}
            {!streaming && results.length > 0 && (
              <div className="mt-12 rounded-[1.5rem] p-6 border relative overflow-hidden"
                style={{ background: AI.card, borderColor: AI.border }}>
                <div className="absolute -right-20 -top-20 w-64 h-64 rounded-full blur-[80px]"
                  style={{ background: 'rgba(109,40,217,0.1)' }} />
                <div className="relative z-10">
                  <h3 className="text-sm font-bold mb-4 flex items-center gap-2 uppercase tracking-widest"
                    style={{ color: AI.accentLight }}>
                    <span className="material-symbols-outlined text-lg">analytics</span>AI 검색 요약
                  </h3>
                  <div className="grid grid-cols-4 gap-4">
                    {[
                      ['총 결과', `${results.length}건`],
                      ['시도 횟수', `${iterationData.filter(it=>it.iteration>0).length}회`],
                      ['최고 신뢰도', `${Math.round((results[0]?.confidence ?? 0) * 100)}%`],
                      ['LLM', hasLLM ? '✓ 사용' : '휴리스틱'],
                    ].map(([label, val]) => (
                      <div key={label} className="p-4 rounded-2xl border"
                        style={{ background: 'rgba(109,40,217,0.05)', borderColor: AI.border }}>
                        <p className="text-[10px] uppercase tracking-widest mb-1" style={{ color: 'rgba(167,139,250,0.4)' }}>{label}</p>
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
            style={{ opacity: detailVisible ? 1 : 0, transform: detailVisible ? 'translateX(0)' : 'translateX(36px)',
              transition: 'opacity 0.35s ease, transform 0.35s ease, margin 0.3s' }}>

            {/* 파일 정보 바 */}
            <div className={`fixed top-16 ${leftEdge} right-0 z-30 backdrop-blur-xl flex items-center justify-between px-8 py-3 border-b transition-[left] duration-300`}
              style={{ background: 'rgba(13,7,24,0.8)', borderColor: AI.border }}>
              <div className="flex items-center gap-3 min-w-0 flex-1 mr-4">
                <span className={`material-symbols-outlined ${meta.color} shrink-0`}>{meta.icon}</span>
                <span className="font-manrope text-lg tracking-wide text-[#dfe4fe] font-bold truncate">{selectedFile.file_name}</span>
                <span className="px-2 py-0.5 rounded-full text-[10px] font-bold border shrink-0"
                  style={{ background: 'rgba(139,92,246,0.15)', color: AI.accentLight, borderColor: AI.border }}>
                  {confPct}%
                </span>
                <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold border shrink-0 ${meta.color} bg-white/5 border-white/10`}>
                  {meta.label}
                </span>
              </div>
              <div className="flex items-center gap-3 shrink-0">
                <button onClick={() => fetch(`${API_BASE}/api/files/open-folder`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ file_path: selectedFile.file_path }) })}
                  className="px-5 py-2 text-[11px] font-bold uppercase tracking-widest rounded-full border transition-all active:scale-95"
                  style={{ color: AI.accentLight, background: AI.card, borderColor: AI.border }}
                  onMouseEnter={e => e.currentTarget.style.borderColor = AI.accentLight}
                  onMouseLeave={e => e.currentTarget.style.borderColor = AI.border}>
                  경로 열기
                </button>
                <button onClick={() => fetch(`${API_BASE}/api/files/open`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ file_path: selectedFile.file_path }) })}
                  className="px-5 py-2 text-[11px] font-bold uppercase tracking-widest text-white rounded-full transition-all active:scale-95"
                  style={{ background: AI.rankBg, boxShadow: '0 0 15px rgba(109,40,217,0.3)' }}>
                  파일 열기
                </button>
              </div>
            </div>

            <section className="pt-36 pb-12 px-8 max-w-7xl mx-auto space-y-8">
              <div className="grid grid-cols-12 gap-6">

                {/* 메인 컨텐츠 */}
                <div className="col-span-8 space-y-6">
                  <div className="rounded-xl min-h-[400px] flex flex-col"
                    style={{ background: AI.card, border: `1px solid ${AI.border}` }}>
                    <div className="flex items-center justify-between px-8 pt-7 pb-5 border-b"
                      style={{ borderColor: AI.border }}>
                      <span className="text-[11px] font-bold tracking-[0.2em] uppercase" style={{ color: AI.accentLight }}>
                        {isAV ? '미디어 플레이어 · 세그먼트' : '콘텐츠 미리보기'}
                      </span>
                      <div className="flex gap-2 items-center">
                        {detailLoading && <span className="material-symbols-outlined text-lg animate-spin" style={{ color: AI.accent }}>progress_activity</span>}
                        <span className="h-2 w-2 rounded-full animate-pulse" style={{ background: AI.accent }} />
                        <span className="h-2 w-2 rounded-full" style={{ background: 'rgba(139,92,246,0.3)' }} />
                      </div>
                    </div>

                    {isAV ? (
                      <AVDetailContent result={selectedFile} />
                    ) : (selectedFile.file_type === 'image' || selectedFile.file_type === 'doc') && selectedFile.preview_url ? (
                      <div className="flex-1 flex items-center justify-center px-8 py-6">
                        <img
                          src={`${API_BASE}${selectedFile.preview_url}`}
                          alt={selectedFile.file_name}
                          className="max-w-full max-h-[380px] object-contain rounded-xl shadow-2xl border"
                          style={{ borderColor: AI.border }}
                        />
                      </div>
                    ) : (
                      <div className="flex-1 px-8 py-6">
                        {detailLoading ? (
                          <div className="flex items-center gap-2" style={{ color: 'rgba(139,92,246,0.4)' }}>
                            <span className="material-symbols-outlined animate-spin text-lg">progress_activity</span>
                            <span className="text-sm">불러오는 중...</span>
                          </div>
                        ) : fileDetail?.full_text ? (
                          <p className="text-on-surface-variant/90 leading-relaxed text-sm whitespace-pre-wrap">{fileDetail.full_text}</p>
                        ) : (
                          <div className="flex flex-col items-center justify-center h-48 gap-3" style={{ color: 'rgba(139,92,246,0.3)' }}>
                            <span className={`material-symbols-outlined text-5xl ${meta.color}/30`} style={{ fontVariationSettings: '"FILL" 1' }}>{meta.icon}</span>
                            <p className="text-sm">미리보기 없음</p>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                </div>

                {/* 메타데이터 패널 */}
                <div className="col-span-4 space-y-5">
                  {/* 신뢰도 */}
                  <div className="rounded-xl p-6 border relative overflow-hidden"
                    style={{ background: AI.card, borderColor: AI.border }}>
                    <div className="absolute -right-4 -top-4 w-24 h-24 blur-3xl" style={{ background: 'rgba(109,40,217,0.15)' }} />
                    <h4 className="text-[11px] font-bold tracking-[0.15em] uppercase mb-4" style={{ color: AI.accentLight }}>신뢰도 분석</h4>
                    <div className="space-y-3">
                      <div className="flex items-center gap-3">
                        <div className="flex-1 h-1.5 rounded-full overflow-hidden" style={{ background: 'rgba(109,40,217,0.15)' }}>
                          <div className="h-full rounded-full transition-all duration-700"
                            style={{ width: `${confPct}%`, background: `linear-gradient(to right, ${AI.accentDark}, ${AI.accentLight})`,
                              boxShadow: `0 0 8px rgba(139,92,246,0.5)` }} />
                        </div>
                        <span className="text-sm font-bold text-on-surface tabular-nums">{confPct}%</span>
                      </div>
                      <p className="text-[10px] text-on-surface-variant/50">TRI-CHEF Hermitian 유사도 · AI Calibration</p>
                    </div>
                  </div>

                  {/* 파일 정보 */}
                  <div className="rounded-xl p-6 border" style={{ background: AI.card, borderColor: AI.border }}>
                    <h4 className="text-[11px] font-bold tracking-[0.15em] uppercase mb-4" style={{ color: AI.accentLight }}>파일 정보</h4>
                    <div className="space-y-3">
                      {[
                        ['파일명', selectedFile.file_name],
                        ['타입', meta.label],
                        selectedFile.page_num != null ? ['페이지', `${selectedFile.page_num}p`] : null,
                        ['경로', selectedFile.file_path],
                        selectedFile.dense != null ? ['Dense', selectedFile.dense.toFixed(4)] : null,
                        selectedFile.lexical != null ? ['Lexical', selectedFile.lexical.toFixed(4)] : null,
                      ].filter(Boolean).map(([label, val]) => (
                        <div key={label} className="flex gap-3 py-2 border-b last:border-0" style={{ borderColor: AI.border }}>
                          <span className="text-[10px] uppercase tracking-widest min-w-[60px] shrink-0" style={{ color: 'rgba(167,139,250,0.5)' }}>{label}</span>
                          <span className="text-[11px] text-on-surface-variant break-all font-mono">{val}</span>
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* AI 검색 여정 요약 */}
                  {iterationData.filter(it=>it.iteration>0).length > 0 && (<div className="rounded-xl p-6 border" style={{ background: AI.card, borderColor: AI.border }}>
                      <h4 className="text-[11px] font-bold tracking-[0.15em] uppercase mb-4" style={{ color: AI.accentLight }}>
                        검색 여정 ({iterationData.filter(it=>it.iteration>0).length}회 시도)
                      </h4>
                      <div className="space-y-2">
                        {iterationData.filter(it=>it.iteration>0).map((h, i) => (
                          <div key={i} className="flex items-start gap-2">
                            <span className="text-[10px] font-bold mt-0.5 shrink-0" style={{ color: AI.accentDark }}>#{i+1}</span>
                            <div>
                              <span className="text-[10px] font-mono" style={{ color: AI.accentLight }}>"{h.query}"</span>
                              <span className="text-[10px] text-on-surface-variant/40 ml-1">{h.count}건</span>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </section>
          </main>
        )
      })()}
    </div>
  )
}
