import { useState, useRef, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import SearchSidebar from '../components/SearchSidebar'
import AnimatedOrb from '../components/AnimatedOrb'
import AmbientPageBackdrop from '../components/AmbientPageBackdrop'
import { useSidebar } from '../context/SidebarContext'
import { API_BASE } from '../api'

// ── 파일 타입 메타 ───────────────────────────────────────
const TYPE_META = {
  doc:   { icon: 'description', color: 'text-[#85adff]',   label: '문서',   grad: 'from-[#1e3a8a] to-[#1e40af]' },
  video: { icon: 'movie',       color: 'text-[#ac8aff]',   label: '동영상', grad: 'from-[#4c1d95] to-[#5b21b6]' },
  image: { icon: 'image',       color: 'text-emerald-400', label: '이미지', grad: 'from-[#064e3b] to-[#065f46]' },
  audio: { icon: 'volume_up',   color: 'text-amber-400',   label: '음성',   grad: 'from-[#78350f] to-[#92400e]' },
}
const getTypeMeta = (t) => TYPE_META[t] ?? { icon: 'insert_drive_file', color: 'text-on-surface-variant', label: t ?? '파일', grad: 'from-[#1c253e] to-[#263354]' }

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
  return data.results ?? []
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

/** v0 AIHero 퀵 서제스트 (동일 문구) */
const V0_HOME_SUGGESTIONS = ['Write an email', 'Summarize text', 'Translate', 'Generate ideas']

// ── 결과 카드 ────────────────────────────────────────────
function ResultCard({ result, onClick }) {
  const meta    = getTypeMeta(result.file_type)
  const simPct  = Math.round(result.similarity * 100)

  return (
    <div className="flex-none w-[400px] snap-start">
      <div
        onClick={onClick}
        className="bg-surface-container-high rounded-[1.5rem] p-1 h-full shadow-[0_20px_50px_rgba(0,0,0,0.3)] hover:shadow-primary/10 transition-all group/card border border-outline-variant/5 cursor-pointer hover:border-primary/20"
      >
        {/* 썸네일 영역 — 타입별 그라데이션 */}
        <div className={`relative rounded-[1.4rem] overflow-hidden aspect-video bg-gradient-to-br ${meta.grad} border border-outline-variant/10 flex items-center justify-center`}>
          <span className="material-symbols-outlined text-white/20 text-[80px]" style={{ fontVariationSettings: '"FILL" 1' }}>{meta.icon}</span>
          <div className="absolute inset-0 bg-gradient-to-t from-slate-950/90 to-transparent" />
          <div className="absolute top-4 left-4 p-2 glass-panel rounded-xl">
            <span className={`material-symbols-outlined ${meta.color}`}>{meta.icon}</span>
          </div>
          <div className="absolute bottom-4 left-4 right-4 flex justify-between items-end">
            <div className="space-y-1 min-w-0 flex-1 mr-3">
              <p className={`text-xs font-bold tracking-widest uppercase ${meta.color}`}>{meta.label}</p>
              <p className="text-lg font-bold text-on-surface truncate">{result.file_name}</p>
            </div>
            <div className="text-right shrink-0">
              <div className="text-2xl font-black text-primary">{simPct}%</div>
              <div className="text-[10px] text-on-surface-variant font-medium">유사도</div>
            </div>
          </div>
        </div>

        {/* 스니펫 */}
        <div className="p-5 space-y-3">
          <p className="text-[10px] font-bold text-primary tracking-widest uppercase">일치 내용</p>
          <p className="text-sm text-on-surface-variant leading-relaxed line-clamp-3">
            {result.snippet || '(미리보기 없음)'}
          </p>
          <div className="pt-3 border-t border-outline-variant/10 flex justify-between items-center">
            <span className="text-[10px] text-on-surface-variant/40 font-mono truncate max-w-[200px]">{result.file_path}</span>
            <span className="text-xs font-bold text-primary flex items-center gap-1 group-hover/card:translate-x-1 transition-transform shrink-0">
              열기 <span className="material-symbols-outlined text-sm">arrow_forward</span>
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── 동영상 상세: BLIP / STT 탭 뷰 ──────────────────────
function VideoDetailContent({ fileDetail, meta }) {
  const [activeTab, setActiveTab] = useState('stt')
  const chunks = fileDetail?.chunks ?? []
  const blipChunks = chunks.filter(c => c.chunk_source === 'blip')
  const sttChunks  = chunks.filter(c => c.chunk_source !== 'blip')

  const blipText = blipChunks.map(c => c.chunk_text).join(' ')
  const sttText  = sttChunks.map(c => c.chunk_text).join(' ')

  return (
    <div className="flex-1 flex flex-col">
      {/* 탭 버튼 */}
      <div className="flex gap-1 px-8 py-3 border-b border-outline-variant/10">
        {[
          { id: 'stt',  label: '음성 텍스트 (STT)',  icon: 'mic',    count: sttChunks.length  },
          { id: 'blip', label: '프레임 캡션 (BLIP)', icon: 'image',  count: blipChunks.length },
        ].map(t => (
          <button
            key={t.id}
            onClick={() => setActiveTab(t.id)}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold transition-all
              ${activeTab === t.id ? 'bg-primary/15 text-primary border border-primary/20' : 'text-on-surface-variant hover:bg-white/5'}`}
          >
            <span className="material-symbols-outlined text-sm">{t.icon}</span>
            {t.label}
            <span className={`ml-1 px-1.5 py-0.5 rounded-full text-[9px] ${activeTab === t.id ? 'bg-primary/20 text-primary' : 'bg-white/10 text-on-surface-variant'}`}>
              {t.count}
            </span>
          </button>
        ))}
      </div>
      {/* 콘텐츠 */}
      <div className="flex-1 px-8 py-6 overflow-y-auto max-h-[420px]">
        {activeTab === 'stt' ? (
          sttText
            ? <p className="text-on-surface-variant/90 leading-relaxed text-sm whitespace-pre-wrap">{sttText}</p>
            : <p className="text-on-surface-variant/30 text-sm">(음성 텍스트 없음)</p>
        ) : (
          blipText
            ? <p className="text-on-surface-variant/90 leading-relaxed text-sm whitespace-pre-wrap">{blipText}</p>
            : <p className="text-on-surface-variant/30 text-sm">(프레임 캡션 없음)</p>
        )}
      </div>
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
  const [fileDetail, setFileDetail] = useState(null)   // 상세 전체 콘텐츠
  const [detailLoading, setDetailLoading] = useState(false)

  // 검색 결과
  const [results, setResults] = useState([])
  const [searching, setSearching] = useState(false)
  const [searchError, setSearchError] = useState('')

  // home → results 애니메이션
  const [flyStyle, setFlyStyle] = useState(null)
  const [homeExiting, setHomeExiting] = useState(false)
  const [resultsReady, setResultsReady] = useState(false)
  const [searchFocused, setSearchFocused] = useState(false)

  // results → detail 슬라이드
  const [detailVisible, setDetailVisible] = useState(false)

  // AI 포털 전환
  const [aiTransitioning, setAiTransitioning] = useState(false)
  const [ripplePos, setRipplePos] = useState({ x: '50%', y: '50%' })

  /** 홈 첫 진입 시 stagger 등장(보안 인증 포털 직후 메인과 이어지게) */
  const [searchEntranceOn, setSearchEntranceOn] = useState(
    () =>
      typeof window !== 'undefined' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches,
  )

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

  useEffect(() => {
    if (
      typeof window !== 'undefined' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches
    )
      return
    /* 한 박자 쉬었다가 entrance-on: 블러 초기 상태가 한 번 보이도록 */
    const t = window.setTimeout(() => setSearchEntranceOn(true), 180)
    return () => clearTimeout(t)
  }, [])

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
      // 검색창 fly 애니메이션
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
    // 전체 콘텐츠 비동기 fetch
    setDetailLoading(true)
    fetch(`${API_BASE}/api/files/detail?path=${encodeURIComponent(file.file_path)}`)
      .then(r => r.json())
      .then(d => { setFileDetail(d); setDetailLoading(false) })
      .catch(() => setDetailLoading(false))
  }

  const handleBackToResults = () => { setDetailVisible(false); setTimeout(() => setView('results'), 320) }

  const handleGoToAI = () => {
    const rect = btnRef.current?.getBoundingClientRect()
    if (rect) setRipplePos({ x: `${rect.left + rect.width / 2}px`, y: `${rect.top + rect.height / 2}px` })
    setAiTransitioning(true)
    setTimeout(() => navigate('/ai'), 900)
  }

  return (
    <div
      className={`relative text-on-surface ${view === 'home' ? 'min-h-screen h-screen overflow-x-hidden overflow-y-auto' : 'min-h-screen overflow-x-hidden'}`}
    >
      <AmbientPageBackdrop />

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
            <span className="font-manrope uppercase tracking-[0.25em] text-xs text-[#a5aac2]">AI 모드</span>
          </div>
        </div>
      )}

      {/* 사이드바 */}
      <SearchSidebar />

      {/* ════ HOME — v0 AIHero 레이아웃 + 기존 검색/STT/플라이 로직 ════ */}
      {view === 'home' && (
        <>
          <main
            className={`${ml} relative z-10 flex h-full flex-col items-center justify-center overflow-visible px-6 pb-16 pt-14 transition-[margin] duration-300 md:px-8 md:pt-16 ${
              searchEntranceOn ? 'main-search-entrance-on' : 'main-search-entrance-off'
            }`}
          >
            <div className="z-10 flex w-full max-w-xl flex-col items-center">
              {/* Hero (v0) */}
              <div
                className={`mse-hero-down mb-6 text-center transition-all duration-300 ${homeExiting ? 'opacity-0 -translate-y-6' : ''}`}
              >
                <h1 className="mb-3 text-3xl font-light tracking-tight text-on-surface text-balance md:text-5xl lg:text-6xl">
                  Local Intelligence
                </h1>
                <p className="text-lg text-on-surface-variant md:text-xl">Your Data Stays Yours</p>
              </div>

              {/* Orb (v0) */}
              <div
                className={`mse-orb-mid my-4 overflow-visible md:my-8 ${homeExiting ? 'pointer-events-none opacity-0' : ''}`}
              >
                <AnimatedOrb onMicClick={toggleMic} listening={listening} />
              </div>

              {/* 검색 필 (v0 LLM input 스타일) */}
              <form
                ref={formRef}
                onSubmit={handleSearch}
                className="mse-search-up relative w-full max-w-xl"
                style={homeExiting ? { visibility: 'hidden' } : {}}
              >
                <div
                  className={`relative flex items-center gap-3 rounded-full border bg-surface-container-high/60 px-1 py-1 pl-2 backdrop-blur-xl transition-all duration-300 md:pl-3
                    ${
                      listening
                        ? 'border-red-400/60 shadow-[0_0_24px_rgba(248,113,113,0.2)]'
                        : searchFocused
                          ? 'border-primary/50 shadow-lg shadow-primary/20'
                          : 'border-white/10 hover:border-white/20'
                    }`}
                >
                  <div className="pl-3 md:pl-4">
                    <span className={`material-symbols-outlined text-xl ${listening ? 'text-red-400' : 'text-on-surface-variant'}`}>
                      search
                    </span>
                  </div>
                  <div className="relative min-h-[3.25rem] flex-1">
                    <input
                      type="text"
                      value={listening ? '' : inputValue}
                      onChange={(e) => !listening && setInputValue(e.target.value)}
                      onFocus={() => setSearchFocused(true)}
                      onBlur={() => setSearchFocused(false)}
                      placeholder={listening ? '' : 'Ask anything...'}
                      className="h-full w-full bg-transparent py-3 text-base text-on-surface placeholder:text-on-surface-variant/50 focus:outline-none md:py-4 md:text-base"
                      readOnly={listening}
                    />
                    {listening && (
                      <div className="absolute inset-0 flex items-center gap-2 py-3 pointer-events-none md:py-4">
                        <span className="truncate font-manrope text-base text-red-400">
                          {interim || <span className="text-on-surface-variant/50">듣는 중...</span>}
                        </span>
                        <div className="flex shrink-0 items-center gap-[3px]">
                          {[0, 0.15, 0.3, 0.15, 0].map((delay, i) => (
                            <div
                              key={i}
                              className="animate-bounce rounded-full bg-red-400"
                              style={{
                                width: '3px',
                                height: `${[10, 16, 22, 16, 10][i]}px`,
                                animationDelay: `${delay}s`,
                                animationDuration: '0.8s',
                              }}
                            />
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                  <button
                    type="submit"
                    disabled={aiTransitioning}
                    className="mr-2 shrink-0 rounded-full bg-primary p-2 text-on-primary-fixed transition-colors hover:bg-primary-dim disabled:opacity-40 md:mr-3"
                  >
                    <span className="material-symbols-outlined text-xl">arrow_forward</span>
                  </button>
                </div>
              </form>

              {/* Quick suggestions (v0) */}
              <div
                className={`mse-search-up mse-search-up-delay-1 mt-6 flex flex-wrap justify-center gap-2 transition-all duration-300 ${homeExiting ? 'pointer-events-none opacity-0' : ''}`}
              >
                {V0_HOME_SUGGESTIONS.map((suggestion) => (
                  <button
                    key={suggestion}
                    type="button"
                    onClick={() => setInputValue(suggestion)}
                    className="rounded-full border border-white/5 bg-surface-container-high/40 px-4 py-2 text-sm text-on-surface-variant backdrop-blur-sm transition-all hover:border-white/10 hover:bg-surface-container-high/60 hover:text-on-surface"
                  >
                    {suggestion}
                  </button>
                ))}
              </div>

              <div
                className={`mse-search-up mse-search-up-delay-2 mt-10 flex justify-center ${homeExiting ? 'pointer-events-none opacity-0' : ''}`}
              >
                <button
                  ref={btnRef}
                  type="button"
                  onClick={handleGoToAI}
                  disabled={aiTransitioning}
                  className="group flex items-center gap-3 rounded-full border border-outline-variant/20 bg-surface-container-high px-8 py-3 text-sm font-bold uppercase tracking-widest text-on-surface-variant transition-all duration-300 hover:bg-surface-container-highest hover:text-on-surface disabled:pointer-events-none glow-primary"
                >
                  <span className="h-2 w-2 animate-pulse rounded-full bg-primary" />
                  AI 모드로 전환
                  <span className="material-symbols-outlined text-lg transition-transform group-hover:translate-x-1">arrow_forward</span>
                </button>
              </div>

              {/* fly 클론 */}
              {flyStyle && (
                <div style={{ ...flyStyle }}>
                  <div className="flex items-center gap-3 rounded-full border border-primary/40 bg-surface-container-high/80 px-4 py-3 shadow-[0_0_30px_rgba(133,173,255,0.15)] backdrop-blur-xl">
                    <span className="material-symbols-outlined text-primary">search</span>
                    <span className="flex-1 truncate font-manrope text-sm text-on-surface">{inputValue}</span>
                  </div>
                </div>
              )}
            </div>
          </main>
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
              <span className={`material-symbols-outlined text-sm ${listening ? 'text-red-400' : 'text-primary'}`}>search</span>
              <div className="flex-1 relative">
                <input
                  className="bg-transparent border-none focus:ring-0 w-full text-on-surface placeholder-on-surface-variant text-sm outline-none"
                  placeholder={listening ? '' : '인텔리전스에 질문하세요...'}
                  value={listening ? '' : inputValue}
                  onChange={(e) => !listening && setInputValue(e.target.value)}
                  readOnly={listening}
                />
                {listening && (
                  <div className="absolute inset-0 flex items-center gap-2 pointer-events-none">
                    <span className="text-red-400 text-sm truncate">{interim || '듣는 중...'}</span>
                    <div className="flex items-center gap-[2px] shrink-0">
                      {[0,0.1,0.2,0.1,0].map((d,i) => (
                        <div key={i} className="w-[2px] bg-red-400 rounded-full animate-bounce"
                          style={{ height: `${[6,10,14,10,6][i]}px`, animationDelay: `${d}s`, animationDuration: '0.7s' }} />
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          </form>

          {view === 'detail' && (
            <button onClick={handleBackToResults}
              className="flex items-center gap-2 px-4 py-2 rounded-full bg-surface-container-high border border-outline-variant/20 text-xs font-bold text-on-surface-variant hover:text-primary hover:border-primary/30 transition-all shrink-0">
              <span className="material-symbols-outlined text-sm">arrow_back</span>결과로
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
                <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-primary/10 text-primary uppercase tracking-widest border border-primary/20">현재 쿼리</span>
                <h1 className="text-4xl font-extrabold tracking-tighter text-on-surface">{query}</h1>
                {searching
                  ? <p className="text-on-surface-variant flex items-center gap-2">
                      <span className="material-symbols-outlined text-primary text-sm animate-spin">progress_activity</span>검색 중...
                    </p>
                  : searchError
                    ? <p className="text-red-400 text-sm">{searchError}</p>
                    : <p className="text-on-surface-variant">로컬 보관소에서 <span className="text-primary font-bold">{results.length}건</span>을 찾았습니다.</p>
                }
              </div>
              <div className="flex gap-3">
                <button className="px-4 py-2 rounded-full glass-panel border border-outline-variant/20 text-xs font-bold hover:bg-primary/5 transition-all flex items-center gap-2">
                  <span className="material-symbols-outlined text-sm">filter_list</span>관련도
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
                  <ResultCard key={r.file_path + i} result={r} onClick={() => handleSelectFile(r)} />
                ))}
              </div>
            )}

            {/* 하단 통계 */}
            {!searching && results.length > 0 && (
              <div className="mt-12 glass-panel rounded-[1.5rem] p-6 border border-outline-variant/10 relative overflow-hidden">
                <div className="absolute -right-20 -top-20 w-64 h-64 bg-primary/10 rounded-full blur-[80px]" />
                <div className="relative z-10">
                  <h3 className="text-sm font-bold text-primary mb-4 flex items-center gap-2 uppercase tracking-widest">
                    <span className="material-symbols-outlined text-sm">analytics</span>검색 요약
                  </h3>
                  <p className="text-on-surface leading-relaxed mb-6">
                    <span className="text-primary font-bold">"{query}"</span>에 대해 벡터 유사도 기준으로 정렬된 결과입니다.
                  </p>
                  <div className="grid grid-cols-4 gap-4">
                    {[
                      ['총 결과', `${results.length}건`],
                      ['최고 유사도', `${Math.round((results[0]?.similarity ?? 0) * 100)}%`],
                      ['문서', `${results.filter(r => r.file_type === 'doc').length}건`],
                      ['미디어', `${results.filter(r => r.file_type !== 'doc').length}건`],
                    ].map(([label, val]) => (
                      <div key={label} className="p-4 rounded-2xl bg-slate-900/40 border border-outline-variant/5">
                        <p className="text-[10px] text-slate-500 uppercase tracking-widest mb-1">{label}</p>
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
        const meta   = getTypeMeta(selectedFile.file_type)
        const simPct = Math.round(selectedFile.similarity * 100)
        return (
          <main className={`${ml} min-h-screen relative transition-[margin] duration-300`}
            style={{ backgroundImage: 'radial-gradient(rgba(133,173,255,0.05) 1px, transparent 1px)', backgroundSize: '32px 32px',
              opacity: detailVisible ? 1 : 0, transform: detailVisible ? 'translateX(0)' : 'translateX(36px)',
              transition: 'opacity 0.35s ease, transform 0.35s ease, margin 0.3s' }}>

            {/* 파일 정보 바 */}
            <div className={`fixed top-[88px] ${leftEdge} right-0 z-30 bg-[#070d1f]/60 backdrop-blur-xl flex items-center justify-between px-8 py-3 border-b border-outline-variant/10 transition-[left] duration-300`}>
              <div className="flex items-center gap-3 min-w-0 flex-1 mr-4">
                <span className={`material-symbols-outlined ${meta.color} shrink-0`}>{meta.icon}</span>
                <span className="font-manrope text-sm tracking-wide text-[#dfe4fe] font-bold truncate">{selectedFile.file_name}</span>
                <span className="px-2 py-0.5 rounded-full bg-primary/10 text-primary text-[10px] font-bold border border-primary/20 shrink-0">{simPct}%</span>
                <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold border shrink-0 ${meta.color} bg-white/5 border-white/10`}>{meta.label}</span>
              </div>
              <div className="flex items-center gap-3 shrink-0">
                <button
                  onClick={() => openFolder(selectedFile.file_path)}
                  className="px-5 py-2 text-xs font-bold uppercase tracking-widest text-primary bg-surface-container-high border border-outline-variant/15 rounded-full hover:bg-surface-variant transition-colors active:scale-95">
                  경로 열기
                </button>
                <button
                  onClick={() => openFile(selectedFile.file_path)}
                  className="px-5 py-2 text-xs font-bold uppercase tracking-widest text-on-primary bg-primary rounded-full hover:brightness-110 transition-all active:scale-95">
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
                      <span className="text-[10px] font-bold tracking-[0.2em] text-primary uppercase">추출된 콘텐츠 스트림</span>
                      <div className="flex gap-2 items-center">
                        {detailLoading && <span className="material-symbols-outlined text-primary text-sm animate-spin">progress_activity</span>}
                        <span className="h-2 w-2 rounded-full bg-primary animate-pulse" />
                        <span className="h-2 w-2 rounded-full bg-secondary/50" />
                      </div>
                    </div>

                    {/* 동영상: BLIP + STT 탭 */}
                    {selectedFile.file_type === 'video' && fileDetail ? (
                      <VideoDetailContent fileDetail={fileDetail} meta={meta} />
                    ) : (
                      <div className="flex-1 px-8 py-6">
                        {detailLoading ? (
                          <div className="flex items-center gap-2 text-on-surface-variant/40">
                            <span className="material-symbols-outlined animate-spin text-sm">progress_activity</span>
                            <span className="text-sm">콘텐츠 불러오는 중...</span>
                          </div>
                        ) : fileDetail?.full_text ? (
                          <p className="text-on-surface-variant/90 leading-relaxed text-sm whitespace-pre-wrap">{fileDetail.full_text}</p>
                        ) : selectedFile.snippet ? (
                          <p className="text-on-surface-variant/90 leading-relaxed text-sm whitespace-pre-wrap">{selectedFile.snippet}</p>
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

                  {/* 유사도 카드 */}
                  <div className="bg-surface-container-high rounded-xl p-6 border border-outline-variant/10 relative overflow-hidden group">
                    <div className="absolute -right-4 -top-4 w-24 h-24 bg-primary/10 blur-3xl group-hover:bg-primary/20 transition-all" />
                    <h4 className="text-[10px] font-bold tracking-[0.15em] text-primary mb-4 uppercase">유사도 분석</h4>
                    <div className="space-y-3">
                      <div className="flex items-center gap-3">
                        <div className="flex-1 h-1.5 bg-surface-container-highest rounded-full overflow-hidden">
                          <div className="h-full bg-gradient-to-r from-primary to-secondary shadow-[0_0_8px_rgba(133,173,255,0.5)] transition-all duration-700"
                            style={{ width: `${simPct}%` }} />
                        </div>
                        <span className="text-sm font-bold text-on-surface tabular-nums">{simPct}%</span>
                      </div>
                      <p className="text-xs text-on-surface-variant/60">코사인 유사도 기준 상위 매칭</p>
                    </div>
                  </div>

                  {/* 파일 메타데이터 */}
                  <div className="bg-surface-container-low rounded-xl p-6 border border-outline-variant/5">
                    <h4 className="text-[10px] font-bold tracking-[0.15em] text-secondary mb-4 uppercase">파일 정보</h4>
                    <div className="space-y-0">
                      {[
                        ['파일명', selectedFile.file_name],
                        ['유형',   meta.label],
                        ['유사도', `${simPct}%`],
                        ['청크 수', fileDetail ? `${fileDetail.chunks?.length ?? '-'}개` : '-'],
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
                      <span className="material-symbols-outlined text-xs text-on-surface-variant">open_in_new</span>
                    </button>
                    <button
                      onClick={() => openFolder(selectedFile.file_path)}
                      className="w-full group flex items-center justify-between p-4 rounded-xl bg-surface-container-highest hover:bg-primary/10 transition-colors border border-transparent hover:border-primary/20">
                      <div className="flex items-center gap-3">
                        <span className="material-symbols-outlined text-on-surface-variant group-hover:text-primary">folder_open</span>
                        <span className="text-sm font-semibold">탐색기에서 보기</span>
                      </div>
                      <span className="material-symbols-outlined text-xs text-on-surface-variant">chevron_right</span>
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
