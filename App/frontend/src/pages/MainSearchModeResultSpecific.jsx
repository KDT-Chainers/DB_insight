import { useNavigate, useLocation } from 'react-router-dom'
import SearchSidebar from '../components/SearchSidebar'
import { useSidebar } from '../context/SidebarContext'

export default function MainSearchModeResultSpecific() {
  const navigate = useNavigate()
  const location = useLocation()
  const { open } = useSidebar()
  const file = location.state?.file || { name: 'neural_network_architecture_v4.pdf', icon: 'description' }

  return (
    <div className="bg-surface text-on-surface selection:bg-primary/30 selection:text-primary min-h-screen">
      <SearchSidebar />

      {/* Main */}
      <main className={`${open ? 'ml-64' : 'ml-0'} min-h-screen relative transition-[margin] duration-300`} style={{ backgroundImage: 'radial-gradient(rgba(133,173,255,0.05) 1px, transparent 1px)', backgroundSize: '32px 32px' }}>
        {/* Top bar */}
        <header className={`fixed top-0 ${open ? 'left-64' : 'left-0'} right-0 z-40 bg-[#070d1f]/60 backdrop-blur-xl flex items-center justify-between px-8 py-4 shadow-[0_4px_20px_rgba(133,173,255,0.1)] transition-[left] duration-300`}>
          <div className="flex items-center gap-4">
            <span className="material-symbols-outlined text-primary">description</span>
            <h2 className="font-manrope text-sm tracking-wide text-[#dfe4fe] font-bold">{file.name || 'neural_network_architecture_v4.pdf'}</h2>
          </div>
          <div className="flex items-center gap-3">
            <button className="px-5 py-2 text-xs font-bold uppercase tracking-widest text-primary bg-surface-container-high border border-outline-variant/15 rounded-full hover:bg-surface-variant transition-colors active:scale-95">
              경로 열기
            </button>
            <button className="px-5 py-2 text-xs font-bold uppercase tracking-widest text-on-primary bg-primary rounded-full hover:brightness-110 transition-all active:scale-95">
              파일 열기
            </button>
            <div className="h-8 w-[1px] bg-outline-variant/30 mx-2"></div>
            <button className="p-2 text-on-surface-variant hover:text-primary transition-colors"><span className="material-symbols-outlined">mail</span></button>
            <button className="p-2 text-on-surface-variant hover:text-primary transition-colors"><span className="material-symbols-outlined">more_vert</span></button>
          </div>
        </header>

        <section className="pt-24 pb-12 px-8 max-w-7xl mx-auto space-y-8">
          <div className="grid grid-cols-12 gap-6">
            {/* Main preview */}
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

            {/* Metadata sidebar */}
            <div className="col-span-4 space-y-6">
              {/* AI Summary */}
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

              {/* Metadata */}
              <div className="bg-surface-container-low rounded-xl p-6 border border-outline-variant/5">
                <h4 className="text-[10px] font-bold tracking-[0.15em] text-secondary mb-4 uppercase">파일 메타데이터</h4>
                <div className="space-y-4">
                  {[['크기', '12.4 MB'], ['페이지', '42'], ['생성일', '2023년 10월 24일'], ['형식', 'PDF 문서']].map(([k, v]) => (
                    <div key={k} className="flex justify-between items-center py-2 border-b border-outline-variant/10 last:border-0">
                      <span className="text-xs text-on-surface-variant">{k}</span>
                      <span className="text-xs font-bold text-on-surface">{v}</span>
                    </div>
                  ))}
                </div>
              </div>

              {/* Processing log */}
              <div className="bg-[#000000] rounded-xl p-6 border border-primary/20 shadow-[inset_0_0_20px_rgba(133,173,255,0.05)]">
                <h4 className="text-[10px] font-bold tracking-[0.15em] text-on-surface-variant mb-6 uppercase flex items-center gap-2">
                  <span className="material-symbols-outlined text-sm">terminal</span>처리 로그
                </h4>
                <div className="space-y-3 font-mono text-[10px] text-primary/70">
                  {[['12:00:01', '의미 클러스터 스캔 중...'], ['12:00:02', '고유 식별자 14개 발견.'], ['12:00:03', 'Obsidian DB와 상관관계 분석.', 'text-secondary'], ['12:00:04', '분석 완료.', 'text-on-surface']].map(([t, msg, cls]) => (
                    <div key={t} className="flex gap-2">
                      <span className="text-on-surface-variant">{t}</span>
                      <span className={cls}>{msg}</span>
                    </div>
                  ))}
                </div>
              </div>

              {/* Action buttons */}
              <div className="p-2 space-y-2">
                <button className="w-full group flex items-center justify-between p-4 rounded-xl bg-surface-container-highest hover:bg-primary/10 transition-colors border border-transparent hover:border-primary/20">
                  <div className="flex items-center gap-3">
                    <span className="material-symbols-outlined text-on-surface-variant group-hover:text-primary">share</span>
                    <span className="text-sm font-semibold">노드에 공유</span>
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
    </div>
  )
}
