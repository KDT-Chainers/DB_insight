import { useNavigate, useLocation } from 'react-router-dom'
import AISidebar from '../components/AISidebar'

const AI_RESULTS = [
  {
    id: '1',
    tag: 'DATAPACK_772',
    title: 'Quantum Memory Allocation',
    desc: 'Structural analysis of distributed memory nodes across the fuchsia quadrant. High redundancy detected in sector 9.',
    modified: '2h ago',
    img: 'https://lh3.googleusercontent.com/aida-public/AB6AXuBiusmUQ-dF9m6N2dat_eOi8PeAoliSDsbJq4jNjPUMeLdXktUuZ0dHPASMIqM6HxhOFd_BRotNPPM6fK9p-x5FPhrSJnCnR7zxeBt-3NQMG1LK8RWuj3Q2N_XJXFJcQcNIcCpmZrMUB1BkVkXnIYeipnjBZkJfeYwHyIQcQC064JM4zpL5IVLiQEzGmp8JHFb4G2I8EKZAnkfPT1R_WDK_WmT290fPuMpL6yQ0FeI38nkMQ2cxf8FvKKbnJKTS75oONti5_kSDnsRs',
  },
  {
    id: '2',
    tag: 'LOG_STREAM',
    title: 'Cognitive Load Distribution',
    desc: 'Real-time balancing of heuristic weights in active thinking cycles. Optimization protocol initiated.',
    modified: 'Active',
    img: 'https://lh3.googleusercontent.com/aida-public/AB6AXuDSfkJz1BrXhj8JKwbl2czpkysEDmYSvRLX2WptNVJq5GJscS_bMt0Yw0409-4Mz39isL0K_hQ8FdKu5lqkvABJ8n0vJHnxybkP8aHVBwk42jjs9TxiSkwRM5gmboyIByUnkBup1-2dfsuTIA2ZL_U1UW1oUgTyhfO9XnDgBvSbCDE4_wPvHvzmY6pcCN5UCVYvdxM_xBYnyJlEGKcxDuMKDjNexPXPd4pe3wHFrDnUjk-UKfmY889GTbwLU_SFHcsBdwqZzG8nKGRr',
  },
  {
    id: '3',
    tag: 'VAULT_ARCHIVE',
    title: 'Crystalline Knowledge Base',
    desc: 'Deep-storage retrieval of historical training sets. Integrity verified through multi-pass hash check.',
    modified: '4.2 PB',
    img: 'https://lh3.googleusercontent.com/aida-public/AB6AXuBXIIVVDVBdpsRK-VyjwcBDfX5m0q1aGVB7lNkqsmY3dnaihm7xe0kRv0F5SB93RYrEFiaVKDroBKUb0yqjB14Q3hUTiu_9wYEmnleWOuLQgAic_0PcIER1IlnGP2ap7aQAAAnTRu7-AujKhHzk5MJQmkbfFPbVlZfq7edimXxeOIbqjUX22lvKQ8LbHkTBm_mOcQeleA8WE2d-S1rVKWTZYJFPQt29wNzi9wc-qgwniGitShIKul7FnudpG4SUfJyEO8K5OwYnH2E6',
  },
]

export default function MainAIModeResult() {
  const navigate = useNavigate()
  const location = useLocation()

  return (
    <div className="bg-surface text-on-surface selection:bg-secondary/30">
      <AISidebar />

      {/* Top nav */}
      <header className="fixed top-0 w-full z-50 bg-[#070d1f]/60 backdrop-blur-xl shadow-[0_4px_30px_rgba(172,138,255,0.1)]">
        <div className="flex justify-between items-center px-8 h-16 w-full font-manrope tracking-tight">
          <div className="flex items-center gap-8">
            <span className="text-xl font-bold tracking-tighter bg-gradient-to-r from-violet-400 to-fuchsia-400 bg-clip-text text-transparent">Obsidian Intelligence</span>
            <div className="hidden md:flex items-center gap-6">
              {['Models', 'Datasets', 'Neural Logs'].map((item) => (
                <button key={item} className="text-slate-400 hover:text-slate-200 transition-colors">{item}</button>
              ))}
            </div>
          </div>
          <div className="flex items-center gap-4">
            <div className="relative group">
              <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-violet-400/50">search</span>
              <input className="bg-white/5 border-none rounded-full pl-10 pr-4 py-1.5 text-sm w-64 focus:ring-1 focus:ring-violet-500/50 transition-all outline-none" placeholder="Neural Search..." />
            </div>
            <button onClick={() => navigate('/settings')} className="p-2 text-slate-400 hover:bg-white/5 rounded-full transition-all">
              <span className="material-symbols-outlined">settings</span>
            </button>
          </div>
        </div>
        <div className="bg-gradient-to-b from-violet-500/10 to-transparent h-[1px]"></div>
      </header>

      {/* Main */}
      <main className="pl-64 pt-16 min-h-screen">
        <div className="p-10 max-w-7xl mx-auto">
          {/* Header */}
          <div className="mb-12 relative">
            <div className="absolute -top-20 -left-20 w-96 h-96 bg-secondary/10 blur-[100px] rounded-full"></div>
            <div className="relative z-10">
              <span className="text-secondary text-xs font-bold tracking-[0.3em] uppercase mb-4 block">Refined Intelligence Output</span>
              <h1 className="text-5xl font-extrabold tracking-tighter text-on-surface mb-4">Neural Search Results</h1>
              <div className="flex items-center gap-4 text-on-surface-variant">
                <span className="flex items-center gap-2 px-3 py-1 bg-surface-container-high rounded-full border border-outline-variant/20 text-sm">
                  <span className="w-1.5 h-1.5 rounded-full bg-secondary"></span>342 Matches Found
                </span>
                <span className="text-sm">Processed in 124ms</span>
              </div>
            </div>
          </div>

          {/* Bento grid */}
          <div className="grid grid-cols-12 gap-6">
            {/* AI synthesis card */}
            <div className="col-span-12 lg:col-span-8 bg-surface-variant/60 backdrop-blur-2xl rounded-xl p-8 border border-secondary/20 relative overflow-hidden group">
              <div className="absolute top-0 right-0 p-4">
                <span className="material-symbols-outlined text-secondary opacity-50 text-4xl" style={{ fontVariationSettings: '"FILL" 1' }}>auto_awesome</span>
              </div>
              <div className="relative z-10">
                <h3 className="text-secondary text-xs font-black tracking-widest uppercase mb-6">AI Contextual Synthesis</h3>
                <p className="text-2xl font-light text-on-surface leading-relaxed mb-8">
                  Based on your recent <span className="text-secondary font-medium">Neural Logs</span> and the refinement of{' '}
                  <span className="text-secondary font-medium">Processing Nodes</span>, the system has identified a strong correlation between the selected datasets
                  and your current trajectory in "Predictive Analytics Phase 4".
                </p>
                <div className="flex gap-3">
                  <button className="bg-secondary text-on-secondary px-6 py-2.5 rounded-full font-bold text-sm tracking-tight active:scale-95 transition-all">Expand Synthesis</button>
                  <button className="bg-surface-container-highest text-on-surface px-6 py-2.5 rounded-full font-bold text-sm tracking-tight border border-outline-variant/30 hover:bg-surface-bright transition-all">Audit Logic</button>
                </div>
              </div>
            </div>

            {/* Model stats */}
            <div className="col-span-12 lg:col-span-4 bg-surface-container-high rounded-xl p-6 border border-outline-variant/10 flex flex-col justify-between">
              <div>
                <h4 className="text-on-surface-variant text-[10px] font-black tracking-[0.2em] uppercase mb-6">Model Integrity</h4>
                <div className="space-y-6">
                  {[['Coherence Level', '98.4%', 'w-[98%]'], ['Latency Shift', '-12ms', 'w-[75%]']].map(([label, val, w]) => (
                    <div key={label}>
                      <div className="flex justify-between text-xs mb-2">
                        <span className="text-on-surface/80">{label}</span>
                        <span className="text-secondary">{val}</span>
                      </div>
                      <div className="h-1.5 w-full bg-surface-container-highest rounded-full overflow-hidden">
                        <div className={`h-full bg-secondary ${w} shadow-[0_0_10px_rgba(172,138,255,0.5)]`}></div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
              <div className="mt-8 pt-6 border-t border-outline-variant/10">
                <div className="flex items-center gap-3">
                  <div className="p-2 bg-secondary/10 rounded-lg">
                    <span className="material-symbols-outlined text-secondary" style={{ fontVariationSettings: '"FILL" 1' }}>bolt</span>
                  </div>
                  <div>
                    <p className="text-xs font-bold text-on-surface">Obsidian-v4.2</p>
                    <p className="text-[10px] text-on-surface-variant">LATEST REFINEMENT</p>
                  </div>
                </div>
              </div>
            </div>

            {/* Result cards */}
            {AI_RESULTS.map((r) => (
              <div key={r.id} className="col-span-12 md:col-span-6 lg:col-span-4 group cursor-pointer">
                <div
                  className="bg-surface-container-low rounded-xl overflow-hidden border border-outline-variant/10 hover:border-secondary/30 transition-all duration-500 hover:-translate-y-1"
                  onClick={() => navigate(`/ai/results/${r.id}`, { state: { result: r } })}
                >
                  <div className="h-48 relative">
                    <img src={r.img} alt={r.title} className="w-full h-full object-cover grayscale opacity-50 group-hover:grayscale-0 group-hover:opacity-80 transition-all duration-700" />
                    <div className="absolute inset-0 bg-gradient-to-t from-surface-container-low to-transparent"></div>
                    <span className="absolute top-4 left-4 bg-secondary/20 backdrop-blur-md border border-secondary/40 text-secondary text-[10px] font-bold px-2 py-1 rounded">{r.tag}</span>
                  </div>
                  <div className="p-6">
                    <h3 className="text-lg font-bold text-on-surface mb-2 group-hover:text-secondary transition-colors">{r.title}</h3>
                    <p className="text-sm text-on-surface-variant line-clamp-2 mb-4 leading-relaxed">{r.desc}</p>
                    <div className="flex justify-between items-center">
                      <span className="text-[10px] font-bold text-outline uppercase tracking-widest">Modified: {r.modified}</span>
                      <span className="material-symbols-outlined text-on-surface-variant group-hover:translate-x-1 transition-transform">arrow_forward</span>
                    </div>
                  </div>
                </div>
              </div>
            ))}

            {/* Pagination */}
            <div className="col-span-12 bg-surface-container-highest/40 border border-outline-variant/20 rounded-xl p-4 flex items-center justify-between">
              <div className="flex items-center gap-6">
                <p className="text-xs text-on-surface-variant font-medium">Page 1 of 34</p>
                <div className="flex gap-2">
                  {[1, 2, 3].map((n) => (
                    <button key={n} className={`w-8 h-8 rounded-lg flex items-center justify-center text-sm ${n === 2 ? 'bg-secondary text-on-secondary font-bold' : 'bg-surface-container text-on-surface-variant hover:text-secondary border border-outline-variant/10'}`}>{n}</button>
                  ))}
                  <span className="text-on-surface-variant px-1">...</span>
                  <button className="w-8 h-8 rounded-lg bg-surface-container flex items-center justify-center text-on-surface-variant hover:text-secondary border border-outline-variant/10 text-sm">34</button>
                </div>
              </div>
              <div className="flex gap-4">
                <button className="flex items-center gap-2 px-4 py-2 text-xs font-bold uppercase tracking-widest text-on-surface-variant hover:text-secondary transition-all">
                  Export Manifest<span className="material-symbols-outlined text-sm">download</span>
                </button>
              </div>
            </div>
          </div>
        </div>
      </main>

      {/* FAB */}
      <div className="fixed bottom-10 right-10 z-50">
        <button className="w-14 h-14 rounded-full bg-gradient-to-tr from-secondary to-fuchsia-500 text-on-secondary shadow-[0_0_30px_rgba(172,138,255,0.4)] flex items-center justify-center active:scale-90 transition-all group">
          <span className="material-symbols-outlined text-3xl group-hover:rotate-12 transition-transform" style={{ fontVariationSettings: '"FILL" 1' }}>auto_awesome</span>
        </button>
      </div>
    </div>
  )
}
