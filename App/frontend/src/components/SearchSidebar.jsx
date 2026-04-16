import { useNavigate, useLocation } from 'react-router-dom'

export default function SearchSidebar() {
  const navigate = useNavigate()
  const location = useLocation()

  return (
    <aside className="fixed left-0 top-0 h-full w-64 rounded-r-3xl flex flex-col p-4 bg-[#070d1f]/60 backdrop-blur-xl border-r border-[#41475b]/15 shadow-[20px_0_40px_rgba(133,173,255,0.05)] z-50">
      {/* Logo */}
      <div className="mb-10 flex items-center gap-3 px-2">
        <div className="w-8 h-8 bg-gradient-to-br from-primary to-secondary rounded-lg flex items-center justify-center">
          <span className="material-symbols-outlined text-on-primary-fixed text-lg" style={{ fontVariationSettings: '"FILL" 1' }}>dataset</span>
        </div>
        <div>
          <h1 className="text-xl font-black text-[#dfe4fe] leading-none">DB_insight</h1>
          <p className="text-[0.65rem] uppercase tracking-widest text-on-surface-variant mt-1">Local Intelligence</p>
        </div>
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
          <span className="font-manrope uppercase tracking-[0.05em] text-[0.7rem]">Settings</span>
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
          <span className="font-manrope uppercase tracking-[0.05em] text-[0.7rem]">Data</span>
        </button>
      </div>

      {/* Nav items */}
      <div className="flex-1 overflow-y-auto space-y-1">
        <div className="px-4 py-2">
          <p className="font-manrope uppercase tracking-[0.05em] text-[0.75rem] text-primary mb-4">Search History</p>
        </div>
        <button
          onClick={() => navigate('/search')}
          className={`w-full flex items-center gap-3 rounded-xl px-4 py-3 active:translate-x-1 duration-200 ${
            location.pathname === '/search' ? 'text-primary bg-[#1c253e]' : 'text-[#a5aac2] hover:bg-[#1c253e]/50 hover:text-[#dfe4fe]'
          }`}
        >
          <span className="material-symbols-outlined">history</span>
          <span className="font-manrope uppercase tracking-[0.05em] text-[0.75rem]">Search History</span>
        </button>
        <button className="w-full flex items-center gap-3 text-[#a5aac2] px-4 py-3 hover:bg-[#1c253e]/50 hover:text-[#dfe4fe] transition-all active:translate-x-1 duration-200">
          <span className="material-symbols-outlined">search_check</span>
          <span className="font-manrope uppercase tracking-[0.05em] text-[0.75rem]">Recent Queries</span>
        </button>

        {/* Recent queries */}
        <div className="mt-8 px-4 space-y-4">
          <p className="font-manrope uppercase tracking-[0.05em] text-[0.7rem] text-on-surface-variant/60">Recents</p>
          <div className="space-y-3">
            {['Project alpha documentation...', 'Revenue charts Q3 2023', 'Meeting notes encrypted'].map((item, i) => (
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
          <p className="text-sm font-bold text-on-surface truncate">Admin User</p>
          <p className="text-[0.65rem] text-on-surface-variant">Deep Insight Access</p>
        </div>
      </div>
    </aside>
  )
}
