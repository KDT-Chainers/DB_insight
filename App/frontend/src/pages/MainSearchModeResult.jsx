import { useNavigate, useLocation } from 'react-router-dom'

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

export default function MainSearchModeResult() {
  const navigate = useNavigate()
  const location = useLocation()
  const query = location.state?.query || '로컬 보관소의 신경망 벡터 클러스터'

  return (
    <div className="bg-background text-on-surface min-h-screen overflow-x-hidden" style={{ backgroundImage: 'radial-gradient(circle at 2px 2px, rgba(65, 71, 91, 0.15) 1px, transparent 0)', backgroundSize: '32px 32px' }}>
      {/* Top app bar */}
      <header className="fixed top-0 w-full z-50 bg-slate-950/60 backdrop-blur-xl shadow-[0_0_20px_rgba(133,173,255,0.1)] flex justify-between items-center px-6 py-3">
        <div className="flex items-center gap-8 w-full max-w-6xl mx-auto">
          <button onClick={() => navigate('/search')} className="text-xl font-bold tracking-tighter bg-gradient-to-r from-blue-300 to-purple-400 bg-clip-text text-transparent shrink-0">
            Obsidian 검색
          </button>
          <div className="relative flex-1 group">
            <div className="absolute inset-0 bg-primary/10 blur-xl rounded-full opacity-50 group-focus-within:opacity-100 transition-opacity"></div>
            <div className="relative flex items-center bg-surface-container-high rounded-full border border-outline-variant/20 px-4 py-2 gap-3 focus-within:border-primary/50 transition-all">
              <span className="material-symbols-outlined text-primary">search</span>
              <input
                className="bg-transparent border-none focus:ring-0 w-full text-on-surface placeholder-on-surface-variant text-sm outline-none"
                placeholder="인텔리전스에 질문하세요..."
                defaultValue={query}
                onKeyDown={(e) => e.key === 'Enter' && navigate('/search/results', { state: { query: e.target.value } })}
              />
            </div>
          </div>
          <nav className="hidden md:flex items-center gap-6 shrink-0">
            <button className="text-blue-300 border-b-2 border-blue-400 pb-1">탐색기</button>
            <button className="text-slate-400 hover:text-blue-200 transition-colors">최근</button>
            <button className="text-slate-400 hover:text-blue-200 transition-colors">보관소</button>
          </nav>
        </div>
      </header>

      {/* Sidebar */}
      <aside className="fixed left-0 top-0 h-full w-64 pt-20 bg-slate-950/80 backdrop-blur-2xl shadow-[10px_0_30px_rgba(0,0,0,0.5)] flex flex-col gap-4 p-4 z-40">
        <div className="px-2 py-4">
          <div className="flex items-center gap-3 mb-6">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-primary to-secondary p-px">
              <div className="w-full h-full bg-slate-950 rounded-[11px] flex items-center justify-center">
                <span className="material-symbols-outlined text-primary text-xl">hub</span>
              </div>
            </div>
            <div>
              <p className="text-sm font-bold text-blue-300 font-manrope">신경망 노드 01</p>
              <p className="text-[10px] text-slate-500 tracking-widest uppercase">로컬 인텔리전스 활성화</p>
            </div>
          </div>
        </div>
        <nav className="space-y-1">
          <button onClick={() => navigate('/search')} className="w-full text-slate-500 hover:text-slate-300 flex items-center gap-3 px-3 py-2.5 rounded-xl hover:bg-slate-900/50 transition-all text-sm font-medium tracking-wide">
            <span className="material-symbols-outlined">history</span><span>기록</span>
          </button>
          <div className="text-blue-300 bg-blue-500/5 border-r-2 border-blue-500/50 flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium tracking-wide">
            <span className="material-symbols-outlined">analytics</span><span>데이터 클러스터</span>
          </div>
          <button onClick={() => navigate('/settings')} className="w-full text-slate-500 hover:text-slate-300 flex items-center gap-3 px-3 py-2.5 rounded-xl hover:bg-slate-900/50 transition-all text-sm font-medium tracking-wide">
            <span className="material-symbols-outlined">settings</span><span>설정</span>
          </button>
        </nav>
        <div className="mt-auto p-4 glass-panel rounded-2xl border border-outline-variant/10">
          <p className="text-[10px] font-bold text-primary mb-2 uppercase tracking-tighter">메모리 인덱스 상태</p>
          <div className="h-1.5 w-full bg-surface-container-highest rounded-full overflow-hidden">
            <div className="h-full w-3/4 bg-gradient-to-r from-primary to-secondary shadow-[0_0_8px_rgba(133,173,255,0.5)]"></div>
          </div>
          <p className="text-[10px] text-on-surface-variant mt-2">1.2TB / 2.0TB 인덱싱됨</p>
        </div>
      </aside>

      {/* Main */}
      <main className="pl-64 pt-24 min-h-screen">
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
              <button className="px-4 py-2 rounded-full bg-gradient-to-r from-primary to-secondary text-on-primary font-bold text-xs shadow-lg shadow-primary/20 flex items-center gap-2">
                <span className="material-symbols-outlined text-sm">auto_awesome</span>전체 합성
              </button>
            </div>
          </div>

          {/* Results carousel */}
          <div className="flex gap-6 overflow-x-auto no-scrollbar pb-12 snap-x snap-mandatory">
            {RESULTS.map((r) => (
              <div key={r.id} className="flex-none w-[420px] snap-start">
                <div className="bg-surface-container-high rounded-[1.5rem] p-1 h-full shadow-[0_20px_50px_rgba(0,0,0,0.3)] hover:shadow-primary/5 transition-all group/card border border-outline-variant/5">
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
                      <button
                        onClick={() => navigate(`/search/results/${r.id}`, { state: { file: r } })}
                        className="text-xs font-bold text-primary flex items-center gap-1 group-hover/card:translate-x-1 transition-transform"
                      >
                        파일 열기
                        <span className="material-symbols-outlined text-sm">arrow_forward</span>
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>

          {/* Bottom grid */}
          <div className="mt-12 grid grid-cols-12 gap-6">
            <div className="col-span-4 bg-surface-container-low rounded-[1.5rem] p-6 border border-outline-variant/10">
              <div className="flex justify-between items-center mb-6">
                <h3 className="text-sm font-bold text-on-surface flex items-center gap-2">
                  <span className="material-symbols-outlined text-primary text-sm">history</span>최근 탐색
                </h3>
              </div>
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
                  요청한 <span className="text-primary font-bold">신경망 벡터 클러스터</span>가 로컬 저장소의 여러 도메인에 걸쳐 나타납니다.
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

      {/* Floating AI button */}
      <div className="fixed bottom-10 right-10 z-50">
        <button
          onClick={() => navigate('/ai')}
          className="p-4 rounded-full bg-gradient-to-br from-primary to-secondary shadow-[0_0_30px_rgba(133,173,255,0.4)] cursor-pointer hover:scale-110 transition-transform active:scale-95"
        >
          <span className="material-symbols-outlined text-white">auto_awesome</span>
        </button>
      </div>
    </div>
  )
}
