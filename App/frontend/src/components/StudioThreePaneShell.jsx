/**
 * 데이터·설정 공용 스튜디오 셸 — 대시보드형 3열
 * (좁은 좌 내비 | 넓은 중앙 작업 | 우 위젯) + 상단 브레드크럼·유틸.
 */
import { useEffect, useMemo, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import TeamLogoMark from './TeamLogoMark'

/**
 * @param {object} props
 * @param {string} props.discoverTitle 영역 라벨 (브랜드 아래 한 줄)
 * @param {string} props.areaSubtitle 보조 설명
 * @param {string} [props.navSectionLabel]
 * @param {Array<{ key: string, icon: string, label: string, subtitle?: string, active?: boolean, onClick: () => void }>} props.navItems
 * @param {import('react').ReactNode} props.titleBar
 * @param {import('react').ReactNode} [props.breadcrumb] 상단 경로 (좌측)
 * @param {import('react').ReactNode} [props.toolbarRight] 유틸 줄 우측 커스텀 액션
 * @param {import('react').ReactNode} props.hero 중앙 페이지 헤더(제목·설명)
 * @param {import('react').ReactNode} [props.actionBar] 필터·칩·주요 버튼 줄
 * @param {string | null} [props.listSectionTitle]
 * @param {import('react').ReactNode} props.children 중앙 본문
 * @param {import('react').ReactNode} [props.rightWidgets] 우측 위젯 열 (넓은 화면에서만)
 * @param {import('react').ReactNode} [props.floatingFooter]
 */
export default function StudioThreePaneShell({
  discoverTitle,
  areaSubtitle,
  navSectionLabel = '메뉴',
  navItems,
  titleBar,
  breadcrumb,
  toolbarRight,
  hero,
  actionBar,
  listSectionTitle,
  children,
  rightWidgets,
  floatingFooter,
}) {
  const navigate = useNavigate()
  const location = useLocation()
  const [navQuery, setNavQuery] = useState('')
  const [adminToggleOn, setAdminToggleOn] = useState(
    () => location.pathname === '/settings',
  )

  useEffect(() => {
    setAdminToggleOn(location.pathname === '/settings')
  }, [location.pathname])

  const filteredNav = useMemo(() => {
    const q = navQuery.trim().toLowerCase()
    if (!q) return navItems
    return navItems.filter(
      (it) =>
        it.label.toLowerCase().includes(q) ||
        (it.subtitle && it.subtitle.toLowerCase().includes(q)),
    )
  }, [navItems, navQuery])

  return (
    <div className="flex h-screen min-h-0 w-full overflow-hidden px-2.5 pb-2.5 pt-1.5 text-on-surface sm:px-3 sm:pb-3 sm:pt-2">
      <div className="apple-studio-unified-canvas flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden rounded-[20px] sm:rounded-[24px]">
        <div className="shrink-0 border-b border-white/[0.06]">{titleBar}</div>

        <div className="flex min-h-0 min-w-0 flex-1">
          {/* ── 좌: 아이콘 + 라벨 내비 (대시보드형) ── */}
          <aside className="apple-studio-sidebar-col relative flex w-[min(220px,22vw)] shrink-0 flex-col border-r border-white/[0.04] py-4 pl-3 pr-2 sm:w-[min(236px,24vw)] sm:py-5 sm:pl-3.5 sm:pr-2.5">
            <div
              className="pointer-events-none absolute right-0 top-6 bottom-6 w-px bg-gradient-to-b from-transparent via-white/[0.06] to-transparent"
              aria-hidden
            />

            <div className="mb-5 flex items-center gap-3 px-1">
              <TeamLogoMark className="!h-10 !w-10 rounded-[12px]" />
              <div className="min-w-0">
                <p className="truncate text-[15px] font-bold tracking-tight text-white">DB_insight</p>
                <p className="truncate text-[11px] font-medium uppercase tracking-[0.14em] text-white/52">
                  {discoverTitle}
                </p>
                <p className="truncate text-[10px] text-white/44">{areaSubtitle}</p>
              </div>
            </div>

            <div className="mb-3 px-0.5">
              <div className="relative">
                <span className="material-symbols-outlined pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[1rem] text-white/32">
                  search
                </span>
                <input
                  type="search"
                  value={navQuery}
                  onChange={(e) => setNavQuery(e.target.value)}
                  placeholder="메뉴 검색"
                  className="w-full rounded-full border-0 bg-white/[0.07] py-2 pl-9 pr-3 text-[12px] text-white/90 outline-none ring-1 ring-inset ring-white/[0.08] placeholder:text-white/42 focus:ring-2 focus:ring-sky-400/30"
                />
              </div>
            </div>

            <p className="mb-1.5 px-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-white/44">
              {navSectionLabel}
            </p>
            <nav className="min-h-0 flex-1 space-y-0.5 overflow-y-auto px-0.5 pb-2">
              {filteredNav.length === 0 ? (
                <p className="px-2 py-5 text-center text-[11px] text-white/42">검색 결과 없음</p>
              ) : null}
              {filteredNav.map((item) => (
                <button
                  key={item.key}
                  type="button"
                  onClick={item.onClick}
                  className={`flex w-full items-center gap-3 rounded-2xl py-2 pl-1.5 pr-2 text-left transition-all ${
                    item.active ? 'bg-white/[0.08]' : 'hover:bg-white/[0.05]'
                  }`}
                >
                  <div
                    className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full transition-all ${
                      item.active
                        ? 'bg-sky-500/25 text-sky-200 shadow-[0_0_22px_rgba(56,189,248,0.28)] ring-1 ring-sky-400/35'
                        : 'bg-white/[0.06] text-white/58'
                    }`}
                  >
                    <span
                      className="material-symbols-outlined text-[1.35rem]"
                      style={{ fontVariationSettings: item.active ? '"FILL" 1' : undefined }}
                    >
                      {item.icon}
                    </span>
                  </div>
                  <span className="min-w-0 flex-1">
                    <span
                      className={`block truncate text-[13px] font-semibold leading-tight ${
                        item.active ? 'text-white' : 'text-white/68'
                      }`}
                    >
                      {item.label}
                    </span>
                    {item.subtitle ? (
                      <span className="mt-0.5 block truncate text-[10px] leading-snug text-white/44">
                        {item.subtitle}
                      </span>
                    ) : null}
                  </span>
                </button>
              ))}
            </nav>

            <div className="mt-auto space-y-2 border-t border-white/[0.05] pt-3">
              <button
                type="button"
                onClick={() => {
                  const next = !adminToggleOn
                  setAdminToggleOn(next)
                  setTimeout(() => navigate(next ? '/settings' : '/data'), 160)
                }}
                aria-pressed={adminToggleOn}
                className="apple-widget-card relative mt-1 flex h-11 w-[132px] items-center overflow-hidden rounded-full p-1 text-left"
              >
                <span
                  className={`absolute left-1 top-1/2 flex h-9 w-9 -translate-y-1/2 items-center justify-center rounded-full text-white transition-[transform,background-color,box-shadow] duration-300 ease-out ${
                    adminToggleOn
                      ? 'translate-x-[78px] bg-sky-500/35 shadow-[0_0_20px_rgba(56,189,248,0.35)]'
                      : 'translate-x-0 bg-white/[0.13]'
                  }`}
                >
                  <span className="material-symbols-outlined text-[1.1rem]">person</span>
                </span>
                <span
                  className={`pointer-events-none pl-11 text-[12px] font-semibold transition-all duration-300 ${
                    adminToggleOn ? 'translate-x-1 text-white/94' : 'translate-x-0 text-white/78'
                  }`}
                >
                  관리자
                </span>
              </button>
            </div>
          </aside>

          {/* ── 우측 전체: 상단 바 + (중앙 | 위젯) ── */}
          <div className="relative flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-transparent">
            {/* 대시보드 상단 바 */}
            <div
              className="flex shrink-0 items-center justify-between gap-3 border-b border-white/[0.05] px-3 py-2.5 sm:px-5"
              style={{ WebkitAppRegion: 'no-drag' }}
            >
              <div className="flex min-w-0 flex-1 items-center gap-2 overflow-x-auto text-[12px] text-white/58 sm:text-[13px]">
                {breadcrumb}
              </div>
              <div className="flex shrink-0 items-center gap-1.5 sm:gap-2">
                <button
                  type="button"
                  className="flex h-9 w-9 items-center justify-center rounded-full bg-white/[0.07] text-white/45 ring-1 ring-inset ring-white/[0.08] transition hover:bg-white/[0.11] hover:text-white/75"
                  aria-label="검색"
                >
                  <span className="material-symbols-outlined text-[1.15rem]">search</span>
                </button>
                <button
                  type="button"
                  className="flex h-9 w-9 items-center justify-center rounded-full bg-white/[0.07] text-white/45 ring-1 ring-inset ring-white/[0.08] transition hover:bg-white/[0.11] hover:text-white/75"
                  aria-label="알림"
                >
                  <span className="material-symbols-outlined text-[1.15rem]">notifications</span>
                </button>
                {toolbarRight}
              </div>
            </div>

            <div className="flex min-h-0 min-w-0 flex-1 gap-3 overflow-hidden px-3 pb-3 pt-2 sm:gap-4 sm:px-5 sm:pb-4 sm:pt-3">
              {/* 중앙 넓은 열 */}
              <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
                <section className="apple-hero-card mb-3 shrink-0 rounded-[18px] p-4 sm:mb-4 sm:rounded-[22px] sm:p-6">
                  {hero}
                </section>

                {actionBar ? (
                  <div className="mb-3 flex min-h-0 shrink-0 flex-wrap items-center gap-2 sm:mb-4 sm:gap-2.5">
                    {actionBar}
                  </div>
                ) : null}

                {listSectionTitle ? (
                  <div className="mb-2 flex shrink-0 items-center justify-between gap-2 px-0.5">
                    <h3 className="text-[15px] font-semibold tracking-tight text-white/90 sm:text-[16px]">
                      {listSectionTitle}
                    </h3>
                  </div>
                ) : null}

                <div className="relative flex min-h-0 flex-1 flex-col overflow-hidden rounded-[18px] border border-white/[0.055] bg-white/[0.004] shadow-[inset_0_1px_0_rgba(255,255,255,0.04)] backdrop-blur-[72px] backdrop-saturate-105 sm:rounded-[20px]">
                  <div className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden">{children}</div>
                  {floatingFooter ? (
                    <div className="shrink-0 border-t border-white/[0.045] bg-gradient-to-t from-black/14 to-transparent px-3 py-2.5 backdrop-blur-md">
                      {floatingFooter}
                    </div>
                  ) : null}
                </div>
              </div>

              {/* 우 위젯 열 */}
              {rightWidgets ? (
                <aside className="apple-studio-widgets hidden w-[min(280px,28%)] shrink-0 flex-col gap-3 overflow-y-auto pt-0.5 lg:flex">
                  {rightWidgets}
                </aside>
              ) : null}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
