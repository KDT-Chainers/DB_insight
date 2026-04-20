import { useState, useRef, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import SearchSidebar from '../components/SearchSidebar'
import { useSidebar } from '../context/SidebarContext'

// ── STT 훅 ──────────────────────────────────────────────
function useSpeechRecognition({ onFinal }) {
  const [listening, setListening] = useState(false)
  const [interim, setInterim] = useState('')
  const recognitionRef = useRef(null)
  const latestRef = useRef('')

  const start = useCallback(() => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition
    if (!SR) { alert('이 환경에서는 음성 인식이 지원되지 않습니다.'); return }

    const r = new SR()
    r.lang = 'ko-KR'
    r.continuous = false
    r.interimResults = true

    r.onstart = () => { setListening(true); setInterim(''); latestRef.current = '' }

    r.onresult = (e) => {
      let fin = '', tmp = ''
      for (let i = e.resultIndex; i < e.results.length; i++) {
        if (e.results[i].isFinal) fin += e.results[i][0].transcript
        else tmp += e.results[i][0].transcript
      }
      if (tmp) { setInterim(tmp); latestRef.current = tmp }
      if (fin) { setInterim(''); latestRef.current = fin }
    }

    r.onend = () => {
      setListening(false)
      setInterim('')
      const text = latestRef.current.trim()
      latestRef.current = ''
      if (text) onFinal(text)
    }

    r.onerror = () => { setListening(false); setInterim('') }

    recognitionRef.current = r
    r.start()
  }, [onFinal])

  const stop = useCallback(() => {
    recognitionRef.current?.stop()
  }, [])

  const toggle = useCallback(() => {
    if (listening) stop()
    else start()
  }, [listening, start, stop])

  return { listening, interim, toggle }
}

const RESULTS = [
  {
    id: '1',
    type: '문서',
    name: 'vector_database_arch_v2.pdf',
    similarity: '98%',
    icon: 'description',
    iconColor: 'text-primary',
    reason: '신경망 클러스터 쿼리와 일치하는 로컬 벡터 저장소 아키텍처 다이어그램이 포함되어 있습니다.',
    img: 'https://lh3.googleusercontent.com/aida-public/AB6AXuBzDCy3TCFjaRCUXkAmFkejs4ryS2sp53Cj6ZA8ReqVAz_eOX4B2M101z86d8j-hiEDQ50yERnpDqCKDZ604xKJ238H_ZOravJHM9oL1fYC9Q7BmG5zlkBBQrtuzKMbHM-LSjDO6Xp8Q6WgeZJNYKTAv5_wPmCQQF3LjiQDt4Zjvkm8fDLgkxfuEMnK01p9FquLmW5ye7t0vKEGKij9wJIu2h3aonO7QaJ1cCRS1ozTD6DDMCF0Kw0IGLvDcWMmQNKQiG01QDSlxli9',
  },
  {
    id: '2',
    type: '동영상',
    name: 'node_clustering_demo.mp4',
    similarity: '92%',
    icon: 'movie',
    iconColor: 'text-secondary',
    reason: '02:45부터 시작하는 메타데이터 트랙에서 식별된 노드 연결점의 시각적 데모입니다.',
    img: 'https://lh3.googleusercontent.com/aida-public/AB6AXuBGsh-aKl9e4wjjrd75-2XG231PmwX2z_wyF8OR2dotcOI9Q2xww7ak7U_DQdT5G6gWDI-JX9XDSnoSBLWLMnAmj0fSDvCo8gBvCtqldry5T7X-Tj5sz2Oj3r1HtnMtCm8_exkFvPDJsKnV0mZ9-CzaKe1Q4EfftzYu2QCJ2h8T6vGiFTZpc38WuGidSBQiNiugNWu4qBlCijFjqni4JcNwdz0XbaxOwQvc6yBolRCp9BbhFyA5xnXlam8YTTpqQPZ5bKIQ34SQVp3r',
  },
  {
    id: '3',
    type: '이미지',
    name: 'local_intelligence_map.png',
    similarity: '87%',
    icon: 'image',
    iconColor: 'text-primary',
    reason: '클러스터 쿼리 파라미터와 일치하는 노드의 하드웨어 분산 현황을 보여주는 시각적 맵입니다.',
    img: 'https://lh3.googleusercontent.com/aida-public/AB6AXuD_kJpxDBr7JrfSFTZGIhAMqlRgbenA1NI-txWQnDl_B2HXw7HPksPhJaRa4BZ2rME4vI3RV-knNZau-ErAaGBBRxNQeEMxlvRPi2Un-Ww4Uy3pwvJdLD8WWqutNUVefAWaLEAh9LVMuyuFucw49KMi_KWjch7wSDoFB5dAgyVlTMOpeASeyqqGfuWV9Nc6VQtc8wtUX__jYd_WgdOkkH7A8UP454_VAcbBs92z42ZqDfdMWEbs4pXiDJ-VE9vJ1y89yo2hY5F2SXlq',
  },
  {
    id: '4',
    type: '시스템 로그',
    name: 'cluster_performance_log.txt',
    similarity: '81%',
    icon: 'article',
    iconColor: 'text-secondary',
    reason: '아키텍처 검색에 언급된 특정 클러스터의 원시 성능 데이터가 포함되어 있습니다.',
    img: 'https://lh3.googleusercontent.com/aida-public/AB6AXuAHAF3v7t44jdCPpXChdt_rv3ClyfpSU6H_qVC4NY_l5jlEIOkHO9N_hbnd9yemgEKeOFDLBWOTlawnHOx8aKAmt0_tdag0fSp8pGmlctZlN1b_ht5R0ZIjEfvT7FJsEHNO8O71N-y2kkjDSyrtytDekK8k0N3Gju_3NIXQiuLB1B26E33dV6f0ZUnGWTWwub9ttPrfB-UGTSwCdfTHjjXH6f85xfe_d76TxeeWT9ArtfoQrGdq7-E13X-VqVYFhtN4674dbNFRGNPX',
  },
]

export default function MainSearch() {
  const navigate = useNavigate()
  const { open } = useSidebar()

  // view: 'home' | 'results' | 'detail'
  const [view, setView] = useState('home')
  const [query, setQuery] = useState('')
  const [inputValue, setInputValue] = useState('')
  const [selectedFile, setSelectedFile] = useState(null)

  // home → results: fly animation
  const [flyStyle, setFlyStyle] = useState(null)
  const [homeExiting, setHomeExiting] = useState(false)
  const [resultsReady, setResultsReady] = useState(false)

  // results → detail: slide in
  const [detailVisible, setDetailVisible] = useState(false)

  // AI portal
  const [aiTransitioning, setAiTransitioning] = useState(false)
  const [ripplePos, setRipplePos] = useState({ x: '50%', y: '50%' })

  const btnRef = useRef(null)
  const formRef = useRef(null)

  // STT — doSearch보다 먼저 선언하지만 ref로 지연 참조
  const doSearchRef = useRef(null)
  const { listening, interim, toggle: toggleMic } = useSpeechRecognition({
    onFinal: useCallback((text) => {
      setInputValue(text)
      setTimeout(() => doSearchRef.current?.(text), 80)
    }, []),
  })

  const ml = open ? 'ml-64' : 'ml-0'
  const leftEdge = open ? 'left-64' : 'left-0'
  const sidebarPx = open ? 256 : 0

  // 브라우저 뒤로가기 처리
  useEffect(() => {
    const handlePopState = () => {
      setDetailVisible(false)
      if (view === 'detail') {
        setTimeout(() => setView('results'), 320)
      } else if (view === 'results') {
        setResultsReady(false)
        setView('home')
      }
    }
    window.addEventListener('popstate', handlePopState)
    return () => window.removeEventListener('popstate', handlePopState)
  }, [view])

  const doSearch = (q) => {
    if (!q.trim() || aiTransitioning) return
    setQuery(q)
    setInputValue(q)

    if (view === 'home') {
      const rect = formRef.current?.getBoundingClientRect()
      if (rect) {
        setFlyStyle({
          position: 'fixed',
          top: rect.top,
          left: rect.left,
          width: rect.width,
          transition: 'none',
          zIndex: 9998,
        })
        setHomeExiting(true)
        requestAnimationFrame(() => {
          requestAnimationFrame(() => {
            setFlyStyle({
              position: 'fixed',
              top: 10,
              left: sidebarPx + 180,
              width: `calc(100vw - ${sidebarPx + 460}px)`,
              transition: 'all 0.45s cubic-bezier(0.4,0,0.2,1)',
              zIndex: 9998,
            })
          })
        })
      }
      setTimeout(() => {
        setFlyStyle(null)
        setHomeExiting(false)
        setResultsReady(false)
        setView('results')
        window.history.pushState({ view: 'results' }, '')
        requestAnimationFrame(() => setResultsReady(true))
      }, 480)
    } else {
      setView('results')
    }
  }

  // doSearch ref 항상 최신 유지 (STT onFinal 콜백에서 사용)
  useEffect(() => { doSearchRef.current = doSearch })

  const handleSearch = (e) => {
    e?.preventDefault()
    doSearch(inputValue)
  }

  const handleSelectFile = (file) => {
    setSelectedFile(file)
    setDetailVisible(false)
    setView('detail')
    window.history.pushState({ view: 'detail' }, '')
    requestAnimationFrame(() => requestAnimationFrame(() => setDetailVisible(true)))
  }

  const handleBackToResults = () => {
    setDetailVisible(false)
    setTimeout(() => setView('results'), 320)
  }

  const handleGoToAI = () => {
    const rect = btnRef.current?.getBoundingClientRect()
    if (rect) setRipplePos({ x: `${rect.left + rect.width / 2}px`, y: `${rect.top + rect.height / 2}px` })
    setAiTransitioning(true)
    setTimeout(() => navigate('/ai'), 900)
  }

  return (
    <div
      className={view === 'home' ? 'overflow-hidden h-screen grid-bg relative' : 'min-h-screen relative bg-background text-on-surface'}
      style={view !== 'home' ? { backgroundImage: 'radial-gradient(circle at 2px 2px, rgba(65,71,91,0.15) 1px, transparent 0)', backgroundSize: '32px 32px' } : {}}
    >

      {/* AI 포털 전환 */}
      {aiTransitioning && (
        <div className="fixed inset-0 z-[9999] pointer-events-none overflow-hidden">
          <div
            className="portal-overlay absolute rounded-full"
            style={{
              width: '80px', height: '80px',
              left: ripplePos.x, top: ripplePos.y,
              transform: 'translate(-50%, -50%)',
              background: 'radial-gradient(circle, #1c253e 0%, #0c1326 60%, #070d1f 100%)',
              boxShadow: '0 0 30px 10px rgba(172,138,255,0.15)',
            }}
          />
          {[0, 200].map((delay, i) => (
            <div
              key={i}
              className="portal-ring absolute rounded-full border border-[#ac8aff]/25"
              style={{
                width: '160px', height: '160px',
                left: ripplePos.x, top: ripplePos.y,
                transform: 'translate(-50%, -50%)',
                animationDelay: `${delay}ms`,
              }}
            />
          ))}
          <div className="portal-text absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 flex flex-col items-center gap-2">
            <span className="material-symbols-outlined text-[#a5aac2] text-4xl" style={{ fontVariationSettings: '"FILL" 1' }}>psychology</span>
            <span className="font-manrope uppercase tracking-[0.25em] text-xs text-[#a5aac2]">AI 모드</span>
          </div>
        </div>
      )}

      {/* 사이드바 — 항상 마운트 유지 */}
      <SearchSidebar />

      {/* ════════════════════════════════
          HOME VIEW
      ════════════════════════════════ */}
      {view === 'home' && (
        <>

          <main className={`${ml} h-full flex flex-col items-center justify-center p-8 pt-16 relative transition-[margin] duration-300`}>
            <div className="absolute top-1/4 left-1/4 w-96 h-96 bg-primary/10 rounded-full blur-[120px] pointer-events-none"></div>
            <div className="absolute bottom-1/4 right-1/4 w-[500px] h-[500px] bg-secondary/5 rounded-full blur-[150px] pointer-events-none"></div>

            <div className="w-full max-w-4xl flex flex-col items-center z-10">
              <div className={`mb-12 text-center transition-all duration-300 ${homeExiting ? 'opacity-0 -translate-y-6' : 'opacity-100 translate-y-0'}`}>
                <h2 className="text-5xl md:text-6xl font-black tracking-tighter text-on-surface mb-4">
                  로컬 인텔리전스<span className="text-primary">.</span>
                </h2>
                <p className="text-on-surface-variant text-lg max-w-xl mx-auto font-light">
                  개인 신경망 엔진이 파일을 인덱싱하고 분석합니다.
                </p>
              </div>

              <form
                ref={formRef}
                onSubmit={handleSearch}
                className="w-full relative group"
                style={homeExiting ? { visibility: 'hidden' } : {}}
              >
                <div className={`glass-effect rounded-full p-2 flex items-center gap-4 shadow-[0_0_50px_rgba(133,173,255,0.1)] transition-all duration-300
                  ${listening
                    ? 'border border-red-400/60 shadow-[0_0_30px_rgba(248,113,113,0.2)]'
                    : 'border border-outline-variant/20 hover:border-primary/40'}`}>
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
                    {/* 음성 인식 중 표시 */}
                    {listening && (
                      <div className="absolute inset-0 flex items-center gap-3 py-4 pointer-events-none">
                        <span className="text-red-400 font-manrope text-lg truncate">
                          {interim || <span className="text-on-surface-variant/50">듣는 중...</span>}
                        </span>
                        {/* 웨이브 애니메이션 */}
                        <div className="flex items-center gap-[3px] shrink-0">
                          {[0, 0.15, 0.3, 0.15, 0].map((delay, i) => (
                            <div key={i} className="w-[3px] bg-red-400 rounded-full animate-bounce"
                              style={{ height: `${[12,20,28,20,12][i]}px`, animationDelay: `${delay}s`, animationDuration: '0.8s' }} />
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                  {/* 마이크 버튼 */}
                  <button
                    type="button"
                    onClick={toggleMic}
                    className={`w-12 h-12 rounded-full flex items-center justify-center transition-all duration-200 shrink-0
                      ${listening
                        ? 'bg-red-500/20 text-red-400 animate-pulse'
                        : 'text-on-surface-variant hover:text-primary hover:bg-primary/10'}`}
                  >
                    <span className="material-symbols-outlined" style={listening ? { fontVariationSettings: '"FILL" 1' } : {}}>
                      {listening ? 'mic' : 'mic'}
                    </span>
                  </button>
                </div>
              </form>

              <div className="mt-10 flex justify-center" style={homeExiting ? { visibility: 'hidden' } : {}}>
                <button
                  ref={btnRef}
                  onClick={handleGoToAI}
                  disabled={aiTransitioning}
                  className="px-8 py-3 rounded-full bg-surface-container-high border border-outline-variant/20 flex items-center gap-3 text-sm font-bold tracking-widest uppercase text-on-surface-variant hover:text-on-surface hover:bg-surface-container-highest transition-all duration-300 group glow-primary disabled:pointer-events-none"
                >
                  <span className="w-2 h-2 rounded-full bg-primary animate-pulse"></span>
                  AI 모드로 전환
                  <span className="material-symbols-outlined text-lg group-hover:translate-x-1 transition-transform">arrow_forward</span>
                </button>
              </div>

              {/* 검색창 fly 클론 */}
              {flyStyle && (
                <div style={{ ...flyStyle }}>
                  <div className="glass-effect rounded-full p-2 border border-primary/40 shadow-[0_0_30px_rgba(133,173,255,0.15)] flex items-center gap-3 px-4 py-3">
                    <span className="material-symbols-outlined text-primary">search</span>
                    <span className="flex-1 text-on-surface font-manrope text-sm truncate">{inputValue}</span>
                  </div>
                </div>
              )}

              <div className={`grid grid-cols-1 md:grid-cols-3 gap-4 mt-24 w-full transition-all duration-300 ${homeExiting ? 'opacity-0 translate-y-4' : 'opacity-100 translate-y-0'}`}>
                {[
                  { icon: 'summarize', color: 'text-primary', title: 'PDF 요약', sub: '신경망 처리' },
                  { icon: 'search_insights', color: 'text-secondary', title: '심층 메타데이터', sub: '속성 분석' },
                  { icon: 'auto_awesome', color: 'text-primary', title: '비주얼 검색', sub: '비전 엔진' },
                ].map((card) => (
                  <div key={card.title} className="glass-effect p-6 rounded-xl border border-outline-variant/15 hover:border-primary/20 transition-all group cursor-pointer">
                    <span className={`material-symbols-outlined ${card.color} mb-4 block`}>{card.icon}</span>
                    <h3 className="text-on-surface font-bold mb-1">{card.title}</h3>
                    <p className="text-on-surface-variant text-xs uppercase tracking-tighter">{card.sub}</p>
                  </div>
                ))}
              </div>
            </div>

            <div className="absolute bottom-0 left-0 w-full h-32 bg-gradient-to-t from-surface-container-low/80 to-transparent pointer-events-none"></div>
          </main>

          <div className="fixed top-0 right-0 w-1/3 h-screen bg-gradient-to-l from-primary/5 to-transparent pointer-events-none"></div>
        </>
      )}

      {/* ════════════════════════════════
          RESULTS / DETAIL 공통 헤더
      ════════════════════════════════ */}
      {view !== 'home' && (
        /* top-8 = 드래그 바(32px) 아래에서 시작 */
        <header className={`fixed top-8 ${leftEdge} right-0 z-40 bg-slate-950/60 backdrop-blur-xl flex items-center px-6 py-3 gap-4 border-b border-outline-variant/10 shadow-[0_0_20px_rgba(133,173,255,0.1)] transition-[left] duration-300`}>
          <button
            onClick={() => { setView('home'); setInputValue('') }}
            className={`text-lg font-bold tracking-tighter bg-gradient-to-r from-blue-300 to-purple-400 bg-clip-text text-transparent shrink-0 hover:opacity-70 transition-opacity ${!open ? 'ml-10' : ''}`}
          >
            DB_insight
          </button>

          <form onSubmit={handleSearch} className="flex-1">
            <div className={`flex items-center rounded-full border px-4 py-2 gap-3 transition-all
              ${listening
                ? 'bg-red-500/5 border-red-400/50 shadow-[0_0_15px_rgba(248,113,113,0.15)]'
                : 'bg-surface-container-high border-outline-variant/20 focus-within:border-primary/50'}`}>
              <span className={`material-symbols-outlined text-sm ${listening ? 'text-red-400' : 'text-primary'}`}>
                {listening ? 'mic' : 'search'}
              </span>
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
              <button
                type="button"
                onClick={toggleMic}
                className={`shrink-0 transition-all duration-200 ${listening ? 'text-red-400 animate-pulse' : 'text-on-surface-variant hover:text-primary'}`}
              >
                <span className="material-symbols-outlined text-sm" style={listening ? { fontVariationSettings: '"FILL" 1' } : {}}>mic</span>
              </button>
            </div>
          </form>

          {view === 'detail' && (
            <button
              onClick={handleBackToResults}
              className="flex items-center gap-2 px-4 py-2 rounded-full bg-surface-container-high border border-outline-variant/20 text-xs font-bold text-on-surface-variant hover:text-primary hover:border-primary/30 transition-all shrink-0"
            >
              <span className="material-symbols-outlined text-sm">arrow_back</span>
              결과로
            </button>
          )}
        </header>
      )}

      {/* ════════════════════════════════
          RESULTS VIEW
      ════════════════════════════════ */}
      {view === 'results' && (
        <main
          className={`${ml} pt-24 min-h-screen transition-[margin] duration-300`}
          style={{
            opacity: resultsReady ? 1 : 0,
            transform: resultsReady ? 'translateY(0)' : 'translateY(24px)',
            transition: 'opacity 0.38s ease, transform 0.38s ease, margin 0.3s',
          }}
        >
          <div className="p-8 max-w-[1400px] mx-auto">
            <div className="flex justify-between items-end mb-10">
              <div className="space-y-2">
                <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-primary/10 text-primary uppercase tracking-widest border border-primary/20">현재 쿼리</span>
                <h1 className="text-4xl font-extrabold tracking-tighter text-on-surface">신경망 분석 결과</h1>
                <p className="text-on-surface-variant max-w-xl">로컬 보관소에서 주요 의미 매칭 {RESULTS.length}건을 찾았습니다.</p>
              </div>
              <div className="flex gap-3">
                <button className="px-4 py-2 rounded-full glass-panel border border-outline-variant/20 text-xs font-bold hover:bg-primary/5 transition-all flex items-center gap-2">
                  <span className="material-symbols-outlined text-sm">filter_list</span>관련도
                </button>
              </div>
            </div>

            {/* 결과 카드 */}
            <div className="flex gap-6 overflow-x-auto no-scrollbar pb-12 snap-x snap-mandatory">
              {RESULTS.map((r) => (
                <div key={r.id} className="flex-none w-[420px] snap-start">
                  <div
                    onClick={() => handleSelectFile(r)}
                    className="bg-surface-container-high rounded-[1.5rem] p-1 h-full shadow-[0_20px_50px_rgba(0,0,0,0.3)] hover:shadow-primary/10 transition-all group/card border border-outline-variant/5 cursor-pointer hover:border-primary/20"
                  >
                    <div className="relative rounded-[1.4rem] overflow-hidden aspect-video bg-slate-900 border border-outline-variant/10">
                      <img src={r.img} className="w-full h-full object-cover opacity-60" alt={r.name} />
                      <div className="absolute inset-0 bg-gradient-to-t from-slate-950 to-transparent"></div>
                      <div className="absolute top-4 left-4 p-2 glass-panel rounded-xl">
                        <span className={`material-symbols-outlined ${r.iconColor}`}>{r.icon}</span>
                      </div>
                      <div className="absolute bottom-4 left-4 right-4 flex justify-between items-end">
                        <div className="space-y-1">
                          <p className="text-xs text-secondary font-bold tracking-widest uppercase">{r.type}</p>
                          <p className="text-lg font-bold text-on-surface truncate">{r.name}</p>
                        </div>
                        <div className="text-right">
                          <div className="text-2xl font-black text-primary">{r.similarity}</div>
                          <div className="text-[10px] text-on-surface-variant font-medium">유사도</div>
                        </div>
                      </div>
                    </div>
                    <div className="p-6 space-y-4">
                      <p className="text-[10px] font-bold text-primary tracking-widest uppercase">분석 이유</p>
                      <p className="text-sm text-on-surface-variant leading-relaxed">{r.reason}</p>
                      <div className="pt-4 border-t border-outline-variant/10 flex justify-end items-center">
                        <span className="text-xs font-bold text-primary flex items-center gap-1 group-hover/card:translate-x-1 transition-transform">
                          파일 열기
                          <span className="material-symbols-outlined text-sm">arrow_forward</span>
                        </span>
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>

            {/* 하단 그리드 */}
            <div className="mt-12 grid grid-cols-12 gap-6">
              <div className="col-span-4 bg-surface-container-low rounded-[1.5rem] p-6 border border-outline-variant/10">
                <h3 className="text-sm font-bold text-on-surface flex items-center gap-2 mb-6">
                  <span className="material-symbols-outlined text-primary text-sm">history</span>최근 탐색
                </h3>
                <div className="space-y-4">
                  {['vector_weights_01.bin', 'neural_mesh_topology', 'encryption_key_manifest'].map((item, i) => (
                    <div key={i} className="flex items-center justify-between p-3 rounded-xl bg-surface-container-high/50 border border-outline-variant/5">
                      <span className="text-xs text-on-surface-variant">{item}</span>
                      <span className="text-[10px] text-slate-500 uppercase">{['2시간 전', '5시간 전', '어제'][i]}</span>
                    </div>
                  ))}
                </div>
              </div>
              <div className="col-span-8 glass-panel rounded-[1.5rem] p-6 border border-outline-variant/10 relative overflow-hidden">
                <div className="absolute -right-20 -top-20 w-64 h-64 bg-primary/10 rounded-full blur-[80px]"></div>
                <div className="relative z-10">
                  <h3 className="text-sm font-bold text-primary mb-4 flex items-center gap-2 uppercase tracking-widest">
                    <span className="material-symbols-outlined text-sm">psychology</span>합성 컨텍스트
                  </h3>
                  <p className="text-on-surface leading-relaxed mb-6">
                    요청한 <span className="text-primary font-bold">{query}</span>가 로컬 저장소의 여러 도메인에 걸쳐 나타납니다.
                    고밀도 매칭은 "Research/ML-Architecture" 디렉토리에 집중되어 있습니다.
                  </p>
                  <div className="grid grid-cols-3 gap-4">
                    {[['총 용량', '4.8 GB'], ['엔티티', '12 노드'], ['마지막 업데이트', '12분 전']].map(([label, val]) => (
                      <div key={label} className="p-4 rounded-2xl bg-slate-900/40 border border-outline-variant/5">
                        <p className="text-[10px] text-slate-500 uppercase tracking-widest mb-1">{label}</p>
                        <p className="text-lg font-bold text-on-surface">{val}</p>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </div>

        </main>
      )}

      {/* ════════════════════════════════
          DETAIL VIEW
      ════════════════════════════════ */}
      {view === 'detail' && selectedFile && (
        <main
          className={`${ml} min-h-screen relative transition-[margin] duration-300`}
          style={{
            backgroundImage: 'radial-gradient(rgba(133,173,255,0.05) 1px, transparent 1px)',
            backgroundSize: '32px 32px',
            opacity: detailVisible ? 1 : 0,
            transform: detailVisible ? 'translateX(0)' : 'translateX(36px)',
            transition: 'opacity 0.35s ease, transform 0.35s ease, margin 0.3s',
          }}
        >
          {/* 상단 파일 정보 바 */}
          <div className={`fixed top-[88px] ${leftEdge} right-0 z-30 bg-[#070d1f]/60 backdrop-blur-xl flex items-center justify-between px-8 py-3 border-b border-outline-variant/10 transition-[left] duration-300`}>
            <div className="flex items-center gap-3">
              <span className={`material-symbols-outlined ${selectedFile.iconColor}`}>{selectedFile.icon}</span>
              <span className="font-manrope text-sm tracking-wide text-[#dfe4fe] font-bold">{selectedFile.name}</span>
              <span className="px-2 py-0.5 rounded-full bg-primary/10 text-primary text-[10px] font-bold border border-primary/20">{selectedFile.similarity}</span>
            </div>
            <div className="flex items-center gap-3">
              <button className="px-5 py-2 text-xs font-bold uppercase tracking-widest text-primary bg-surface-container-high border border-outline-variant/15 rounded-full hover:bg-surface-variant transition-colors active:scale-95">
                경로 열기
              </button>
              <button className="px-5 py-2 text-xs font-bold uppercase tracking-widest text-on-primary bg-primary rounded-full hover:brightness-110 transition-all active:scale-95">
                파일 열기
              </button>
            </div>
          </div>

          <section className="pt-44 pb-12 px-8 max-w-7xl mx-auto space-y-8">
            <div className="grid grid-cols-12 gap-6">
              {/* 메인 프리뷰 */}
              <div className="col-span-8 space-y-6">
                <div className="bg-surface-container-low rounded-xl p-8 glass-panel glow-primary min-h-[600px] flex flex-col" style={{ border: '1px solid rgba(65,71,91,0.15)' }}>
                  <div className="flex items-center justify-between mb-8">
                    <span className="text-[10px] font-bold tracking-[0.2em] text-primary uppercase">추출된 문서 스트림</span>
                    <div className="flex gap-2">
                      <span className="h-2 w-2 rounded-full bg-primary animate-pulse"></span>
                      <span className="h-2 w-2 rounded-full bg-secondary/50"></span>
                    </div>
                  </div>
                  <div className="prose prose-invert max-w-none font-body text-on-surface-variant/90 leading-relaxed space-y-6">
                    <h1 className="text-3xl font-extrabold text-on-surface tracking-tight">신경망 레이어 구성 및 토폴로지</h1>
                    <p>현재 아키텍처 분석 결과, 주요 처리 블록 내부에 고밀도 피드백 루프가 존재합니다. 옵시디언 레이어 구현은 로컬 우선 인텔리전스 모델을 활용하여 고주파 데이터 수집 중 지연 시간을 최소화합니다.</p>
                    <div className="bg-surface-container-highest p-6 rounded-xl border-l-4 border-primary">
                      <code className="text-sm font-mono text-primary-fixed block">
                        [SYSTEM_INIT] LOAD global_weights_v4.2<br />
                        [NEURAL_MAP] ATTACHING sensory_input_node_01<br />
                        [SECURITY] LOCAL_ENCRYPTION_ACTIVE (AES-256-GCM)
                      </code>
                    </div>
                    <p>메타데이터에 따르면 이 파일은 04:00 동기화 사이클 중 <strong>Node_774</strong>에 의해 수정되었습니다. 무결성 검사 결과 99.9% 신뢰도로 통과되었습니다.</p>
                    <ul className="list-disc pl-5 space-y-2 text-on-surface">
                      <li>비대칭 루미노시티 패턴</li>
                      <li>대기 깊이 매핑</li>
                      <li>옵시디언 보이드 압축 비율</li>
                    </ul>
                  </div>
                </div>
              </div>

              {/* 메타데이터 패널 */}
              <div className="col-span-4 space-y-6">
                <div className="bg-surface-container-high rounded-xl p-6 border border-outline-variant/10 relative overflow-hidden group">
                  <div className="absolute -right-4 -top-4 w-24 h-24 bg-primary/10 blur-3xl group-hover:bg-primary/20 transition-all"></div>
                  <h4 className="text-[10px] font-bold tracking-[0.15em] text-primary mb-4 uppercase">AI 분석 요약</h4>
                  <div className="space-y-4">
                    <div>
                      <p className="text-[10px] text-on-surface-variant uppercase font-medium">신뢰도</p>
                      <div className="flex items-center gap-3 mt-1">
                        <div className="flex-1 h-1.5 bg-surface-container-highest rounded-full overflow-hidden">
                          <div className="h-full w-[94%] bg-gradient-to-r from-primary to-secondary shadow-[0_0_8px_rgba(133,173,255,0.5)]"></div>
                        </div>
                        <span className="text-xs font-bold text-on-surface">94%</span>
                      </div>
                    </div>
                    <p className="text-sm text-on-surface-variant leading-relaxed italic">"문서 구조상 높은 수준의 기술적 정교함이 감지되며, 개인 연구 환경에서 생성된 것으로 추정됩니다."</p>
                  </div>
                </div>

                <div className="bg-surface-container-low rounded-xl p-6 border border-outline-variant/5">
                  <h4 className="text-[10px] font-bold tracking-[0.15em] text-secondary mb-4 uppercase">파일 메타데이터</h4>
                  <div className="space-y-4">
                    {[['파일명', selectedFile.name], ['유형', selectedFile.type], ['유사도', selectedFile.similarity], ['크기', '12.4 MB'], ['형식', 'PDF 문서']].map(([k, v]) => (
                      <div key={k} className="flex justify-between items-center py-2 border-b border-outline-variant/10 last:border-0">
                        <span className="text-xs text-on-surface-variant">{k}</span>
                        <span className="text-xs font-bold text-on-surface truncate max-w-[60%] text-right">{v}</span>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="bg-[#000000] rounded-xl p-6 border border-primary/20 shadow-[inset_0_0_20px_rgba(133,173,255,0.05)]">
                  <h4 className="text-[10px] font-bold tracking-[0.15em] text-on-surface-variant mb-6 uppercase flex items-center gap-2">
                    <span className="material-symbols-outlined text-sm">terminal</span>처리 로그
                  </h4>
                  <div className="space-y-3 font-mono text-[10px]">
                    {[
                      ['12:00:01', '의미 클러스터 스캔 중...', 'text-primary/70'],
                      ['12:00:02', '고유 식별자 14개 발견.', 'text-primary/70'],
                      ['12:00:03', 'Obsidian DB와 상관관계 분석.', 'text-secondary'],
                      ['12:00:04', '분석 완료.', 'text-on-surface'],
                    ].map(([t, msg, cls]) => (
                      <div key={t} className="flex gap-2">
                        <span className="text-on-surface-variant">{t}</span>
                        <span className={cls}>{msg}</span>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="p-2 space-y-2">
                  <button className="w-full group flex items-center justify-between p-4 rounded-xl bg-surface-container-highest hover:bg-primary/10 transition-colors border border-transparent hover:border-primary/20">
                    <div className="flex items-center gap-3">
                      <span className="material-symbols-outlined text-on-surface-variant group-hover:text-primary">share</span>
                      <span className="text-sm font-semibold">노드에 공유</span>
                    </div>
                    <span className="material-symbols-outlined text-xs text-on-surface-variant">chevron_right</span>
                  </button>
                  <button
                    onClick={() => { window.location.href = `mailto:?subject=${encodeURIComponent(selectedFile.name)}&body=${encodeURIComponent(selectedFile.name + ' 파일을 공유합니다.')}` }}
                    className="w-full group flex items-center justify-between p-4 rounded-xl bg-surface-container-highest hover:bg-primary/10 transition-colors border border-transparent hover:border-primary/20"
                  >
                    <div className="flex items-center gap-3">
                      <span className="material-symbols-outlined text-on-surface-variant group-hover:text-primary">mail</span>
                      <span className="text-sm font-semibold">이메일로 보내기</span>
                    </div>
                    <span className="material-symbols-outlined text-xs text-on-surface-variant">chevron_right</span>
                  </button>
                  <button className="w-full group flex items-center justify-between p-4 rounded-xl bg-surface-container-highest hover:bg-secondary/10 transition-colors border border-transparent hover:border-secondary/20">
                    <div className="flex items-center gap-3">
                      <span className="material-symbols-outlined text-on-surface-variant group-hover:text-secondary">cloud_download</span>
                      <span className="text-sm font-semibold">인텔리전스로 내보내기</span>
                    </div>
                    <span className="material-symbols-outlined text-xs text-on-surface-variant">chevron_right</span>
                  </button>
                </div>
              </div>
            </div>
          </section>

          <div className="fixed bottom-[-10%] left-[20%] w-[40%] h-[40%] bg-primary/5 blur-[120px] pointer-events-none rounded-full"></div>
          <div className="fixed top-[10%] right-[-5%] w-[30%] h-[30%] bg-secondary/5 blur-[100px] pointer-events-none rounded-full"></div>
        </main>
      )}
    </div>
  )
}
