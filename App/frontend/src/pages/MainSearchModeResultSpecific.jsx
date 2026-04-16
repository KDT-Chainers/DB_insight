import { useNavigate, useLocation } from 'react-router-dom'

export default function MainSearchModeResultSpecific() {
  const navigate = useNavigate()
  const location = useLocation()
  const file = location.state?.file || { name: 'neural_network_architecture_v4.pdf', icon: 'description' }

  return (
    <div className="bg-surface text-on-surface selection:bg-primary/30 selection:text-primary min-h-screen">
      {/* Sidebar */}
      <aside className="h-screen w-64 fixed left-0 top-0 bg-[#070d1f] flex flex-col border-r border-[#41475b]/15 z-50">
        <div className="p-8">
          <h1 className="text-xl font-black text-[#dfe4fe] tracking-tight">Obsidian</h1>
          <p className="text-[10px] font-semibold uppercase tracking-[0.1em] text-on-surface-variant mt-1">Local Intelligence</p>
        </div>
        <nav className="flex-1 px-4 mt-4 space-y-2">
          {[
            { icon: 'search', label: 'Search', onClick: () => navigate('/search') },
            { icon: 'psychology', label: 'Neural Analysis', onClick: null },
            { icon: 'history', label: 'History', onClick: () => navigate('/search') },
            { icon: 'settings', label: 'Settings', onClick: () => navigate('/settings') },
          ].map((item) => (
            <button
              key={item.label}
              onClick={item.onClick}
              className="w-full text-[#a5aac2] py-3 px-6 hover:bg-[#1c253e] transition-all rounded-xl flex items-center gap-3 cursor-pointer group"
            >
              <span className="material-symbols-outlined text-xl group-hover:text-primary">{item.icon}</span>
              <span className="font-manrope text-xs font-semibold uppercase tracking-[0.05em]">{item.label}</span>
            </button>
          ))}
        </nav>
        <div className="p-6">
          <button
            onClick={() => navigate('/search')}
            className="w-full py-4 bg-gradient-to-r from-primary to-secondary text-on-primary-fixed font-bold rounded-full active:scale-95 transition-transform flex items-center justify-center gap-2"
          >
            <span className="material-symbols-outlined" style={{ fontVariationSettings: '"FILL" 1' }}>add</span>
            <span>New Analysis</span>
          </button>
        </div>
      </aside>

      {/* Main */}
      <main className="ml-64 min-h-screen relative" style={{ backgroundImage: 'radial-gradient(rgba(133,173,255,0.05) 1px, transparent 1px)', backgroundSize: '32px 32px' }}>
        {/* Top bar */}
        <header className="fixed top-0 left-64 right-0 z-50 bg-[#070d1f]/60 backdrop-blur-xl flex items-center justify-between px-8 py-4 shadow-[0_4px_20px_rgba(133,173,255,0.1)]">
          <div className="flex items-center gap-4">
            <span className="material-symbols-outlined text-primary">description</span>
            <h2 className="font-manrope text-sm tracking-wide text-[#dfe4fe] font-bold">{file.name || 'neural_network_architecture_v4.pdf'}</h2>
          </div>
          <div className="flex items-center gap-3">
            <button className="px-5 py-2 text-xs font-bold uppercase tracking-widest text-primary bg-surface-container-high border border-outline-variant/15 rounded-full hover:bg-surface-variant transition-colors active:scale-95">
              Open Path
            </button>
            <button className="px-5 py-2 text-xs font-bold uppercase tracking-widest text-on-primary bg-primary rounded-full hover:brightness-110 transition-all active:scale-95">
              Open File
            </button>
            <div className="h-8 w-[1px] bg-outline-variant/30 mx-2"></div>
            <button className="p-2 text-on-surface-variant hover:text-primary transition-colors"><span className="material-symbols-outlined">mail</span></button>
            <button className="p-2 text-on-surface-variant hover:text-primary transition-colors"><span className="material-symbols-outlined">more_vert</span></button>
          </div>
        </header>

        <section className="pt-24 pb-12 px-8 max-w-7xl mx-auto space-y-8">
          <div className="grid grid-cols-12 gap-6">
            {/* Main preview */}
            <div className="col-span-8 space-y-6">
              <div className="bg-surface-container-low rounded-xl p-8 glass-panel glow-primary min-h-[600px] flex flex-col" style={{ border: '1px solid rgba(65,71,91,0.15)' }}>
                <div className="flex items-center justify-between mb-8">
                  <span className="text-[10px] font-bold tracking-[0.2em] text-primary uppercase">Extracted Document Stream</span>
                  <div className="flex gap-2">
                    <span className="h-2 w-2 rounded-full bg-primary animate-pulse"></span>
                    <span className="h-2 w-2 rounded-full bg-secondary/50"></span>
                  </div>
                </div>
                <div className="prose prose-invert max-w-none font-body text-on-surface-variant/90 leading-relaxed space-y-6">
                  <h1 className="text-3xl font-extrabold text-on-surface tracking-tight">Neural Layer Configuration & Topology</h1>
                  <p>Analysis of current architecture reveals a high-density feedback loop within the primary processing blocks. The obsidian-layer implementation utilizes a local-first intelligence model, minimizing latency during high-frequency data ingestion.</p>
                  <div className="bg-surface-container-highest p-6 rounded-xl border-l-4 border-primary">
                    <code className="text-sm font-mono text-primary-fixed block">
                      [SYSTEM_INIT] LOAD global_weights_v4.2<br />
                      [NEURAL_MAP] ATTACHING sensory_input_node_01<br />
                      [SECURITY] LOCAL_ENCRYPTION_ACTIVE (AES-256-GCM)
                    </code>
                  </div>
                  <p>Metadata suggests this file was modified by <strong>Node_774</strong> during the 04:00 synchronization cycle. Integrity checks pass with 99.9% confidence.</p>
                  <ul className="list-disc pl-5 space-y-2 text-on-surface">
                    <li>Asymmetrical Luminosity Patterns</li>
                    <li>Atmospheric Depth Mapping</li>
                    <li>Obsidian Void Compression Ratios</li>
                  </ul>
                </div>
              </div>
            </div>

            {/* Metadata sidebar */}
            <div className="col-span-4 space-y-6">
              {/* AI Summary */}
              <div className="bg-surface-container-high rounded-xl p-6 border border-outline-variant/10 relative overflow-hidden group">
                <div className="absolute -right-4 -top-4 w-24 h-24 bg-primary/10 blur-3xl group-hover:bg-primary/20 transition-all"></div>
                <h4 className="text-[10px] font-bold tracking-[0.15em] text-primary mb-4 uppercase">AI Intelligence Summary</h4>
                <div className="space-y-4">
                  <div>
                    <p className="text-[10px] text-on-surface-variant uppercase font-medium">Confidence Score</p>
                    <div className="flex items-center gap-3 mt-1">
                      <div className="flex-1 h-1.5 bg-surface-container-highest rounded-full overflow-hidden">
                        <div className="h-full w-[94%] bg-gradient-to-r from-primary to-secondary shadow-[0_0_8px_rgba(133,173,255,0.5)]"></div>
                      </div>
                      <span className="text-xs font-bold text-on-surface">94%</span>
                    </div>
                  </div>
                  <p className="text-sm text-on-surface-variant leading-relaxed italic">"The document structure suggests a high degree of technical sophistication, likely originating from a private laboratory environment."</p>
                </div>
              </div>

              {/* Metadata */}
              <div className="bg-surface-container-low rounded-xl p-6 border border-outline-variant/5">
                <h4 className="text-[10px] font-bold tracking-[0.15em] text-secondary mb-4 uppercase">File Metadata</h4>
                <div className="space-y-4">
                  {[['Size', '12.4 MB'], ['Pages', '42'], ['Created', 'Oct 24, 2023'], ['Type', 'Portable Document']].map(([k, v]) => (
                    <div key={k} className="flex justify-between items-center py-2 border-b border-outline-variant/10 last:border-0">
                      <span className="text-xs text-on-surface-variant">{k}</span>
                      <span className="text-xs font-bold text-on-surface">{v}</span>
                    </div>
                  ))}
                </div>
              </div>

              {/* Processing log */}
              <div className="bg-[#000000] rounded-xl p-6 border border-primary/20 shadow-[inset_0_0_20px_rgba(133,173,255,0.05)]">
                <h4 className="text-[10px] font-bold tracking-[0.15em] text-on-surface-variant mb-6 uppercase flex items-center gap-2">
                  <span className="material-symbols-outlined text-sm">terminal</span>Processing Log
                </h4>
                <div className="space-y-3 font-mono text-[10px] text-primary/70">
                  {[['12:00:01', 'Scanning semantic clusters...'], ['12:00:02', 'Found 14 unique identifiers.'], ['12:00:03', 'Correlating with Obsidian DB.', 'text-secondary'], ['12:00:04', 'Analysis complete.', 'text-on-surface']].map(([t, msg, cls]) => (
                    <div key={t} className="flex gap-2">
                      <span className="text-on-surface-variant">{t}</span>
                      <span className={cls}>{msg}</span>
                    </div>
                  ))}
                </div>
              </div>

              {/* Action buttons */}
              <div className="p-2 space-y-2">
                <button className="w-full group flex items-center justify-between p-4 rounded-xl bg-surface-container-highest hover:bg-primary/10 transition-colors border border-transparent hover:border-primary/20">
                  <div className="flex items-center gap-3">
                    <span className="material-symbols-outlined text-on-surface-variant group-hover:text-primary">share</span>
                    <span className="text-sm font-semibold">Share with Node</span>
                  </div>
                  <span className="material-symbols-outlined text-xs text-on-surface-variant">chevron_right</span>
                </button>
                <button className="w-full group flex items-center justify-between p-4 rounded-xl bg-surface-container-highest hover:bg-secondary/10 transition-colors border border-transparent hover:border-secondary/20">
                  <div className="flex items-center gap-3">
                    <span className="material-symbols-outlined text-on-surface-variant group-hover:text-secondary">cloud_download</span>
                    <span className="text-sm font-semibold">Export to Intelligence</span>
                  </div>
                  <span className="material-symbols-outlined text-xs text-on-surface-variant">chevron_right</span>
                </button>
              </div>
            </div>
          </div>
        </section>

        <div className="fixed bottom-[-10%] left-[20%] w-[40%] h-[40%] bg-primary/5 blur-[120px] pointer-events-none rounded-full"></div>
        <div className="fixed top-[10%] right-[-5%] w-[30%] h-[30%] bg-secondary/5 blur-[100px] pointer-events-none rounded-full"></div>
      </main>
    </div>
  )
}
