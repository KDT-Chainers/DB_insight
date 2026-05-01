import { useState, useEffect, useCallback } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { useSidebar } from '../context/SidebarContext'
import WindowControls from './WindowControls'
import { API_BASE } from '../api'

export default function SearchSidebar() {
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

  return (
    <>
      {/* 사이드바 */}
      <aside
        className={`fixed left-0 top-0 h-full w-64 rounded-r-3xl flex flex-col p-4 pt-10 bg-[#070d1f]/60 backdrop-blur-xl border-r border-[#41475b]/15 shadow-[20px_0_40px_rgba(133,173,255,0.05)] z-50 transition-transform duration-300 ${open ? 'translate-x-0' : '-translate-x-full'}`}
      >
        {/* Logo + 토글 */}
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
              <p className="text-base uppercase tracking-widest text-on-surface-variant mt-1">로컬 인텔리전스</p>
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
        <div className="flex gap-2 mb-6">
          <button
            onClick={() => navigate('/settings')}
            className={`flex-1 flex items-center justify-center gap-2 py-2 px-3 rounded-xl border transition-all duration-200 ${
              location.pathname === '/settings'
                ? 'bg-surface-container-highest border-primary/30 text-primary'
                : 'bg-surface-container-high border-outline-variant/15 hover:bg-surface-container-highest text-on-surface'
            }`}
          >
            <span className="material-symbols-outlined text-lg">settings</span>
            <span className="font-manrope uppercase tracking-[0.05em] text-lg">설정</span>
          </button>
          <button
            onClick={() => navigate('/data')}
            className={`flex-1 flex items-center justify-center gap-2 py-2 px-3 rounded-xl border transition-all duration-200 ${
              location.pathname === '/data'
                ? 'bg-surface-container-highest border-primary/30 text-primary'
                : 'bg-surface-container-high border-outline-variant/15 hover:bg-surface-container-highest text-on-surface'
            }`}
          >
            <span className="material-symbols-outlined text-lg">database</span>
            <span className="font-manrope uppercase tracking-[0.05em] text-lg">데이터</span>
          </button>
        </div>

        {/* 검색 기록 섹션 */}
        <div className="flex-1 overflow-y-auto min-h-0">
          <div className="flex items-center justify-between px-2 mb-3">
            <p className="font-manrope uppercase tracking-[0.05em] text-base text-primary flex items-center gap-1.5">
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

        {/* Footer */}
        <div className="mt-auto pt-4 border-t border-outline-variant/10 flex items-center gap-3 px-2">
          <div className="w-9 h-9 rounded-full border-2 border-primary-fixed-dim/20 bg-surface-container-highest flex items-center justify-center shrink-0">
            <span className="material-symbols-outlined text-primary text-lg">account_circle</span>
          </div>
          <div className="overflow-hidden">
            <p className="text-sm font-bold text-on-surface truncate">관리자</p>
            <p className="text-xs text-on-surface-variant">심층 분석 접근 권한</p>
          </div>
        </div>
      </aside>

      {/* 사이드바 닫혔을 때 토글 버튼 */}
      {!open && (
        <button
          onClick={toggle}
          className="fixed left-3 top-10 z-50 w-9 h-9 rounded-lg flex items-center justify-center bg-[#070d1f]/80 backdrop-blur border border-[#41475b]/30 text-on-surface-variant hover:text-primary hover:border-primary/30 transition-all"
        >
          <span className="material-symbols-outlined text-lg">menu</span>
        </button>
      )}

      {/* 드래그 타이틀바 + 윈도우 컨트롤 */}
      <div
        className="fixed top-0 right-0 h-8 bg-[#070d1f] z-[9999] flex items-center justify-end px-2"
        style={{ WebkitAppRegion: 'drag', left: open ? '256px' : '0', transition: 'left 0.3s' }}
      >
        <div style={{ WebkitAppRegion: 'no-drag' }}>
          <WindowControls />
        </div>
      </div>
    </>
  )
}
