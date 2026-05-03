import { useNavigate, useLocation } from 'react-router-dom'
import { useSidebar } from '../context/SidebarContext'
import WindowControls from './WindowControls'
import TeamLogoMark from './TeamLogoMark'

/** 검색 모드·AI 모드 사이드바 팔레트 분리 (한 색으로 통일하지 않음) */
const SIDEBAR = {
  search: {
    shell:
      'bg-[#070d1f]/60 backdrop-blur-xl border-r border-[#41475b]/15 shadow-[20px_0_40px_rgba(133,173,255,0.05)]',
    catHeading: 'text-primary',
    navActive: 'text-primary bg-[#1c253e]',
    navIdle: 'text-[#a5aac2] hover:bg-[#1c253e]/50 hover:text-[#dfe4fe]',
    pillIdle:
      'bg-surface-container-high border-outline-variant/15 hover:bg-surface-container-highest text-on-surface',
    pillActive: 'bg-surface-container-highest border-primary/30 text-primary',
    floatBtn:
      'bg-[#070d1f]/80 backdrop-blur border border-[#41475b]/30 text-on-surface-variant hover:text-primary hover:border-primary/30',
  },
  ai: {
    shell:
      'bg-black/80 backdrop-blur-xl border-r border-white/10 shadow-[20px_0_48px_rgba(109,40,217,0.12)]',
    catHeading: 'text-violet-300/90',
    navActive: 'text-violet-200 bg-violet-950/45 border border-violet-500/25',
    navIdle: 'text-neutral-400 hover:bg-violet-950/30 hover:text-violet-100',
    pillIdle:
      'bg-white/[0.06] border-white/10 hover:bg-violet-950/35 text-neutral-300 hover:text-violet-100',
    pillActive: 'bg-violet-950/55 border-violet-400/35 text-violet-200',
    floatBtn:
      'bg-black/85 backdrop-blur border border-white/15 text-neutral-400 hover:text-violet-300 hover:border-violet-500/35',
  },
}

export default function SearchSidebar() {
  const navigate = useNavigate()
  const location = useLocation()
  const { open, toggle } = useSidebar()

  const ai = location.pathname === '/ai' || location.pathname.startsWith('/ai/')
  const S = ai ? SIDEBAR.ai : SIDEBAR.search

  return (
    <>
      {/* 사이드바 */}
      <aside
        className={`fixed left-0 top-0 z-50 flex h-full w-64 flex-col rounded-r-3xl p-4 pt-10 transition-transform duration-300 ${S.shell} ${open ? 'translate-x-0' : '-translate-x-full'}`}
      >
        {/* Logo + 토글 버튼 — h-8 드래그 바 아래에서 시작 */}
        <div className="mb-10 flex items-center justify-between px-2">
          <button
            onClick={() => navigate('/search')}
            className="flex items-center gap-3 hover:opacity-80 transition-opacity"
          >
            <TeamLogoMark />
            <div className="text-left">
              <h1 className="text-xl font-black text-[#dfe4fe] leading-none">DB_insight</h1>
              <p
                className={`mt-1 text-[0.65rem] uppercase tracking-widest ${ai ? 'text-violet-400/55' : 'text-on-surface-variant'}`}
              >
                로컬 인텔리전스
              </p>
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
        <div className="mb-8 flex gap-2">
          <button
            onClick={() => navigate('/settings')}
            className={`flex flex-1 items-center justify-center gap-2 rounded-xl border px-3 py-2 transition-all duration-200 ${
              location.pathname === '/settings' ? S.pillActive : S.pillIdle
            }`}
          >
            <span className="material-symbols-outlined text-sm">settings</span>
            <span className="font-manrope uppercase tracking-[0.05em] text-[0.7rem]">설정</span>
          </button>
          <button
            onClick={() => navigate('/data')}
            className={`flex flex-1 items-center justify-center gap-2 rounded-xl border px-3 py-2 transition-all duration-200 ${
              location.pathname === '/data' ? S.pillActive : S.pillIdle
            }`}
          >
            <span className="material-symbols-outlined text-sm">database</span>
            <span className="font-manrope uppercase tracking-[0.05em] text-[0.7rem]">데이터</span>
          </button>
        </div>

        {/* Nav items */}
        <div className="flex-1 space-y-1 overflow-y-auto">
          <div className="px-4 py-2">
            <p className={`mb-4 font-manrope text-[0.75rem] uppercase tracking-[0.05em] ${S.catHeading}`}>
              검색 기록
            </p>
          </div>
          <button
            onClick={() => navigate('/search')}
            className={`flex w-full items-center gap-3 rounded-xl px-4 py-3 duration-200 active:translate-x-1 ${
              location.pathname === '/search' ? S.navActive : S.navIdle
            }`}
          >
            <span className="material-symbols-outlined">history</span>
            <span className="font-manrope uppercase tracking-[0.05em] text-[0.75rem]">검색 기록</span>
          </button>
          <button
            className={`flex w-full items-center gap-3 rounded-xl px-4 py-3 transition-all duration-200 active:translate-x-1 ${S.navIdle}`}
          >
            <span className="material-symbols-outlined">search_check</span>
            <span className="font-manrope uppercase tracking-[0.05em] text-[0.75rem]">최근 검색어</span>
          </button>

          {/* Recent queries */}
          <div className="mt-8 space-y-4 px-4">
            <p
              className={`font-manrope text-[0.7rem] uppercase tracking-[0.05em] ${ai ? 'text-neutral-500' : 'text-on-surface-variant/60'}`}
            >
              최근
            </p>
            <div className="space-y-3">
              {['프로젝트 알파 문서...', '매출 차트 Q3 2023', '회의록 암호화'].map((item, i) => (
                <div
                  key={i}
                  className={`cursor-pointer truncate text-[0.8rem] transition-colors ${ai ? 'text-neutral-500 hover:text-violet-200/90' : 'text-on-surface-variant hover:text-on-surface'}`}
                >
                  {item}
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Footer profile */}
        <div
          className={`mt-auto flex items-center gap-3 border-t px-2 pt-6 ${ai ? 'border-white/10' : 'border-outline-variant/10'}`}
        >
          <div
            className={`flex h-10 w-10 items-center justify-center rounded-full border-2 ${ai ? 'border-violet-500/25 bg-violet-950/40' : 'border-primary-fixed-dim/20 bg-surface-container-highest'}`}
          >
            <span className={`material-symbols-outlined text-xl ${ai ? 'text-violet-300' : 'text-primary'}`}>
              account_circle
            </span>
          </div>
          <div className="overflow-hidden">
            <p className={`truncate text-sm font-bold ${ai ? 'text-neutral-100' : 'text-on-surface'}`}>관리자</p>
            <p className={`text-[0.65rem] ${ai ? 'text-neutral-500' : 'text-on-surface-variant'}`}>심층 분석 접근 권한</p>
          </div>
        </div>
      </aside>

      {/* 사이드바 닫혔을 때 떠있는 토글 버튼 — h-8(32px) 드래그 바 아래 */}
      {!open && (
        <button
          onClick={toggle}
          className={`fixed left-3 top-10 z-50 flex h-9 w-9 items-center justify-center rounded-lg transition-all ${S.floatBtn}`}
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
