import { useNavigate, useLocation } from 'react-router-dom'
import AISidebar from '../components/AISidebar'

const BAR_HEIGHTS = ['60%', '45%', '85%', '30%', '70%', '55%', '95%', '40%']

export default function MainAIModeResultSpecific() {
  const navigate = useNavigate()
  const location = useLocation()
  const result = location.state?.result || { title: 'DB_insight.bin', tag: 'DATAPACK' }

  return (
    <div className="bg-surface text-on-surface overflow-x-hidden min-h-screen">
      <AISidebar />

      {/* Top nav */}
      <header className="fixed top-0 w-full z-50 bg-[#070d1f]/60 backdrop-blur-xl flex justify-between items-center px-8 h-16 shadow-[0_4px_30px_rgba(172,138,255,0.1)]">
        <div className="flex items-center gap-8">
          <span className="text-xl font-bold tracking-tighter bg-gradient-to-r from-violet-400 to-fuchsia-400 bg-clip-text text-transparent">Obsidian Intelligence</span>
          <nav className="hidden md:flex gap-6 items-center">
            <button className="font-manrope tracking-tight text-slate-400 hover:text-slate-200 transition-colors">Models</button>
            <button className="font-manrope tracking-tight text-violet-300 border-b-2 border-violet-500 pb-1">Datasets</button>
            <button className="font-manrope tracking-tight text-slate-400 hover:text-slate-200 transition-colors">Neural Logs</button>
          </nav>
        </div>
        <div className="flex items-center gap-4">
          <button onClick={() => navigate('/settings')} className="material-symbols-outlined text-slate-400 cursor-pointer hover:text-violet-400 transition-all">settings</button>
        </div>
        <div className="absolute bottom-0 left-0 w-full bg-gradient-to-b from-violet-500/10 to-transparent h-[1px]"></div>
      </header>

      {/* Main */}
      <main className="ml-64 pt-24 pb-12 px-10 min-h-screen">
        {/* Breadcrumbs */}
        <div className="mb-8 flex justify-between items-end">
          <div>
            <nav className="flex items-center gap-2 text-on-surface-variant text-xs font-label uppercase tracking-widest mb-4">
              <button onClick={() => navigate('/ai/results')} className="hover:text-secondary cursor-pointer">Datasets</button>
              <span className="material-symbols-outlined text-[14px]">chevron_right</span>
              <span className="hover:text-secondary cursor-pointer">Neural Assets</span>
              <span className="material-symbols-outlined text-[14px]">chevron_right</span>
              <span className="text-secondary">DB_insight</span>
            </nav>
            <h1 className="text-4xl font-extrabold tracking-tighter text-on-surface mb-2">File Details - AI Mode</h1>
            <p className="text-on-surface-variant max-w-2xl">
              Visualizing high-density cognitive data structures for object{' '}
              <span className="text-secondary font-semibold">{result.title || 'DB_insight.bin'}</span>.
            </p>
          </div>
          <div className="flex gap-4">
            <button className="flex items-center gap-2 px-6 py-3 bg-surface-container-high border border-outline-variant rounded-full font-bold text-sm text-on-surface hover:bg-surface-container-highest transition-all">
              <span className="material-symbols-outlined text-[18px]">download</span>EXFILTRATE
            </button>
            <button className="flex items-center gap-2 px-8 py-3 bg-gradient-to-r from-secondary to-primary rounded-full font-extrabold text-sm text-on-primary active:scale-95 transition-all shadow-[0_0_20px_rgba(172,138,255,0.4)]">
              <span className="material-symbols-outlined text-[18px]" style={{ fontVariationSettings: '"FILL" 1' }}>bolt</span>RE-PROCESS
            </button>
          </div>
        </div>

        {/* Grid */}
        <div className="grid grid-cols-12 gap-6">
          {/* Left column */}
          <div className="col-span-8 space-y-6">
            {/* Visualizer */}
            <div className="bg-surface-container-low rounded-[1.5rem] p-1 overflow-hidden relative group">
              <div className="absolute inset-0 bg-gradient-to-br from-secondary/10 via-transparent to-primary/5 opacity-50"></div>
              <div className="relative bg-surface rounded-[1.4rem] p-8 min-h-[400px] flex flex-col">
                <div className="flex justify-between items-start mb-12">
                  <div>
                    <span className="text-[10px] font-label uppercase tracking-[0.2em] text-secondary mb-1 block">NEURAL TOPOGRAPHY</span>
                    <h3 className="text-xl font-bold">Latency Heatmap</h3>
                  </div>
                  <div className="flex gap-2">
                    <span className="w-3 h-3 rounded-full bg-secondary" style={{ boxShadow: '0 0 15px rgba(172,138,255,0.4)' }}></span>
                    <span className="w-3 h-3 rounded-full bg-primary/40"></span>
                    <span className="w-3 h-3 rounded-full bg-outline-variant"></span>
                  </div>
                </div>
                <div className="flex-1 flex items-center justify-center relative">
                  <div className="relative z-10 w-full h-48 flex items-end justify-between gap-2">
                    {BAR_HEIGHTS.map((h, i) => (
                      <div key={i} className="w-full bg-surface-container-highest rounded-t-lg relative transition-all duration-500" style={{ height: h }}>
                        <div className={`absolute bottom-0 w-full bg-gradient-to-t ${i % 3 === 2 ? 'from-primary' : 'from-secondary'} to-transparent h-full rounded-t-lg opacity-${30 + i * 5}`}></div>
                      </div>
                    ))}
                  </div>
                  <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-64 h-64 bg-secondary/10 blur-[100px] rounded-full pointer-events-none"></div>
                </div>
                <div className="mt-12 flex items-center justify-between border-t border-outline-variant pt-6">
                  <div className="flex gap-8">
                    {[['Stability', '99.98%', ''], ['Entropy', 'Low', 'text-secondary'], ['Cycles', '4.2k', '']].map(([label, val, cls]) => (
                      <div key={label}>
                        <p className="text-[10px] font-label uppercase tracking-widest text-on-surface-variant mb-1">{label}</p>
                        <p className={`text-xl font-bold ${cls}`}>{val}</p>
                      </div>
                    ))}
                  </div>
                  <div className="flex gap-2">
                    <button className="p-2 rounded-lg bg-surface-container-high text-on-surface-variant hover:text-secondary transition-all"><span className="material-symbols-outlined">zoom_in</span></button>
                    <button className="p-2 rounded-lg bg-surface-container-high text-on-surface-variant hover:text-secondary transition-all"><span className="material-symbols-outlined">fullscreen</span></button>
                  </div>
                </div>
              </div>
            </div>

            {/* Metadata table */}
            <div className="bg-surface-container-low rounded-[1.5rem] p-8 border border-outline-variant/10">
              <div className="flex justify-between items-center mb-8">
                <h3 className="text-lg font-bold flex items-center gap-2">
                  <span className="material-symbols-outlined text-secondary">database</span>Neural Metadata Extract
                </h3>
                <button className="text-secondary text-xs font-label uppercase tracking-widest hover:underline">Export JSON</button>
              </div>
              <div className="space-y-4">
                {[
                  ['Cognitive Node', 'node_alpha_x99283', 'SECURE', 'text-secondary'],
                  ['Hash Sequence', '0x77ae...bb91', 'VERIFIED', 'text-secondary'],
                  ['Origin Cluster', 'Euclidean-North-Grid', 'REMOTE', 'text-on-surface-variant'],
                  ['Last Pulse', '2024-05-18T14:22:01.002Z', 'SYNCED', 'text-primary'],
                ].map(([label, val, status, cls]) => (
                  <div key={label} className="grid grid-cols-4 gap-4 p-4 rounded-xl hover:bg-surface-container-high transition-all border-b border-outline-variant/10 last:border-0">
                    <span className="text-xs font-label uppercase tracking-widest text-on-surface-variant">{label}</span>
                    <span className="text-xs font-medium text-on-surface col-span-2 font-mono">{val}</span>
                    <span className={`text-right text-[10px] font-bold ${cls}`}>{status}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Right column */}
          <div className="col-span-4 space-y-6">
            {/* AI summary */}
            <div className="glass-panel rounded-[1.5rem] p-8 border border-secondary/20 relative overflow-hidden" style={{ boxShadow: '0 0 20px rgba(172,138,255,0.15)' }}>
              <div className="absolute -right-10 -top-10 w-32 h-32 bg-secondary/20 blur-[60px] rounded-full"></div>
              <div className="flex items-center gap-3 mb-6">
                <div className="w-10 h-10 rounded-full bg-secondary-container flex items-center justify-center" style={{ boxShadow: '0 0 20px rgba(172,138,255,0.15)' }}>
                  <span className="material-symbols-outlined text-secondary" style={{ fontVariationSettings: '"FILL" 1' }}>auto_awesome</span>
                </div>
                <div>
                  <h4 className="font-bold text-on-surface">Neural Summary</h4>
                  <p className="text-[10px] text-secondary uppercase font-label tracking-widest">AI Generated Insight</p>
                </div>
              </div>
              <p className="text-sm leading-relaxed text-on-surface-variant mb-6 italic">
                "The object DB_insight contains multi-layered vector embeddings with high correlation to 'Predictive Logistics' clusters. Processing reveals a 12% increase in efficiency potential if integrated with Node Alpha."
              </p>
              <div className="p-4 rounded-xl bg-surface-container-lowest/50 border border-outline-variant/20">
                <h5 className="text-[10px] font-label uppercase tracking-widest text-secondary mb-3">Suggested Protocol</h5>
                {['Vector Quantization', 'Layer Normalization'].map((item) => (
                  <div key={item} className="flex items-center gap-3 mb-2">
                    <span className="material-symbols-outlined text-primary text-sm">check_circle</span>
                    <span className="text-xs text-on-surface">{item}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Access panel */}
            <div className="bg-surface-container-low rounded-[1.5rem] p-8 border border-outline-variant/10">
              <h4 className="text-xs font-label uppercase tracking-widest text-on-surface-variant mb-6">Access Hierarchy</h4>
              {[
                { icon: 'person', label: 'Lead Architect', badge: 'RW-X' },
                { icon: 'shield', label: 'System Admin', badge: 'OWNER' },
                { icon: 'groups', label: 'Analyst Team', badge: 'READ', dim: true },
              ].map((item) => (
                <div key={item.label} className={`flex items-center justify-between mb-4 ${item.dim ? 'opacity-50' : ''}`}>
                  <div className="flex items-center gap-3">
                    <div className="w-8 h-8 rounded-lg bg-surface-container-highest flex items-center justify-center">
                      <span className="material-symbols-outlined text-sm">{item.icon}</span>
                    </div>
                    <span className="text-sm">{item.label}</span>
                  </div>
                  <span className="text-[10px] px-2 py-1 rounded bg-secondary/10 text-secondary border border-secondary/20 font-bold uppercase tracking-widest">{item.badge}</span>
                </div>
              ))}
              <button className="w-full mt-6 py-3 border border-outline-variant/20 rounded-xl text-xs font-label uppercase tracking-widest hover:border-secondary hover:text-secondary transition-all">
                Manage Access
              </button>
            </div>

            {/* Timeline */}
            <div className="bg-surface-container-low rounded-[1.5rem] p-8 border border-outline-variant/10">
              <h4 className="text-xs font-label uppercase tracking-widest text-on-surface-variant mb-6">Temporal Logs</h4>
              <div className="relative pl-6 space-y-6 before:content-[''] before:absolute before:left-[3px] before:top-2 before:bottom-2 before:w-[2px] before:bg-outline-variant/30">
                {[
                  { title: 'Neural Optimization', time: '2h ago by System AI', active: true },
                  { title: 'Dataset Merged', time: '14h ago by Architect_A', active: false },
                  { title: 'Object Initialized', time: '2d ago by Root', active: false },
                ].map((item, i) => (
                  <div key={i} className={`relative ${i > 0 ? `opacity-${i === 1 ? '70' : '50'}` : ''}`}>
                    <div className={`absolute -left-[27px] top-1 w-2 h-2 rounded-full ${item.active ? 'bg-secondary' : 'bg-outline-variant'}`} style={item.active ? { boxShadow: '0 0 15px rgba(172,138,255,0.4)' } : {}}></div>
                    <p className="text-xs font-bold text-on-surface">{item.title}</p>
                    <p className="text-[10px] text-on-surface-variant">{item.time}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </main>

      <div className="fixed bottom-0 left-64 right-0 h-1 bg-gradient-to-r from-transparent via-secondary/20 to-transparent"></div>
    </div>
  )
}
