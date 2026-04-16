import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import SearchSidebar from '../components/SearchSidebar'

export default function MainSearchMode() {
  const navigate = useNavigate()
  const [query, setQuery] = useState('')

  const handleSearch = (e) => {
    e.preventDefault()
    if (query.trim()) {
      navigate('/search/results', { state: { query } })
    }
  }

  return (
    <div className="overflow-hidden h-screen grid-bg">
      <SearchSidebar />

      {/* Top nav */}
      <nav className="fixed top-0 w-full flex justify-between items-center px-6 py-4 bg-transparent z-40">
        <div className="ml-64"></div>
        <div className="flex items-center gap-6">
          <div className="hidden md:flex gap-8 items-center">
            <button className="font-manrope tracking-tight text-sm text-[#85adff] font-bold hover:text-[#85adff] transition-colors active:scale-95 duration-200">Explore</button>
            <button className="font-manrope tracking-tight text-sm text-[#a5aac2] hover:text-[#85adff] transition-colors active:scale-95 duration-200">Intelligence</button>
            <button className="font-manrope tracking-tight text-sm text-[#a5aac2] hover:text-[#85adff] transition-colors active:scale-95 duration-200">Cloud Sync</button>
          </div>
          <div className="w-8 h-8 rounded-full bg-surface-variant flex items-center justify-center cursor-pointer hover:bg-surface-container-highest transition-colors">
            <span className="material-symbols-outlined text-primary text-xl">account_circle</span>
          </div>
        </div>
      </nav>

      {/* Main content */}
      <main className="ml-64 h-full flex flex-col items-center justify-center p-8 relative">
        <div className="absolute top-1/4 left-1/4 w-96 h-96 bg-primary/10 rounded-full blur-[120px] pointer-events-none"></div>
        <div className="absolute bottom-1/4 right-1/4 w-[500px] h-[500px] bg-secondary/5 rounded-full blur-[150px] pointer-events-none"></div>

        <div className="w-full max-w-4xl flex flex-col items-center z-10">
          <div className="mb-12 text-center">
            <h2 className="text-5xl md:text-6xl font-black tracking-tighter text-on-surface mb-4">
              Local Intelligence<span className="text-primary">.</span>
            </h2>
            <p className="text-on-surface-variant text-lg max-w-xl mx-auto font-light">
              Your files, indexed and understood by your personal neural engine.
            </p>
          </div>

          {/* Search bar */}
          <form onSubmit={handleSearch} className="w-full relative group">
            <div className="glass-effect rounded-full p-2 border border-outline-variant/20 shadow-[0_0_50px_rgba(133,173,255,0.1)] flex items-center gap-4 hover:border-primary/40 transition-all duration-300">
              <button
                type="button"
                className="w-12 h-12 rounded-full bg-gradient-to-r from-primary to-secondary flex items-center justify-center text-on-primary-fixed shadow-lg active:scale-90 transition-transform"
              >
                <span className="material-symbols-outlined font-bold">add</span>
              </button>
              <input
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Ask anything about your local files..."
                className="flex-1 bg-transparent border-none focus:ring-0 text-on-surface placeholder:text-on-surface-variant/40 font-manrope text-lg py-4 outline-none"
              />
              <button type="button" className="w-12 h-12 rounded-full flex items-center justify-center text-on-surface-variant hover:text-primary hover:bg-primary/10 transition-all duration-200">
                <span className="material-symbols-outlined">mic</span>
              </button>
            </div>

            {/* AI mode button */}
            <div className="mt-10 flex justify-center">
              <button
                type="button"
                onClick={() => navigate('/ai')}
                className="px-8 py-3 rounded-full bg-surface-container-high border border-outline-variant/20 flex items-center gap-3 text-sm font-bold tracking-widest uppercase text-on-surface-variant hover:text-on-surface hover:bg-surface-container-highest transition-all duration-300 group glow-primary"
              >
                <span className="w-2 h-2 rounded-full bg-primary animate-pulse"></span>
                Go to AI Mode
                <span className="material-symbols-outlined text-lg group-hover:translate-x-1 transition-transform">arrow_forward</span>
              </button>
            </div>
          </form>

          {/* Quick action cards */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mt-24 w-full">
            {[
              { icon: 'summarize', color: 'text-primary', title: 'Summarize PDF', sub: 'Neural Processing' },
              { icon: 'search_insights', color: 'text-secondary', title: 'Deep Metadata', sub: 'Attribute Analysis' },
              { icon: 'auto_awesome', color: 'text-primary', title: 'Visual Search', sub: 'Vision Engine' },
            ].map((card) => (
              <div key={card.title} className="glass-effect p-6 rounded-xl border border-outline-variant/15 hover:border-primary/20 transition-all group cursor-pointer">
                <span className={`material-symbols-outlined ${card.color} mb-4 block`}>{card.icon}</span>
                <h3 className="text-on-surface font-bold mb-1">{card.title}</h3>
                <p className="text-on-surface-variant text-xs uppercase tracking-tighter">{card.sub}</p>
              </div>
            ))}
          </div>
        </div>

        <div className="absolute bottom-0 left-0 w-full h-32 bg-gradient-to-t from-surface-container-low/80 to-transparent pointer-events-none"></div>
      </main>

      <div className="fixed top-0 right-0 w-1/3 h-screen bg-gradient-to-l from-primary/5 to-transparent pointer-events-none"></div>
    </div>
  )
}
