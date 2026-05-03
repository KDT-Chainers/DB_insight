import { useState, useRef, useEffect, useCallback, Fragment } from 'react'
import { useNavigate } from 'react-router-dom'
import SearchSidebar from '../components/SearchSidebar'
import { useSidebar } from '../context/SidebarContext'
import { API_BASE } from '../api'
import LocationBadge from '../components/search/LocationBadge'
import DomainFilter from '../components/search/DomainFilter'
import ScoreBreakdown from '../components/search/ScoreBreakdown'

// ── 파일 타입 메타 ───────────────────────────────────────
const TYPE_META = {
  doc:   { icon: 'description', color: 'text-[#85adff]',   label: '문서',   grad: 'from-[#1e3a8a] to-[#1e40af]' },
  video: { icon: 'movie',       color: 'text-[#ac8aff]',   label: '동영상', grad: 'from-[#4c1d95] to-[#5b21b6]' },
  image: { icon: 'image',       color: 'text-emerald-400', label: '이미지', grad: 'from-[#064e3b] to-[#065f46]' },
  audio: { icon: 'volume_up',   color: 'text-amber-400',   label: '음성',   grad: 'from-[#78350f] to-[#92400e]' },
  movie: { icon: 'movie',       color: 'text-[#ac8aff]',   label: '동영상', grad: 'from-[#4c1d95] to-[#5b21b6]' },
  music: { icon: 'volume_up',   color: 'text-amber-400',   label: '음성',   grad: 'from-[#78350f] to-[#92400e]' },
  bgm:   { icon: 'music_note',  color: 'text-pink-400',    label: 'BGM',    grad: 'from-[#831843] to-[#9d174d]' },
}
const getTypeMeta = (t) =>
  TYPE_META[t] ?? { icon: 'insert_drive_file', color: 'text-on-surface-variant', label: t ?? '파일', grad: 'from-[#1c253e] to-[#263354]' }

// ── 경량 Markdown 렌더러 (## ### **bold** *italic* `code` - bullet > quote --- hr) ──
// LLM 출력을 추가 의존성 없이 풍부한 UI 로 렌더. 외부 패키지 없음.
function MarkdownLite({ text }) {
  if (!text) return null
  // 인라인 패턴 — bold, italic, code, link
  const renderInline = (s, baseKey = 'i') => {
    // 순서 중요: code → bold → italic → link
    const parts = []
    let buf = s
    let key = 0
    const push = (chunk) => parts.push(<Fragment key={`${baseKey}-${key++}`}>{chunk}</Fragment>)
    // 단순 토큰 파서 (regex 기반 누적)
    const re = /(\*\*[^*\n]+\*\*)|(\*[^*\n]+\*)|(`[^`\n]+`)|(\[[^\]]+\]\([^)]+\))/g
    let last = 0
    let m
    while ((m = re.exec(buf)) !== null) {
      if (m.index > last) push(buf.slice(last, m.index))
      const tok = m[0]
      if (tok.startsWith('**'))      push(<strong className="text-white font-bold">{tok.slice(2, -2)}</strong>)
      else if (tok.startsWith('`'))  push(<code className="px-1.5 py-0.5 rounded bg-purple-500/20 text-purple-200 font-mono text-[0.92em]">{tok.slice(1, -1)}</code>)
      else if (tok.startsWith('['))  {
        const mm = /\[([^\]]+)\]\(([^)]+)\)/.exec(tok)
        if (mm) push(<a href={mm[2]} className="text-purple-300 underline" target="_blank" rel="noreferrer">{mm[1]}</a>)
        else push(tok)
      }
      else if (tok.startsWith('*'))  push(<em className="italic text-purple-100">{tok.slice(1, -1)}</em>)
      else                            push(tok)
      last = m.index + tok.length
    }
    if (last < buf.length) push(buf.slice(last))
    return parts
  }

  // 라인 단위 처리 — heading, list, blockquote, hr, paragraph
  const lines = text.split('\n')
  const blocks = []
  let para = []   // 현재 문단 라인 누적
  let list = null // {type:'ul'|'ol', items:[[lines]]}
  const flushPara = () => {
    if (para.length) {
      blocks.push(
        <p key={`p${blocks.length}`} className="leading-[1.85] text-on-surface/95 my-3">
          {renderInline(para.join(' '), `p${blocks.length}`)}
        </p>
      )
      para = []
    }
  }
  const flushList = () => {
    if (list && list.items.length) {
      const Tag = list.type === 'ol' ? 'ol' : 'ul'
      blocks.push(
        <Tag key={`l${blocks.length}`} className={`my-3 ml-5 space-y-1.5 ${list.type === 'ol' ? 'list-decimal' : 'list-disc'} marker:text-purple-400`}>
          {list.items.map((line, i) => (
            <li key={i} className="leading-[1.7] text-on-surface/95 pl-1">
              {renderInline(line, `l${blocks.length}-${i}`)}
            </li>
          ))}
        </Tag>
      )
      list = null
    }
  }

  for (let i = 0; i < lines.length; i++) {
    const raw = lines[i]
    const line = raw.trimEnd()

    // 빈 줄 → 문단 종결
    if (!line.trim()) { flushPara(); flushList(); continue }

    // ### / ## / # 헤딩
    let m
    if ((m = /^###\s+(.+)$/.exec(line))) {
      flushPara(); flushList()
      blocks.push(
        <h3 key={`h${blocks.length}`} className="text-base font-bold text-purple-200 mt-5 mb-2 flex items-center gap-2">
          <span className="w-1 h-4 rounded-full bg-purple-400" />
          {renderInline(m[1], `h${blocks.length}`)}
        </h3>
      )
      continue
    }
    if ((m = /^##\s+(.+)$/.exec(line))) {
      flushPara(); flushList()
      blocks.push(
        <h2 key={`h${blocks.length}`} className="text-lg font-bold text-purple-100 mt-6 mb-3 pb-1 border-b border-purple-500/30">
          {renderInline(m[1], `h${blocks.length}`)}
        </h2>
      )
      continue
    }
    if ((m = /^#\s+(.+)$/.exec(line))) {
      flushPara(); flushList()
      blocks.push(
        <h1 key={`h${blocks.length}`} className="text-xl font-bold text-purple-50 mt-7 mb-3">
          {renderInline(m[1], `h${blocks.length}`)}
        </h1>
      )
      continue
    }

    // 수평선 ---
    if (/^[-*_]{3,}\s*$/.test(line)) {
      flushPara(); flushList()
      blocks.push(<hr key={`hr${blocks.length}`} className="my-4 border-purple-500/20" />)
      continue
    }

    // 인용문 >
    if ((m = /^>\s+(.+)$/.exec(line))) {
      flushPara(); flushList()
      blocks.push(
        <blockquote key={`q${blocks.length}`} className="border-l-4 border-purple-400/50 pl-4 my-3 italic text-purple-100/80">
          {renderInline(m[1], `q${blocks.length}`)}
        </blockquote>
      )
      continue
    }

    // 순서 있는 리스트  1. xx
    if ((m = /^\d+\.\s+(.+)$/.exec(line))) {
      flushPara()
      if (!list || list.type !== 'ol') { flushList(); list = { type: 'ol', items: [] } }
      list.items.push(m[1])
      continue
    }
    // 순서 없는 리스트  - xx  / * xx
    if ((m = /^[-*]\s+(.+)$/.exec(line))) {
      flushPara()
      if (!list || list.type !== 'ul') { flushList(); list = { type: 'ul', items: [] } }
      list.items.push(m[1])
      continue
    }

    // 일반 문단 — 줄 누적
    flushList()
    para.push(line.trim())
  }
  flushPara(); flushList()

  return <div className="markdown-lite">{blocks}</div>
}

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

// ── 이미지 업로드 → 이미지 검색 (TRI-CHEF) ────────────
async function searchByImage(file, topK = 30) {
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
    file_path:      r.source_path || r.id,
    file_name:      r.file_name || (r.id || '').split('/').pop(),
    file_type:      'image',
    confidence:     r.confidence ?? 0,
    similarity:     r.confidence ?? 0,
    dense:          r.dense ?? 0,
    snippet:        r.caption ?? '',
    preview_url:    r.preview_url ?? null,
    segments:       [],
    trichef_id:     r.id,
    trichef_domain: 'image',
  }))
}

// ── BGM 결과 행 → MainSearch 결과 카드 형식 변환 ──────────
function _mapBgmRow(r) {
  const title  = r.acr_title  || r.guess_title  || (r.filename || '').replace(/\.[^.]+$/, '')
  const artist = r.acr_artist || r.guess_artist || ''
  const conf   = r.confidence ?? r.score ?? 0
  return {
    file_path:      r.filename,                   // BGM은 RAW_BGM_DIR 내부 — preview는 /api/bgm/file 사용
    file_name:      r.filename,
    file_type:      'bgm',
    confidence:     conf,
    similarity:     conf,
    dense:          r.dense ?? r.score ?? conf,
    snippet:        artist ? `${artist} · ${title}` : title,
    preview_url:    null,
    segments:       r.segments || [],             // [{start, end, score, label}]
    bgm_filename:   r.filename,
    bgm_artist:     artist,
    bgm_title:      title,
    bgm_tags:       r.tags || [],
    bgm_duration:   r.duration ?? 0,
    bgm_acr:        Boolean(r.acr_artist || r.acr_title),
    bgm_top_segment: r.top_segment || null,
    bgm_source:     r.source || 'catalog',        // catalog | movie_lib | rec_lib
    trichef_domain: 'bgm',
  }
}

async function searchBgm(query, topK = 20) {
  const res = await fetch(`${API_BASE}/api/bgm/search`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, top_k: topK }),
  })
  if (!res.ok) {
    // BGM 인덱스가 없거나 엔진 미준비여도 일반 검색은 계속되도록 빈 배열 반환
    return []
  }
  const data = await res.json()
  if (data.error) return []
  return (data.results ?? []).map(_mapBgmRow)
}

// ── 검색 API ────────────────────────────────────────────
async function searchFiles(query, topK = 20, type = '') {
  // BGM 단독 도메인일 때는 /api/bgm/search 만 호출
  if (type === 'bgm') {
    return await searchBgm(query, topK)
  }

  const typeQ = type ? `&type=${encodeURIComponent(type)}` : ''
  const generalP = fetch(`${API_BASE}/api/search?q=${encodeURIComponent(query)}&top_k=${topK}${typeQ}`)
    .then(async (res) => {
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      if (data.error) throw new Error(data.error)
      return (data.results ?? []).map(r => ({
        ...r,
        confidence: r.confidence ?? r.similarity ?? 0,
        similarity:  r.similarity  ?? r.confidence ?? 0,
        segments:    r.segments    ?? [],
      }))
    })

  // 도메인 필터가 비어 있을 때(전체 검색)에만 BGM도 병합
  const bgmP = type === '' ? searchBgm(query, Math.max(5, Math.floor(topK / 2))) : Promise.resolve([])

  const [general, bgm] = await Promise.all([generalP, bgmP.catch(() => [])])
  // BGM은 confidence 내림차순으로 일반 결과 사이에 자연 병합
  const merged = [...general, ...bgm]
  merged.sort((a, b) => (b.confidence ?? 0) - (a.confidence ?? 0))
  return merged
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

// ── 한↔영 양방향 사전 (location_resolver.py 와 동기화) ────
const KO_EN_BIDICT = {
  '취업':   ['employment', 'employ', 'job', 'hire', 'career'],
  '교육':   ['education', 'educational', 'learning', 'training'],
  '학습':   ['learning', 'study', 'studying'],
  '분석':   ['analysis', 'analytical'],
  '통계':   ['statistics', 'statistical'],
  '보고서': ['report', 'yearbook'],
  '예산':   ['budget', 'fiscal'],
  '정책':   ['policy', 'policies'],
  '기술':   ['technology', 'technical'],
  '연구':   ['research', 'study'],
  '회의':   ['meeting', 'conference'],
  '환경':   ['environment', 'environmental'],
  '사람':   ['person', 'people'],
  '정보':   ['information'],
  '서비스': ['service'],
  '산업':   ['industry', 'industrial'],
  '건강':   ['health'],
  '개발':   ['development', 'develop'],
  '관리':   ['management', 'manage'],
  '운영':   ['operation'],
  '투자':   ['investment', 'invest'],
  '지원':   ['support', 'subsidy'],
  '기업':   ['company', 'corporate', 'enterprise'],
  '시장':   ['market'],
  '데이터': ['data'],
  '인공지능': ['ai', 'artificial intelligence'],
  '보안':   ['security'],
  '데이터센터': ['data center', 'datacenter'],
}

function expandQueryTokens(query) {
  if (!query) return []
  const raw = (query.match(/[\w가-힣]+/g) || [])
    .map(t => t.toLowerCase())
    .filter(t => t.length >= 2)
  const tokens = [...new Set(raw)]
  // 양방향 확장
  const reverse = {}
  Object.entries(KO_EN_BIDICT).forEach(([ko, ens]) => {
    ens.forEach(en => {
      reverse[en.toLowerCase()] = (reverse[en.toLowerCase()] || []).concat(ko)
    })
  })
  const out = new Set(tokens)
  tokens.forEach(t => {
    (KO_EN_BIDICT[t] || []).forEach(en => out.add(en.toLowerCase()))
    ;(reverse[t] || []).forEach(ko => out.add(ko))
  })
  return [...out]
}

// 별점 + 백분율 — "★★★★☆ 87%"
// 백엔드가 confidence (이미 z-score CDF normalize) 를 줄 때는 그대로 사용,
// 없으면 raw score 를 보수적 정규화 (legacy fallback).
function _legacyNormalize(s) {
  const x = Math.max(0, Number(s) || 0)
  if (x <= 0.2)  return (x / 0.2) * 0.30
  if (x <= 0.4)  return 0.30 + (x - 0.2) / 0.2 * 0.35
  if (x <= 0.55) return 0.65 + (x - 0.4) / 0.15 * 0.30
  return Math.min(1.0, 0.95 + (x - 0.55) / 0.15 * 0.05)
}

function ScoreStars({ score, confidence, className = '' }) {
  // confidence (backend z-score CDF) 우선 — 5도메인 통합 % 표시
  const norm = (confidence != null && Number.isFinite(Number(confidence)))
    ? Math.max(0, Math.min(1, Number(confidence)))
    : _legacyNormalize(score)
  const pct = Math.round(norm * 100)
  const fillCount = Math.max(0, Math.min(5, Math.round(norm * 5)))
  const stars = '★'.repeat(fillCount) + '☆'.repeat(5 - fillCount)
  return (
    <span className={`inline-flex items-center gap-1 ${className}`}>
      <span className="text-yellow-400 font-mono tracking-tighter">{stars}</span>
      <span className="font-mono text-on-surface-variant">{pct}%</span>
    </span>
  )
}

// 검색어 토큰을 텍스트에서 찾아 <mark> 로 감싸기 (React fragments)
function HighlightedText({ text, query, className = '' }) {
  if (!text) return null
  const tokens = expandQueryTokens(query)
  if (!tokens.length) return <>{text}</>
  // 길이 내림차순 (긴 토큰 우선 매칭)
  const sorted = [...tokens].sort((a, b) => b.length - a.length)
  const escaped = sorted.map(t => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
  const re = new RegExp(`(${escaped.join('|')})`, 'gi')
  const parts = String(text).split(re)
  return (
    <span className={className}>
      {parts.map((p, i) => {
        if (!p) return null
        const lower = p.toLowerCase()
        const isMatch = tokens.some(t => lower === t)
        if (isMatch) {
          return (
            <mark key={i} className="bg-yellow-400/35 text-yellow-100 px-0.5 rounded font-semibold">
              {p}
            </mark>
          )
        }
        return <span key={i}>{p}</span>
      })}
    </span>
  )
}

// ── 결과 카드 (admin.html card / avCard 구조 대응) ────────
function ResultCard({ result, rank, onClick, securityMode = false, query = '' }) {
  const isAV       = result.file_type === 'video' || result.file_type === 'audio'
  const hasPreview = (result.file_type === 'image' || result.file_type === 'doc') && result.preview_url
  const [imgError, setImgError] = useState(false)
  const playerRef  = useRef(null)

  // ── 보안 모드: 이미지/문서 미리보기에 PII 마스킹 적용 ──
  const [maskedSrc, setMaskedSrc] = useState(null)
  const [secState, setSecState]   = useState('idle')  // idle | loading | done | nopii
  const [piiTypes, setPiiTypes]   = useState([])
  useEffect(() => {
    if (!securityMode || !hasPreview || isAV) return
    if (secState !== 'idle') return
    setSecState('loading')
    const rel = result.trichef_id || result.file_path
    const domain = result.trichef_domain || (result.file_type === 'doc' ? 'doc_page' : 'image')
    fetch(`${API_BASE}/api/security/mask_image?path=${encodeURIComponent(rel)}&domain=${domain}`)
      .then(r => r.json())
      .then(d => {
        if (d.pii_found && d.masked_b64) {
          setMaskedSrc(`data:image/png;base64,${d.masked_b64}`)
          setPiiTypes(d.pii_types || [])
          setSecState('done')
        } else {
          setSecState('nopii')
        }
      })
      .catch(() => setSecState('nopii'))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [securityMode, hasPreview, isAV, result.trichef_id, result.file_path, secState])
  // 보안 모드 OFF 시 상태 초기화
  useEffect(() => {
    if (!securityMode) {
      setSecState('idle')
      setMaskedSrc(null)
      setPiiTypes([])
    }
  }, [securityMode])

  // 점수 계산 (admin.html 동일)
  // [BUGFIX] 백엔드는 'rerank_score' 필드로 송신. 'rerank' 만 보던 기존 코드는
  // 항상 null → (z_score+3)/6 폴백으로 모든 결과 정확도 0.500 표시되는 버그.
  const conf    = result.confidence ?? result.similarity ?? 0
  const confPct = (conf * 100).toFixed(1)
  const dense   = result.dense ?? null
  const rerank  = result.rerank_score ?? result.rerank ?? null
  const zScore  = result.z_score ?? null

  const clamp01 = x => (x == null || isNaN(x)) ? null : Math.max(0, Math.min(1, x))
  // [정확도 표시] BGE-reranker-v2-m3 의 raw logit 은 보통 [-15, +15] 범위로,
  // 그대로 sigmoid 하면 음수 결과가 모두 0.001 근처에 압축되어 의미가 없다.
  // 중심점 -3 (= 비관련 로짓 평균), 스케일 3 으로 시프트한 sigmoid 사용:
  //   rerank=-10 → -7/3=-2.33 → 0.089
  //   rerank=-5  → -2/3=-0.67 → 0.339
  //   rerank=-3  → 0          → 0.500   ← 중립
  //   rerank=0   → 1.0        → 0.731
  //   rerank=+3  → 2.0        → 0.881
  //   rerank=+10 → 13/3=4.33  → 0.987
  const sigmCalibrated = x => 1 / (1 + Math.exp(-((x + 3) / 3)))
  // 신뢰도/정확도/유사도 모두 0~100% 형식으로 통일 표시
  const sim     = clamp01(dense) != null ? `${(clamp01(dense) * 100).toFixed(1)}%` : '—'
  const acc     = rerank != null
    ? `${(sigmCalibrated(rerank) * 100).toFixed(1)}%`
    : `${(Math.max(0, Math.min(1, ((zScore ?? 0) + 3) / 6)) * 100).toFixed(1)}%`

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

      {/* 이미지·문서: 썸네일 (보안 모드 시 PII 마스킹) */}
      {!isAV && (
        <div className="relative h-[200px] bg-[#0b1220] flex items-center justify-center overflow-hidden">
          {hasPreview && !imgError ? (
            <>
              <img
                src={securityMode && maskedSrc ? maskedSrc : `${API_BASE}${result.preview_url}`}
                alt={result.file_name}
                className="max-w-full max-h-full object-contain cursor-zoom-in"
                onError={() => setImgError(true)}
              />
              {/* 보안 모드 로딩 스피너 */}
              {securityMode && secState === 'loading' && (
                <div className="absolute inset-0 bg-black/40 flex items-center justify-center">
                  <span className="material-symbols-outlined text-amber-400 animate-spin">progress_activity</span>
                </div>
              )}
              {/* PII 발견 배지 */}
              {securityMode && secState === 'done' && piiTypes.length > 0 && (
                <span className="absolute top-2 right-2 px-2 py-0.5 rounded-md bg-red-500 text-white text-[10px] font-bold shadow flex items-center gap-1">
                  <span className="material-symbols-outlined text-xs">shield</span>
                  PII 마스킹 ({piiTypes.length})
                </span>
              )}
              {/* PII 없음 배지 */}
              {securityMode && secState === 'nopii' && (
                <span className="absolute top-2 right-2 px-2 py-0.5 rounded-md bg-emerald-500/80 text-white text-[10px] font-bold shadow flex items-center gap-1">
                  <span className="material-symbols-outlined text-xs">check_circle</span>
                  안전
                </span>
              )}
            </>
          ) : (
            <span className="text-[#64748b] text-xs">{domainLabel}</span>
          )}
        </div>
      )}

      {/* 바디 */}
      <div className="p-3 flex flex-col gap-2 flex-1 text-[#e2e8f0]">

        {/* 1. 도메인 배지 */}
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

        {/* 2. 핵심 3지표 (요청에 따라 도메인 배지 바로 아래로 이동) */}
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

        {/* 3. 파일명 + 위치 배지 (페이지/타임코드) */}
        <div className="flex items-start gap-1.5">
          <div className="font-semibold text-[13px] text-[#f1f5f9] break-all flex-1">
            <HighlightedText text={result.file_name} query={query} />
          </div>
          <LocationBadge location={result.location} fileType={result.file_type} />
        </div>

        {/* 4. 경로 */}
        <div className="text-[11px] text-[#64748b] break-all font-mono">{result.file_path}</div>

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
                      <ScoreStars score={sc} className="whitespace-nowrap" />
                      <span className="text-[#94a3b8] flex-1 overflow-hidden text-ellipsis whitespace-nowrap">
                        <HighlightedText text={preview} query={query} />
                      </span>
                    </button>
                  )
                })}
              </div>
            </div>
          )
        })()}

        {/* BGM: 미니 플레이어 + 메타 (artist · BPM · tags) + 세그먼트 timestamp */}
        {result.file_type === 'bgm' && (() => {
          // useRef 는 hooks 규칙상 컴포넌트 최상단에만 가능 — id 기반 DOM 조회로 우회
          const audioId = `bgm-audio-${rank}-${(result.bgm_filename || result.file_name || '').replace(/[^\w]/g, '_')}`
          const seekBgm = (sec) => {
            const a = document.getElementById(audioId)
            if (!a) return
            try {
              a.currentTime = sec
              a.play().catch(() => {})
            } catch (_) {}
          }
          return (
          <div className="space-y-2" onClick={e => e.stopPropagation()}>
            <div className="bg-pink-500/5 border border-pink-500/20 rounded-md p-2">
              <audio
                id={audioId}
                src={`${API_BASE}/api/bgm/file?id=${encodeURIComponent(result.bgm_filename || result.file_name)}`}
                controls preload="metadata"
                className="w-full h-7" style={{ maxHeight: '28px' }}
              />
              <div className="flex flex-wrap items-center gap-1.5 mt-1.5 text-[11px]">
                {result.bgm_artist && (
                  <span className="text-pink-300 font-bold">
                    <HighlightedText text={result.bgm_artist} query={query} />
                  </span>
                )}
                {result.bgm_artist && result.bgm_title && (
                  <span className="text-[#64748b]">·</span>
                )}
                {result.bgm_title && (
                  <span className="text-on-surface">
                    <HighlightedText text={result.bgm_title} query={query} />
                  </span>
                )}
                {result.bgm_duration > 0 && (
                  <>
                    <span className="text-[#64748b]">·</span>
                    <span className="text-[#94a3b8] font-mono">{Math.round(result.bgm_duration)}s</span>
                  </>
                )}
                {result.bgm_acr && (
                  <span className="px-1.5 py-0.5 rounded-full text-[9px] bg-emerald-500/20 text-emerald-300 font-bold">
                    ACR
                  </span>
                )}
                {result.bgm_source && result.bgm_source !== 'catalog' && (
                  <span className={`px-1.5 py-0.5 rounded-full text-[9px] font-bold ${
                    result.bgm_source === 'movie_lib'
                      ? 'bg-purple-500/20 text-purple-300'
                      : 'bg-amber-500/20 text-amber-300'
                  }`}>
                    {result.bgm_source === 'movie_lib' ? '🎬 영상 라이브러리' : '🎙 오디오 라이브러리'}
                  </span>
                )}
                {result.bgm_source === 'catalog' && (
                  <span className="px-1.5 py-0.5 rounded-full text-[9px] bg-pink-500/30 text-pink-200 font-bold">
                    🎵 카탈로그
                  </span>
                )}
              </div>
              {Array.isArray(result.bgm_tags) && result.bgm_tags.length > 0 && (
                <div className="flex flex-wrap gap-1 mt-1.5">
                  {result.bgm_tags.slice(0, 5).map((t, i) => (
                    <span key={i} className="text-[10px] px-1.5 py-0.5 rounded-full bg-pink-500/10 text-pink-300/80 border border-pink-500/20">
                      {t}
                    </span>
                  ))}
                </div>
              )}
              {/* 세그먼트 timestamp — 검색어와 부합하는 구간 */}
              {Array.isArray(result.segments) && result.segments.length > 0 && (
                <div className="mt-2 pt-2 border-t border-pink-500/15">
                  <div className="text-[10px] text-pink-300/80 font-bold uppercase tracking-wide mb-1">
                    검색어 부합 구간
                  </div>
                  <div className="flex flex-col gap-1">
                    {result.segments.slice(0, 5).map((s, i) => (
                      <button key={i} type="button"
                        onClick={() => seekBgm(s.start)}
                        className="flex items-center gap-2 px-2 py-1 bg-pink-500/5 border border-pink-500/20 rounded text-[11px] hover:bg-pink-500/15 hover:border-pink-400/40 transition text-left">
                        <span className="material-symbols-outlined text-xs text-pink-300">play_arrow</span>
                        <span className="font-mono font-semibold text-pink-200 min-w-[88px]">{s.label}</span>
                        <ScoreStars score={s.score} confidence={s.confidence} />
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
          )
        })()}

        {/* 5-A. Doc — 페이지/줄 + 매칭 줄 텍스트 (검색어 하이라이트) */}
        {!isAV && result.file_type === 'doc' && (result.snippet || result.location?.snippet) && (
          <div className="text-[12px] text-[#cbd5e1] bg-[#0b1220] px-2 py-2 rounded border border-[#334155] max-h-[160px] overflow-auto whitespace-pre-wrap">
            <div className="flex flex-wrap items-center gap-1.5 mb-1.5">
              {result.location?.page_label && (
                <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-[#85adff]/20 text-[#85adff] font-bold">
                  {result.location.page_label}
                </span>
              )}
              {result.location?.line_label && (
                <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-[#85adff]/20 text-[#85adff] font-bold">
                  {result.location.line_label}
                </span>
              )}
              {result.location?.caption && !result.location?.line_label && (
                <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-emerald-500/20 text-emerald-300 font-bold">
                  캡션
                </span>
              )}
            </div>
            <HighlightedText
              text={result.location?.snippet || result.snippet}
              query={query}
            />
          </div>
        )}

        {/* 5-B. Image — 캡션 (한줄 정리/상세 정리) + 검색어 하이라이트 */}
        {!isAV && result.file_type === 'image' && (
          (result.snippet || result.location?.caption || result.location?.title || result.location?.tagline || result.location?.synopsis) && (
            <div className="text-[12px] text-[#cbd5e1] bg-[#0b1220] px-2 py-2 rounded border border-[#334155] max-h-[200px] overflow-auto space-y-1.5">
              {result.location?.title && (
                <div>
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-300 font-bold mr-1.5">
                    제목
                  </span>
                  <HighlightedText text={result.location.title} query={query} />
                </div>
              )}
              {result.location?.tagline && (
                <div>
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-300 font-bold mr-1.5">
                    한줄
                  </span>
                  <HighlightedText text={result.location.tagline} query={query} />
                </div>
              )}
              {result.location?.synopsis && (
                <div>
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-300 font-bold mr-1.5">
                    상세
                  </span>
                  <HighlightedText text={result.location.synopsis} query={query} />
                </div>
              )}
              {/* fallback — title/tagline/synopsis 없을 때 기존 캡션/스니펫 */}
              {!result.location?.title && !result.location?.tagline && !result.location?.synopsis && (
                <HighlightedText
                  text={result.snippet || result.location?.caption}
                  query={query}
                />
              )}
            </div>
          )
        )}
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
  // [#2] 도메인 필터 — '' (전체) | 'doc' | 'image' | 'video' | 'audio'
  const [domainFilter, setDomainFilter] = useState('')
  // [노이즈 제거] 저신뢰도 결과 숨김 (기본 ON). 사용자가 토글로 모두 표시 가능.
  const [hideLowConf, setHideLowConf] = useState(true)
  // 보안 모드 — 활성 시 결과 미리보기에 PII 마스킹 (주민번호/여권/계좌 등)
  const [securityMode, setSecurityMode] = useState(false)
  // + 버튼 멀티 메뉴
  const [plusMenuOpen, setPlusMenuOpen] = useState(false)
  // 이미지 검색 — 입력 모달 + 업로드 파일 + 미리보기
  const imageInputRef = useRef(null)
  const [imageSearchFile, setImageSearchFile] = useState(null)
  const [imageSearchModalOpen, setImageSearchModalOpen] = useState(false)
  const [imageSearchPreviewUrl, setImageSearchPreviewUrl] = useState(null)
  const [imageSearchActive, setImageSearchActive] = useState(false)
  const [isDraggingImage, setIsDraggingImage] = useState(false)

  // BGM 식별 — 모달 + 업로드 + 결과
  const bgmInputRef = useRef(null)
  const [bgmModalOpen, setBgmModalOpen]     = useState(false)
  const [bgmFile, setBgmFile]                = useState(null)
  const [bgmIdentifying, setBgmIdentifying]  = useState(false)
  const [bgmIdentifyResult, setBgmIdentifyResult] = useState(null)
  const [isDraggingBgm, setIsDraggingBgm]    = useState(false)

  // 요약 (Ollama qwen) — SSE 스트리밍
  const [summarizing,  setSummarizing]  = useState(false)
  const [summaryText,  setSummaryText]  = useState('')
  const [summaryDone,  setSummaryDone]  = useState(false)
  const [summaryError, setSummaryError] = useState('')
  const [summaryMeta,  setSummaryMeta]  = useState(null) // {model, length, kind}
  const summaryAbortRef = useRef(null)

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
  const homeInputRef    = useRef(null)
  const resultsInputRef = useRef(null)

  // 페이지 진입 / view 변경 시 검색창 자동 포커스
  useEffect(() => {
    const t = setTimeout(() => {
      if (view === 'home') homeInputRef.current?.focus()
      else if (view === 'results') resultsInputRef.current?.focus()
    }, 100)
    return () => clearTimeout(t)
  }, [view])

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
  // [#2] 도메인 필터를 백엔드에 전달 → 서버 측에서 type 별 top_k 할당.
  const fetchResults = useCallback(async (q, type = '') => {
    setSearching(true)
    setSearchError('')
    try {
      const data = await searchFiles(q, 20, type)
      setResults(data)
    } catch (e) {
      setSearchError(e.message)
      setResults([])
    } finally {
      setSearching(false)
    }
  }, [])

  // [#2] 도메인 필터 변경 시 자동 재검색 (현재 query 가 있을 때만).
  useEffect(() => {
    if (view === 'results' && query) fetchResults(query, domainFilter)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [domainFilter])

  // 모달에서 파일 선택 (드래그앤드롭 또는 클릭)
  const handleImageFileSelect = useCallback((file) => {
    if (!file || !file.type.startsWith('image/')) return
    setImageSearchFile(file)
    if (imageSearchPreviewUrl) URL.revokeObjectURL(imageSearchPreviewUrl)
    setImageSearchPreviewUrl(URL.createObjectURL(file))
  }, [imageSearchPreviewUrl])

  // 이미지 모달 닫기 (preview 정리)
  const closeImageModal = useCallback((clearPreview = false) => {
    setImageSearchModalOpen(false)
    if (clearPreview) {
      setImageSearchFile(null)
      if (imageSearchPreviewUrl) URL.revokeObjectURL(imageSearchPreviewUrl)
      setImageSearchPreviewUrl(null)
      setImageSearchActive(false)
    }
  }, [imageSearchPreviewUrl])

  // ── BGM 식별 (mp4 업로드) ─────────────────────────────────
  const handleBgmFileSelect = useCallback((file) => {
    if (!file) return
    setBgmFile(file)
    setBgmIdentifyResult(null)
  }, [])

  const closeBgmModal = useCallback((reset = false) => {
    setBgmModalOpen(false)
    if (reset) {
      setBgmFile(null)
      setBgmIdentifyResult(null)
      setIsDraggingBgm(false)
    }
  }, [])

  // ── 요약 시작 (Ollama qwen 스트리밍) ─────────────────────────
  const handleSummarize = useCallback(async (file) => {
    if (!file) return
    if (summaryAbortRef.current) summaryAbortRef.current.abort()
    const ctrl = new AbortController()
    summaryAbortRef.current = ctrl
    setSummarizing(true)
    setSummaryText('')
    setSummaryDone(false)
    setSummaryError('')
    setSummaryMeta(null)
    try {
      const body = {
        file_type:  file.file_type,
        trichef_id: file.trichef_id || file.id || '',
        file_path:  file.file_path  || '',
        file_name:  file.file_name  || '',
        segments:   file.segments   || [],
      }
      const res = await fetch(`${API_BASE}/api/aimode/summarize`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        signal: ctrl.signal,
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop()
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          let ev
          try { ev = JSON.parse(line.slice(6)) } catch { continue }
          if (ev.type === 'token')          setSummaryText(prev => prev + (ev.text || ''))
          else if (ev.type === 'content_loaded') setSummaryMeta(m => ({ ...(m||{}), length: ev.length, kind: ev.kind }))
          else if (ev.type === 'info')      setSummaryMeta(m => ({ ...(m||{}), model: ev.model }))
          else if (ev.type === 'done')      { setSummaryDone(true); if (ev.summary) setSummaryText(ev.summary) }
          else if (ev.type === 'error')     setSummaryError(ev.message || '오류')
        }
      }
    } catch (e) {
      if (e.name !== 'AbortError') setSummaryError(e.message || '요약 실패')
    } finally {
      setSummarizing(false)
    }
  }, [])

  const closeSummary = useCallback(() => {
    if (summaryAbortRef.current) summaryAbortRef.current.abort()
    setSummarizing(false)
    setSummaryText('')
    setSummaryDone(false)
    setSummaryError('')
    setSummaryMeta(null)
  }, [])

  const handleBgmIdentify = useCallback(async (file) => {
    if (!file) return
    setBgmIdentifying(true)
    setBgmIdentifyResult(null)
    try {
      const fd = new FormData()
      fd.append('file', file)
      fd.append('top_k', '5')
      const res = await fetch(`${API_BASE}/api/bgm/identify`, { method: 'POST', body: fd })
      const data = await res.json()
      setBgmIdentifyResult(data)
    } catch (e) {
      setBgmIdentifyResult({ error: e.message || 'BGM 식별 실패' })
    } finally {
      setBgmIdentifying(false)
    }
  }, [])

  // 이미지 검색 실행
  const handleImageSearch = useCallback(async (file) => {
    if (!file) return
    setImageSearchActive(true)
    setQuery(`[이미지 검색] ${file.name}`)
    setInputValue(file.name)
    setView('results')
    setResultsReady(true)
    setSearching(true)
    setSearchError('')
    setImageSearchModalOpen(false)
    try {
      const data = await searchByImage(file, 30)
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
    // 텍스트 검색 시작 → 이미지 검색 모드 해제 + preview 정리
    if (imageSearchActive) {
      setImageSearchActive(false)
      if (imageSearchPreviewUrl) URL.revokeObjectURL(imageSearchPreviewUrl)
      setImageSearchPreviewUrl(null)
      setImageSearchFile(null)
    }
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
        fetchResults(q, domainFilter)
      }, 480)
    } else {
      setView('results')
      fetchResults(q, domainFilter)
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

              {/* 이미지 검색용 hidden file input — 모달의 클릭 영역에서 트리거 */}
              <input
                ref={imageInputRef}
                type="file"
                accept="image/*"
                className="hidden"
                onChange={(e) => {
                  const file = e.target.files?.[0]
                  if (file) handleImageFileSelect(file)
                  e.target.value = ''
                }}
              />
              <form ref={formRef} onSubmit={handleSearch} className="w-full relative group"
                style={homeExiting ? { visibility: 'hidden' } : {}}>
                <div className={`glass-effect rounded-full p-2 flex items-center gap-4 shadow-[0_0_50px_rgba(133,173,255,0.1)] transition-all duration-300
                  ${listening ? 'border border-red-400/60 shadow-[0_0_30px_rgba(248,113,113,0.2)]' : 'border border-outline-variant/20 hover:border-primary/40'}`}>
                  <div className="relative shrink-0">
                    <button type="button"
                      onClick={() => setPlusMenuOpen(v => !v)}
                      className={`w-12 h-12 rounded-full bg-gradient-to-r from-primary to-secondary flex items-center justify-center text-on-primary-fixed shadow-lg active:scale-90 transition-all duration-300
                        ${plusMenuOpen ? 'rotate-45' : ''}`}>
                      <span className="material-symbols-outlined font-bold">add</span>
                    </button>
                    {/* 멀티 입력 메뉴 — + 버튼 클릭 시 애니메이션 펼침 */}
                    {[
                      { id: 'image-search', label: '이미지 검색', icon: 'image_search', domain: 'image', color: 'from-emerald-500 to-teal-500' },
                      { id: 'bgm-search',   label: 'BGM 검색',   icon: 'music_note',   domain: 'audio', color: 'from-amber-500 to-orange-500' },
                      { id: 'doc',          label: '문서',       icon: 'description',  domain: 'doc',   color: 'from-blue-500 to-indigo-500' },
                      { id: 'image',        label: '이미지',     icon: 'image',        domain: 'image', color: 'from-emerald-500 to-green-500' },
                      { id: 'audio',        label: '음성',       icon: 'mic',          domain: 'audio', color: 'from-amber-500 to-yellow-500' },
                      { id: 'video',        label: '동영상',     icon: 'movie',        domain: 'video', color: 'from-purple-500 to-pink-500' },
                    ].map((item, i) => {
                      // 원형 배치 — 6개 항목 60도 간격, -90도(상단) 시작 시계방향
                      const total = 6
                      const angle = -90 + (i * (360 / total))   // -90, -30, 30, 90, 150, 210
                      const radius = 110
                      const rad = angle * Math.PI / 180
                      const tx = Math.cos(rad) * radius
                      const ty = Math.sin(rad) * radius
                      return (
                        <button
                          key={item.id}
                          type="button"
                          onClick={() => {
                            if (item.id === 'image-search') {
                              setImageSearchModalOpen(true)
                            } else if (item.id === 'bgm-search') {
                              // BGM 식별 모달 (mp4 업로드 → 곡 인식)
                              setBgmModalOpen(true)
                            } else if (item.id === 'bgm-domain') {
                              setDomainFilter('bgm')
                            } else {
                              setDomainFilter(item.domain)
                            }
                            setPlusMenuOpen(false)
                          }}
                          title={item.label}
                          style={{
                            // + 버튼 (48x48) 정중앙 기준 이동: 좌상단(0,0) → 중앙으로 이동 후 원형 분포
                            transform: plusMenuOpen
                              ? `translate(${tx}px, ${ty}px) scale(1)`
                              : 'translate(0, 0) scale(0)',
                            transitionDelay: plusMenuOpen ? `${i * 30}ms` : `${(total - 1 - i) * 20}ms`,
                            zIndex: 30,
                          }}
                          className={`absolute top-0 left-0 w-12 h-12 rounded-full bg-gradient-to-br ${item.color}
                            flex flex-col items-center justify-center text-white text-[9px] font-bold
                            shadow-lg shadow-black/30 active:scale-90
                            transition-all duration-400 ease-out hover:scale-110
                            ${plusMenuOpen ? 'opacity-100 pointer-events-auto' : 'opacity-0 pointer-events-none'}`}
                        >
                          <span className="material-symbols-outlined text-base leading-none">{item.icon}</span>
                          <span className="mt-0.5 leading-none">{item.label}</span>
                        </button>
                      )
                    })}
                  </div>
                  <div className="flex-1 relative">
                    <input
                      ref={homeInputRef}
                      type="text"
                      autoFocus
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
                  {/* 보안 모드 토글 — 마이크 옆에 위치 */}
                  <button type="button" onClick={() => setSecurityMode(v => !v)}
                    title={securityMode ? '보안 모드 켜짐: 결과 미리보기에 PII 마스킹 적용' : '보안 모드 꺼짐'}
                    className={`w-12 h-12 rounded-full flex items-center justify-center transition-all duration-200 shrink-0
                      ${securityMode
                        ? 'bg-red-500/20 text-red-400 ring-2 ring-red-400/40 shadow-[0_0_20px_rgba(248,113,113,0.3)]'
                        : 'text-on-surface-variant hover:text-red-400 hover:bg-red-400/10'}`}>
                    <span className="material-symbols-outlined" style={securityMode ? { fontVariationSettings: '"FILL" 1' } : {}}>shield</span>
                  </button>
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
                  ref={resultsInputRef}
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
              {/* 보안 모드 토글 (results header) */}
              <button type="button" onClick={() => setSecurityMode(v => !v)}
                title={securityMode ? '보안 모드 켜짐' : '보안 모드 꺼짐'}
                className={`shrink-0 transition-all duration-200 ${securityMode ? 'text-red-400' : 'text-on-surface-variant hover:text-red-400'}`}>
                <span className="material-symbols-outlined text-lg" style={securityMode ? { fontVariationSettings: '"FILL" 1' } : {}}>shield</span>
              </button>
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
              <div className="space-y-2 flex-1 min-w-0">
                <span className="px-2 py-0.5 rounded text-lg font-bold bg-primary/10 text-primary uppercase tracking-widest border border-primary/20">현재 쿼리</span>
                {/* 이미지 검색 시 — 미리보기 + 파일명 표시 */}
                {imageSearchActive && imageSearchPreviewUrl ? (
                  <div className="flex items-start gap-4">
                    <div className="relative shrink-0 group">
                      <img
                        src={imageSearchPreviewUrl}
                        alt="검색 이미지"
                        className="w-28 h-28 object-cover rounded-xl border-2 border-emerald-500/40 shadow-lg shadow-emerald-500/10"
                      />
                      <span className="absolute -top-2 -left-2 px-1.5 py-0.5 rounded-md bg-emerald-500 text-white text-[10px] font-bold shadow">
                        이미지 검색
                      </span>
                      <button
                        type="button"
                        onClick={() => setImageSearchModalOpen(true)}
                        title="이미지 변경"
                        className="absolute -bottom-2 -right-2 w-7 h-7 rounded-full bg-primary text-on-primary-fixed shadow-lg flex items-center justify-center hover:scale-110 transition"
                      >
                        <span className="material-symbols-outlined text-sm">edit</span>
                      </button>
                    </div>
                    <div className="min-w-0 flex-1">
                      <h1 className="text-2xl font-extrabold tracking-tight text-on-surface truncate">
                        {imageSearchFile?.name || '이미지 검색'}
                      </h1>
                      <p className="text-xs text-on-surface-variant/60 mt-1">시각 임베딩 (SigLIP2) 기반 유사도 검색</p>
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
                    : <p className="text-on-surface-variant">로컬 보관소에서 <span className="text-primary font-bold">{results.length}건</span>을 찾았습니다.</p>
                }
              </div>
              <div className="flex gap-3">
                <button className="px-4 py-2 rounded-full glass-panel border border-outline-variant/20 text-base font-bold hover:bg-primary/5 transition-all flex items-center gap-2">
                  <span className="material-symbols-outlined text-lg">filter_list</span>관련도
                </button>
              </div>
            </div>

            {/* [#2] 도메인 필터 칩 — 검색창 구조 미변경, 결과 헤더 아래에 독립 마운트 */}
            <div className="mb-6 -mt-4">
              <DomainFilter
                value={domainFilter}
                onChange={setDomainFilter}
                counts={(() => {
                  const c = { _total: results.length, doc: 0, image: 0, video: 0, audio: 0, bgm: 0 }
                  results.forEach(r => { c[r.file_type] = (c[r.file_type] ?? 0) + 1 })
                  return c
                })()}
              />
            </div>

            {/* [노이즈 제거] 저신뢰도 결과 숨김 토글 — 신뢰도 < 5% 인 결과 자동 hide.
                Reranker 가 부적합 판정한 결과(예: '박태웅 의장' 검색에 신발 사진)를
                기본 숨김 처리하여 노이즈 제거. 사용자는 토글로 전체 보기 가능. */}
            {(() => {
              const LOW = 0.05
              const lowCount = results.filter(r => (r.confidence ?? 0) < LOW).length
              if (lowCount === 0) return null
              return (
                <div className="mb-4 -mt-2 flex items-center gap-3 text-sm">
                  <span className="text-on-surface-variant/60">
                    {hideLowConf
                      ? <>저신뢰도 <span className="font-bold text-amber-400">{lowCount}건</span> 숨김</>
                      : <>모든 결과 표시 중</>}
                  </span>
                  <button
                    onClick={() => setHideLowConf(v => !v)}
                    className="px-2 py-0.5 rounded-full bg-white/5 hover:bg-white/10 text-xs font-bold text-on-surface-variant transition-all"
                  >
                    {hideLowConf ? '모두 표시' : '저신뢰도 숨김'}
                  </button>
                </div>
              )
            })()}

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

            {/* 결과 카드 — 저신뢰도 숨김 토글 적용 */}
            {!searching && results.length > 0 && (() => {
              const LOW = 0.05
              const visible = hideLowConf
                ? results.filter(r => (r.confidence ?? 0) >= LOW)
                : results
              if (visible.length === 0) {
                return (
                  <div className="flex flex-col items-center justify-center py-20 gap-3">
                    <span className="material-symbols-outlined text-on-surface-variant/30 text-5xl">filter_alt_off</span>
                    <p className="text-on-surface-variant">신뢰할 만한 결과를 찾지 못했습니다.</p>
                    <p className="text-xs text-on-surface-variant/40">
                      모든 결과의 신뢰도가 5% 미만입니다. 다른 키워드를 시도하거나
                      <button onClick={() => setHideLowConf(false)}
                              className="ml-1 underline hover:text-primary">전체 결과 보기</button>
                    </p>
                  </div>
                )
              }
              return (
                <div className="grid gap-4" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))' }}>
                  {visible.map((r, i) => (
                    <ResultCard key={r.file_path + i} result={r} rank={i + 1} onClick={() => handleSelectFile(r)} securityMode={securityMode} query={query} />
                  ))}
                </div>
              )
            })()}

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
                {/* ✨ AI 요약 — Ollama qwen 스트리밍 */}
                <button
                  onClick={() => handleSummarize(selectedFile)}
                  disabled={summarizing}
                  title="이 파일의 핵심 내용을 AI가 요약합니다"
                  className="px-5 py-2 text-base font-bold uppercase tracking-widest rounded-full transition-all active:scale-95 flex items-center gap-2 disabled:opacity-60"
                  style={{
                    background: 'linear-gradient(135deg, rgba(168,85,247,0.18), rgba(236,72,153,0.12))',
                    border: '1px solid rgba(168,85,247,0.4)',
                    color: '#e9d5ff',
                  }}>
                  <span className={`material-symbols-outlined text-base ${summarizing ? 'animate-spin' : ''}`}>
                    {summarizing ? 'progress_activity' : 'auto_awesome'}
                  </span>
                  {summarizing ? '요약 중...' : 'AI 요약'}
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

                  {/* [#9] 점수 분해 — dense/lexical/asf/rerank/z_score 시각화 (admin.html 패리티) */}
                  <div className="bg-surface-container-low rounded-xl p-5 border border-outline-variant/5">
                    <h4 className="text-sm font-bold tracking-[0.15em] text-on-surface-variant mb-3 uppercase">점수 분해</h4>
                    <ScoreBreakdown result={selectedFile} />
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

              {/* ── ✨ AI 요약 인라인 패널 (상세 페이지 하단) ──────────────── */}
              {(summarizing || summaryText || summaryError) && (
                <div className="rounded-2xl overflow-hidden relative"
                  style={{
                    background: 'linear-gradient(135deg, rgba(13,7,24,0.85), rgba(20,12,40,0.85))',
                    border: '1px solid rgba(168,85,247,0.4)',
                    boxShadow: '0 0 30px rgba(168,85,247,0.15)',
                  }}>
                  {/* 헤더 */}
                  <div className="px-6 py-4 flex items-center gap-3 border-b border-purple-500/20">
                    <span className="material-symbols-outlined text-purple-300 animate-pulse">auto_awesome</span>
                    <div className="min-w-0 flex-1">
                      <h3 className="text-base font-bold text-purple-100 tracking-wide">
                        AI 상세 요약
                      </h3>
                      {summaryMeta && (
                        <p className="text-[11px] text-purple-300/60 mt-0.5">
                          {summaryMeta.model && <>모델: <span className="font-mono">{summaryMeta.model}</span></>}
                          {summaryMeta.length != null && <> · 본문 {summaryMeta.length.toLocaleString()}자</>}
                          {summaryMeta.kind && <> · <span className="opacity-70">{summaryMeta.kind}</span></>}
                        </p>
                      )}
                    </div>
                    {summaryDone ? (
                      <span className="flex items-center gap-1 text-emerald-400 text-xs">
                        <span className="material-symbols-outlined text-base">check_circle</span> 완료
                      </span>
                    ) : summaryError ? (
                      <span className="text-rose-300 text-xs">실패</span>
                    ) : (
                      <span className="flex items-center gap-1 text-purple-300 text-xs">
                        <span className="material-symbols-outlined text-base animate-spin">progress_activity</span>
                        스트리밍
                      </span>
                    )}
                    <button
                      type="button"
                      onClick={closeSummary}
                      className="w-7 h-7 rounded-full hover:bg-white/10 flex items-center justify-center text-on-surface-variant ml-2"
                      title={summarizing ? '중단' : '닫기'}
                    >
                      <span className="material-symbols-outlined text-lg">close</span>
                    </button>
                  </div>

                  {/* 본문 — Markdown 렌더링 + 스트리밍 커서 */}
                  <div className="px-7 py-6 text-base">
                    {summaryError ? (
                      <div className="rounded-xl bg-rose-500/10 border border-rose-500/30 p-4 text-rose-300">
                        <div className="flex items-center gap-2 mb-1">
                          <span className="material-symbols-outlined text-base">error</span>
                          <span className="font-bold">요약 실패</span>
                        </div>
                        <p className="text-sm">{summaryError}</p>
                      </div>
                    ) : summaryText ? (
                      <div className="relative">
                        <MarkdownLite text={summaryText} />
                        {!summaryDone && (
                          <span className="inline-block w-2 h-4 bg-purple-300 ml-1 animate-pulse align-middle" />
                        )}
                      </div>
                    ) : (
                      <div className="flex items-center gap-3 text-on-surface-variant/50">
                        <span className="material-symbols-outlined animate-spin">progress_activity</span>
                        <span>본문 추출 + AI 모델 호출 중... (PDF 18,000자 / 영상·음성 80개 세그먼트까지)</span>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </section>

            <div className="fixed bottom-[-10%] left-[20%] w-[40%] h-[40%] bg-primary/5 blur-[120px] pointer-events-none rounded-full" />
            <div className="fixed top-[10%] right-[-5%] w-[30%] h-[30%] bg-secondary/5 blur-[100px] pointer-events-none rounded-full" />
          </main>
        )
      })()}

      {/* ── 이미지 검색 입력 모달 ─────────────────────────── */}
      {imageSearchModalOpen && (
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center bg-black/70 backdrop-blur-sm"
          onClick={() => closeImageModal(false)}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            className="relative w-full max-w-lg mx-4 bg-surface-container border border-outline-variant/30 rounded-3xl p-8 shadow-2xl animate-in fade-in zoom-in duration-200"
          >
            {/* 헤더 */}
            <div className="flex items-center justify-between mb-6">
              <h3 className="text-xl font-bold text-on-surface flex items-center gap-2">
                <span className="material-symbols-outlined text-primary">image_search</span>
                이미지 검색
              </h3>
              <button
                type="button"
                onClick={() => closeImageModal(true)}
                className="w-8 h-8 rounded-full hover:bg-white/10 flex items-center justify-center text-on-surface-variant"
              >
                <span className="material-symbols-outlined text-lg">close</span>
              </button>
            </div>

            {/* 드래그앤드롭 + 파일 선택 영역 */}
            <div
              onClick={() => imageInputRef.current?.click()}
              onDragOver={(e) => { e.preventDefault(); setIsDraggingImage(true) }}
              onDragLeave={() => setIsDraggingImage(false)}
              onDrop={(e) => {
                e.preventDefault()
                setIsDraggingImage(false)
                const file = e.dataTransfer.files?.[0]
                if (file && file.type.startsWith('image/')) handleImageFileSelect(file)
              }}
              className={`relative cursor-pointer rounded-2xl border-2 border-dashed transition-all
                ${isDraggingImage
                  ? 'border-primary bg-primary/10 scale-[1.02]'
                  : 'border-outline-variant/40 hover:border-primary/60 hover:bg-white/5'}
                ${imageSearchPreviewUrl ? 'p-3' : 'p-12 text-center'}`}
            >
              {imageSearchPreviewUrl ? (
                <div className="flex flex-col items-center gap-3">
                  <img
                    src={imageSearchPreviewUrl}
                    alt="검색 이미지 미리보기"
                    className="max-h-64 max-w-full rounded-xl shadow-lg object-contain"
                  />
                  <div className="text-xs text-on-surface-variant truncate max-w-full">
                    {imageSearchFile?.name}
                  </div>
                  <div className="text-[11px] text-on-surface-variant/60">
                    클릭하면 다른 이미지로 변경
                  </div>
                </div>
              ) : (
                <div className="flex flex-col items-center gap-3">
                  <span className="material-symbols-outlined text-6xl text-on-surface-variant/40">
                    add_photo_alternate
                  </span>
                  <div className="text-base font-bold text-on-surface">
                    여기에 이미지를 끌어놓거나 클릭하여 선택하세요
                  </div>
                  <div className="text-xs text-on-surface-variant/60">
                    JPG · PNG · WebP · GIF 등 (최대 50 MB)
                  </div>
                </div>
              )}
            </div>

            {/* 액션 버튼 */}
            <div className="flex gap-3 mt-6 justify-end">
              <button
                type="button"
                onClick={() => closeImageModal(true)}
                className="px-5 py-2 rounded-full border border-outline-variant/30 text-on-surface-variant hover:bg-white/5 transition"
              >
                취소
              </button>
              <button
                type="button"
                disabled={!imageSearchFile}
                onClick={() => imageSearchFile && handleImageSearch(imageSearchFile)}
                className="px-6 py-2 rounded-full bg-gradient-to-r from-primary to-secondary text-on-primary-fixed font-bold disabled:opacity-40 disabled:cursor-not-allowed hover:shadow-lg hover:shadow-primary/30 transition"
              >
                <span className="material-symbols-outlined text-base align-middle mr-1">search</span>
                검색
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── BGM 식별 모달 — 동영상/오디오 업로드 → 곡 인식 ────── */}
      {bgmModalOpen && (
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center bg-black/70 backdrop-blur-sm"
          onClick={() => closeBgmModal(false)}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            className="relative w-full max-w-lg mx-4 bg-surface-container border border-outline-variant/30 rounded-3xl p-8 shadow-2xl animate-in fade-in zoom-in duration-200"
          >
            <div className="flex items-center justify-between mb-6">
              <h3 className="text-xl font-bold text-on-surface flex items-center gap-2">
                <span className="material-symbols-outlined text-pink-400">music_note</span>
                BGM 식별
              </h3>
              <button
                type="button"
                onClick={() => closeBgmModal(true)}
                className="w-8 h-8 rounded-full hover:bg-white/10 flex items-center justify-center text-on-surface-variant"
              >
                <span className="material-symbols-outlined text-lg">close</span>
              </button>
            </div>

            <input
              ref={bgmInputRef}
              type="file"
              accept="video/*,audio/*"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0]
                if (f) handleBgmFileSelect(f)
                e.target.value = ''
              }}
            />

            <div
              onClick={() => bgmInputRef.current?.click()}
              onDragOver={(e) => { e.preventDefault(); setIsDraggingBgm(true) }}
              onDragLeave={() => setIsDraggingBgm(false)}
              onDrop={(e) => {
                e.preventDefault()
                setIsDraggingBgm(false)
                const f = e.dataTransfer.files?.[0]
                if (f) handleBgmFileSelect(f)
              }}
              className={`relative cursor-pointer rounded-2xl border-2 border-dashed transition-all
                ${isDraggingBgm
                  ? 'border-pink-400 bg-pink-400/10 scale-[1.02]'
                  : 'border-outline-variant/40 hover:border-pink-400/60 hover:bg-white/5'}
                ${bgmFile ? 'p-4' : 'p-12 text-center'}`}
            >
              {bgmFile ? (
                <div className="flex items-center gap-3">
                  <span className="material-symbols-outlined text-4xl text-pink-400">audio_file</span>
                  <div className="flex-1 min-w-0">
                    <div className="font-bold text-on-surface truncate">{bgmFile.name}</div>
                    <div className="text-xs text-on-surface-variant">
                      {(bgmFile.size / (1024 * 1024)).toFixed(1)} MB
                    </div>
                  </div>
                  <span className="text-[11px] text-on-surface-variant/60 whitespace-nowrap">
                    클릭하면 변경
                  </span>
                </div>
              ) : (
                <div className="flex flex-col items-center gap-3">
                  <span className="material-symbols-outlined text-6xl text-on-surface-variant/40">
                    upload_file
                  </span>
                  <div className="text-base font-bold text-on-surface">
                    동영상 또는 오디오 파일을 끌어놓거나 클릭하여 선택
                  </div>
                  <div className="text-xs text-on-surface-variant/60">
                    MP4 · MP3 · WAV · M4A · WebM (최대 100 MB)
                  </div>
                  <div className="text-[11px] text-pink-400/80 mt-1">
                    Chromaprint(정확매칭) → CLAP(의미매칭) → ACR API(옵션) 순으로 시도
                  </div>
                </div>
              )}
            </div>

            {/* 식별 결과 */}
            {bgmIdentifyResult && !bgmIdentifyResult.error && (
              <div className="mt-5 rounded-2xl bg-white/5 border border-outline-variant/20 p-4 max-h-72 overflow-auto">
                <div className="flex items-center justify-between mb-3">
                  <span className="text-xs uppercase tracking-wide text-on-surface-variant">
                    식별 결과 ({bgmIdentifyResult.method || '?'})
                  </span>
                  <span className={`text-xs px-2 py-0.5 rounded-full font-bold
                    ${bgmIdentifyResult.confidence === 'high'   ? 'bg-emerald-500/20 text-emerald-300' :
                      bgmIdentifyResult.confidence === 'medium' ? 'bg-amber-500/20 text-amber-300' :
                                                                  'bg-rose-500/20 text-rose-300'}`}>
                    {bgmIdentifyResult.confidence}
                  </span>
                </div>
                {(bgmIdentifyResult.results || []).map((r, idx) => (
                  <div key={idx} className="py-2 border-t first:border-t-0 border-outline-variant/10">
                    <div className="font-bold text-on-surface flex items-center gap-2">
                      <span className="text-pink-400">#{r.rank ?? idx + 1}</span>
                      {r.acr_title || r.guess_title || r.filename || '(이름 없음)'}
                    </div>
                    {(r.acr_artist || r.guess_artist) && (
                      <div className="text-xs text-on-surface-variant">
                        {r.acr_artist || r.guess_artist}
                      </div>
                    )}
                    <div className="text-[11px] text-on-surface-variant/60 mt-1">
                      유사도 {((r.confidence ?? 0) * 100).toFixed(1)}%
                      {r.duration ? ` · ${Math.round(r.duration)}s` : ''}
                      {r.external ? ' · 외부 API' : ''}
                    </div>
                  </div>
                ))}
                {(bgmIdentifyResult.results || []).length === 0 && (
                  <div className="text-sm text-on-surface-variant/70 py-4 text-center">
                    매칭된 곡이 없습니다.
                  </div>
                )}
              </div>
            )}
            {bgmIdentifyResult?.error && (
              <div className="mt-5 rounded-xl bg-rose-500/10 border border-rose-500/30 p-3 text-sm text-rose-300">
                {bgmIdentifyResult.error}
              </div>
            )}

            <div className="flex gap-3 mt-6 justify-end">
              <button
                type="button"
                onClick={() => closeBgmModal(true)}
                className="px-5 py-2 rounded-full border border-outline-variant/30 text-on-surface-variant hover:bg-white/5 transition"
              >
                취소
              </button>
              <button
                type="button"
                disabled={!bgmFile || bgmIdentifying}
                onClick={() => bgmFile && handleBgmIdentify(bgmFile)}
                className="px-6 py-2 rounded-full bg-gradient-to-r from-pink-500 to-rose-500 text-white font-bold disabled:opacity-40 disabled:cursor-not-allowed hover:shadow-lg hover:shadow-pink-500/30 transition"
              >
                {bgmIdentifying ? (
                  <span className="flex items-center gap-1">
                    <span className="material-symbols-outlined text-base animate-spin">progress_activity</span>
                    식별 중...
                  </span>
                ) : (
                  <span className="flex items-center gap-1">
                    <span className="material-symbols-outlined text-base">search</span>
                    이 곡 찾기
                  </span>
                )}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* (요약 모달 제거됨 — 상세 페이지 하단 인라인 패널로 변경됨) */}
    </div>
  )
}
