import { useNavigate, useLocation } from 'react-router-dom'
import AISidebar from '../components/AISidebar'
import { useSidebar } from '../context/SidebarContext'

const BAR_HEIGHTS = ['60%', '45%', '85%', '30%', '70%', '55%', '95%', '40%']

export default function MainAIModeResultSpecific() {
  const navigate = useNavigate()
  const location = useLocation()
  const result = location.state?.result || { title: 'DB_insight.bin', tag: 'DATAPACK' }
  const { open } = useSidebar()

  return (
    <div className="bg-surface text-on-surface overflow-x-hidden min-h-screen">
      <AISidebar />

      {/* Top nav */}
      <header className="fixed top-0 w-full z-50 bg-[#070d1f]/60 backdrop-blur-xl flex justify-between items-center px-8 h-16 shadow-[0_4px_30px_rgba(172,138,255,0.1)]">
        <div className="flex items-center gap-8">
          <span className="text-xl font-bold tracking-tighter bg-gradient-to-r from-violet-400 to-fuchsia-400 bg-clip-text text-transparent">Obsidian 인텔리전스</span>
          <nav className="hidden md:flex gap-6 items-center">
            <button className="font-manrope tracking-tight text-slate-400 hover:text-slate-200 transition-colors">모델</button>
            <button className="font-manrope tracking-tight text-violet-300 border-b-2 border-violet-500 pb-1">데이터셋</button>
            <button className="font-manrope tracking-tight text-slate-400 hover:text-slate-200 transition-colors">신경망 로그</button>
          </nav>
        </div>
        <div className="flex items-center gap-4">
          <button onClick={() => navigate('/settings')} className="material-symbols-outlined text-slate-400 cursor-pointer hover:text-violet-400 transition-all">settings</button>
        </div>
        <div className="absolute bottom-0 left-0 w-full bg-gradient-to-b from-violet-500/10 to-transparent h-[1px]"></div>
      </header>

      {/* Main */}
      <main className={`${open ? 'ml-64' : 'ml-0'} pt-24 pb-12 px-10 min-h-screen transition-[margin] duration-300`}>
        {/* Breadcrumbs */}
        <div className="mb-8 flex justify-between items-end">
          <div>
            <nav className="flex items-center gap-2 text-on-surface-variant text-xs font-label uppercase tracking-widest mb-4">
              <button onClick={() => navigate('/ai/results')} className="hover:text-secondary cursor-pointer">데이터셋</button>
              <span className="material-symbols-outlined text-[14px]">chevron_right</span>
              <span className="hover:text-secondary cursor-pointer">신경망 자산</span>
              <span className="material-symbols-outlined text-[14px]">chevron_right</span>
              <span className="text-secondary">DB_insight</span>
            </nav>
            <h1 className="text-4xl font-extrabold tracking-tighter text-on-surface mb-2">파일 상세 - AI 모드</h1>
            <p className="text-on-surface-variant max-w-2xl">
              객체{' '}
              <span className="text-secondary font-semibold">{result.title || 'DB_insight.bin'}</span>의
              고밀도 인지 데이터 구조를 시각화합니다.
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

        {/* Grid */}
        <div className="grid grid-cols-12 gap-6">
          {/* Left column */}
          <div className="col-span-8 space-y-6">
            {/* Visualizer */}
            <div className="bg-surface-container-low rounded-[1.5rem] p-1 overflow-hidden relative group">
              <div className="absolute inset-0 bg-gradient-to-br from-secondary/10 via-transparent to-primary/5 opacity-50"></div>
              <div className="relative bg-surface rounded-[1.4rem] p-8 min-h-[400px] flex flex-col">
                <div className="flex justify-between items-start mb-12">
                  <div>
                    <span className="text-[10px] font-label uppercase tracking-[0.2em] text-secondary mb-1 block">신경망 지형도</span>
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
                        <p className="text-[10px] font-label uppercase tracking-widest text-on-surface-variant mb-1">{label}</p>
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

            {/* Metadata table */}
            <div className="bg-surface-container-low rounded-[1.5rem] p-8 border border-outline-variant/10">
              <div className="flex justify-between items-center mb-8">
                <h3 className="text-lg font-bold flex items-center gap-2">
                  <span className="material-symbols-outlined text-secondary">database</span>신경망 메타데이터 추출
                </h3>
                <button className="text-secondary text-xs font-label uppercase tracking-widest hover:underline">JSON 내보내기</button>
              </div>
              <div className="space-y-4">
                {[
                  ['인지 노드', 'node_alpha_x99283', '보안', 'text-secondary'],
                  ['해시 시퀀스', '0x77ae...bb91', '검증됨', 'text-secondary'],
                  ['원본 클러스터', 'Euclidean-North-Grid', '원격', 'text-on-surface-variant'],
                  ['마지막 펄스', '2024-05-18T14:22:01.002Z', '동기화됨', 'text-primary'],
                ].map(([label, val, status, cls]) => (
                  <div key={label} className="grid grid-cols-4 gap-4 p-4 rounded-xl hover:bg-surface-container-high transition-all border-b border-outline-variant/10 last:border-0">
                    <span className="text-xs font-label uppercase tracking-widest text-on-surface-variant">{label}</span>
                    <span className="text-xs font-medium text-on-surface col-span-2 font-mono">{val}</span>
                    <span className={`text-right text-[10px] font-bold ${cls}`}>{status}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Right column */}
          <div className="col-span-4 space-y-6">
            {/* AI summary */}
            <div className="glass-panel rounded-[1.5rem] p-8 border border-secondary/20 relative overflow-hidden" style={{ boxShadow: '0 0 20px rgba(172,138,255,0.15)' }}>
              <div className="absolute -right-10 -top-10 w-32 h-32 bg-secondary/20 blur-[60px] rounded-full"></div>
              <div className="flex items-center gap-3 mb-6">
                <div className="w-10 h-10 rounded-full bg-secondary-container flex items-center justify-center" style={{ boxShadow: '0 0 20px rgba(172,138,255,0.15)' }}>
                  <span className="material-symbols-outlined text-secondary" style={{ fontVariationSettings: '"FILL" 1' }}>auto_awesome</span>
                </div>
                <div>
                  <h4 className="font-bold text-on-surface">신경망 요약</h4>
                  <p className="text-[10px] text-secondary uppercase font-label tracking-widest">AI 생성 인사이트</p>
                </div>
              </div>
              <p className="text-sm leading-relaxed text-on-surface-variant mb-6 italic">
                "DB_insight 객체는 '예측 물류' 클러스터와 높은 상관관계를 가진 다층 벡터 임베딩을 포함합니다. 처리 결과, 노드 알파와 통합 시 효율성이 12% 향상될 가능성이 있습니다."
              </p>
              <div className="p-4 rounded-xl bg-surface-container-lowest/50 border border-outline-variant/20">
                <h5 className="text-[10px] font-label uppercase tracking-widest text-secondary mb-3">권장 프로토콜</h5>
                {['벡터 양자화', '레이어 정규화'].map((item) => (
                  <div key={item} className="flex items-center gap-3 mb-2">
                    <span className="material-symbols-outlined text-primary text-sm">check_circle</span>
                    <span className="text-xs text-on-surface">{item}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Access panel */}
            <div className="bg-surface-container-low rounded-[1.5rem] p-8 border border-outline-variant/10">
              <h4 className="text-xs font-label uppercase tracking-widest text-on-surface-variant mb-6">접근 권한 계층</h4>
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
              <button className="w-full mt-6 py-3 border border-outline-variant/20 rounded-xl text-xs font-label uppercase tracking-widest hover:border-secondary hover:text-secondary transition-all">
                접근 권한 관리
              </button>
            </div>

            {/* Timeline */}
            <div className="bg-surface-container-low rounded-[1.5rem] p-8 border border-outline-variant/10">
              <h4 className="text-xs font-label uppercase tracking-widest text-on-surface-variant mb-6">시간순 로그</h4>
              <div className="relative pl-6 space-y-6 before:content-[''] before:absolute before:left-[3px] before:top-2 before:bottom-2 before:w-[2px] before:bg-outline-variant/30">
                {[
                  { title: '신경망 최적화', time: '2시간 전 (시스템 AI)', active: true },
                  { title: '데이터셋 병합', time: '14시간 전 (Architect_A)', active: false },
                  { title: '객체 초기화', time: '2일 전 (Root)', active: false },
                ].map((item, i) => (
                  <div key={i} className={`relative ${i > 0 ? `opacity-${i === 1 ? '70' : '50'}` : ''}`}>
                    <div className={`absolute -left-[27px] top-1 w-2 h-2 rounded-full ${item.active ? 'bg-secondary' : 'bg-outline-variant'}`} style={item.active ? { boxShadow: '0 0 15px rgba(172,138,255,0.4)' } : {}}></div>
                    <p className="text-xs font-bold text-on-surface">{item.title}</p>
                    <p className="text-[10px] text-on-surface-variant">{item.time}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </main>

      <div className="fixed bottom-0 left-64 right-0 h-1 bg-gradient-to-r from-transparent via-secondary/20 to-transparent"></div>
    </div>
  )
}
