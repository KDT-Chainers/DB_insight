import { useState, useRef, useEffect, useCallback, useMemo } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import SearchSidebar from '../components/SearchSidebar'
import AnimatedOrb from '../components/AnimatedOrb'
import { useSidebar } from '../context/SidebarContext'
import { useSpeechRecognition } from '../hooks/useSpeechRecognition'
import { useMicLevelRef } from '../hooks/useMicLevelRef'
import { API_BASE } from '../api'

// ── 파일 타입 메타 (AI 오브 점 색상 계열) ─────────────────────
/** AnimatedOrb `aiPointColor` 와 동일 계열 (가독성 위해 일부만 살짝 보정) */
const ORB = {
  navy: '#5c9dff',
  pink: '#ff59e0',
  mint: '#52fac7',
  coral: '#ff6142',
  electric: '#8cf2ff',
}

const TYPE_META = {
  doc:   { icon: 'description', color: 'text-[#8cf2ff]', label: '문서',   grad: 'from-[#1e3a6e] to-[#5c9dff]' },
  video: { icon: 'movie',       color: 'text-[#ff59e0]', label: '동영상', grad: 'from-[#581c87] to-[#be185d]' },
  image: { icon: 'image',       color: 'text-[#52fac7]', label: '이미지', grad: 'from-[#0f766e] to-[#14b8a6]' },
  audio: { icon: 'volume_up',   color: 'text-[#ff7a5c]', label: '음성',   grad: 'from-[#7c2d12] to-[#ea580c]' },
  movie: { icon: 'movie',       color: 'text-[#ff59e0]', label: '동영상', grad: 'from-[#581c87] to-[#be185d]' },
  music: { icon: 'volume_up',   color: 'text-[#ff7a5c]', label: '음성',   grad: 'from-[#7c2d12] to-[#ea580c]' },
}
const getTypeMeta = (t) =>
  TYPE_META[t] ?? { icon: 'insert_drive_file', color: 'text-on-surface-variant', label: t ?? '파일', grad: 'from-[#1c253e] to-[#263354]' }

/** Orb `assembleIntro` 길이와 헤일로 PNG `ai-orbit-halo-emerge` 동기 (초) */
const AI_ORB_ASSEMBLE_SECONDS = 8

function fmtTime(sec) {
  if (!sec && sec !== 0) return '0:00'
  const s = Math.floor(sec)
  const m = Math.floor(s / 60)
  return `${m}:${String(s % 60).padStart(2, '0')}`
}

// AI 답변 안전장치 — 시스템 프롬프트로 마크다운 금지했지만,
// LLM 이 이를 어길 경우를 대비한 프론트엔드 폴리필.
// 별표/헤딩/백틱/인용/하이픈 불릿 → 평문 변환
function stripMarkdown(text) {
  if (!text) return text
  return text
    // **bold** / *italic* → 따옴표 스타일
    .replace(/\*\*(.+?)\*\*/g, '$1')
    .replace(/(?<![*\w])\*(.+?)\*(?!\*)/g, '$1')
    // ### / ## / # 헤딩 → 일반 텍스트
    .replace(/^#{1,6}\s+/gm, '')
    // `code` → 일반 텍스트
    .replace(/`([^`\n]+)`/g, '$1')
    // > 인용 → 일반 텍스트
    .replace(/^>\s+/gm, '')
    // --- 가로선 → 빈 줄
    .replace(/^[-*_]{3,}\s*$/gm, '')
    // - / * 불릿 → • 점
    .replace(/^(\s*)[-*]\s+/gm, '$1• ')
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
  /** 카드·패널에서 공통 참조하는 오브 포인트 */
  orb: ORB,
}

/** 로컬 UI 프리뷰 전용 (#/ai?devDummy=1). 프로덕션 배포에서는 localhost 에서만 동작 */
const _LOCAL_AI_DUMMY_HOST =
  typeof window !== 'undefined' &&
  (window.location.hostname === 'localhost' ||
    window.location.hostname === '127.0.0.1')

// ── 결과 카드 (AI 색상) ───────────────────────────────────────
function AiResultCard({ result, rank, onClick }) {
  const isAV       = result.file_type === 'video' || result.file_type === 'audio'
  const hasPreview = (result.file_type === 'image' || result.file_type === 'doc') && result.preview_url
  const [imgError, setImgError] = useState(false)
  const playerRef  = useRef(null)

  const conf    = result.confidence ?? result.similarity ?? 0
  const confPct = (conf * 100).toFixed(1)
  const dense   = result.dense ?? null
  const rerank  = result.rerank_score ?? result.rerank ?? null
  const zScore  = result.z_score ?? null
  const lexical = result.lexical ?? null

  const clamp01 = x => (x == null || isNaN(x)) ? null : Math.max(0, Math.min(1, x))
  const sigm    = x => 1 / (1 + Math.exp(-x))
  const sim     = clamp01(dense) != null ? clamp01(dense).toFixed(3) : '—'

  // 정확도 산출 — 도메인 인지 폴백:
  //   doc/audio/video : BGE-reranker (텍스트→텍스트) 가 신뢰할 만함 → sigm 그대로
  //   image           : BGE-reranker 는 캡션만 보므로 dense (SigLIP2 시각) 가 더 정확
  // 1) rerank 양수: sigm(rerank) 그대로
  // 2) rerank 음수: dense 우선 (이미지) / dense 블렌드 (기타)
  // 3) rerank null: dense or lexical or conf 추정
  const _accFromMix = () => {
    const d = clamp01(dense) ?? 0
    const ft = result.file_type
    if (rerank != null) {
      const s = sigm(rerank)
      if (s >= 0.5) return s            // 양수 정상 reranker → 그대로 신뢰
      // 음수 폴백
      if (ft === 'image') {
        // 이미지는 BGE-reranker 무력 → dense 우선 (max), 단 reranker 신호도 약하게 반영
        return Math.max(d * 0.9, s)
      }
      // doc/video/audio: dense 와 reranker 블렌드
      return s * 0.4 + d * 0.6
    }
    if (zScore != null) return Math.max(0, Math.min(1, (zScore + 3) / 6))
    if (lexical != null && d > 0) return d * 0.7 + Math.min(1, lexical * 1.5) * 0.3
    return d > 0 ? d * 0.85 : conf * 0.9
  }
  const acc = _accFromMix().toFixed(3)

  const domainLabel = result.trichef_domain ?? result.file_type ?? 'unknown'
  const segments    = result.segments ?? []
  const streamUrl   = isAV ? avStreamUrl(result) : null

  const DOMAIN_CLS = {
    image:    'text-[#52fac7] border-[#52fac7]/35',
    doc_page: 'text-[#8cf2ff] border-[#5c9dff]/40',
    movie:    'text-[#ff9edc] border-[#ff59e0]/35',
    music:    'text-[#ffc4b3] border-[#ff6142]/40',
  }
  
  const getDomainStyle = (label) => {
    const colorMap = {
      image:    { text: '#52fac7', glow: 'rgba(82, 250, 199, 0.25)' },
      doc_page: { text: '#8cf2ff', glow: 'rgba(140, 242, 255, 0.25)' },
      movie:    { text: '#ff9edc', glow: 'rgba(255, 158, 220, 0.25)' },
      music:    { text: '#ffc4b3', glow: 'rgba(255, 196, 179, 0.25)' },
    }
    const color = colorMap[label] || { text: '#a78bfa', glow: 'rgba(167, 139, 250, 0.25)' }
    return {
      background: 'rgba(13, 7, 24, 0.5)',
      backdropFilter: 'blur(12px)',
      border: `1.5px solid ${color.text}28`,
      color: color.text,
      boxShadow: `0 4px 16px ${color.glow}, inset 0 1px 2px rgba(255, 255, 255, 0.12), inset 0 -1px 2px rgba(0, 0, 0, 0.3)`
    }
  }

  const seekTo = (t) => { const p = playerRef.current; if (!p) return; p.currentTime = t; p.play().catch(() => {}) }

  return (
    <div
      onClick={onClick}
      className="rounded-[10px] overflow-hidden flex flex-col relative transition-all duration-200 cursor-pointer hover:-translate-y-0.5"
      style={{
        background: AI.card,
        border: `1px solid ${AI.border}`,
      }}
      onMouseEnter={e => { e.currentTarget.style.borderColor = AI.borderHover; e.currentTarget.style.boxShadow = AI.glow }}
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
            <span className="text-xs" style={{ color: AI.orb.pink }}>{domainLabel}</span>
          )}
        </div>
      )}

      {/* 바디 */}
      <div className="p-3 flex flex-col gap-2 flex-1 text-[#e2e8f0]">
        {/* 3지표 — 미리보기 화면 바로 아래 */}
        <div className="grid grid-cols-3 gap-1.5">
          {[
            { label: '신뢰도', value: `${confPct}%`, cls: 'text-[#ff59e0]' },
            { label: '정확도', value: acc,            cls: 'text-[#8cf2ff]' },
            { label: '유사도', value: sim,            cls: 'text-[#52fac7]' },
          ].map(({ label, value, cls }) => (
            <div key={label} className="rounded-md p-1.5 text-center border"
              style={{ background: '#0b0515', borderColor: AI.border }}>
              <div className="text-[10px] text-[#6b7280] uppercase tracking-wide">{label}</div>
              <div className={`text-[15px] font-bold mt-0.5 ${cls}`}>{value}</div>
            </div>
          ))}
        </div>

        {/* 도메인 배지 */}
        <div className="flex gap-1 flex-wrap">
          <span 
            className="text-[10px] px-2 py-0.5 rounded-full border transform origin-left transition-transform duration-200 ease-out hover:scale-x-105"
            style={getDomainStyle(domainLabel)}
          >
            {domainLabel}
          </span>
          {isAV && (
            <span className="border border-[#ff59e0]/35 bg-purple-950/60 text-[10px] text-[#f0abfc] px-2 py-0.5 rounded-full">
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
            <span className="shrink-0 rounded border border-[#5c9dff]/35 bg-indigo-950/60 px-1.5 py-0.5 font-mono text-[10px] text-[#8cf2ff] whitespace-nowrap">
              {result.page_num}p
            </span>
          )}
        </div>

        {/* 경로 */}
        <div className="text-[11px] text-[#6b7280] break-all font-mono">
          {result.file_path || result.trichef_id}
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
                      <span className="font-mono font-semibold whitespace-nowrap min-w-[112px]" style={{ color: ORB.electric }}>{fmtTime(t0)} ~ {fmtTime(t1)}</span>
                      <span className="font-mono whitespace-nowrap" style={{ color: ORB.pink }}>s={sc.toFixed(3)}</span>
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
              <span className="material-symbols-outlined text-4xl" style={{ fontVariationSettings: '"FILL" 1', color: ORB.coral }}>volume_up</span>
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
  image:    { label: '이미지', icon: 'image',       bg: '#0d0718', text: '#a7f3d0', border: ORB.mint },
  doc_page: { label: '문서',   icon: 'description', bg: '#0d0718', text: '#dbeafe', border: ORB.electric },
  movie:    { label: '동영상', icon: 'movie',       bg: '#0d0718', text: '#fce7f3', border: ORB.pink },
  music:    { label: '음성',   icon: 'volume_up',   bg: '#0d0718', text: '#ffedd5', border: ORB.coral },
  all:      { label: '전체',   icon: 'search',      bg: '#0d0718', text: '#e9d5ff', border: '#a78bfa' },
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
        <div className="h-9 flex items-center justify-center" 
          style={{ 
            background: 'rgba(13, 7, 24, 0.5)',
            backdropFilter: 'blur(12px)',
            border: `1.5px solid ${dc.border}28`,
            boxShadow: `inset 0 1px 2px rgba(255, 255, 255, 0.08), inset 0 -1px 2px rgba(0, 0, 0, 0.3)`
          }}>
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
                  style={{ 
                    border: `1.5px solid ${dc.border}28`, 
                    background: 'rgba(13, 7, 24, 0.5)',
                    backdropFilter: 'blur(12px)',
                    boxShadow: `0 4px 16px rgba(0, 0, 0, 0.2), inset 0 1px 2px rgba(255, 255, 255, 0.08), inset 0 -1px 2px rgba(0, 0, 0, 0.3)`
                  }}>

                  {/* 단계 헤더 */}
                  <div className="flex items-center gap-2 px-3 py-2"
                    style={{ 
                      background: `rgba(13, 7, 24, 0.6)`,
                      backdropFilter: 'blur(12px)',
                      borderBottom: `1.5px solid ${dc.border}28`
                    }}>
                    <div className="w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold text-white shrink-0"
                      style={{ background: step.done ? `linear-gradient(135deg,${ORB.mint},#0d9488)` : isGlobal ? 'rgba(140,242,255,0.35)' : AI.rankBg }}>
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
                        style={{ color: step.done ? ORB.mint : AI.accent, fontVariationSettings: '"FILL" 1' }}>
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
  const [iterationData,  setIterationData]  = useState([])
  const [domainSelection,setDomainSelection]= useState(null)
  const [aiError,        setAiError]        = useState('')
  const [finalQuery,     setFinalQuery]     = useState('')
  const [hasLLM,         setHasLLM]         = useState(undefined)

  // ── AIMODE 시각화 4-step 상태 ─────────────────────────────
  const [aimodeSteps,       setAimodeSteps]       = useState([])
  const [aimodeQuery,       setAimodeQuery]       = useState('')
  const [aimodeContentKws,  setAimodeContentKws]  = useState([])
  const [aimodeDetailKws,   setAimodeDetailKws]   = useState([])
  const [aimodeSources,     setAimodeSources]     = useState([])
  const [aimodeSelected,    setAimodeSelected]    = useState(null)
  const [aimodeAnswer,      setAimodeAnswer]      = useState('')
  const [aimodeDone,        setAimodeDone]        = useState(false)
  const [useAimode,         setUseAimode]         = useState(true)
  const [topK,              setTopK]              = useState(20)
  const [maxIter,           setMaxIter]           = useState(5)
  const abortRef = useRef(null)
  const activeQueryRef = useRef('')

  const dispatchAiSidebarView = useCallback((viewName) => {
    try {
      window.dispatchEvent(
        new CustomEvent('ai-sidebar-view-changed', { detail: { view: viewName } }),
      )
    } catch {}
  }, [])

  // 애니메이션
  const [homeExiting,  setHomeExiting]  = useState(false)
  const [resultsReady, setResultsReady] = useState(false)
  const [detailVisible,setDetailVisible]= useState(false)

  const [aiHomeEntranceOn, setAiHomeEntranceOn] = useState(
    () => typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches
  )

  // 포털 전환
  const [searchTransitioning, setSearchTransitioning] = useState(false)
  const [ripplePos, setRipplePos] = useState({ x: '50%', y: '50%' })
  const [aiDockExpanded, setAiDockExpanded] = useState(false)
  const btnRef      = useRef(null)
  const formRef     = useRef(null)
  const inputRef    = useRef(null)
  const orbSinkRef  = useRef(null)
  const orbVoiceRef = useRef(0)

  // aiHomeEntranceOn 제어
  useEffect(() => {
    if (view !== 'home') { setAiHomeEntranceOn(false); return }
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) { setAiHomeEntranceOn(true); return }
    setAiHomeEntranceOn(false)
    const t = window.setTimeout(() => setAiHomeEntranceOn(true), 180)
    return () => clearTimeout(t)
  }, [view])

  // 뷰 변경 시 검색창 자동 포커스 (detail 제외 모든 뷰)
  useEffect(() => {
    if (view !== 'detail') {
      const t = setTimeout(() => inputRef.current?.focus(), 150)
      return () => clearTimeout(t)
    }
  }, [view])

  const ml       = open ? 'ml-64' : 'ml-0'
  const leftEdge = open ? 'left-64' : 'left-0'
  const sidebarPx= open ? 256 : 0

  // STT
  const doSearchRef = useRef(null)
  const { listening, interim, toggle: toggleMic, stop: stopMic } = useSpeechRecognition({
    onFinal: useCallback((text) => {
      setInputValue(text)
      setTimeout(() => doSearchRef.current?.(text), 80)
    }, []),
  })

  useMicLevelRef(view === 'home' && listening, orbVoiceRef, { startDelayMs: 420 })

  useEffect(() => {
    if (view !== 'home') stopMic()
  }, [view, stopMic])

  useEffect(() => {
    if (view !== 'results' && aiDockExpanded) setAiDockExpanded(false)
  }, [view, aiDockExpanded])

  // 로컬 전용: AIMODE 결과·상세 레이아웃 프리뷰 (백엔드 없이)
  useEffect(() => {
    if (!_LOCAL_AI_DUMMY_HOST || location.pathname !== '/ai') return
    const sp = new URLSearchParams(location.search || '')
    if (sp.get('devDummy') !== '1') return

    const userQ = '김라민 생년월일이 적힌 보고서를 찾아줘 (더미)'
    const extracted = '김라민 보고서'
    const rawItems = [
      {
        file_path: '/tmp/dev-dummy/report_kim.pdf',
        file_name: 'report_kim.pdf',
        file_type: 'doc',
        confidence: 0.91,
        similarity: 0.91,
        snippet: '김라민 — 생년월일: 1995-03-12 (더미 텍스트)',
        preview_url: null,
        segments: [],
        trichef_id: 'doc_dummy_1',
        trichef_domain: 'doc_page',
        dense: 0.82,
        lexical: 0.44,
      },
      {
        file_path: '/tmp/dev-dummy/meeting_photo.jpg',
        file_name: 'meeting_photo.jpg',
        file_type: 'image',
        confidence: 0.76,
        similarity: 0.76,
        snippet: '회의 장면 스냅 — 배경에 이름표 (더미)',
        preview_url: null,
        segments: [],
        trichef_id: 'img_dummy_1',
        trichef_domain: 'image',
        dense: 0.71,
        lexical: null,
      },
      {
        file_path: '/tmp/dev-dummy/interview_clip.mp4',
        file_name: 'interview_clip.mp4',
        file_type: 'video',
        confidence: 0.68,
        similarity: 0.68,
        snippet: '인터뷰 구간 — 자막에 김라민 언급 (더미)',
        preview_url: null,
        segments: [],
        trichef_id: 'mov_dummy_1',
        trichef_domain: 'movie',
        dense: 0.65,
        rerank_score: 0.2,
      },
    ]
    const mappedItems = rawItems.map(mapItem)

    activeQueryRef.current = userQ
    setStreaming(false)
    setAiError('')
    setQuery(userQ)
    setInputValue(userQ)
    setFinalQuery(extracted)
    setAimodeQuery(extracted)
    setAimodeContentKws(['생년월일', '보고서'])
    setAimodeDetailKws(['김라민', '생년월일'])
    setAimodeSources(mappedItems)
    setAimodeSelected(0)
    setAimodeAnswer(
      '[더미] 첫 번째 PDF 보고서에서 김라민의 생년월일을 확인했습니다. (실제 데이터 아님)',
    )
    setAimodeDone(true)
    setAimodeSteps([
      { step: 1, label: '✓ 검색어 추출', done: true, query: extracted },
      { step: 2, label: `✓ ${rawItems.length}건 발견`, done: true },
      { step: 3, label: '✓ #1 자동 선택', done: true, selected_idx: 0 },
      { step: 4, label: '✓ 답변', done: true },
    ])
    setResults(mappedItems)
    setResultsReady(false)
    setView('results')
    window.history.replaceState({ view: 'results' }, '')
    requestAnimationFrame(() => setResultsReady(true))
  }, [location.pathname, location.search])

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

  // ── SSE 실행 (AIMODE 시각화 또는 기존 에이전트) ─────────────
  const runAISearch = useCallback(async (q) => {
    if (abortRef.current) abortRef.current.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setStreaming(true)
    setResults([])
    setIterationData([])
    setDomainSelection(null)
    setAiError('')
    setFinalQuery(q)
    activeQueryRef.current = q
    setHasLLM(undefined)

    // AIMODE 시각화 상태 초기화
    setAimodeSteps([])
    setAimodeQuery('')
    setAimodeContentKws([])
    setAimodeDetailKws([])
    setAimodeSources([])
    setAimodeSelected(null)
    setAimodeAnswer('')
    setAimodeDone(false)

    const endpoint = useAimode
      ? `${API_BASE}/api/aimode/chat`
      : `${API_BASE}/api/ai/search`
    // LangGraph thread_id — localStorage 영속 (24h TTL)
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
    const body = useAimode
      ? { query: q, topk: topK, thread_id: tid }
      : { query: q, topk: topK, max_iterations: maxIter }

    try {
      const res = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
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
  }, [topK, maxIter, useAimode])

  const mapItem = (item) => {
    const dom =
      item.domain ??
      item.trichef_domain ??
      (item.file_type === 'doc'
        ? 'doc_page'
        : item.file_type === 'video'
          ? 'movie'
          : item.file_type === 'audio'
            ? 'music'
            : item.file_type === 'image'
              ? 'image'
              : null)
    const isDocPage = dom === 'doc_page'
    const pathKey =
      item.file_path || item.source_path || item.id || item.trichef_id || ''
    const idKey = item.trichef_id ?? item.id ?? pathKey
    let ft = item.file_type
    if (!ft && dom === 'image') ft = 'image'
    else if (!ft && isDocPage) ft = 'doc'
    else if (!ft && dom === 'movie') ft = 'video'
    else if (!ft && dom === 'music') ft = 'audio'
    else if (!ft) ft = 'doc'
    const conf =
      item.confidence ?? item.similarity ?? 0
    return {
      file_path:      pathKey,
      trichef_id:     idKey,
      file_name:      item.file_name || String(pathKey).split(/[/\\]/).pop() || '?',
      page_num:       item.page_num ?? null,
      file_type:      ft,
      confidence:     conf,
      similarity:     item.similarity ?? conf,
      dense:          item.dense ?? 0,
      lexical:        item.lexical ?? null,
      asf:            item.asf ?? null,
      snippet:        item.snippet ?? '',
      preview_url:    item.preview_url ?? null,
      segments:       item.segments ?? [],
      low_confidence: item.low_confidence ?? false,
      trichef_domain: dom ?? undefined,
      rerank_score:   item.rerank_score ?? item.rerank ?? null,
      z_score:        item.z_score ?? null,
    }
  }

  const handleSSEEvent = (ev) => {
    switch (ev.type) {
      // ── AIMODE 시각화 이벤트 (/api/aimode/chat) ─────────────
      case 'step':
        setAimodeSteps(prev => {
          const idx = prev.findIndex(s => s.step === ev.step)
          const entry = {
            step: ev.step,
            label: ev.label,
            done: ev.done === true,
            query: ev.query,
            selected_idx: ev.selected_idx,
          }
          if (idx >= 0) {
            const next = [...prev]
            next[idx] = { ...next[idx], ...entry }
            return next
          }
          return [...prev, entry]
        })
        if (ev.step === 1 && ev.done) {
          if (ev.query) setAimodeQuery(ev.query)
          if (ev.content_keywords) setAimodeContentKws(ev.content_keywords)
          if (ev.detail_keywords)  setAimodeDetailKws(ev.detail_keywords)
        }
        if (ev.step === 3 && typeof ev.selected_idx === 'number') {
          setAimodeSelected(ev.selected_idx)
          // Step 3 완료 — LangGraph 가 선택한 카드 자동 클릭 (1.4s 딜레이 후)
          setAimodeSources(prev => {
            const file = prev[ev.selected_idx]
            if (file) {
              setTimeout(() => handleSelectFile(file), 1400)
            }
            return prev
          })
        }
        break

      case 'sources': {
        // AIMODE 검색 결과 — 작은 단계 패널용 + MainSearch 와 동일한 큰 카드 그리드용
        const items = ev.items || []
        const mapped = items.map(mapItem)
        setAimodeSources(mapped)
        // ★ 동일 데이터를 큰 카드 그리드로도 렌더 (MainSearch 와 동일한 UX)
        setResults(mapped)
        const histQ =
          activeQueryRef.current ||
          ev.query ||
          finalQuery ||
          ''
        // 검색 기록 저장
        fetch(`${API_BASE}/api/history`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            query: histQ,
            method: 'aimode',
            result_count: mapped.length,
          }),
        }).then(() => {
          window.dispatchEvent(new Event('history-updated'))
        }).catch(() => {})
        break
      }

      case 'token':
        setAimodeAnswer(prev => prev + (ev.text || ''))
        break

      case 'done':
        setAimodeDone(true)
        if (ev.answer) setAimodeAnswer(ev.answer)
        if (typeof ev.selected_idx === 'number') setAimodeSelected(ev.selected_idx)
        break

      case 'error':
        setAiError(ev.message || '오류')
        break

      // ── 기존 ai_search 이벤트 (fallback) ─────────────────────
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
      // case 'error' 는 위쪽에 이미 정의 (AIMODE/legacy 공용)
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
        dispatchAiSidebarView('results')
        requestAnimationFrame(() => setResultsReady(true))
        runAISearch(q)
      }, 420)
    } else {
      setView('results')
      window.history.pushState({ view: 'results' }, '')
      dispatchAiSidebarView('results')
      runAISearch(q)
    }
  }

  doSearchRef.current = doSearch;

  useEffect(() => { doSearchRef.current = doSearch })

  const handleSearch  = (e) => { e?.preventDefault(); doSearch(inputValue) }

  const handleSelectFile = (file) => {
    setSelectedFile(file)
    setFileDetail(null)
    setDetailVisible(false)
    setView('detail')
    window.history.pushState({ view: 'detail' }, '')
    dispatchAiSidebarView('detail')
    requestAnimationFrame(() => requestAnimationFrame(() => setDetailVisible(true)))
    const isAV = file.file_type === 'video' || file.file_type === 'audio'
    if (!isAV) {
      setDetailLoading(true)
      fetch(`${API_BASE}/api/files/detail?path=${encodeURIComponent(file.file_path)}`)
        .then(r => r.json()).then(d => { setFileDetail(d); setDetailLoading(false) })
        .catch(() => setDetailLoading(false))
    }
  }

  const handleBackToResults = () => {
    setDetailVisible(false)
    window.history.pushState({ view: 'results' }, '')
    dispatchAiSidebarView('results')
    setTimeout(() => setView('results'), 320)
  }

  // 새 대화 — 서버 history + localStorage thread_id 모두 비움
  const handleNewConversation = useCallback(async () => {
    if (abortRef.current) abortRef.current.abort()
    const tid = window.__aimodeThreadId
    if (tid) {
      try { await fetch(`${API_BASE}/api/aimode/chat/${encodeURIComponent(tid)}`, { method: 'DELETE' }) } catch {}
    }
    try { localStorage.removeItem('aimode_thread_id') } catch {}
    window.__aimodeThreadId = null
    setAimodeSteps([])
    setAimodeQuery('')
    setAimodeContentKws([])
    setAimodeDetailKws([])
    setAimodeSources([])
    setAimodeSelected(null)
    setAimodeAnswer('')
    setAimodeDone(false)
    setResults([])
    setIterationData([])
    setSelectedFile(null)
    setFileDetail(null)
    setAiError('')
    setView('home')
    setInputValue('')
  }, [])

  const handleGoToSearch = () => {
    const rect = btnRef.current?.getBoundingClientRect();
    if (rect)
      setRipplePos({
        x: `${rect.left + rect.width / 2}px`,
        y: `${rect.top + rect.height / 2}px`,
      });
    setSearchTransitioning(true);
    setTimeout(() => navigate("/search"), 900);
  };

  // ── 렌더 ────────────────────────────────────────────────────
  return (
    <div className={view === 'home' ? 'overflow-hidden h-screen relative' : 'min-h-screen relative text-on-surface'}
      style={{
        backgroundColor: view === 'home' ? AI.bg : AI.bg,
        backgroundImage: view !== 'home'
          ? [
              'radial-gradient(ellipse 100% 72% at 50% -18%, rgba(124,58,237,0.38), transparent 56%)',
              'radial-gradient(ellipse 55% 48% at 92% 38%, rgba(192,38,211,0.16), transparent 52%)',
              'radial-gradient(ellipse 50% 44% at 8% 72%, rgba(76,29,149,0.42), transparent 52%)',
              'radial-gradient(circle at 2px 2px, rgba(109,40,217,0.09) 1px, transparent 0)',
            ].join(', ')
          : undefined,
        backgroundSize: view !== 'home' ? '100% 100%, 100% 100%, 100% 100%, 32px 32px' : undefined,
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
            <div key={i} className="portal-ring absolute rounded-full border border-[#8cf2ff]/28"
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
        <>
          <main className={`${ml} relative flex h-full min-h-0 flex-col overflow-x-hidden overflow-y-auto bg-transparent transition-[margin] duration-300 pt-8`}>
            <div
              className="ai-home-orbit-bg pointer-events-none absolute inset-0 z-0 min-h-0"
              style={{ '--ai-orbit-assemble': `${AI_ORB_ASSEMBLE_SECONDS}s` }}
              aria-hidden
            />
            {/* Orb */}
            <div ref={orbSinkRef} className="absolute inset-0 z-0 min-h-0" aria-hidden>
              <AnimatedOrb
                layout="fill"
                colorMode="ai"
                hideCenterUI
                interactive={false}
                aiHoverFx
                pointScaleMul={1.45}
                particleCount={11000}
                size={720}
                assembleIntro
                assembleDuration={AI_ORB_ASSEMBLE_SECONDS}
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
                    <form
                      onSubmit={handleSearch}
                      className="mse-search-up group pointer-events-auto relative z-10 w-full max-w-[min(90vw,22rem)] shrink-0 md:max-w-[24rem]"
                      style={homeExiting ? { visibility: 'hidden' } : {}}
                    >
                      <div className="pointer-events-none absolute -inset-[2px] rounded-full bg-gradient-to-r from-fuchsia-500/0 via-violet-400/25 to-fuchsia-500/0 opacity-0 blur-md transition-opacity duration-500 group-focus-within:opacity-100" />
                      <div className="relative flex items-center gap-2 rounded-full border border-violet-200/[0.14] bg-gradient-to-b from-violet-100/[0.09] to-violet-950/[0.28] px-1.5 py-1.5 shadow-[inset_0_1px_0_rgba(255,255,255,0.16),inset_0_-1px_0_rgba(0,0,0,0.22),0_10px_44px_rgba(32,12,58,0.5)] backdrop-blur-2xl transition-all duration-300 group-focus-within:border-violet-200/25 group-focus-within:from-violet-100/[0.12] group-focus-within:to-violet-950/[0.34]">
                        <button
                          type="button"
                          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-violet-900 to-purple-600 text-violet-50 shadow-[0_0_20px_rgba(124,58,237,0.32),inset_0_1px_0_rgba(255,255,255,0.18)] transition-transform hover:from-violet-800 hover:to-purple-500 active:scale-90"
                        >
                          <span className="material-symbols-outlined text-[20px] font-bold">add</span>
                        </button>
                        <input
                          type="text"
                          value={inputValue}
                          onChange={(e) => setInputValue(e.target.value)}
                          placeholder={
                            listening ? "듣는 중…" : "Anything you need"
                          }
                          className="min-w-0 flex-1 border-none bg-transparent py-2 font-manrope text-sm text-violet-100/90 outline-none ring-0 placeholder:text-violet-300/45 md:py-2.5 md:text-base"
                        />
                        <button
                          type="button"
                          onClick={toggleMic}
                          aria-pressed={listening}
                          aria-label={
                            listening ? "음성 입력 끄기" : "음성 입력"
                          }
                          className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full border backdrop-blur-md transition-colors ${
                            listening
                              ? "border-rose-400/35 bg-rose-950/40 text-rose-200 shadow-[0_0_16px_rgba(251,113,133,0.25)]"
                              : "border-violet-300/18 bg-violet-950/35 text-violet-200/80 hover:border-violet-200/30 hover:bg-violet-900/40 hover:text-violet-100"
                          }`}
                        >
                          <span className="material-symbols-outlined text-[20px]">
                            mic
                          </span>
                        </button>
                      </div>
                    </form>
                  </div>
                </div>
              </div>

              <div
                className="mse-search-up mse-search-up-delay-1 pointer-events-auto flex shrink-0 flex-col items-center justify-end px-6 pb-10 pt-2 md:px-8"
                style={homeExiting ? { visibility: "hidden" } : {}}
              >
                <button
                  ref={btnRef}
                  onClick={handleGoToSearch}
                  disabled={searchTransitioning}
                  className="group flex items-center gap-3 rounded-full border border-white/20 px-8 py-3 text-sm font-bold uppercase tracking-widest text-neutral-300 transition-all duration-300 hover:border-white/40 hover:text-white hover:shadow-lg disabled:pointer-events-none"
                  style={{
                    background: 'rgba(255, 255, 255, 0.1)',
                    backdropFilter: 'blur(10px)',
                    boxShadow: '0 8px 32px rgba(139, 92, 246, 0.1), inset 0 1px 1px rgba(255, 255, 255, 0.2)',
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.background = 'rgba(255, 255, 255, 0.15)';
                    e.currentTarget.style.boxShadow =
                      "0 8px 32px rgba(139, 92, 246, 0.3), inset 0 1px 1px rgba(255, 255, 255, 0.3), 0 0 30px rgba(139, 92, 246, 0.25)";
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.background = 'rgba(255, 255, 255, 0.1)';
                    e.currentTarget.style.boxShadow = '0 8px 32px rgba(139, 92, 246, 0.1), inset 0 1px 1px rgba(255, 255, 255, 0.2)';
                  }}
                >
                  <span
                    className="h-2 w-2 animate-pulse rounded-full bg-violet-500"
                    style={{ boxShadow: "0 0 6px rgba(139, 92, 246, 0.9)" }}
                  />
                  검색 모드로 전환
                  <span className="material-symbols-outlined text-lg transition-transform group-hover:translate-x-1">
                    arrow_forward
                  </span>
                </button>
              </div>
            </div>
          </main>
        </>
      )}

      {/* ════════════════════════════════
          RESULTS / DETAIL 공통 헤더
      ════════════════════════════════ */}
      {view !== "home" && (
        <header
          className={`fixed top-8 ${leftEdge} right-0 z-40 transition-[left] duration-300`}
        >
          <div className="mx-auto max-w-[1600px] px-8">
            <div className="relative flex h-16 items-center gap-6 rounded-[22px] border border-[#41567f]/35 bg-[#0b1326]/72 px-8 shadow-[0_4px_30px_rgba(34,98,214,0.12)] backdrop-blur-xl">
          <button
            onClick={() => {
              setView("home");
              setInputValue("");
            }}
            className={`text-xl font-bold tracking-tighter bg-gradient-to-r from-violet-400 to-fuchsia-400 bg-clip-text text-transparent shrink-0 hover:opacity-70 transition-opacity ${!open ? "ml-10" : ""}`}
          >
            Insight AI
          </button>

          <form onSubmit={handleSearch} className="flex-1">
            <div className="relative group flex items-center">
              <input
                ref={inputRef}
                autoFocus
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

          <button onClick={handleNewConversation} title="대화 이력 초기화 (새 대화 시작)"
            className="flex items-center gap-2 px-4 py-2 rounded-full border text-base font-bold transition-all shrink-0 text-on-surface-variant hover:text-on-surface"
            style={{ background: AI.card, borderColor: AI.border }}
            onMouseEnter={e => e.currentTarget.style.borderColor = AI.accentLight}
            onMouseLeave={e => e.currentTarget.style.borderColor = AI.border}>
            <span className="material-symbols-outlined text-lg">restart_alt</span>새 대화
          </button>

          <div className="absolute bottom-0 left-0 w-full h-[1px] opacity-30"
            style={{ background: `linear-gradient(to right, transparent, ${AI.accent}, transparent)` }} />
            </div>
          </div>
        </header>
      )}

      {/* ════ RESULTS VIEW — 노멀 상세와 동일 12-col 그리드, 팔레트는 AI 오브 톤 ════ */}
      {view === 'results' && (
        <main
          className={`${ml} relative min-h-screen transition-[margin] duration-300`}
          style={{
            paddingTop: '128px',
            opacity: resultsReady ? 1 : 0,
            transform: resultsReady ? 'translateY(0)' : 'translateY(24px)',
            transition: 'opacity 0.38s ease, transform 0.38s ease, margin 0.3s',
          }}
        >
          <section className="mx-auto max-w-[1600px] px-8 pb-12">
            <div className="rounded-[30px] border border-[#41567f]/35 bg-[#0b1326]/66 p-6 shadow-[0_24px_70px_rgba(14,40,84,0.36)] backdrop-blur-xl sm:p-8">
            {/* 대시보드형 2컬럼: 좌 = 요약·KPI·목록 / 우 = AI 사이드 도크(sticky) */}
            <div className="flex flex-col gap-8 lg:flex-row lg:items-start lg:gap-10">

              {/* ── 좌측 메인 컬럼 ── */}
              <div className="min-w-0 flex-1 space-y-6">

                {/* 상단 헤더 — 인사 영역처럼 얇게 */}
                <div className="space-y-1">
                  <p className="text-[11px] font-bold uppercase tracking-[0.2em] text-on-surface-variant/50">
                    Insight AI<span className="mx-2 text-on-surface-variant/25">/</span>
                    검색 결과
                  </p>
                  <span
                    className="inline-flex rounded-md border border-violet-400/25 bg-violet-500/10 px-2 py-0.5 text-[10px] font-bold uppercase tracking-widest mt-3"
                    style={{ color: AI.accentLight }}
                  >
                    AI 쿼리
                  </span>
                  <h1 className="mt-2 break-words text-3xl font-extrabold tracking-tight text-on-surface sm:text-4xl lg:text-[2.25rem] lg:leading-tight">
                    {query}
                  </h1>
                  {finalQuery && finalQuery !== query && (
                    <p className="flex flex-wrap items-center gap-1.5 pt-1 text-xs" style={{ color: 'rgba(167,139,250,0.65)' }}>
                      <span className="material-symbols-outlined shrink-0 text-sm">arrow_forward</span>
                      최종 쿼리:{' '}
                      <span className="break-all font-mono font-bold" style={{ color: AI.accentLight }}>
                        &quot;{finalQuery}&quot;
                      </span>
                    </p>
                  )}
                  {streaming ? (
                    <p className="flex items-center gap-2 pt-2 text-sm text-on-surface-variant">
                      <span className="material-symbols-outlined animate-spin text-lg" style={{ color: AI.accent }}>
                        progress_activity
                      </span>
                      AI가 검색·분석 중...
                    </p>
                  ) : aiError ? (
                    <p className="pt-2 text-sm text-red-400">{aiError}</p>
                  ) : (
                    <p className="pt-2 text-sm text-on-surface-variant">
                      로컬 보관소에서{' '}
                      <span className="font-bold" style={{ color: AI.accentLight }}>
                        {results.length}건
                      </span>
                      을 찾았습니다.
                    </p>
                  )}
                </div>

                {/* KPI 3카드 행 */}
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                  {(
                    [
                      {
                        label: '총 결과',
                        value: streaming && results.length === 0 ? '—' : `${results.length}건`,
                        icon: 'dataset',
                      },
                      {
                        label: '최고 신뢰도',
                        value:
                          streaming && results.length === 0
                            ? '—'
                            : results.length > 0
                              ? `${Math.round((results[0]?.confidence ?? 0) * 100)}%`
                              : '—',
                        icon: 'trending_up',
                      },
                      {
                        label: '미디어',
                        value:
                          streaming && results.length === 0
                            ? '—'
                            : `${results.filter((r) => r.file_type === 'video' || r.file_type === 'audio').length}건`,
                        icon: 'smart_display',
                      },
                    ]
                  ).map(({ label, value, icon }) => (
                    <div
                      key={label}
                      className="rounded-2xl border border-white/[0.08] bg-white/[0.035] p-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.05)]"
                    >
                      <div className="mb-3 flex items-center justify-between gap-2">
                        <span className="text-[11px] font-bold uppercase tracking-wider text-on-surface-variant/45">
                          {label}
                        </span>
                        <span className="material-symbols-outlined text-[22px] opacity-70" style={{ color: AI.accentLight }}>
                          {icon}
                        </span>
                      </div>
                      <p className="text-2xl font-extrabold tabular-nums tracking-tight text-on-surface">{value}</p>
                    </div>
                  ))}
                </div>

                {/* 대형 목록 패널 */}
                <div
                  className="flex min-h-[360px] flex-col overflow-hidden rounded-[22px] border border-white/[0.07] bg-white/[0.02] shadow-[inset_0_1px_0_rgba(255,255,255,0.05)] backdrop-blur-[40px]"
                >
                  <div className="flex items-center justify-between border-b border-white/[0.08] px-6 pb-4 pt-5 sm:px-8 sm:pb-5 sm:pt-7">
                    <span className="text-sm font-bold uppercase tracking-[0.2em]" style={{ color: AI.accentLight }}>
                      매칭 파일
                    </span>
                    <div className="flex items-center gap-2">
                      {streaming && results.length === 0 && (
                        <span className="material-symbols-outlined animate-spin text-lg" style={{ color: AI.accent }}>
                          progress_activity
                        </span>
                      )}
                      <span className="h-2 w-2 animate-pulse rounded-full bg-[#52fac7]/90" />
                      <span className="h-2 w-2 rounded-full bg-white/15" />
                    </div>
                  </div>

                  <div className="flex flex-1 flex-col p-4 sm:p-5">
                    {streaming && results.length === 0 && (
                      <div className="flex flex-1 flex-col items-center justify-center gap-4 py-20">
                        <span className="material-symbols-outlined animate-spin text-5xl" style={{ color: AI.accent }}>
                          psychology
                        </span>
                        <p className="text-on-surface-variant">
                          <span style={{ color: AI.accentLight, fontWeight: 700 }}>AI</span>가 검색어를 분석하고 결과를
                          가져오는 중...
                        </p>
                      </div>
                    )}

                    {!streaming && !aiError && results.length === 0 && (
                      <div className="flex flex-1 flex-col items-center justify-center gap-4 py-20">
                        <span className="material-symbols-outlined text-6xl text-on-surface-variant/20">search_off</span>
                        <p className="text-on-surface-variant">일치하는 파일을 찾지 못했습니다.</p>
                      </div>
                    )}

                    {results.length > 0 && (
                      <div
                        className="grid gap-4"
                        style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))' }}
                      >
                        {results.map((r, i) => {
                          const isAiPick = aimodeSelected === i
                          return (
                            <div key={r.file_path + i} className="relative">
                              {isAiPick && (
                                <>
                                  <div
                                    className="pointer-events-none absolute inset-[-4px] z-10 animate-pulse rounded-[14px]"
                                    style={{
                                      background: 'transparent',
                                      boxShadow: `0 0 0 3px ${AI.accentLight}, 0 0 30px 5px rgba(168,85,247,0.55)`,
                                    }}
                                  />
                                  <div
                                    className="absolute -top-3 left-3 z-20 animate-bounce rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-widest text-white"
                                    style={{ background: AI.rankBg, boxShadow: AI.glow }}
                                  >
                                    🤖 AI 선택중...
                                  </div>
                                </>
                              )}
                              <AiResultCard result={r} rank={i + 1} onClick={() => handleSelectFile(r)} />
                            </div>
                          )
                        })}
                      </div>
                    )}
                  </div>
                </div>
              </div>

              {/* ── 우측 사이드 패널 (Exchange 스타일 단일 컬럼) ── */}
              {aiDockExpanded && (
                <button
                  type="button"
                  aria-label="AI 상태 확대 닫기"
                  onClick={() => setAiDockExpanded(false)}
                  className="fixed inset-0 z-[85] bg-black/55 backdrop-blur-[2px]"
                />
              )}
              <aside
                className={
                  aiDockExpanded
                    ? `fixed z-[90] ${leftEdge} right-0 top-24 bottom-6 px-6`
                    : 'w-full shrink-0 space-y-5 lg:sticky lg:top-[7.5rem] lg:w-[min(100%,380px)] xl:w-[400px]'
                }
              >
                <div className={aiDockExpanded
                  ? "h-full overflow-y-auto rounded-[24px] border border-white/[0.11] bg-[#120b23]/90 p-5 shadow-[0_30px_80px_rgba(0,0,0,0.55)] backdrop-blur-xl"
                  : "rounded-[24px] border border-white/[0.09] bg-white/[0.03] p-5 shadow-[0_24px_60px_rgba(0,0,0,0.35)] backdrop-blur-xl"}>
                  <div className="mb-5 flex items-center justify-between border-b border-white/[0.08] pb-4">
                    <div className="flex items-center gap-2">
                      <span className="material-symbols-outlined text-xl" style={{ color: AI.accentLight }}>
                        tune
                      </span>
                      <span className="text-sm font-bold uppercase tracking-[0.12em] text-on-surface">AI 상태</span>
                    </div>
                    <button
                      type="button"
                      onClick={() => setAiDockExpanded(v => !v)}
                      className="flex h-8 w-8 items-center justify-center rounded-full text-on-surface-variant/60 transition hover:bg-white/10 hover:text-on-surface"
                      title={aiDockExpanded ? '축소' : '확대'}
                    >
                      <span className="material-symbols-outlined text-xl" aria-hidden>
                        {aiDockExpanded ? 'close_fullscreen' : 'open_in_full'}
                      </span>
                    </button>
                  </div>

                  <div className="space-y-6">
                    {useAimode && aimodeSteps.length > 0 ? (
                      <div className="rounded-2xl border border-white/[0.06] bg-white/[0.02] p-4">
                        <div className="flex flex-wrap items-center gap-x-2 gap-y-2">
                          <span className="material-symbols-outlined shrink-0 text-lg" style={{ color: AI.accentLight }}>
                            auto_awesome
                          </span>
                          <span className="shrink-0 text-[10px] font-bold uppercase tracking-widest" style={{ color: AI.accentLight }}>
                            AI MODE
                          </span>
                        </div>
                        <div className="mt-3 flex flex-wrap items-center gap-x-1 gap-y-1">
                          {[1, 2, 3, 4].map((stepNum) => {
                            const s = aimodeSteps.find((st) => st.step === stepNum)
                            const labels = { 1: '분류', 2: '검색', 3: '선택', 4: '답변' }
                            const active = !!s
                            const done = s?.done
                            return (
                              <div key={stepNum} className="flex shrink-0 items-center gap-1.5 text-[11px]">
                                <div
                                  className={`flex h-5 w-5 items-center justify-center rounded-full border text-[10px] font-bold ${
                                    done
                                      ? 'border-[#52fac7] bg-teal-500/15 text-[#7af5d9]'
                                      : active
                                        ? 'animate-pulse border-fuchsia-400/80 text-fuchsia-200'
                                        : 'border-white/15 text-on-surface-variant/40'
                                  }`}
                                >
                                  {done ? '✓' : stepNum}
                                </div>
                                <span
                                  className={done ? 'text-[#7af5d9]' : active ? 'text-on-surface' : 'text-on-surface-variant/40'}
                                >
                                  {labels[stepNum]}
                                </span>
                                {stepNum < 4 && <span className="text-on-surface-variant/20">→</span>}
                              </div>
                            )
                          })}
                        </div>
                        {aimodeSteps.find((s) => s.step === 1 && s.done) && (
                          <div className="mt-3 flex flex-col gap-2 border-t border-white/[0.08] pt-3">
                            {[
                              { label: '파일검색', value: aimodeQuery, icon: 'folder_search', color: AI.accentLight },
                              { label: '내용검색', value: aimodeContentKws.join(' · '), icon: 'manage_search', color: ORB.mint },
                              { label: '상세내용', value: aimodeDetailKws.join(' · '), icon: 'lightbulb', color: ORB.coral },
                            ].map(({ label, value, icon, color }) =>
                              value ? (
                                <div key={label} className="flex min-w-0 flex-wrap items-baseline gap-1.5 text-[11px]">
                                  <span className="material-symbols-outlined shrink-0 text-sm" style={{ color }}>
                                    {icon}
                                  </span>
                                  <span className="shrink-0 text-on-surface-variant/50">{label}:</span>
                                  <span className="min-w-0 break-all font-mono font-semibold" style={{ color }}>
                                    &quot;{value}&quot;
                                  </span>
                                </div>
                              ) : null,
                            )}
                          </div>
                        )}
                      </div>
                    ) : null}

                    {results.length > 0 &&
                      (() => {
                        const bestPct = Math.round((results[0]?.confidence ?? 0) * 100)
                        const avgConfPct = Math.round(
                          (results.reduce((a, r) => a + (r.confidence ?? 0), 0) / results.length) * 100,
                        )
                        const avgSimPct = Math.round(
                          (results.reduce((a, r) => {
                            const d =
                              r.dense != null ? Math.max(0, Math.min(1, r.dense)) : (r.confidence ?? r.similarity ?? 0)
                            return a + d
                          }, 0) /
                            results.length) *
                            100,
                        )
                        const bars = [
                          { label: '신뢰도', pct: bestPct, text: 'text-[#ff59e0]' },
                          { label: '정확도', pct: avgConfPct, text: 'text-[#8cf2ff]' },
                          { label: '유사도', pct: avgSimPct, text: 'text-[#52fac7]' },
                        ]
                        return (
                          <div className="flex min-w-0 divide-x divide-white/[0.08] rounded-2xl border border-white/[0.06] bg-white/[0.02] p-3 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]">
                            {bars.map(({ label, pct, text }) => (
                              <div key={label} className="flex flex-1 flex-col items-center gap-1 px-2">
                                <span className={`text-xl font-extrabold tabular-nums leading-none ${text}`}>
                                  {pct}
                                  <span className="text-xs font-bold">%</span>
                                </span>
                                <span className="text-[10px] font-bold uppercase tracking-[0.08em] text-on-surface-variant/55">
                                  {label}
                                </span>
                              </div>
                            ))}
                          </div>
                        )
                      })()}

                    {results.length > 0 && (
                      <div>
                        <h4 className="mb-3 flex items-center gap-2 text-xs font-bold uppercase tracking-[0.15em]" style={{ color: AI.accentLight }}>
                          <span className="material-symbols-outlined text-[18px]">analytics</span>
                          결과 분포
                        </h4>
                        <div className="grid grid-cols-2 gap-2">
                          {[
                            ['총 결과', `${results.length}건`],
                            ['최고 신뢰도', `${Math.round((results[0]?.confidence ?? 0) * 100)}%`],
                            [
                              '문서·이미지',
                              `${results.filter((r) => r.file_type === 'doc' || r.file_type === 'image').length}건`,
                            ],
                            [
                              '영상·음성',
                              `${results.filter((r) => r.file_type === 'video' || r.file_type === 'audio').length}건`,
                            ],
                          ].map(([k, v]) => (
                            <div key={k} className="rounded-xl border border-white/[0.06] bg-black/25 p-2.5">
                              <p className="mb-0.5 text-[10px] font-bold uppercase tracking-widest text-on-surface-variant/50">
                                {k}
                              </p>
                              <p className="text-base font-bold text-on-surface">{v}</p>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {(aimodeQuery || aimodeContentKws.length > 0 || aimodeDetailKws.length > 0) && (
                      <div>
                        <h4 className="mb-3 text-xs font-bold uppercase tracking-[0.15em]" style={{ color: AI.accentLight }}>
                          검색 컨텍스트
                        </h4>
                        <div className="space-y-0 rounded-xl border border-white/[0.06] bg-black/20 px-3">
                          {[
                            ['파일검색', aimodeQuery || '—'],
                            ['내용검색', aimodeContentKws.length ? aimodeContentKws.join(' · ') : '—'],
                            ['상세내용', aimodeDetailKws.length ? aimodeDetailKws.join(' · ') : '—'],
                          ].map(([k, v]) => (
                            <div
                              key={k}
                              className="flex items-start justify-between gap-2 border-b border-white/[0.06] py-2.5 text-[11px] last:border-0"
                            >
                              <span className="shrink-0 text-on-surface-variant/70">{k}</span>
                              <span className="break-all text-right font-semibold text-on-surface">{v}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {streaming && results.length === 0 && (
                      <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] px-4 py-3 text-center text-xs text-on-surface-variant">
                        AIMODE 파이프라인이 실행 중입니다. 잠시만 기다려 주세요.
                      </div>
                    )}

                    {useAimode && aimodeAnswer && !streaming && (
                      <div className="relative overflow-hidden rounded-xl border border-white/[0.08] bg-white/[0.03]">
                        <div className="pointer-events-none absolute inset-0 bg-gradient-to-br from-fuchsia-500/[0.07] via-transparent to-violet-500/[0.08]" />
                        <div className="relative flex items-center gap-3 border-b border-white/[0.08] px-4 py-2.5">
                          <span className="material-symbols-outlined text-lg" style={{ color: AI.accentLight }}>
                            stylus
                          </span>
                          <span className="text-[11px] font-bold uppercase tracking-widest" style={{ color: AI.accentLight }}>
                            초안 답변
                          </span>
                          {aimodeDone ? (
                            <span className="ml-auto flex items-center gap-1 text-[11px] text-[#7af5d9]">
                              <span className="material-symbols-outlined text-base">check_circle</span> 완료
                            </span>
                          ) : (
                            <span className="ml-auto flex items-center gap-1 text-[11px]" style={{ color: AI.accentLight }}>
                              <span className="material-symbols-outlined animate-spin text-base">progress_activity</span>
                              작성 중
                            </span>
                          )}
                        </div>
                        <div className="relative px-4 py-3 text-xs leading-relaxed text-on-surface/95 whitespace-pre-wrap">
                          {stripMarkdown(aimodeAnswer)}
                          {!aimodeDone && (
                            <span
                              className="ml-1 inline-block h-4 w-0.5 animate-pulse align-middle"
                              style={{ background: AI.accentLight }}
                            />
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              </aside>
            </div>
            </div>

            {/* HIDDEN — old detailed panel preserved for backward compat (do not render) */}
            {false && useAimode && (aimodeSteps.length > 0 || aimodeAnswer) && (
              <div className="mb-6 rounded-2xl border p-5 space-y-4"
                style={{ background: AI.card, borderColor: AI.border }}>
                <div className="flex items-center gap-2">
                  <span className="material-symbols-outlined text-lg" style={{ color: AI.accentLight }}>auto_awesome</span>
                  <span className="text-xs uppercase tracking-widest font-bold"
                    style={{ color: AI.accentLight }}>AI MODE — 시각화 추적</span>
                </div>

                {/* 사용자 질문 */}
                <div className="text-sm">
                  <span className="text-on-surface-variant text-xs">▼ 사용자 질문</span>
                  <div className="mt-1 px-3 py-2 rounded-lg bg-white/5 border border-outline-variant/15">
                    {finalQuery}
                  </div>
                </div>

                {/* Step 1: 검색어 추출 */}
                {aimodeSteps.find(s => s.step === 1) && (
                  <div>
                    <div className="text-xs text-on-surface-variant mb-1 flex items-center gap-1">
                      <span className="material-symbols-outlined text-base" style={{ color: ORB.electric }}>search</span>
                      Step 1 — 검색어 추출
                      {aimodeSteps.find(s => s.step === 1 && s.done) && (
                        <span className="material-symbols-outlined ml-auto text-base text-[#7af5d9]">check_circle</span>
                      )}
                    </div>
                    <div className="px-3 py-2 rounded-lg bg-amber-500/10 border border-amber-500/20 font-mono text-sm">
                      {aimodeQuery || '...'}
                    </div>
                  </div>
                )}

                {/* Step 2: 검색 결과 카드 */}
                {aimodeSteps.find(s => s.step === 2) && (
                  <div>
                    <div className="text-xs text-on-surface-variant mb-2 flex items-center gap-1">
                      <span className="material-symbols-outlined text-base" style={{ color: ORB.electric }}>folder_open</span>
                      Step 2 — 데이터베이스 검색 ({aimodeSources.length}건)
                      {aimodeSteps.find(s => s.step === 2 && s.done) && (
                        <span className="material-symbols-outlined ml-auto text-base text-[#7af5d9]">check_circle</span>
                      )}
                    </div>
                    <div className="grid gap-2" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))' }}>
                      {aimodeSources.slice(0, 6).map((s, i) => {
                        const isSelected = aimodeSelected === i
                        return (
                          <div key={i} className={`rounded-lg p-2 border transition-all ${
                            isSelected
                              ? 'bg-gradient-to-br from-purple-500/30 to-pink-500/20 border-purple-400 shadow-[0_0_20px_rgba(168,85,247,0.5)] scale-[1.03]'
                              : 'bg-white/5 border-outline-variant/15'
                          }`}>
                            <div className="flex items-center gap-1 text-[10px] mb-1">
                              <span className={`px-1.5 py-0.5 rounded font-bold ${isSelected ? 'bg-purple-400 text-white' : 'bg-white/10'}`}>
                                #{i + 1}
                              </span>
                              <span className="text-on-surface-variant uppercase">{s.file_type || s.domain || ''}</span>
                              <span className="ml-auto font-mono font-bold text-[#7af5d9]">
                                {((s.confidence ?? 0) * 100).toFixed(0)}%
                              </span>
                            </div>
                            <div className="text-xs font-semibold truncate">{s.file_name || '?'}</div>
                            {s.snippet && (
                              <div className="text-[10px] text-on-surface-variant/70 mt-1 line-clamp-2">
                                {s.snippet.slice(0, 60)}
                              </div>
                            )}
                          </div>
                        )
                      })}
                    </div>
                  </div>
                )}

                {/* Step 3: 카드 선택 */}
                {aimodeSteps.find(s => s.step === 3) && aimodeSources[aimodeSelected ?? 0] && (
                  <div>
                    <div className="text-xs text-on-surface-variant mb-1 flex items-center gap-1">
                      <span className="material-symbols-outlined text-base text-purple-400">center_focus_strong</span>
                      Step 3 — #{(aimodeSelected ?? 0) + 1} 자동 선택
                      <span className="material-symbols-outlined ml-auto text-base text-[#7af5d9]">check_circle</span>
                    </div>
                    <div className="px-3 py-2 rounded-lg bg-purple-500/10 border border-purple-500/30 text-sm">
                      <span className="text-purple-300 font-bold">선택:</span>{' '}
                      {aimodeSources[aimodeSelected ?? 0]?.file_name || '?'}
                    </div>
                  </div>
                )}

                {/* Step 4: 답변 */}
                {(aimodeSteps.find(s => s.step === 4) || aimodeAnswer) && (
                  <div>
                    <div className="text-xs text-on-surface-variant mb-1 flex items-center gap-1">
                      <span className="material-symbols-outlined text-base text-pink-400 animate-pulse">stylus</span>
                      Step 4 — 답변 정리 {aimodeDone && (
                        <span className="material-symbols-outlined ml-auto text-base text-[#7af5d9]">check_circle</span>
                      )}
                    </div>
                    <div className="px-4 py-3 rounded-lg bg-gradient-to-br from-pink-500/10 to-purple-500/10 border border-pink-500/20 text-sm whitespace-pre-wrap leading-relaxed">
                      {aimodeAnswer || (
                        <span className="text-on-surface-variant/50 italic">생성 중...</span>
                      )}
                      {!aimodeDone && aimodeAnswer && (
                        <span className="inline-block w-2 h-4 bg-pink-400 ml-1 animate-pulse align-middle"></span>
                      )}
                    </div>
                  </div>
                )}
              </div>
            )}

          </section>
        </main>
      )}

      {/* ════ DETAIL VIEW ════ */}
      {view === 'detail' && selectedFile && (() => {
        const meta    = getTypeMeta(selectedFile.file_type)
        const confPct = Math.round((selectedFile.confidence ?? selectedFile.similarity ?? 0) * 100)
        const isAV    = selectedFile.file_type === 'video' || selectedFile.file_type === 'audio'

        return (
          <main className={`${ml} relative min-h-screen bg-gradient-to-b from-transparent via-transparent to-[#0d0718]/45 transition-[margin] duration-300`}
            style={{ opacity: detailVisible ? 1 : 0, transform: detailVisible ? 'translateX(0)' : 'translateX(36px)',
              transition: 'opacity 0.35s ease, transform 0.35s ease, margin 0.3s' }}>

            {/* 파일 정보 바 */}
            <div className={`fixed top-24 ${leftEdge} right-0 z-30 backdrop-blur-xl flex items-center justify-between px-8 py-3 border-b transition-[left] duration-300`}
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

            <section className="pt-44 pb-12 px-8 max-w-7xl mx-auto space-y-8">
              {/* ★ AI 답변 패널 — AI 가 자동 선택한 카드와 일치할 때만 표시
                  (사용자가 다른 카드 클릭 시에는 답변 숨김 — 답변은 AI 가 분석한 카드에만 유효) */}
              {(() => {
                const aiPickedFile = aimodeSources[aimodeSelected ?? -1]
                const isAiPicked = aiPickedFile &&
                  (aiPickedFile.file_path === selectedFile.file_path ||
                   aiPickedFile.trichef_id === selectedFile.trichef_id)
                if (!isAiPicked) {
                  // 사용자가 다른 카드 클릭 — 답변 대신 안내 메시지 + AI 요약 유도
                  return aimodeAnswer ? (
                    <div className="rounded-xl px-6 py-4 border flex items-center gap-3"
                      style={{ background: AI.card, borderColor: AI.border, color: 'rgba(167,139,250,0.7)' }}>
                      <span className="material-symbols-outlined text-base">info</span>
                      <span className="text-sm">
                        AI 답변은 자동 선택된 <span className="font-mono">"{aiPickedFile?.file_name}"</span> 에 대한 내용입니다.
                        이 파일에 대한 요약은 <span className="font-bold" style={{ color: AI.accentLight }}>일반 검색의 AI 요약 기능</span> 을 사용하세요.
                      </span>
                    </div>
                  ) : null
                }
                return null
              })()}
              {(aimodeAnswer || aimodeSteps.find(s => s.step === 4)) && (() => {
                const aiPickedFile = aimodeSources[aimodeSelected ?? -1]
                const isAiPicked = aiPickedFile &&
                  (aiPickedFile.file_path === selectedFile.file_path ||
                   aiPickedFile.trichef_id === selectedFile.trichef_id)
                if (!isAiPicked) return null
                return (
                <div className="rounded-2xl border overflow-hidden relative"
                  style={{ background: 'linear-gradient(135deg, rgba(109,40,217,0.12), rgba(192,38,211,0.08))',
                    borderColor: AI.borderHover,
                    boxShadow: '0 0 30px rgba(168,85,247,0.15)' }}>
                  <div className="px-6 py-3 flex items-center gap-3 border-b"
                    style={{ borderColor: AI.border, background: 'rgba(13,7,24,0.4)' }}>
                    <span className="material-symbols-outlined animate-pulse" style={{ color: AI.accentLight }}>auto_awesome</span>
                    <span className="text-xs uppercase tracking-widest font-bold" style={{ color: AI.accentLight }}>
                      AI 답변 — 본문에서 찾은 내용
                    </span>
                    {aimodeDone ? (
                      <span className="ml-auto flex items-center gap-1 text-[10px] text-[#7af5d9]">
                        <span className="material-symbols-outlined text-base">check_circle</span> 완료
                      </span>
                    ) : (
                      <span className="ml-auto text-[10px] flex items-center gap-1" style={{ color: AI.accentLight }}>
                        <span className="material-symbols-outlined text-base animate-spin">progress_activity</span> 작성 중
                      </span>
                    )}
                  </div>
                  <div className="px-6 py-5 leading-relaxed text-on-surface text-base whitespace-pre-wrap min-h-[80px]">
                    {aimodeAnswer ? stripMarkdown(aimodeAnswer) : (
                      <span className="text-on-surface-variant/40 italic">본문을 분석해 답변을 정리하는 중입니다...</span>
                    )}
                    {!aimodeDone && aimodeAnswer && (
                      <span className="inline-block w-2 h-4 ml-1 align-middle animate-pulse"
                        style={{ background: AI.accentLight }} />
                    )}
                  </div>
                  {(aimodeQuery || aimodeContentKws.length > 0) && (
                    <div className="px-6 py-2 border-t flex flex-wrap items-center gap-3 text-[11px]"
                      style={{ borderColor: AI.border, background: 'rgba(13,7,24,0.4)' }}>
                      {aimodeQuery && <>
                        <span className="material-symbols-outlined text-sm" style={{ color: AI.accentDark }}>folder_search</span>
                        <span className="text-on-surface-variant/50">파일검색:</span>
                        <span className="font-mono font-semibold" style={{ color: AI.accentLight }}>"{aimodeQuery}"</span>
                      </>}
                      {aimodeContentKws.length > 0 && <>
                        <span className="text-on-surface-variant/20">|</span>
                        <span className="material-symbols-outlined text-sm" style={{ color: ORB.mint }}>manage_search</span>
                        <span className="text-on-surface-variant/50">내용검색:</span>
                        <span className="font-mono font-semibold" style={{ color: ORB.mint }}>"{aimodeContentKws.join(' · ')}"</span>
                      </>}
                      {aimodeDetailKws.length > 0 && <>
                        <span className="text-on-surface-variant/20">|</span>
                        <span className="material-symbols-outlined text-sm" style={{ color: ORB.coral }}>lightbulb</span>
                        <span className="text-on-surface-variant/50">상세내용:</span>
                        <span className="font-mono font-semibold" style={{ color: ORB.coral }}>"{aimodeDetailKws.join(' · ')}"</span>
                      </>}
                    </div>
                  )}
                </div>
                )
              })()}

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
                  {/* 신뢰도 · 정확도 · 유사도 통합 패널 */}
                  {(() => {
                    const conf = selectedFile.confidence ?? selectedFile.similarity ?? 0
                    const dense = selectedFile.dense
                    const rerank = selectedFile.rerank_score ?? selectedFile.rerank
                    const zScore = selectedFile.z_score
                    const lexical = selectedFile.lexical
                    const sigm = (x) => 1 / (1 + Math.exp(-x))
                    const d01 = dense != null ? Math.max(0, Math.min(1, dense)) : 0
                    const ft = selectedFile.file_type
                    // 정확도 — 도메인 인지 폴백 (카드와 동일)
                    let acc
                    if (rerank != null) {
                      const s = sigm(rerank)
                      if (s >= 0.5) {
                        acc = s
                      } else if (ft === 'image') {
                        acc = Math.max(d01 * 0.9, s)  // 이미지는 dense 우선
                      } else {
                        acc = s * 0.4 + d01 * 0.6
                      }
                    } else if (zScore != null) {
                      acc = Math.max(0, Math.min(1, (zScore + 3) / 6))
                    } else if (lexical != null && d01 > 0) {
                      acc = d01 * 0.7 + Math.min(1, lexical * 1.5) * 0.3
                    } else {
                      acc = d01 > 0 ? d01 * 0.85 : conf * 0.9
                    }
                    // 유사도: dense 기반
                    const sim = d01 > 0 ? d01 : conf
                    const ROWS = [
                      {
                        label: '신뢰도', value: conf, source: rerank != null ? 'Rerank+Calib' : 'Hermitian',
                        desc: 'Calibration 적용 후 종합 점수',
                        gradFrom: AI.accentDark, gradTo: AI.accentLight,
                      },
                      {
                        label: '정확도', value: acc, source: rerank != null ? 'BGE-reranker-v2-m3' : (zScore != null ? 'z-score' : 'sparse·lexical'),
                        desc: 'Cross-encoder 재정렬 확률',
                        gradFrom: '#0d9488', gradTo: ORB.mint,
                      },
                      {
                        label: '유사도', value: sim, source: 'SigLIP2 / BGE-M3 dense',
                        desc: '벡터 임베딩 코사인 유사도 (정규화)',
                        gradFrom: ORB.navy, gradTo: ORB.electric,
                      },
                    ]
                    return (
                      <div className="rounded-xl p-6 border relative overflow-hidden"
                        style={{ background: AI.card, borderColor: AI.border }}>
                        <div className="absolute -right-4 -top-4 w-24 h-24 blur-3xl" style={{ background: 'rgba(109,40,217,0.15)' }} />
                        <h4 className="text-[11px] font-bold tracking-[0.15em] uppercase mb-4 flex items-center gap-2"
                          style={{ color: AI.accentLight }}>
                          <span className="material-symbols-outlined text-sm">analytics</span>
                          점수 분해
                        </h4>
                        {/* 가로 3 컬럼 — 라벨 + % 만, bar 없음 */}
                        <div className="grid grid-cols-3 gap-2">
                          {ROWS.map((r) => {
                            const pct = Math.max(0, Math.min(100, (r.value || 0) * 100))
                            return (
                              <div key={r.label} title={`${r.desc} · ${r.source}`}
                                className="flex flex-col items-center justify-center py-2 px-1 rounded-lg"
                                style={{ background: 'rgba(255,255,255,0.02)' }}>
                                <span className="text-[10px] uppercase tracking-widest text-on-surface-variant/60 mb-1">
                                  {r.label}
                                </span>
                                <span className="text-2xl font-extrabold tabular-nums leading-none"
                                  style={{ color: r.gradTo }}>
                                  {pct.toFixed(1)}<span className="text-sm font-bold">%</span>
                                </span>
                              </div>
                            )
                          })}
                        </div>
                      </div>
                    )
                  })()}

                  {/* 파일 정보 */}
                  <div className="rounded-xl p-6 border" style={{ background: AI.card, borderColor: AI.border }}>
                    <h4 className="text-[11px] font-bold tracking-[0.15em] uppercase mb-4" style={{ color: AI.accentLight }}>파일 정보</h4>
                    <div className="space-y-3">
                      {[
                        ['파일명', selectedFile.file_name],
                        ['타입', meta.label],
                        selectedFile.page_num != null ? ['페이지', `${selectedFile.page_num}p`] : null,
                        ['경로', selectedFile.file_path],
                      ].filter(Boolean).map(([label, val]) => (
                        <div key={label} className="flex gap-3 py-2 border-b last:border-0" style={{ borderColor: AI.border }}>
                          <span className="text-[10px] uppercase tracking-widest min-w-[60px] shrink-0" style={{ color: 'rgba(167,139,250,0.5)' }}>{label}</span>
                          <span className="text-[11px] text-on-surface-variant break-all font-mono">{val}</span>
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* (legacy "검색 여정" 패널 제거 — AIMODE 는 단일 호출이라 의미 없음) */}
                </div>
              </div>
            </section>
          </main>
        )
      })()}
    </div>
  );
}
