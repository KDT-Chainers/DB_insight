import { useNavigate, useLocation } from 'react-router-dom'

export default function AISidebar() {
  const navigate = useNavigate()
  const location = useLocation()

  const navItems = [
    { label: 'Neural Search', icon: 'search', path: '/ai' },
    { label: 'File Vault', icon: 'folder_open', path: null },
    { label: 'Processing', icon: 'memory', path: null },
    { label: 'History', icon: 'history', path: null },
    { label: 'Analytics', icon: 'insights', path: null },
  ]

  return (
    <aside className="fixed left-0 top-0 h-full w-64 z-40 bg-[#000000] shadow-[10px_0_40px_rgba(172,138,255,0.05)] border-r border-outline-variant/10">
      <div className="flex flex-col h-full py-8">
        <div className="px-6 mb-10">
          <div className="flex items-center gap-3 mb-2">
            <div className="w-2 h-2 rounded-full bg-violet-400 animate-pulse"></div>
            <span className="text-lg font-black text-violet-400">Core Terminal</span>
          </div>
          <p className="text-[10px] uppercase tracking-[0.2em] text-violet-400/60 font-bold">AI Mode Active</p>
        </div>

        <nav className="flex-1 space-y-1">
          {navItems.map((item) => {
            const isActive = item.path && location.pathname === item.path
            return (
              <button
                key={item.label}
                onClick={() => item.path && navigate(item.path)}
                className={`w-full flex items-center gap-3 px-6 py-4 font-manrope text-sm font-medium uppercase tracking-widest group transition-all ${
                  isActive
                    ? 'bg-gradient-to-r from-violet-900/40 to-transparent text-violet-200 border-l-4 border-violet-500'
                    : 'text-slate-500 hover:bg-violet-900/20 hover:text-violet-300'
                }`}
              >
                <span className={`material-symbols-outlined ${isActive ? 'text-violet-400' : ''}`}>{item.icon}</span>
                <span className="group-hover:translate-x-1 duration-300">{item.label}</span>
              </button>
            )
          })}
        </nav>

        <div className="px-6 mt-auto pt-8">
          <button className="w-full py-3 px-4 rounded-xl bg-gradient-to-r from-secondary-container to-secondary text-on-secondary font-bold text-xs tracking-widest uppercase hover:opacity-90 active:scale-95 transition-all glow-violet">
            Initialize Sync
          </button>
          <div className="mt-8 space-y-4">
            <button className="flex items-center gap-3 text-slate-500 hover:text-violet-300 transition-all text-xs tracking-widest uppercase font-bold w-full">
              <span className="material-symbols-outlined text-sm">help</span>
              Support
            </button>
            <button
              onClick={() => navigate('/settings')}
              className="flex items-center gap-3 text-slate-500 hover:text-violet-300 transition-all text-xs tracking-widest uppercase font-bold w-full"
            >
              <span className="material-symbols-outlined text-sm">sensors</span>
              Status
            </button>
          </div>
        </div>
      </div>
    </aside>
  )
}
