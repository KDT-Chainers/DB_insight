import { useState, useEffect, useCallback, useMemo } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { useSidebar } from '../context/SidebarContext'
import WindowControls from './WindowControls'
import TeamLogoMark from './TeamLogoMark'
import { API_BASE } from '../api'

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

/**
 * @param {{ entranceOn?: boolean }} props
 * entranceOn: 메인과 동일 타이밍(~180ms 후 true)으로 패널 **전체**가 배경에 묻인 듯했다가 선명해지며 등장. 미전달 시 애니 없음.
 */
export default function SearchSidebar({ entranceOn } = {}) {
  const navigate = useNavigate()
  const location = useLocation()
  const { open, toggle } = useSidebar()

  const [historyList, setHistoryList] = useState([])

  // 사이드바 열릴 때마다 기록 갱신
  const loadHistory = useCallback(async () => {
    try {
      const res  = await fetch(`${API_BASE}/api/history?limit=30`)
      const data = await res.json()
      setHistoryList(data.history ?? [])
    } catch (_) {}
  }, [])

  useEffect(() => {
    if (open) loadHistory()
  }, [open, loadHistory])

  // 새 검색 완료 시 자동 갱신 (사이드바가 열려있어도 반영)
  useEffect(() => {
    const handler = () => loadHistory()
    window.addEventListener('history-updated', handler)
    return () => window.removeEventListener('history-updated', handler)
  }, [loadHistory])

  const deleteItem = async (id, e) => {
    e.stopPropagation()
    try {
      await fetch(`${API_BASE}/api/history/${id}`, { method: 'DELETE' })
      setHistoryList(prev => prev.filter(h => h.id !== id))
    } catch (_) {}
  }

  const deleteAll = async () => {
    try {
      await fetch(`${API_BASE}/api/history`, { method: 'DELETE' })
      setHistoryList([])
    } catch (_) {}
  }

  const runQuery = (query) => {
    navigate('/search', { state: { query } })
  }

  const ai = location.pathname === '/ai' || location.pathname.startsWith('/ai/')
  const S = ai ? SIDEBAR.ai : SIDEBAR.search
  const hasEntrance = entranceOn !== undefined
  const reduceMotion = useMemo(
    () => typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches,
    [],
  )
  const shellEntranceClass = useMemo(() => {
    if (!hasEntrance || reduceMotion) return ''
    return entranceOn ? 'sidebar-shell-entrance-on' : 'sidebar-shell-entrance-off'
  }, [hasEntrance, reduceMotion, entranceOn])

  return (
    <>
      {/* 사이드바 — translate는 래퍼에, 등장 효과는 패널(aside) 전체에 */}
      <div
        className={`search-sidebar-aside fixed left-0 top-0 z-50 h-full w-64 transition-transform duration-300 ${open ? 'translate-x-0' : '-translate-x-full'}`}
      >
        <aside
          className={`flex h-full w-full flex-col rounded-r-3xl p-4 pt-10 ${S.shell} ${shellEntranceClass}`}
        >
        <div className="flex min-h-0 flex-1 flex-col">
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
            <span className="material-symbols-outlined text-base">settings</span>
            <span className="font-manrope uppercase tracking-[0.03em] text-sm whitespace-nowrap">설정</span>
          </button>
          <button
            onClick={() => navigate('/data')}
            className={`flex flex-1 items-center justify-center gap-2 rounded-xl border px-3 py-2 transition-all duration-200 ${
              location.pathname === '/data' ? S.pillActive : S.pillIdle
            }`}
          >
            <span className="material-symbols-outlined text-base">database</span>
            <span className="font-manrope uppercase tracking-[0.03em] text-sm whitespace-nowrap">데이터</span>
          </button>
        </div>

        {/* 검색 기록 섹션 */}
        <div className="flex-1 overflow-y-auto min-h-0">
          <div className="flex items-center justify-between px-2 mb-3">
            <p className={`font-manrope uppercase tracking-[0.05em] text-base flex items-center gap-1.5 ${S.catHeading}`}>
              <span className="material-symbols-outlined text-base">history</span>
              검색 기록
            </p>
            {historyList.length > 0 && (
              <button
                onClick={deleteAll}
                className="text-[10px] text-on-surface-variant/40 hover:text-red-400 transition-colors uppercase tracking-wider"
              >
                전체 삭제
              </button>
            )}
          </div>

          {historyList.length === 0 ? (
            <div className="px-2 py-6 text-center">
              <span className="material-symbols-outlined text-on-surface-variant/20 text-3xl block mb-2">manage_search</span>
              <p className="text-xs text-on-surface-variant/30">검색 기록이 없습니다</p>
            </div>
          ) : (
            <ul className="space-y-0.5">
              {historyList.map((h) => (
                <li
                  key={h.id}
                  onClick={() => runQuery(h.query)}
                  className="group flex items-center gap-2 px-2 py-2 rounded-xl cursor-pointer hover:bg-primary/8 transition-all"
                >
                  <span className="material-symbols-outlined text-on-surface-variant/30 text-base shrink-0">history</span>
                  <span className="flex-1 text-sm text-on-surface-variant group-hover:text-on-surface truncate transition-colors">
                    {h.query}
                  </span>
                  {h.result_count != null && (
                    <span className="text-[10px] text-on-surface-variant/30 shrink-0">{h.result_count}건</span>
                  )}
                  <button
                    onClick={(e) => deleteItem(h.id, e)}
                    className="opacity-0 group-hover:opacity-100 transition-opacity text-on-surface-variant/30 hover:text-red-400 shrink-0"
                  >
                    <span className="material-symbols-outlined text-base">close</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
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
        </div>
        </aside>
      </div>

      {/* 사이드바 닫혔을 때 토글 버튼 */}
      {!open && (
        <button
          onClick={toggle}
          className={`fixed left-3 top-10 z-50 flex h-9 w-9 items-center justify-center rounded-lg transition-all ${S.floatBtn}`}
        >
          <span className="material-symbols-outlined text-lg">menu</span>
        </button>
      )}

      {/* 드래그 타이틀바 + 윈도우 컨트롤 */}
      <div
        className={`fixed top-0 right-0 h-8 z-[9999] flex items-center justify-end px-2 ${ai ? 'titlebar-chrome-studio' : 'titlebar-chrome'}`}
        style={{ WebkitAppRegion: 'drag', left: open ? '256px' : '0', transition: 'left 0.3s' }}
      >
        <div style={{ WebkitAppRegion: 'no-drag' }}>
          <WindowControls />
        </div>
      </div>
    </>
  )
}
