/**
 * PageSidebar — 정적 페이지(Settings, DataIndexing)의 공통 사이드바 Shell.
 * SearchSidebar 와 동일한 시각 스타일(rounded-r-3xl, 블러, 그림자)을 공유한다.
 *
 * Props:
 *   subtitle   {string}    로고 아래 소제목 (예: "데이터 인덱싱")
 *   children               nav 영역에 렌더링할 버튼들
 *   footerExtra            profile 위에 삽입할 추가 영역 (optional)
 *   footerSub  {node}      프로필 아래 두 번째 줄 (기본: "심층 분석 접근 권한")
 */
import { useNavigate } from 'react-router-dom'
import TeamLogoMark from './TeamLogoMark'

export default function PageSidebar({ subtitle, children, footerExtra, footerSub }) {
  const navigate = useNavigate()

  return (
    <aside className="w-64 shrink-0 h-screen bg-[#070d1f]/60 backdrop-blur-xl flex flex-col pt-10 pb-4 border-r border-[#41475b]/15 rounded-r-3xl shadow-[20px_0_40px_rgba(133,173,255,0.05)] z-50">

      {/* ── 로고 헤더 ── */}
      <div className="px-4 mb-8 flex items-center gap-3">
        <button
          onClick={() => navigate('/search')}
          className="flex items-center gap-3 hover:opacity-80 transition-opacity text-left"
        >
          <TeamLogoMark />
          <div>
            <h1 className="text-xl font-black text-[#dfe4fe] leading-none">DB_insight</h1>
            <p className="text-base uppercase tracking-widest text-[#a5aac2] mt-1">{subtitle}</p>
          </div>
        </button>
      </div>

      {/* ── 내비게이션 (슬롯) ── */}
      <nav className="flex-1 px-3 space-y-1 overflow-y-auto">
        {children}
      </nav>

      {/* ── 선택 배지 등 추가 영역 (optional) ── */}
      {footerExtra}

      {/* ── 프로필 푸터 ── */}
      <div className="px-4 mt-auto pt-4 border-t border-outline-variant/10 flex items-center gap-3">
        <div className="w-10 h-10 rounded-full bg-surface-container-highest flex items-center justify-center shrink-0">
          <span className="material-symbols-outlined text-primary">account_circle</span>
        </div>
        <div className="overflow-hidden">
          <p className="text-base font-bold text-on-surface truncate">관리자</p>
          {footerSub ?? (
            <p className="text-base text-on-surface-variant">심층 분석 접근 권한</p>
          )}
        </div>
      </div>
    </aside>
  )
}
