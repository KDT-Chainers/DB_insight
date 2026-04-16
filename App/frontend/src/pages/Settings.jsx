import { useNavigate } from 'react-router-dom'
import { useState } from 'react'

export default function Settings() {
  const navigate = useNavigate()
  const [cloudSync, setCloudSync] = useState(true)
  const [neuralFeedback, setNeuralFeedback] = useState(false)

  return (
    <div className="bg-surface text-on-surface antialiased min-h-screen">
      {/* Sidebar */}
      <aside className="h-screen w-64 fixed left-0 border-r border-outline-variant/15 bg-[#070d1f] flex flex-col py-8 px-4 gap-4 z-50">
        <div className="mb-8 px-4">
          <h1 className="text-[#85adff] font-bold text-xl tracking-tighter">Obsidian Intelligence</h1>
          <p className="font-manrope uppercase tracking-widest text-[0.7rem] text-on-surface-variant mt-1">DB_insight v.2.0.4</p>
        </div>
        <nav className="flex flex-col gap-2">
          <button
            onClick={() => navigate('/search')}
            className="text-[#a5aac2] px-4 py-3 hover:text-[#dfe4fe] hover:bg-[#1c253e]/20 transition-all duration-200 cursor-pointer flex items-center gap-3 rounded-xl group hover:translate-x-1"
          >
            <span className="material-symbols-outlined text-lg">psychology</span>
            <span className="font-manrope uppercase tracking-widest text-[0.75rem]">Intelligence</span>
          </button>
          <button className="text-[#a5aac2] px-4 py-3 hover:text-[#dfe4fe] hover:bg-[#1c253e]/20 transition-all duration-200 cursor-pointer flex items-center gap-3 rounded-xl group hover:translate-x-1">
            <span className="material-symbols-outlined text-lg">folder_open</span>
            <span className="font-manrope uppercase tracking-widest text-[0.75rem]">Files</span>
          </button>
          <div className="text-[#85adff] bg-[#1c253e]/40 rounded-xl px-4 py-3 border-l-2 border-[#ac8aff] flex items-center gap-3 translate-x-1">
            <span className="material-symbols-outlined text-lg" style={{ fontVariationSettings: '"FILL" 1' }}>tune</span>
            <span className="font-manrope uppercase tracking-widest text-[0.75rem] font-semibold">Settings</span>
          </div>
          <button className="text-[#a5aac2] px-4 py-3 hover:text-[#dfe4fe] hover:bg-[#1c253e]/20 transition-all duration-200 cursor-pointer flex items-center gap-3 rounded-xl group hover:translate-x-1">
            <span className="material-symbols-outlined text-lg">help_outline</span>
            <span className="font-manrope uppercase tracking-widest text-[0.75rem]">Support</span>
          </button>
        </nav>
        <div className="mt-auto px-4 py-6 border-t border-outline-variant/10">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-full overflow-hidden border border-primary/30 bg-surface-container-highest flex items-center justify-center">
              <span className="material-symbols-outlined text-primary">account_circle</span>
            </div>
            <div>
              <p className="text-sm font-bold text-on-surface leading-tight">Alex Thorne</p>
              <p className="text-[0.7rem] text-on-surface-variant font-mono">NODE-7721-B</p>
            </div>
          </div>
        </div>
      </aside>

      {/* Main */}
      <main className="ml-64 min-h-screen p-12 relative overflow-hidden">
        <div className="absolute top-[-10%] right-[-10%] w-[500px] h-[500px] bg-primary/10 rounded-full blur-[120px] pointer-events-none"></div>
        <div className="absolute bottom-[-5%] left-[5%] w-[400px] h-[400px] bg-secondary/5 rounded-full blur-[100px] pointer-events-none"></div>

        <div className="max-w-4xl mx-auto relative z-10">
          <header className="mb-12">
            <h2 className="text-4xl font-extrabold tracking-tight text-on-surface mb-2">System Settings</h2>
            <p className="text-on-surface-variant max-w-xl">
              Configure your local intelligence node parameters and manage security protocols for DB_insight.
            </p>
          </header>

          <div className="grid grid-cols-1 gap-8">
            {/* Security */}
            <section className="glass-panel p-8 rounded-xl border border-outline-variant/15 shadow-[0_0_40px_rgba(133,173,255,0.05)]">
              <div className="flex items-center gap-2 mb-6">
                <span className="text-[0.75rem] font-manrope uppercase tracking-[0.2em] text-primary font-bold">Security Protocols</span>
                <div className="h-[1px] flex-grow bg-outline-variant/20"></div>
              </div>
              <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-6">
                <div>
                  <h3 className="text-xl font-semibold text-on-surface mb-2">Master Authentication</h3>
                  <p className="text-on-surface-variant text-sm">The master password decrypts your local database. Resetting this will update your local encryption key.</p>
                </div>
                <button
                  onClick={() => navigate('/setup')}
                  className="bg-gradient-to-tr from-primary to-secondary text-on-primary font-bold py-3 px-8 rounded-full shadow-lg shadow-primary/20 hover:scale-105 active:scale-95 transition-all duration-300 whitespace-nowrap"
                >
                  Change Master Password
                </button>
              </div>
            </section>

            {/* Preferences */}
            <section className="glass-panel p-8 rounded-xl border border-outline-variant/15">
              <div className="flex items-center gap-2 mb-6">
                <span className="text-[0.75rem] font-manrope uppercase tracking-[0.2em] text-primary font-bold">Preferences</span>
                <div className="h-[1px] flex-grow bg-outline-variant/20"></div>
              </div>
              <div className="space-y-8">
                <div>
                  <label className="block text-[0.7rem] uppercase tracking-widest text-on-surface-variant font-bold mb-3">Frequently Used Email</label>
                  <div className="relative max-w-md">
                    <input
                      className="w-full bg-transparent border-0 border-b border-outline-variant py-3 px-0 text-on-surface focus:ring-0 focus:border-primary transition-colors duration-300 placeholder-outline outline-none"
                      placeholder="archivist@obsidian.io"
                      type="email"
                      defaultValue="a.thorne@obsidian-intel.local"
                    />
                  </div>
                  <p className="mt-3 text-xs text-on-surface-variant/70 italic">Used for automated report deliveries and emergency node recovery notifications.</p>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  {/* Toggle: Cloud Sync */}
                  <div className="p-4 rounded-xl bg-surface-container-low border border-outline-variant/10 flex items-center justify-between">
                    <div>
                      <p className="text-sm font-semibold text-on-surface">Cloud Sync</p>
                      <p className="text-xs text-on-surface-variant">Sync local logs to encrypted cloud</p>
                    </div>
                    <button
                      onClick={() => setCloudSync(!cloudSync)}
                      className={`w-10 h-5 rounded-full relative cursor-pointer p-1 transition-colors duration-300 ${cloudSync ? 'bg-primary/30' : 'bg-surface-container-highest'}`}
                    >
                      <div className={`w-3 h-3 bg-primary rounded-full absolute top-1 transition-all ${cloudSync ? 'right-1' : 'left-1'}`}></div>
                    </button>
                  </div>
                  {/* Toggle: Neural Feedback */}
                  <div className="p-4 rounded-xl bg-surface-container-low border border-outline-variant/10 flex items-center justify-between">
                    <div>
                      <p className="text-sm font-semibold text-on-surface">Neural Feedback</p>
                      <p className="text-xs text-on-surface-variant">Enable haptic processing signals</p>
                    </div>
                    <button
                      onClick={() => setNeuralFeedback(!neuralFeedback)}
                      className={`w-10 h-5 rounded-full relative cursor-pointer p-1 transition-colors duration-300 ${neuralFeedback ? 'bg-primary/30' : 'bg-surface-container-highest'}`}
                    >
                      <div className={`w-3 h-3 rounded-full absolute top-1 transition-all ${neuralFeedback ? 'bg-primary right-1' : 'bg-outline left-1'}`}></div>
                    </button>
                  </div>
                </div>
              </div>
            </section>

            {/* Danger zone */}
            <section className="glass-panel p-8 rounded-xl border border-error-dim/20 bg-error-dim/5 relative overflow-hidden">
              <div className="absolute -right-20 -bottom-20 w-64 h-64 bg-error-dim/10 blur-[80px] rounded-full"></div>
              <div className="flex items-center gap-2 mb-6">
                <span className="text-[0.75rem] font-manrope uppercase tracking-[0.2em] text-error-dim font-bold">Danger Zone</span>
                <div className="h-[1px] flex-grow bg-error-dim/20"></div>
              </div>
              <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-6 relative z-10">
                <div className="max-w-xl">
                  <h3 className="text-xl font-semibold text-error-dim mb-2">Factory Reset & Data Purge</h3>
                  <p className="text-on-surface-variant text-sm">
                    Permanently delete all intelligence nodes, local files, and system preferences. This action is irreversible and will zero-out all allocated storage sectors.
                  </p>
                </div>
                <button className="whitespace-nowrap border border-error-dim/40 text-error-dim font-bold py-3 px-8 rounded-full hover:bg-error-dim hover:text-white transition-all duration-300 active:scale-95 shadow-[0_0_20px_rgba(215,56,59,0.1)]">
                  Delete App & Data
                </button>
              </div>
            </section>
          </div>

          {/* Footer */}
          <footer className="mt-16 flex flex-col items-center justify-center text-on-surface-variant/40 space-y-4">
            <div className="flex items-center gap-8">
              {[['Storage', '1.2TB / 4.0TB'], ['Latency', '14ms'], ['Uptime', '1,402h']].map(([label, val]) => (
                <div key={label} className="text-center">
                  <p className="text-[0.6rem] uppercase tracking-widest font-bold">{label}</p>
                  <p className="text-xs font-mono">{val}</p>
                </div>
              ))}
            </div>
            <p className="text-[0.6rem] uppercase tracking-widest">© 2024 Obsidian Intelligence Systems. All Rights Reserved.</p>
          </footer>
        </div>
      </main>
    </div>
  )
}
