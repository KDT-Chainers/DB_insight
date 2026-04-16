import { useState, useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import AISidebar from '../components/AISidebar'
import { useSidebar } from '../context/SidebarContext'

const AI_RESULTS = [
  {
    id: '1',
    tag: 'DATAPACK_772',
    title: '퀀텀 메모리 할당',
    desc: '퓨샤 쿼드런트 전반의 분산 메모리 노드에 대한 구조 분석. 섹터 9에서 높은 중복성이 감지되었습니다.',
    modified: '2시간 전',
    img: 'https://lh3.googleusercontent.com/aida-public/AB6AXuBiusmUQ-dF9m6N2dat_eOi8PeAoliSDsbJq4jNjPUMeLdXktUuZ0dHPASMIqM6HxhOFd_BRotNPPM6fK9p-x5FPhrSJnCnR7zxeBt-3NQMG1LK8RWuj3Q2N_XJXFJcQcNIcCpmZrMUB1BkVkXnIYeipnjBZkJfeYwHyIQcQC064JM4zpL5IVLiQEzGmp8JHFb4G2I8EKZAnkfPT1R_WDK_WmT290fPuMpL6yQ0FeI38nkMQ2cxf8FvKKbnJKTS75oONti5_kSDnsRs',
  },
  {
    id: '2',
    tag: 'LOG_STREAM',
    title: '인지 부하 분산',
    desc: '활성 사고 사이클에서 휴리스틱 가중치의 실시간 균형 조정. 최적화 프로토콜이 시작되었습니다.',
    modified: '활성 중',
    img: 'https://lh3.googleusercontent.com/aida-public/AB6AXuDSfkJz1BrXhj8JKwbl2czpkysEDmYSvRLX2WptNVJq5GJscS_bMt0Yw0409-4Mz39isL0K_hQ8FdKu5lqkvABJ8n0vJHnxybkP8aHVBwk42jjs9TxiSkwRM5gmboyIByUnkBup1-2dfsuTIA2ZL_U1UW1oUgTyhfO9XnDgBvSbCDE4_wPvHvzmY6pcCN5UCVYvdxM_xBYnyJlEGKcxDuMKDjNexPXPd4pe3wHFrDnUjk-UKfmY889GTbwLU_SFHcsBdwqZzG8nKGRr',
  },
  {
    id: '3',
    tag: 'VAULT_ARCHIVE',
    title: '결정형 지식 베이스',
    desc: '과거 학습 데이터셋의 심층 저장소 검색. 다중 패스 해시 검사를 통해 무결성이 검증되었습니다.',
    modified: '4.2 PB',
    img: 'https://lh3.googleusercontent.com/aida-public/AB6AXuBXIIVVDVBdpsRK-VyjwcBDfX5m0q1aGVB7lNkqsmY3dnaihm7xe0kRv0F5SB93RYrEFiaVKDroBKUb0yqjB14Q3hUTiu_9wYEmnleWOuLQgAic_0PcIER1IlnGP2ap7aQAAAnTRu7-AujKhHzk5MJQmkbfFPbVlZfq7edimXxeOIbqjUX22lvKQ8LbHkTBm_mOcQeleA8WE2d-S1rVKWTZYJFPQt29wNzi9wc-qgwniGitShIKul7FnudpG4SUfJyEO8K5OwYnH2E6',
  },
]

const BAR_HEIGHTS = ['60%', '45%', '85%', '30%', '70%', '55%', '95%', '40%']

export default function MainAI() {
  const navigate = useNavigate()
  const { open } = useSidebar()

  const [view, setView] = useState('home')
  const [query, setQuery] = useState('')
  const [inputValue, setInputValue] = useState('')
  const [selectedResult, setSelectedResult] = useState(null)

  const [homeExiting, setHomeExiting] = useState(false)
  const [resultsReady, setResultsReady] = useState(false)
  const [detailVisible, setDetailVisible] = useState(false)

  const [searchTransitioning, setSearchTransitioning] = useState(false)
  const [ripplePos, setRipplePos] = useState({ x: '50%', y: '50%' })
  const btnRef = useRef(null)

  const ml = open ? 'ml-64' : 'ml-0'
  const leftEdge = open ? 'left-64' : 'left-0'

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
    if (!q.trim()) return
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
      }, 420)
    } else {
      setView('results')
    }
  }

  const handleSearch = (e) => {
    e?.preventDefault()
    doSearch(inputValue)
  }

  const handleSelectResult = (result) => {
    setSelectedResult(result)
    setDetailVisible(false)
    setView('detail')
    window.history.pushState({ view: 'detail' }, '')
    requestAnimationFrame(() => requestAnimationFrame(() => setDetailVisible(true)))
  }

  const handleBackToResults = () => {
    setDetailVisible(false)
    setTimeout(() => setView('results'), 320)
  }

  const handleGoToSearch = () => {
    const rect = btnRef.current?.getBoundingClientRect()
    if (rect) setRipplePos({ x: `${rect.left + rect.width / 2}px`, y: `${rect.top + rect.height / 2}px` })
    setSearchTransitioning(true)
    setTimeout(() => navigate('/search'), 900)
  }

  return (
    <div className="bg-background text-on-surface relative min-h-screen overflow-x-hidden">

      {/* 검색 모드 포털 전환 */}
      {searchTransitioning && (
        <div className="fixed inset-0 z-[9999] pointer-events-none overflow-hidden">
          <div
            className="portal-overlay absolute rounded-full"
            style={{
              width: '80px', height: '80px',
              left: ripplePos.x, top: ripplePos.y,
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
                width: '160px', height: '160px',
                left: ripplePos.x, top: ripplePos.y,
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

      {/* 사이드바 — 항상 마운트 유지 */}
      <AISidebar />

      {/* ════════════════════════════════
          HOME VIEW
      ════════════════════════════════ */}
      {view === 'home' && (
        <>
          <header className="bg-[#070d1f]/60 backdrop-blur-3xl text-[#ac8aff] font-manrope tracking-[-0.04em] font-semibold fixed top-0 w-full z-40 shadow-[0_8px_32px_0_rgba(0,0,0,0.3)]">
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

          <main className={`${ml} pt-20 h-screen relative flex flex-col items-center justify-center px-12 overflow-hidden transition-[margin] duration-300`}>
            <div className="absolute inset-0 z-0 pointer-events-none synaptic-glow"></div>
            <div className="absolute top-1/4 right-1/4 w-[500px] h-[500px] bg-secondary/5 blur-[120px] rounded-full"></div>
            <div className="absolute bottom-1/4 left-1/4 w-[400px] h-[400px] bg-primary/5 blur-[100px] rounded-full"></div>

            <div className="w-full max-w-4xl z-10 space-y-12">
              <div className={`text-center space-y-4 transition-all duration-350 ${homeExiting ? 'opacity-0 -translate-y-8' : 'opacity-100 translate-y-0'}`}>
                <h1 className="text-6xl md:text-7xl font-extrabold tracking-[-0.04em] text-on-surface font-headline leading-tight">
                  퀀텀{' '}
                  <span className="bg-gradient-to-r from-primary via-secondary to-primary-container bg-clip-text text-transparent">인텔리전스</span>
                </h1>
                <p className="text-xl text-on-surface-variant max-w-2xl mx-auto font-light leading-relaxed">
                  로컬 시냅스 노드에 접근하고 통합 Obsidian 아키텍처로 복잡한 신경망 스레드를 처리하세요.
                </p>
              </div>

              <form
                onSubmit={handleSearch}
                className={`relative group transition-all duration-350 ${homeExiting ? 'opacity-0 translate-y-4' : 'opacity-100 translate-y-0'}`}
                style={homeExiting ? { animationDelay: '60ms' } : {}}
              >
                <div className="absolute -inset-1 bg-gradient-to-r from-secondary/50 via-primary/30 to-secondary/50 rounded-2xl blur opacity-20 group-focus-within:opacity-40 transition duration-1000"></div>
                <div className="relative glass-panel rounded-2xl border border-outline-variant/15 flex items-center p-2 shadow-2xl">
                  <button type="button" className="p-4 text-on-surface-variant hover:text-secondary transition-colors">
                    <span className="material-symbols-outlined text-[28px]">add</span>
                  </button>
                  <input
                    type="text"
                    value={inputValue}
                    onChange={(e) => setInputValue(e.target.value)}
                    placeholder="신경망 스레드를 시작하거나 로직 보관소를 검색하세요..."
                    className="flex-1 bg-transparent border-none focus:ring-0 text-xl px-4 py-4 text-on-surface placeholder:text-outline/60 font-medium outline-none"
                  />
                  <button type="button" className="p-4 text-on-surface-variant hover:text-primary transition-colors">
                    <span className="material-symbols-outlined text-[28px]">mic</span>
                  </button>
                </div>
              </form>

              <div className={`flex flex-col items-center gap-8 transition-all duration-350 ${homeExiting ? 'opacity-0 translate-y-4' : 'opacity-100 translate-y-0'}`}>
                <button
                  ref={btnRef}
                  onClick={handleGoToSearch}
                  disabled={searchTransitioning}
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
        </>
      )}

      {/* ════════════════════════════════
          RESULTS / DETAIL 공통 헤더
      ════════════════════════════════ */}
      {view !== 'home' && (
        <header className={`fixed top-0 ${leftEdge} right-0 z-50 bg-[#070d1f]/60 backdrop-blur-xl flex items-center px-8 h-16 gap-6 shadow-[0_4px_30px_rgba(172,138,255,0.1)] transition-[left] duration-300`}>
          <button
            onClick={() => { setView('home'); setInputValue('') }}
            className="text-xl font-bold tracking-tighter bg-gradient-to-r from-violet-400 to-fuchsia-400 bg-clip-text text-transparent shrink-0 hover:opacity-70 transition-opacity"
          >
            Obsidian AI
          </button>

          <form onSubmit={handleSearch} className="flex-1">
            <div className="relative group flex items-center">
              <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-violet-400/50">search</span>
              <input
                className="w-full bg-white/5 border-none rounded-full pl-10 pr-4 py-1.5 text-sm focus:ring-1 focus:ring-violet-500/50 transition-all outline-none"
                placeholder="신경망 검색..."
                value={inputValue}
                onChange={(e) => setInputValue(e.target.value)}
              />
            </div>
          </form>

          <nav className="hidden md:flex gap-6 items-center shrink-0">
            <button className={`text-sm transition-colors ${view === 'results' ? 'text-violet-300 border-b-2 border-violet-500 pb-1' : 'text-slate-400 hover:text-slate-200'}`}>모델</button>
            <button className="text-slate-400 hover:text-slate-200 transition-colors text-sm">데이터셋</button>
            <button className="text-slate-400 hover:text-slate-200 transition-colors text-sm">신경망 로그</button>
          </nav>

          <div className="flex items-center gap-3 shrink-0">
            {view === 'detail' && (
              <button
                onClick={handleBackToResults}
                className="flex items-center gap-2 px-4 py-1.5 rounded-full bg-surface-container-high border border-outline-variant/20 text-xs font-bold text-on-surface-variant hover:text-secondary hover:border-secondary/30 transition-all"
              >
                <span className="material-symbols-outlined text-sm">arrow_back</span>
                결과로
              </button>
            )}
            <button onClick={() => navigate('/settings')} className="material-symbols-outlined text-slate-400 hover:text-violet-400 transition-all">settings</button>
          </div>
          <div className="absolute bottom-0 left-0 w-full bg-gradient-to-b from-violet-500/10 to-transparent h-[1px]"></div>
        </header>
      )}

      {/* ════════════════════════════════
          RESULTS VIEW
      ════════════════════════════════ */}
      {view === 'results' && (
        <main
          className={`${ml} pt-16 min-h-screen transition-[margin] duration-300`}
          style={{
            opacity: resultsReady ? 1 : 0,
            transform: resultsReady ? 'translateY(0)' : 'translateY(24px)',
            transition: 'opacity 0.38s ease, transform 0.38s ease, margin 0.3s',
          }}
        >
          <div className="p-10 max-w-7xl mx-auto">
            <div className="mb-12 relative">
              <div className="absolute -top-20 -left-20 w-96 h-96 bg-secondary/10 blur-[100px] rounded-full"></div>
              <div className="relative z-10">
                <span className="text-secondary text-xs font-bold tracking-[0.3em] uppercase mb-4 block">정제된 인텔리전스 출력</span>
                <h1 className="text-5xl font-extrabold tracking-tighter text-on-surface mb-4">신경망 검색 결과</h1>
                <div className="flex items-center gap-4 text-on-surface-variant">
                  <span className="flex items-center gap-2 px-3 py-1 bg-surface-container-high rounded-full border border-outline-variant/20 text-sm">
                    <span className="w-1.5 h-1.5 rounded-full bg-secondary"></span>342개 매칭 발견
                  </span>
                  <span className="text-sm">124ms에 처리 완료</span>
                </div>
              </div>
            </div>

            <div className="grid grid-cols-12 gap-6">
              {/* AI 합성 카드 */}
              <div className="col-span-12 lg:col-span-8 bg-surface-variant/60 backdrop-blur-2xl rounded-xl p-8 border border-secondary/20 relative overflow-hidden group">
                <div className="absolute top-0 right-0 p-4">
                  <span className="material-symbols-outlined text-secondary opacity-50 text-4xl" style={{ fontVariationSettings: '"FILL" 1' }}>auto_awesome</span>
                </div>
                <div className="relative z-10">
                  <h3 className="text-secondary text-xs font-black tracking-widest uppercase mb-6">AI 맥락 합성</h3>
                  <p className="text-2xl font-light text-on-surface leading-relaxed mb-8">
                    최근 <span className="text-secondary font-medium">신경망 로그</span>와{' '}
                    <span className="text-secondary font-medium">처리 노드</span> 정제를 바탕으로, 시스템은 선택된 데이터셋과
                    현재 "예측 분석 4단계" 진행 방향 간의 강한 상관관계를 식별했습니다.
                  </p>
                  <div className="flex gap-3">
                    <button className="bg-secondary text-on-secondary px-6 py-2.5 rounded-full font-bold text-sm tracking-tight active:scale-95 transition-all">합성 확장</button>
                    <button className="bg-surface-container-highest text-on-surface px-6 py-2.5 rounded-full font-bold text-sm tracking-tight border border-outline-variant/30 hover:bg-surface-bright transition-all">로직 감사</button>
                  </div>
                </div>
              </div>

              {/* 모델 통계 */}
              <div className="col-span-12 lg:col-span-4 bg-surface-container-high rounded-xl p-6 border border-outline-variant/10 flex flex-col justify-between">
                <div>
                  <h4 className="text-on-surface-variant text-[10px] font-black tracking-[0.2em] uppercase mb-6">모델 무결성</h4>
                  <div className="space-y-6">
                    {[['일관성 수준', '98.4%', 'w-[98%]'], ['지연 변화', '-12ms', 'w-[75%]']].map(([label, val, w]) => (
                      <div key={label}>
                        <div className="flex justify-between text-xs mb-2">
                          <span className="text-on-surface/80">{label}</span>
                          <span className="text-secondary">{val}</span>
                        </div>
                        <div className="h-1.5 w-full bg-surface-container-highest rounded-full overflow-hidden">
                          <div className={`h-full bg-secondary ${w} shadow-[0_0_10px_rgba(172,138,255,0.5)]`}></div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
                <div className="mt-8 pt-6 border-t border-outline-variant/10">
                  <div className="flex items-center gap-3">
                    <div className="p-2 bg-secondary/10 rounded-lg">
                      <span className="material-symbols-outlined text-secondary" style={{ fontVariationSettings: '"FILL" 1' }}>bolt</span>
                    </div>
                    <div>
                      <p className="text-xs font-bold text-on-surface">Obsidian-v4.2</p>
                      <p className="text-[10px] text-on-surface-variant">최신 업데이트</p>
                    </div>
                  </div>
                </div>
              </div>

              {/* 결과 카드들 */}
              {AI_RESULTS.map((r) => (
                <div key={r.id} className="col-span-12 md:col-span-6 lg:col-span-4 group cursor-pointer">
                  <div
                    className="bg-surface-container-low rounded-xl overflow-hidden border border-outline-variant/10 hover:border-secondary/30 transition-all duration-500 hover:-translate-y-1"
                    onClick={() => handleSelectResult(r)}
                  >
                    <div className="h-48 relative">
                      <img src={r.img} alt={r.title} className="w-full h-full object-cover grayscale opacity-50 group-hover:grayscale-0 group-hover:opacity-80 transition-all duration-700" />
                      <div className="absolute inset-0 bg-gradient-to-t from-surface-container-low to-transparent"></div>
                      <span className="absolute top-4 left-4 bg-secondary/20 backdrop-blur-md border border-secondary/40 text-secondary text-[10px] font-bold px-2 py-1 rounded">{r.tag}</span>
                    </div>
                    <div className="p-6">
                      <h3 className="text-lg font-bold text-on-surface mb-2 group-hover:text-secondary transition-colors">{r.title}</h3>
                      <p className="text-sm text-on-surface-variant line-clamp-2 mb-4 leading-relaxed">{r.desc}</p>
                      <div className="flex justify-between items-center">
                        <span className="text-[10px] font-bold text-outline uppercase tracking-widest">수정: {r.modified}</span>
                        <span className="material-symbols-outlined text-on-surface-variant group-hover:translate-x-1 transition-transform">arrow_forward</span>
                      </div>
                    </div>
                  </div>
                </div>
              ))}

              {/* 페이지네이션 */}
              <div className="col-span-12 bg-surface-container-highest/40 border border-outline-variant/20 rounded-xl p-4 flex items-center justify-between">
                <div className="flex items-center gap-6">
                  <p className="text-xs text-on-surface-variant font-medium">1 / 34 페이지</p>
                  <div className="flex gap-2">
                    {[1, 2, 3].map((n) => (
                      <button key={n} className={`w-8 h-8 rounded-lg flex items-center justify-center text-sm ${n === 2 ? 'bg-secondary text-on-secondary font-bold' : 'bg-surface-container text-on-surface-variant hover:text-secondary border border-outline-variant/10'}`}>{n}</button>
                    ))}
                    <span className="text-on-surface-variant px-1">...</span>
                    <button className="w-8 h-8 rounded-lg bg-surface-container flex items-center justify-center text-on-surface-variant hover:text-secondary border border-outline-variant/10 text-sm">34</button>
                  </div>
                </div>
                <button className="flex items-center gap-2 px-4 py-2 text-xs font-bold uppercase tracking-widest text-on-surface-variant hover:text-secondary transition-all">
                  목록 내보내기<span className="material-symbols-outlined text-sm">download</span>
                </button>
              </div>
            </div>
          </div>

          <div className="fixed bottom-10 right-10 z-50">
            <button className="w-14 h-14 rounded-full bg-gradient-to-tr from-secondary to-fuchsia-500 text-on-secondary shadow-[0_0_30px_rgba(172,138,255,0.4)] flex items-center justify-center active:scale-90 transition-all group">
              <span className="material-symbols-outlined text-3xl group-hover:rotate-12 transition-transform" style={{ fontVariationSettings: '"FILL" 1' }}>auto_awesome</span>
            </button>
          </div>
        </main>
      )}

      {/* ════════════════════════════════
          DETAIL VIEW
      ════════════════════════════════ */}
      {view === 'detail' && selectedResult && (
        <main
          className={`${ml} min-h-screen transition-[margin] duration-300`}
          style={{
            opacity: detailVisible ? 1 : 0,
            transform: detailVisible ? 'translateX(0)' : 'translateX(36px)',
            transition: 'opacity 0.35s ease, transform 0.35s ease, margin 0.3s',
          }}
        >
          <div className="pt-24 pb-12 px-10 max-w-7xl mx-auto">
            {/* 브레드크럼 */}
            <div className="mb-8 flex justify-between items-end">
              <div>
                <nav className="flex items-center gap-2 text-on-surface-variant text-xs uppercase tracking-widest mb-4">
                  <button onClick={handleBackToResults} className="hover:text-secondary cursor-pointer">데이터셋</button>
                  <span className="material-symbols-outlined text-[14px]">chevron_right</span>
                  <span className="hover:text-secondary cursor-pointer">신경망 자산</span>
                  <span className="material-symbols-outlined text-[14px]">chevron_right</span>
                  <span className="text-secondary">{selectedResult.title}</span>
                </nav>
                <h1 className="text-4xl font-extrabold tracking-tighter text-on-surface mb-2">파일 상세 - AI 모드</h1>
                <p className="text-on-surface-variant max-w-2xl">
                  객체 <span className="text-secondary font-semibold">{selectedResult.title}</span>의 고밀도 인지 데이터 구조를 시각화합니다.
                </p>
              </div>
              <div className="flex gap-4">
                <button className="flex items-center gap-2 px-6 py-3 bg-surface-container-high border border-outline-variant rounded-full font-bold text-sm text-on-surface hover:bg-surface-container-highest transition-all">
                  <span className="material-symbols-outlined text-[18px]">download</span>추출
                </button>
                <button className="flex items-center gap-2 px-8 py-3 bg-gradient-to-r from-secondary to-primary rounded-full font-extrabold text-sm text-on-primary active:scale-95 transition-all shadow-[0_0_20px_rgba(172,138,255,0.4)]">
                  <span className="material-symbols-outlined text-[18px]" style={{ fontVariationSettings: '"FILL" 1' }}>bolt</span>재처리
                </button>
              </div>
            </div>

            <div className="grid grid-cols-12 gap-6">
              {/* 좌측: 비주얼라이저 + 메타데이터 테이블 */}
              <div className="col-span-8 space-y-6">
                <div className="bg-surface-container-low rounded-[1.5rem] p-1 overflow-hidden relative group">
                  <div className="absolute inset-0 bg-gradient-to-br from-secondary/10 via-transparent to-primary/5 opacity-50"></div>
                  <div className="relative bg-surface rounded-[1.4rem] p-8 min-h-[400px] flex flex-col">
                    <div className="flex justify-between items-start mb-12">
                      <div>
                        <span className="text-[10px] uppercase tracking-[0.2em] text-secondary mb-1 block">신경망 지형도</span>
                        <h3 className="text-xl font-bold">지연 히트맵</h3>
                      </div>
                      <div className="flex gap-2">
                        <span className="w-3 h-3 rounded-full bg-secondary" style={{ boxShadow: '0 0 15px rgba(172,138,255,0.4)' }}></span>
                        <span className="w-3 h-3 rounded-full bg-primary/40"></span>
                        <span className="w-3 h-3 rounded-full bg-outline-variant"></span>
                      </div>
                    </div>
                    <div className="flex-1 flex items-center justify-center relative">
                      <div className="relative z-10 w-full h-48 flex items-end justify-between gap-2">
                        {BAR_HEIGHTS.map((h, i) => (
                          <div key={i} className="w-full bg-surface-container-highest rounded-t-lg relative transition-all duration-500" style={{ height: h }}>
                            <div className={`absolute bottom-0 w-full bg-gradient-to-t ${i % 3 === 2 ? 'from-primary' : 'from-secondary'} to-transparent h-full rounded-t-lg opacity-${30 + i * 5}`}></div>
                          </div>
                        ))}
                      </div>
                      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-64 h-64 bg-secondary/10 blur-[100px] rounded-full pointer-events-none"></div>
                    </div>
                    <div className="mt-12 flex items-center justify-between border-t border-outline-variant pt-6">
                      <div className="flex gap-8">
                        {[['안정성', '99.98%', ''], ['엔트로피', '낮음', 'text-secondary'], ['사이클', '4.2k', '']].map(([label, val, cls]) => (
                          <div key={label}>
                            <p className="text-[10px] uppercase tracking-widest text-on-surface-variant mb-1">{label}</p>
                            <p className={`text-xl font-bold ${cls}`}>{val}</p>
                          </div>
                        ))}
                      </div>
                      <div className="flex gap-2">
                        <button className="p-2 rounded-lg bg-surface-container-high text-on-surface-variant hover:text-secondary transition-all"><span className="material-symbols-outlined">zoom_in</span></button>
                        <button className="p-2 rounded-lg bg-surface-container-high text-on-surface-variant hover:text-secondary transition-all"><span className="material-symbols-outlined">fullscreen</span></button>
                      </div>
                    </div>
                  </div>
                </div>

                <div className="bg-surface-container-low rounded-[1.5rem] p-8 border border-outline-variant/10">
                  <div className="flex justify-between items-center mb-8">
                    <h3 className="text-lg font-bold flex items-center gap-2">
                      <span className="material-symbols-outlined text-secondary">database</span>신경망 메타데이터 추출
                    </h3>
                    <button className="text-secondary text-xs uppercase tracking-widest hover:underline">JSON 내보내기</button>
                  </div>
                  <div className="space-y-4">
                    {[
                      ['인지 노드', 'node_alpha_x99283', '보안', 'text-secondary'],
                      ['해시 시퀀스', '0x77ae...bb91', '검증됨', 'text-secondary'],
                      ['원본 클러스터', 'Euclidean-North-Grid', '원격', 'text-on-surface-variant'],
                      ['마지막 펄스', '2024-05-18T14:22:01.002Z', '동기화됨', 'text-primary'],
                    ].map(([label, val, status, cls]) => (
                      <div key={label} className="grid grid-cols-4 gap-4 p-4 rounded-xl hover:bg-surface-container-high transition-all border-b border-outline-variant/10 last:border-0">
                        <span className="text-xs uppercase tracking-widest text-on-surface-variant">{label}</span>
                        <span className="text-xs font-medium text-on-surface col-span-2 font-mono">{val}</span>
                        <span className={`text-right text-[10px] font-bold ${cls}`}>{status}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              {/* 우측: AI 요약 + 접근 권한 + 타임라인 */}
              <div className="col-span-4 space-y-6">
                <div className="glass-panel rounded-[1.5rem] p-8 border border-secondary/20 relative overflow-hidden" style={{ boxShadow: '0 0 20px rgba(172,138,255,0.15)' }}>
                  <div className="absolute -right-10 -top-10 w-32 h-32 bg-secondary/20 blur-[60px] rounded-full"></div>
                  <div className="flex items-center gap-3 mb-6">
                    <div className="w-10 h-10 rounded-full bg-secondary-container flex items-center justify-center" style={{ boxShadow: '0 0 20px rgba(172,138,255,0.15)' }}>
                      <span className="material-symbols-outlined text-secondary" style={{ fontVariationSettings: '"FILL" 1' }}>auto_awesome</span>
                    </div>
                    <div>
                      <h4 className="font-bold text-on-surface">신경망 요약</h4>
                      <p className="text-[10px] text-secondary uppercase tracking-widest">AI 생성 인사이트</p>
                    </div>
                  </div>
                  <p className="text-sm leading-relaxed text-on-surface-variant mb-6 italic">
                    "DB_insight 객체는 '예측 물류' 클러스터와 높은 상관관계를 가진 다층 벡터 임베딩을 포함합니다."
                  </p>
                  <div className="p-4 rounded-xl bg-surface-container-lowest/50 border border-outline-variant/20">
                    <h5 className="text-[10px] uppercase tracking-widest text-secondary mb-3">권장 프로토콜</h5>
                    {['벡터 양자화', '레이어 정규화'].map((item) => (
                      <div key={item} className="flex items-center gap-3 mb-2">
                        <span className="material-symbols-outlined text-primary text-sm">check_circle</span>
                        <span className="text-xs text-on-surface">{item}</span>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="bg-surface-container-low rounded-[1.5rem] p-8 border border-outline-variant/10">
                  <h4 className="text-xs uppercase tracking-widest text-on-surface-variant mb-6">접근 권한 계층</h4>
                  {[
                    { icon: 'person', label: '리드 아키텍트', badge: 'RW-X' },
                    { icon: 'shield', label: '시스템 관리자', badge: '소유자' },
                    { icon: 'groups', label: '분석팀', badge: '읽기', dim: true },
                  ].map((item) => (
                    <div key={item.label} className={`flex items-center justify-between mb-4 ${item.dim ? 'opacity-50' : ''}`}>
                      <div className="flex items-center gap-3">
                        <div className="w-8 h-8 rounded-lg bg-surface-container-highest flex items-center justify-center">
                          <span className="material-symbols-outlined text-sm">{item.icon}</span>
                        </div>
                        <span className="text-sm">{item.label}</span>
                      </div>
                      <span className="text-[10px] px-2 py-1 rounded bg-secondary/10 text-secondary border border-secondary/20 font-bold uppercase tracking-widest">{item.badge}</span>
                    </div>
                  ))}
                  <button className="w-full mt-6 py-3 border border-outline-variant/20 rounded-xl text-xs uppercase tracking-widest hover:border-secondary hover:text-secondary transition-all">
                    접근 권한 관리
                  </button>
                </div>

                <div className="bg-surface-container-low rounded-[1.5rem] p-8 border border-outline-variant/10">
                  <h4 className="text-xs uppercase tracking-widest text-on-surface-variant mb-6">시간순 로그</h4>
                  <div className="relative pl-6 space-y-6 before:content-[''] before:absolute before:left-[3px] before:top-2 before:bottom-2 before:w-[2px] before:bg-outline-variant/30">
                    {[
                      { title: '신경망 최적화', time: '2시간 전 (시스템 AI)', active: true },
                      { title: '데이터셋 병합', time: '14시간 전 (Architect_A)', active: false },
                      { title: '객체 초기화', time: '2일 전 (Root)', active: false },
                    ].map((item, i) => (
                      <div key={i} className={`relative ${i === 1 ? 'opacity-70' : i === 2 ? 'opacity-50' : ''}`}>
                        <div className={`absolute -left-[27px] top-1 w-2 h-2 rounded-full ${item.active ? 'bg-secondary' : 'bg-outline-variant'}`} style={item.active ? { boxShadow: '0 0 15px rgba(172,138,255,0.4)' } : {}}></div>
                        <p className="text-xs font-bold text-on-surface">{item.title}</p>
                        <p className="text-[10px] text-on-surface-variant">{item.time}</p>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div className={`fixed bottom-0 ${leftEdge} right-0 h-1 bg-gradient-to-r from-transparent via-secondary/20 to-transparent transition-[left] duration-300`}></div>
        </main>
      )}
    </div>
  )
}
