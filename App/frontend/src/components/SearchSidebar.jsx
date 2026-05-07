import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { useSidebar } from '../context/SidebarContext'
import WindowControls from './WindowControls'
import TeamLogoMark from './TeamLogoMark'
import { API_BASE } from '../api'

/** 검색 모드·AI 모드 사이드바 팔레트 */
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
      'bg-[#050507] border-r border-white/8 shadow-none',
    catHeading: 'text-violet-300/90',
    navActive: 'text-violet-200 bg-violet-950/45 border border-violet-500/25',
    navIdle: 'text-neutral-400 hover:bg-violet-950/30 hover:text-violet-100',
    pillIdle:
      'bg-white/[0.06] border-[#3a4c70]/35 hover:bg-[#16213a]/70 text-neutral-300 hover:text-violet-100',
    pillActive: 'bg-[#1a2440]/85 border-[#5a76ab]/55 text-violet-200',
    floatBtn:
      'bg-[#050507] border border-white/10 text-neutral-400 hover:text-violet-300 hover:border-violet-500/35',
  },
}
const AI_RAIL_WIDTH_PX = 96
const SIDEBAR_MIN_WIDTH_PX = 256
const SIDEBAR_MAX_WIDTH_PX = 420

/**
 * @param {{ entranceOn?: boolean }} props
 * entranceOn: 메인과 동일 타이밍(~180ms 후 true)으로 패널 **전체**가 배경에 묻인 듯했다가 선명해지며 등장. 미전달 시 애니 없음.
 */
export default function SearchSidebar({ entranceOn } = {}) {
  const navigate = useNavigate()
  const location = useLocation()
  const { open, toggle } = useSidebar()
  const aiPath = location.pathname === '/ai' || location.pathname.startsWith('/ai/')
  const [sidebarWidth, setSidebarWidth] = useState(() => {
    try {
      const raw = Number(localStorage.getItem('search-sidebar-width'))
      if (Number.isFinite(raw)) {
        return Math.max(SIDEBAR_MIN_WIDTH_PX, Math.min(SIDEBAR_MAX_WIDTH_PX, raw))
      }
    } catch {}
    return SIDEBAR_MIN_WIDTH_PX
  })
  const resizingRef = useRef(false)
  const workspaceReturn = aiPath ? '/ai' : '/search'
  const goDataPage = useCallback(
    () => navigate('/data', { state: { workspaceReturn } }),
    [navigate, workspaceReturn],
  )

  const [aiSidebarView, setAiSidebarView] = useState(() => {
    const st = (typeof window !== 'undefined' && window.history?.state) ? window.history.state : null
    return st?.view === 'detail' ? 'detail' : 'results'
  })
  const ai = aiPath && aiSidebarView === 'detail'


  const [historyList, setHistoryList] = useState([])
  const [aiHistoryOpen, setAiHistoryOpen] = useState(false)

  useEffect(() => {
    try { localStorage.setItem('search-sidebar-width', String(sidebarWidth)) } catch {}
  }, [sidebarWidth])

  useEffect(() => {
    const onMove = (e) => {
      if (!resizingRef.current) return
      const next = Math.max(
        SIDEBAR_MIN_WIDTH_PX,
        Math.min(SIDEBAR_MAX_WIDTH_PX, e.clientX),
      )
      setSidebarWidth(next)
    }
    const stopResize = () => {
      if (!resizingRef.current) return
      resizingRef.current = false
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', stopResize)
    return () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', stopResize)
      stopResize()
    }
  }, [])

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

  useEffect(() => {
    if (!ai) setAiHistoryOpen(false)
  }, [ai])

  useEffect(() => {
    if (!aiPath) return
    const onChange = (e) => {
      const v = e?.detail?.view
      if (v === 'detail' || v === 'results') setAiSidebarView(v)
    }
    window.addEventListener('ai-sidebar-view-changed', onChange)
    return () => window.removeEventListener('ai-sidebar-view-changed', onChange)
  }, [aiPath])

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
    navigate('/search', { state: { query, historyNonce: Date.now() } })
  }

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
        className={`search-sidebar-aside fixed left-0 top-0 z-50 h-full transition-transform duration-300 ${open ? 'translate-x-0' : '-translate-x-full'}`}
        style={{ width: `${sidebarWidth}px` }}
      >
        <aside
          className={`relative flex h-full w-full flex-col rounded-r-3xl p-4 pt-10 ${S.shell} ${shellEntranceClass}`}
        >
          {open && (
            <button
              type="button"
              aria-label="사이드바 너비 조절"
              onMouseDown={(e) => {
                e.preventDefault()
                resizingRef.current = true
                document.body.style.cursor = 'ew-resize'
                document.body.style.userSelect = 'none'
              }}
              className="absolute right-0 top-0 z-[60] h-full w-2 cursor-ew-resize bg-transparent"
              style={{ transform: 'translateX(50%)' }}
            />
          )}
          {false ? (
            <>
              <div className="mt-24 flex min-h-0 flex-1">
                <div className="w-full flex flex-col items-start pl-3">
                  <div className="relative rounded-[28px] border border-white/10 bg-[#050507] px-2.5 py-3.5 shadow-none">
                    <div className="pointer-events-none absolute left-1/2 top-[46px] bottom-[52px] w-px -translate-x-1/2 bg-gradient-to-b from-white/30 via-white/15 to-transparent" />
                    {[
                      {
                        key: 'settings',
                        icon: 'settings',
                        title: '설정',
                        active: location.pathname === '/settings',
                        onClick: () => navigate('/settings'),
                      },
                      {
                        key: 'data',
                        icon: 'database',
                        title: '데이터',
                        active: location.pathname === '/data',
                        onClick: goDataPage,
                      },
                      {
                        key: 'history',
                        icon: 'history',
                        title: '검색 기록',
                        active: aiHistoryOpen,
                        onClick: () => setAiHistoryOpen(v => !v),
                        dot: historyList.length > 0,
                      },
                    ].map((item, idx, arr) => (
                      <div key={item.key} className="relative flex flex-col items-center">
                        <button
                          onClick={item.onClick}
                          title={item.title}
                          className={`relative z-10 h-10 w-10 rounded-full flex items-center justify-center transition-all ${
                            item.active
                              ? 'bg-violet-500/25 text-violet-200 border border-violet-400/35 shadow-[0_0_18px_rgba(139,92,246,0.25)]'
                              : 'text-neutral-400 hover:bg-violet-500/10 hover:text-violet-200 border border-transparent'
                          }`}
                        >
                          <span className="material-symbols-outlined text-[20px]">{item.icon}</span>
                          {item.dot && (
                            <span className="absolute right-1.5 top-1.5 h-1.5 w-1.5 rounded-full bg-orange-400" />
                          )}
                        </button>
                        {idx < arr.length - 1 && <div className="h-2" />}
                      </div>
                    ))}
                    <div className="mt-2.5 flex items-center justify-center">
                      <button
                        type="button"
                        onClick={goDataPage}
                        title="관리자"
                        className="h-10 w-10 rounded-full border border-white/12 bg-[#050507] text-violet-300 flex items-center justify-center hover:bg-[#0a0a0d] transition-all"
                      >
                        <span className="material-symbols-outlined text-[21px]">account_circle</span>
                      </button>
                    </div>
                  </div>

                  <div className="mt-10 flex flex-col items-center gap-3 pl-1">
                    <button
                      onClick={() => navigate('/ai', { state: { goHomeAt: Date.now() } })}
                      className="h-11 w-11 rounded-full border border-white/10 bg-[#050507] text-neutral-300 shadow-none flex items-center justify-center hover:text-violet-200 hover:border-violet-400/35 transition-all"
                      title="AI 홈으로"
                    >
                      <span className="material-symbols-outlined text-[20px]">refresh</span>
                    </button>
                    <button
                      onClick={toggle}
                      className="h-11 w-11 rounded-full border border-white/10 bg-[#050507] text-neutral-300 shadow-none flex items-center justify-center hover:text-violet-200 hover:border-violet-400/35 transition-all"
                      title="사이드바 접기"
                    >
                      <span className="material-symbols-outlined text-[20px]">menu_open</span>
                    </button>
                  </div>
                </div>
              </div>

              {aiHistoryOpen && (
                <div className="absolute left-[92px] top-24 bottom-16 w-[230px] rounded-2xl border border-white/10 bg-[#050507] p-3 shadow-none">
                  <div className="mb-2 flex items-center justify-between">
                    <p className="text-[11px] font-bold uppercase tracking-widest text-violet-200/85">검색 기록</p>
                    {historyList.length > 0 && (
                      <button
                        onClick={deleteAll}
                        className="text-[10px] text-neutral-400 hover:text-red-300 transition-colors uppercase tracking-wider"
                      >
                        전체 삭제
                      </button>
                    )}
                  </div>
                  <div className="h-full overflow-y-auto pr-1 pb-6">
                    {historyList.length === 0 ? (
                      <div className="px-1 py-6 text-center">
                        <span className="material-symbols-outlined text-neutral-500/35 text-3xl block mb-2">manage_search</span>
                        <p className="text-[11px] text-neutral-500">검색 기록이 없습니다</p>
                      </div>
                    ) : (
                      <ul className="space-y-1">
                        {historyList.map((h) => (
                          <li
                            key={h.id}
                            onClick={() => runQuery(h.query)}
                            className="group flex items-center gap-2 rounded-lg px-2 py-1.5 cursor-pointer hover:bg-violet-500/10 transition-all"
                          >
                            <span className="material-symbols-outlined text-neutral-500 text-sm shrink-0">history</span>
                            <span className="flex-1 text-[11px] text-neutral-300 truncate group-hover:text-violet-100 transition-colors">
                              {h.query}
                            </span>
                            <button
                              onClick={(e) => deleteItem(h.id, e)}
                              className="opacity-0 group-hover:opacity-100 text-neutral-500 hover:text-red-300 transition-all shrink-0"
                            >
                              <span className="material-symbols-outlined text-sm">close</span>
                            </button>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                </div>
              )}

            </>
          ) : (
            <div className="flex min-h-0 flex-1 flex-col">
              {/* Logo + 토글 버튼 — h-8 드래그 바 아래에서 시작 */}
              <div className="mb-10 flex items-center justify-between px-2">
                <button
                  onClick={() => navigate('/search', { state: { goHomeAt: Date.now() } })}
                  className="flex items-center gap-3.5 rounded-full border border-white/80 px-4 py-2 hover:opacity-85 transition-opacity"
                >
                  <TeamLogoMark />
                  <h1 className="text-[1.25rem] font-medium tracking-tight text-[#f1f5f9] leading-none">
                    Insight
                  </h1>
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
                  onClick={goDataPage}
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
              <button
                type="button"
                onClick={goDataPage}
                className="mt-auto flex w-full items-center gap-3 border-t border-outline-variant/10 px-2 pt-6 text-left transition-opacity hover:opacity-85"
              >
                <div className="flex h-10 w-10 items-center justify-center rounded-full border-2 border-primary-fixed-dim/20 bg-surface-container-highest">
                  <span className="material-symbols-outlined text-xl text-primary">account_circle</span>
                </div>
                <div className="overflow-hidden">
                  <p className="truncate text-sm font-bold text-on-surface">관리자</p>
                </div>
              </button>
            </div>
          )}
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
        className={`fixed top-0 right-0 h-8 z-[9999] flex items-center justify-end px-2 ${ai ? 'titlebar-chrome-ai' : 'titlebar-chrome'}`}
        style={{
          WebkitAppRegion: 'drag',
          left: open ? `${sidebarWidth}px` : '0',
          transition: 'left 0.3s',
        }}
      >
        <div style={{ WebkitAppRegion: 'no-drag' }}>
          <WindowControls />
        </div>
      </div>
    </>
  )
}
