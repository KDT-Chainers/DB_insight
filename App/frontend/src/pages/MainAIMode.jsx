import { useState, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import AISidebar from '../components/AISidebar'

export default function MainAIMode() {
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const [transitioning, setTransitioning] = useState(false)
  const [ripplePos, setRipplePos] = useState({ x: '50%', y: '50%' })
  const btnRef = useRef(null)

  const [searching, setSearching] = useState(false)

  const handleSearch = (e) => {
    e.preventDefault()
    if (!query.trim() || searching) return
    setSearching(true)
    setTimeout(() => navigate('/ai/results', { state: { query } }), 480)
  }

  const handleGoToSearch = () => {
    const rect = btnRef.current?.getBoundingClientRect()
    if (rect) {
      setRipplePos({ x: `${rect.left + rect.width / 2}px`, y: `${rect.top + rect.height / 2}px` })
    }
    setTransitioning(true)
    setTimeout(() => navigate('/search'), 900)
  }

  return (
    <div className="bg-background text-on-surface relative" style={{ overflow: 'hidden' }}>
      {/* Search Mode portal transition overlay */}
      {transitioning && (
        <div className="fixed inset-0 z-[9999] pointer-events-none overflow-hidden">
          <div
            className="portal-overlay absolute rounded-full"
            style={{
              width: '80px',
              height: '80px',
              left: ripplePos.x,
              top: ripplePos.y,
              transform: 'translate(-50%, -50%)',
              background: 'radial-gradient(circle, #1c253e 0%, #0c1326 60%, #070d1f 100%)',
              boxShadow: '0 0 30px 10px rgba(133,173,255,0.15)',
            }}
          />
          {[0, 200].map((delay, i) => (
            <div
              key={i}
              className="portal-ring absolute rounded-full border border-[#85adff]/25"
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
            <span className="material-symbols-outlined text-[#a5aac2] text-4xl" style={{ fontVariationSettings: '"FILL" 1' }}>database</span>
            <span className="font-manrope uppercase tracking-[0.25em] text-xs text-[#a5aac2]">검색 모드</span>
          </div>
        </div>
      )}
      <AISidebar />

      {/* Header */}
      <header className="bg-[#070d1f]/60 backdrop-blur-3xl text-[#ac8aff] font-manrope tracking-[-0.04em] font-semibold fixed top-0 w-full z-50 shadow-[0_8px_32px_0_rgba(0,0,0,0.3)]">
        <div className="flex justify-between items-center h-20 px-8 w-full max-w-screen-2xl mx-auto">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-primary to-secondary flex items-center justify-center shadow-[0_0_15px_rgba(172,138,255,0.4)]">
              <span className="material-symbols-outlined text-on-primary-fixed text-sm" style={{ fontVariationSettings: '"FILL" 1' }}>terminal</span>
            </div>
            <span className="text-xl font-bold text-[#dfe4fe] tracking-tighter">Obsidian AI</span>
          </div>
          <nav className="hidden md:flex gap-8 items-center">
            <button className="text-[#ac8aff] border-b-2 border-[#ac8aff] pb-1 hover:text-[#85adff] transition-colors duration-300">신경망 워크스페이스</button>
            <button className="text-[#a5aac2] hover:text-[#85adff] transition-colors duration-300">분석 엔진</button>
            <button className="text-[#a5aac2] hover:text-[#85adff] transition-colors duration-300">클라우드 동기화</button>
          </nav>
          <div className="flex items-center gap-4">
            <button onClick={() => navigate('/settings')} className="p-2 text-[#a5aac2] hover:text-[#ac8aff] transition-colors">
              <span className="material-symbols-outlined">settings</span>
            </button>
            <button onClick={() => navigate('/data')} className="p-2 text-[#a5aac2] hover:text-[#ac8aff] transition-colors">
              <span className="material-symbols-outlined">database</span>
            </button>
          </div>
        </div>
      </header>

      {/* Main */}
      <main className="ml-72 pt-20 h-screen relative flex flex-col items-center justify-center px-12 overflow-hidden">
        <div className="absolute inset-0 z-0 pointer-events-none synaptic-glow"></div>
        <div className="absolute top-1/4 right-1/4 w-[500px] h-[500px] bg-secondary/5 blur-[120px] rounded-full"></div>
        <div className="absolute bottom-1/4 left-1/4 w-[400px] h-[400px] bg-primary/5 blur-[100px] rounded-full"></div>

        <div className="w-full max-w-4xl z-10 space-y-12">
          <div className={`text-center space-y-4 ${searching ? 'search-slide-up' : ''}`}>
            <h1 className="text-6xl md:text-7xl font-extrabold tracking-[-0.04em] text-on-surface font-headline leading-tight">
              퀀텀{' '}
              <span className="bg-gradient-to-r from-primary via-secondary to-primary-container bg-clip-text text-transparent">인텔리전스</span>
            </h1>
            <p className="text-xl text-on-surface-variant max-w-2xl mx-auto font-light leading-relaxed">
              로컬 시냅스 노드에 접근하고 통합 Obsidian 아키텍처로 복잡한 신경망 스레드를 처리하세요.
            </p>
          </div>

          {/* Search */}
          <form onSubmit={handleSearch} className={`relative group ${searching ? 'search-slide-up' : ''}`} style={searching ? { animationDelay: '60ms' } : {}}>
            <div className="absolute -inset-1 bg-gradient-to-r from-secondary/50 via-primary/30 to-secondary/50 rounded-2xl blur opacity-20 group-focus-within:opacity-40 transition duration-1000"></div>
            <div className="relative glass-panel rounded-2xl border border-outline-variant/15 flex items-center p-2 shadow-2xl">
              <button type="button" className="p-4 text-on-surface-variant hover:text-secondary transition-colors">
                <span className="material-symbols-outlined text-[28px]">add</span>
              </button>
              <input
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="신경망 스레드를 시작하거나 로직 보관소를 검색하세요..."
                className="flex-1 bg-transparent border-none focus:ring-0 text-xl px-4 py-4 text-on-surface placeholder:text-outline/60 font-medium outline-none"
              />
              <button type="button" className="p-4 text-on-surface-variant hover:text-primary transition-colors">
                <span className="material-symbols-outlined text-[28px]">mic</span>
              </button>
            </div>
          </form>

          <div className={`flex flex-col items-center gap-8 ${searching ? 'cards-fade-down' : ''}`}>
            <button
              ref={btnRef}
              onClick={handleGoToSearch}
              disabled={transitioning}
              className="px-10 py-4 rounded-full bg-gradient-to-r from-primary to-secondary text-on-primary-fixed font-bold text-lg tracking-tight shadow-[0_0_40px_rgba(133,173,255,0.2)] hover:shadow-[0_0_60px_rgba(172,138,255,0.4)] hover:scale-[1.05] transition-all disabled:pointer-events-none"
            >
              검색 모드로 전환
            </button>

            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 w-full">
              {[
                { icon: 'insights', title: '트렌드 분석', sub: '글로벌 데이터 흐름 분석' },
                { icon: 'auto_awesome', title: '합성', sub: '다중 로직 코어 병합' },
                { icon: 'language', title: '글로벌 인덱스', sub: '아카이브 교차 참조' },
                { icon: 'code_blocks', title: '패턴 맵', sub: '코드 시냅스 시각화' },
              ].map((card) => (
                <div key={card.title} className="glass-panel p-6 rounded-xl border border-outline-variant/10 hover:border-secondary/30 transition-all group cursor-pointer">
                  <span className="material-symbols-outlined text-secondary mb-3 group-hover:scale-110 transition-transform block">{card.icon}</span>
                  <h3 className="text-xs font-black uppercase tracking-widest text-on-surface">{card.title}</h3>
                  <p className="text-[10px] text-on-surface-variant mt-1">{card.sub}</p>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="absolute bottom-12 flex gap-12 items-center text-outline/40">
          {[['bolt', '초저지연'], ['encrypted', '제로 지식 메시'], ['hub', '분산 코어']].map(([icon, label]) => (
            <div key={label} className="flex items-center gap-2">
              <span className="material-symbols-outlined text-sm">{icon}</span>
              <span className="text-[10px] font-bold uppercase tracking-widest">{label}</span>
            </div>
          ))}
        </div>
      </main>

      {/* Status card */}
      <div className="fixed bottom-0 right-0 p-8 z-50">
        <div className="glass-panel p-4 rounded-xl border border-outline-variant/10 max-w-[240px] shadow-xl">
          <div className="flex items-center gap-3 mb-2">
            <div className="w-1.5 h-1.5 rounded-full bg-green-500 shadow-[0_0_5px_#22c55e]"></div>
            <span className="text-[10px] font-bold uppercase tracking-widest text-on-surface">System Status</span>
          </div>
          <div className="space-y-2">
            <div className="h-1 w-full bg-surface-container rounded-full overflow-hidden">
              <div className="h-full w-2/3 bg-gradient-to-r from-primary to-secondary"></div>
            </div>
            <p className="text-[9px] text-on-surface-variant">Neural load balancing at 64% capacity.</p>
          </div>
        </div>
      </div>
    </div>
  )
}
