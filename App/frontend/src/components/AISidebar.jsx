import { useNavigate, useLocation } from 'react-router-dom'
import { useSidebar } from '../context/SidebarContext'

export default function AISidebar() {
  const navigate = useNavigate()
  const location = useLocation()
  const { open, toggle } = useSidebar()

  return (
    <>
      {/* 사이드바 */}
      <aside
        className={`fixed left-0 top-0 h-full w-64 rounded-r-3xl flex flex-col p-4 bg-[#070d1f]/80 backdrop-blur-xl border-r border-violet-900/20 shadow-[20px_0_40px_rgba(172,138,255,0.05)] z-50 transition-transform duration-300 ${open ? 'translate-x-0' : '-translate-x-full'}`}
      >
        {/* Logo + 토글 버튼 */}
        <div className="mb-10 flex items-center justify-between px-2">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 bg-gradient-to-br from-secondary to-fuchsia-500 rounded-lg flex items-center justify-center shadow-[0_0_15px_rgba(172,138,255,0.3)]">
              <span className="material-symbols-outlined text-on-primary-fixed text-lg" style={{ fontVariationSettings: '"FILL" 1' }}>terminal</span>
            </div>
            <div>
              <h1 className="text-xl font-black text-[#dfe4fe] leading-none">Obsidian AI</h1>
              <p className="text-[0.65rem] uppercase tracking-widest text-violet-400/60 mt-1">AI 모드 활성화</p>
            </div>
          </div>
          <button
            onClick={toggle}
            className="w-8 h-8 rounded-lg flex items-center justify-center text-slate-500 hover:text-violet-300 hover:bg-violet-900/20 transition-all"
          >
            <span className="material-symbols-outlined text-lg">menu_open</span>
          </button>
        </div>

        {/* 설정 & 데이터 버튼 */}
        <div className="flex gap-2 mb-8">
          <button
            onClick={() => navigate('/settings')}
            className={`flex-1 flex items-center justify-center gap-2 py-2 px-3 rounded-xl border transition-all duration-200 ${
              location.pathname === '/settings'
                ? 'bg-violet-900/30 border-violet-500/30 text-violet-300'
                : 'bg-white/5 border-white/5 hover:bg-violet-900/20 text-slate-400 hover:text-violet-300'
            }`}
          >
            <span className="material-symbols-outlined text-sm">settings</span>
            <span className="font-manrope uppercase tracking-[0.05em] text-[0.7rem]">설정</span>
          </button>
          <button
            onClick={() => navigate('/data')}
            className={`flex-1 flex items-center justify-center gap-2 py-2 px-3 rounded-xl border transition-all duration-200 ${
              location.pathname === '/data'
                ? 'bg-violet-900/30 border-violet-500/30 text-violet-300'
                : 'bg-white/5 border-white/5 hover:bg-violet-900/20 text-slate-400 hover:text-violet-300'
            }`}
          >
            <span className="material-symbols-outlined text-sm">database</span>
            <span className="font-manrope uppercase tracking-[0.05em] text-[0.7rem]">데이터</span>
          </button>
        </div>

        {/* 네비게이션 */}
        <div className="flex-1 overflow-y-auto space-y-1">
          <div className="px-4 py-2">
            <p className="font-manrope uppercase tracking-[0.05em] text-[0.75rem] text-violet-400/80 mb-4">AI 워크스페이스</p>
          </div>
          {[
            { label: '신경망 검색', icon: 'search', path: '/ai' },
            { label: '파일 보관소', icon: 'folder_open', path: null },
            { label: '처리 중', icon: 'memory', path: null },
            { label: '기록', icon: 'history', path: null },
            { label: '분석', icon: 'insights', path: null },
          ].map((item) => {
            const isActive = item.path && location.pathname === item.path
            return (
              <button
                key={item.label}
                onClick={() => item.path && navigate(item.path)}
                className={`w-full flex items-center gap-3 rounded-xl px-4 py-3 active:translate-x-1 duration-200 transition-all ${
                  isActive
                    ? 'text-violet-300 bg-violet-900/30'
                    : 'text-slate-500 hover:bg-violet-900/20 hover:text-violet-300'
                }`}
              >
                <span className="material-symbols-outlined">{item.icon}</span>
                <span className="font-manrope uppercase tracking-[0.05em] text-[0.75rem]">{item.label}</span>
              </button>
            )
          })}

          {/* 최근 기록 */}
          <div className="mt-8 px-4 space-y-4">
            <p className="font-manrope uppercase tracking-[0.05em] text-[0.7rem] text-slate-600">최근</p>
            <div className="space-y-3">
              {['퀀텀 메모리 분석...', '신경망 토폴로지 검색', '클러스터 최적화'].map((item, i) => (
                <div key={i} className="text-[0.8rem] text-slate-500 hover:text-violet-300 cursor-pointer transition-colors truncate">
                  {item}
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* 하단 프로필 */}
        <div className="mt-auto pt-6 border-t border-violet-900/20 flex items-center gap-3 px-2">
          <div className="w-10 h-10 rounded-full border-2 border-violet-900/30 bg-surface-container-highest flex items-center justify-center">
            <span className="material-symbols-outlined text-violet-400 text-xl">account_circle</span>
          </div>
          <div className="overflow-hidden">
            <p className="text-sm font-bold text-[#dfe4fe] truncate">관리자</p>
            <p className="text-[0.65rem] text-violet-400/60">심층 분석 접근 권한</p>
          </div>
        </div>
      </aside>

      {/* 사이드바 닫혔을 때 떠있는 토글 버튼 */}
      {!open && (
        <button
          onClick={toggle}
          className="fixed left-3 top-3 z-50 w-9 h-9 rounded-lg flex items-center justify-center bg-[#070d1f]/80 backdrop-blur border border-violet-900/30 text-slate-500 hover:text-violet-300 hover:border-violet-500/30 transition-all"
        >
          <span className="material-symbols-outlined text-lg">menu</span>
        </button>
      )}
    </>
  )
}
