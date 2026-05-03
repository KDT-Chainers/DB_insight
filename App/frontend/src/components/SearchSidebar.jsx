import { useNavigate, useLocation } from 'react-router-dom'
import { useSidebar } from '../context/SidebarContext'
import WindowControls from './WindowControls'

export default function SearchSidebar() {
  const navigate = useNavigate()
  const location = useLocation()
  const { open, toggle } = useSidebar()

  return (
    <>
      {/* 사이드바 */}
      <aside
        className={`fixed left-0 top-0 h-full w-64 rounded-r-3xl flex flex-col p-4 pt-10 bg-[#070d1f]/60 backdrop-blur-xl border-r border-[#41475b]/15 shadow-[20px_0_40px_rgba(133,173,255,0.05)] z-50 transition-transform duration-300 ${open ? 'translate-x-0' : '-translate-x-full'}`}
      >
        {/* Logo + 토글 버튼 — h-8 드래그 바 아래에서 시작 */}
        <div className="mb-10 flex items-center justify-between px-2">
          <button
            onClick={() => navigate('/search')}
            className="flex items-center gap-3 hover:opacity-80 transition-opacity"
          >
            <div className="w-8 h-8 bg-gradient-to-br from-primary to-secondary rounded-lg flex items-center justify-center">
              <span className="material-symbols-outlined text-on-primary-fixed text-lg" style={{ fontVariationSettings: '"FILL" 1' }}>dataset</span>
            </div>
            <div className="text-left">
              <h1 className="text-xl font-black text-[#dfe4fe] leading-none">DB_insight</h1>
              <p className="text-[0.65rem] uppercase tracking-widest text-on-surface-variant mt-1">로컬 인텔리전스</p>
            </div>
          </button>
          <button
            onClick={toggle}
            className="w-8 h-8 rounded-lg flex items-center justify-center text-on-surface-variant hover:text-primary hover:bg-primary/10 transition-all"
          >
            <span className="material-symbols-outlined text-lg">menu_open</span>
          </button>
        </div>

        {/* Settings & Data buttons */}
        <div className="flex gap-2 mb-8">
          <button
            onClick={() => navigate('/settings')}
            className={`flex-1 flex items-center justify-center gap-2 py-2 px-3 rounded-xl border transition-all duration-200 ${
              location.pathname === '/settings'
                ? 'bg-surface-container-highest border-primary/30 text-primary'
                : 'bg-surface-container-high border-outline-variant/15 hover:bg-surface-container-highest text-on-surface'
            }`}
          >
            <span className="material-symbols-outlined text-sm">settings</span>
            <span className="font-manrope uppercase tracking-[0.05em] text-[0.7rem]">설정</span>
          </button>
          <button
            onClick={() => navigate('/data')}
            className={`flex-1 flex items-center justify-center gap-2 py-2 px-3 rounded-xl border transition-all duration-200 ${
              location.pathname === '/data'
                ? 'bg-surface-container-highest border-primary/30 text-primary'
                : 'bg-surface-container-high border-outline-variant/15 hover:bg-surface-container-highest text-on-surface'
            }`}
          >
            <span className="material-symbols-outlined text-sm">database</span>
            <span className="font-manrope uppercase tracking-[0.05em] text-[0.7rem]">데이터</span>
          </button>
        </div>

        {/* Nav items */}
        <div className="flex-1 overflow-y-auto space-y-1">
          <div className="px-4 py-2">
            <p className="font-manrope uppercase tracking-[0.05em] text-[0.75rem] text-primary mb-4">검색 기록</p>
          </div>
          <button
            onClick={() => navigate('/search')}
            className={`w-full flex items-center gap-3 rounded-xl px-4 py-3 active:translate-x-1 duration-200 ${
              location.pathname === '/search' ? 'text-primary bg-[#1c253e]' : 'text-[#a5aac2] hover:bg-[#1c253e]/50 hover:text-[#dfe4fe]'
            }`}
          >
            <span className="material-symbols-outlined">history</span>
            <span className="font-manrope uppercase tracking-[0.05em] text-[0.75rem]">검색 기록</span>
          </button>
          <button className="w-full flex items-center gap-3 text-[#a5aac2] px-4 py-3 hover:bg-[#1c253e]/50 hover:text-[#dfe4fe] transition-all active:translate-x-1 duration-200">
            <span className="material-symbols-outlined">search_check</span>
            <span className="font-manrope uppercase tracking-[0.05em] text-[0.75rem]">최근 검색어</span>
          </button>

          {/* Recent queries */}
          <div className="mt-8 px-4 space-y-4">
            <p className="font-manrope uppercase tracking-[0.05em] text-[0.7rem] text-on-surface-variant/60">최근</p>
            <div className="space-y-3">
              {['프로젝트 알파 문서...', '매출 차트 Q3 2023', '회의록 암호화'].map((item, i) => (
                <div key={i} className="text-[0.8rem] text-on-surface-variant hover:text-on-surface cursor-pointer transition-colors truncate">
                  {item}
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Footer profile */}
        <div className="mt-auto pt-6 border-t border-outline-variant/10 flex items-center gap-3 px-2">
          <div className="w-10 h-10 rounded-full border-2 border-primary-fixed-dim/20 bg-surface-container-highest flex items-center justify-center">
            <span className="material-symbols-outlined text-primary text-xl">account_circle</span>
          </div>
          <div className="overflow-hidden">
            <p className="text-sm font-bold text-on-surface truncate">관리자</p>
            <p className="text-[0.65rem] text-on-surface-variant">심층 분석 접근 권한</p>
          </div>
        </div>
      </aside>

      {/* 사이드바 닫혔을 때 떠있는 토글 버튼 — h-8(32px) 드래그 바 아래 */}
      {!open && (
        <button
          onClick={toggle}
          className="fixed left-3 top-10 z-50 w-9 h-9 rounded-lg flex items-center justify-center bg-[#070d1f]/80 backdrop-blur border border-[#41475b]/30 text-on-surface-variant hover:text-primary hover:border-primary/30 transition-all"
        >
          <span className="material-symbols-outlined text-lg">menu</span>
        </button>
      )}

      {/* 드래그 가능한 타이틀바 + 윈도우 컨트롤 */}
      <div
        className="titlebar-chrome fixed top-0 right-0 h-8 z-[9999] flex items-center justify-end px-2"
        style={{ WebkitAppRegion: 'drag', left: open ? '256px' : '0', transition: 'left 0.3s' }}
      >
        <div style={{ WebkitAppRegion: 'no-drag' }}>
          <WindowControls />
        </div>
      </div>
    </>
  )
}
