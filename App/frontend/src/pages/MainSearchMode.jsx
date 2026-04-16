import { useState, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import SearchSidebar from '../components/SearchSidebar'
import { useSidebar } from '../context/SidebarContext'

export default function MainSearchMode() {
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const [transitioning, setTransitioning] = useState(false)
  const [searching, setSearching] = useState(false)
  const [flyStyle, setFlyStyle] = useState(null)
  const [ripplePos, setRipplePos] = useState({ x: '50%', y: '50%' })
  const btnRef = useRef(null)
  const formRef = useRef(null)
  const { open } = useSidebar()

  const handleSearch = (e) => {
    e.preventDefault()
    if (!query.trim() || searching) return

    const rect = formRef.current?.getBoundingClientRect()
    if (rect) {
      // Start: exact current position of the form
      setFlyStyle({
        position: 'fixed',
        top: rect.top,
        left: rect.left,
        width: rect.width,
        transition: 'none',
      })
      // After paint, animate to header position
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          setFlyStyle({
            position: 'fixed',
            top: 10,
            left: 268,
            width: 'calc(100vw - 268px - 260px)',
            transition: 'top 0.48s cubic-bezier(0.4,0,0.2,1), left 0.48s cubic-bezier(0.4,0,0.2,1), width 0.48s cubic-bezier(0.4,0,0.2,1)',
          })
        })
      })
    }

    setSearching(true)
    setTimeout(() => navigate('/search/results', { state: { query } }), 520)
  }

  const handleGoToAI = (e) => {
    const rect = btnRef.current?.getBoundingClientRect()
    if (rect) {
      setRipplePos({ x: `${rect.left + rect.width / 2}px`, y: `${rect.top + rect.height / 2}px` })
    }
    setTransitioning(true)
    setTimeout(() => navigate('/ai'), 900)
  }

  return (
    <div className="overflow-hidden h-screen grid-bg relative">
      {/* Portal transition overlay */}
      {transitioning && (
        <div className="fixed inset-0 z-[9999] pointer-events-none overflow-hidden">
          {/* Expanding orb from button position */}
          <div
            className="portal-overlay absolute rounded-full"
            style={{
              width: '80px',
              height: '80px',
              left: ripplePos.x,
              top: ripplePos.y,
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
                width: '160px',
                height: '160px',
                left: ripplePos.x,
                top: ripplePos.y,
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
      <SearchSidebar />

      {/* Top nav */}
      <nav className="fixed top-0 w-full flex justify-between items-center px-6 py-4 bg-transparent z-40">
        <div className={open ? 'ml-64' : 'ml-0'}></div>
        <div className="flex items-center gap-6">
          <div className="hidden md:flex gap-8 items-center">
            <button className="font-manrope tracking-tight text-sm text-[#85adff] font-bold hover:text-[#85adff] transition-colors active:scale-95 duration-200">탐색</button>
            <button className="font-manrope tracking-tight text-sm text-[#a5aac2] hover:text-[#85adff] transition-colors active:scale-95 duration-200">인텔리전스</button>
            <button className="font-manrope tracking-tight text-sm text-[#a5aac2] hover:text-[#85adff] transition-colors active:scale-95 duration-200">클라우드 동기화</button>
          </div>
          <div className="w-8 h-8 rounded-full bg-surface-variant flex items-center justify-center cursor-pointer hover:bg-surface-container-highest transition-colors">
            <span className="material-symbols-outlined text-primary text-xl">account_circle</span>
          </div>
        </div>
      </nav>

      {/* Main content */}
      <main className={`${open ? 'ml-64' : 'ml-0'} h-full flex flex-col items-center justify-center p-8 relative transition-[margin] duration-300`}>
        <div className="absolute top-1/4 left-1/4 w-96 h-96 bg-primary/10 rounded-full blur-[120px] pointer-events-none"></div>
        <div className="absolute bottom-1/4 right-1/4 w-[500px] h-[500px] bg-secondary/5 rounded-full blur-[150px] pointer-events-none"></div>

        <div className="w-full max-w-4xl flex flex-col items-center z-10">
          <div className={`mb-12 text-center ${searching ? 'search-slide-up' : ''}`}>
            <h2 className="text-5xl md:text-6xl font-black tracking-tighter text-on-surface mb-4">
              로컬 인텔리전스<span className="text-primary">.</span>
            </h2>
            <p className="text-on-surface-variant text-lg max-w-xl mx-auto font-light">
              개인 신경망 엔진이 파일을 인덱싱하고 분석합니다.
            </p>
          </div>

          {/* Search bar */}
          <form
            ref={formRef}
            onSubmit={handleSearch}
            className="w-full relative group"
            style={searching ? { visibility: 'hidden' } : {}}
          >
            <div className="glass-effect rounded-full p-2 border border-outline-variant/20 shadow-[0_0_50px_rgba(133,173,255,0.1)] flex items-center gap-4 hover:border-primary/40 transition-all duration-300">
              <button
                type="button"
                className="w-12 h-12 rounded-full bg-gradient-to-r from-primary to-secondary flex items-center justify-center text-on-primary-fixed shadow-lg active:scale-90 transition-transform"
              >
                <span className="material-symbols-outlined font-bold">add</span>
              </button>
              <input
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="로컬 파일에 대해 무엇이든 물어보세요..."
                className="flex-1 bg-transparent border-none focus:ring-0 text-on-surface placeholder:text-on-surface-variant/40 font-manrope text-lg py-4 outline-none"
              />
              <button type="button" className="w-12 h-12 rounded-full flex items-center justify-center text-on-surface-variant hover:text-primary hover:bg-primary/10 transition-all duration-200">
                <span className="material-symbols-outlined">mic</span>
              </button>
            </div>

            {/* AI mode button */}
            <div className="mt-10 flex justify-center">
              <button
                ref={btnRef}
                type="button"
                onClick={handleGoToAI}
                disabled={transitioning}
                className="px-8 py-3 rounded-full bg-surface-container-high border border-outline-variant/20 flex items-center gap-3 text-sm font-bold tracking-widest uppercase text-on-surface-variant hover:text-on-surface hover:bg-surface-container-highest transition-all duration-300 group glow-primary disabled:pointer-events-none"
              >
                <span className="w-2 h-2 rounded-full bg-primary animate-pulse"></span>
                AI 모드로 전환
                <span className="material-symbols-outlined text-lg group-hover:translate-x-1 transition-transform">arrow_forward</span>
              </button>
            </div>
          </form>

          {/* Flying clone */}
          {flyStyle && (
            <div style={{ ...flyStyle, zIndex: 9998 }}>
              <div className="glass-effect rounded-full p-2 border border-primary/40 shadow-[0_0_30px_rgba(133,173,255,0.15)] flex items-center gap-3">
                <span className="material-symbols-outlined text-primary ml-2">search</span>
                <span className="flex-1 text-on-surface font-manrope text-sm truncate">{query}</span>
              </div>
            </div>
          )}

          {/* Quick action cards */}
          <div className={`grid grid-cols-1 md:grid-cols-3 gap-4 mt-24 w-full transition-none ${searching ? 'cards-fade-down' : ''}`}>
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
    </div>
  )
}
