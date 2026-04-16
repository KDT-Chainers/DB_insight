import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

export default function InitialSetup() {
  const navigate = useNavigate()
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [done, setDone] = useState(false)

  const handleSubmit = (e) => {
    e.preventDefault()
    if (password && password === confirm) {
      setDone(true)
    }
  }

  return (
    <div className="flex items-center justify-center min-h-screen p-4 bg-void">
      {/* Background */}
      <div className="fixed top-[-10%] left-[-10%] w-[60%] h-[60%] orb-glow rounded-full blur-[100px] opacity-40 pointer-events-none"></div>
      <div className="fixed bottom-[-10%] right-[-10%] w-[50%] h-[50%] bg-secondary/10 rounded-full blur-[120px] opacity-30 pointer-events-none"></div>

      <main className="relative w-full max-w-6xl h-[800px] flex overflow-hidden rounded-xl shadow-2xl border border-white/5 animate-fade-in">
        {/* Left branding */}
        <section className="hidden lg:flex w-5/12 flex-col justify-between p-12 bg-surface-container relative overflow-hidden">
          <div className="relative z-10">
            <div className="flex items-center gap-3 mb-12">
              <div className="w-10 h-10 rounded-lg kinetic-gradient flex items-center justify-center shadow-[0_0_20px_rgba(133,173,255,0.4)]">
                <span className="material-symbols-outlined text-on-primary-container" style={{ fontVariationSettings: '"FILL" 1' }}>dataset</span>
              </div>
              <span className="text-2xl font-black tracking-tighter text-on-surface">DB_insight</span>
            </div>
            <h1 className="text-5xl font-extrabold tracking-tight leading-[1.1] mb-6">
              Welcome to{' '}
              <span className="text-transparent bg-clip-text kinetic-gradient">Local Intelligence</span>.
            </h1>
            <p className="text-on-surface-variant text-lg leading-relaxed max-w-sm">
              Secure your private index with a neural-grade master password. All processing remains on your device.
            </p>
          </div>

          {/* AI Orb */}
          <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
            <div className="w-96 h-96 rounded-full orb-glow animate-pulse"></div>
            <div className="absolute w-64 h-64 border border-primary/20 rounded-full animate-reverse-spin"></div>
            <div className="absolute w-80 h-80 border border-secondary/10 rounded-full animate-spin-slow"></div>
          </div>

          <div className="relative z-10 flex items-center gap-4">
            <div className="flex -space-x-3">
              <div className="w-8 h-8 rounded-full border-2 border-surface-container bg-surface-variant flex items-center justify-center text-[10px] font-bold">AI</div>
              <div className="w-8 h-8 rounded-full border-2 border-surface-container bg-surface-variant flex items-center justify-center text-[10px] font-bold">DB</div>
            </div>
            <span className="text-[10px] uppercase tracking-widest text-on-surface-variant font-semibold">Core v2.4 Active</span>
          </div>
        </section>

        {/* Right setup form */}
        <section className="flex-1 flex flex-col p-12 lg:p-20 bg-surface/80 glass-panel relative">
          <div className="max-w-md mx-auto w-full flex flex-col h-full">
            {/* Progress */}
            <div className="flex justify-between items-center mb-12">
              <div className="flex gap-2">
                <div className="h-1 w-12 rounded-full kinetic-gradient"></div>
                <div className="h-1 w-12 rounded-full bg-surface-container-highest"></div>
                <div className="h-1 w-12 rounded-full bg-surface-container-highest"></div>
              </div>
              <span className="text-[10px] uppercase tracking-widest text-primary font-bold">Initial Setup</span>
            </div>

            {/* Form */}
            <form onSubmit={handleSubmit} className="space-y-8 flex-1">
              <div>
                <h2 className="text-3xl font-bold mb-2">Create Master Key</h2>
                <p className="text-on-surface-variant text-sm">Your Master Key encrypts all local data storage.</p>
              </div>
              <div className="space-y-6">
                <div className="group">
                  <label className="block text-[10px] uppercase tracking-widest font-bold text-on-surface-variant mb-2 group-focus-within:text-primary transition-colors">
                    Master Password
                  </label>
                  <div className="relative">
                    <input
                      type="password"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      placeholder="••••••••••••"
                      className="w-full bg-transparent border-b border-outline-variant focus:border-primary focus:ring-0 px-0 py-3 text-xl transition-all placeholder:text-outline-variant/30 outline-none"
                    />
                  </div>
                </div>

                {/* Strength */}
                <div className="grid grid-cols-2 gap-4">
                  {[
                    { label: '8+ Characters', met: password.length >= 8 },
                    { label: 'Uppercase & Symbol', met: /[A-Z]/.test(password) && /[^a-zA-Z0-9]/.test(password) },
                    { label: 'Unique Phrase', met: password.length > 0 },
                    { label: 'No Dictionary Words', met: false },
                  ].map((item) => (
                    <div key={item.label} className="flex items-center gap-2 text-xs text-on-surface-variant">
                      <span
                        className="material-symbols-outlined text-sm"
                        style={item.met ? { fontVariationSettings: '"FILL" 1', color: '#85adff' } : {}}
                      >
                        {item.met ? 'check_circle' : 'circle'}
                      </span>
                      <span>{item.label}</span>
                    </div>
                  ))}
                </div>

                <div className="group">
                  <label className="block text-[10px] uppercase tracking-widest font-bold text-on-surface-variant mb-2 group-focus-within:text-primary transition-colors">
                    Confirm Password
                  </label>
                  <div className="relative">
                    <input
                      type="password"
                      value={confirm}
                      onChange={(e) => setConfirm(e.target.value)}
                      placeholder="••••••••••••"
                      className="w-full bg-transparent border-b border-outline-variant focus:border-primary focus:ring-0 px-0 py-3 text-xl transition-all placeholder:text-outline-variant/30 outline-none"
                    />
                  </div>
                </div>
              </div>

              <button
                type="submit"
                className="w-full kinetic-gradient text-on-primary-container font-bold py-4 rounded-full flex items-center justify-center gap-2 shadow-[0_10px_20px_rgba(133,173,255,0.2)] hover:shadow-[0_15px_30px_rgba(133,173,255,0.3)] transition-all group active:scale-95"
              >
                Initialize Core
                <span className="material-symbols-outlined group-hover:translate-x-1 transition-transform">arrow_forward</span>
              </button>
            </form>

            <div className="mt-auto pt-8 border-t border-outline-variant/10 flex items-center justify-between">
              <div className="flex items-center gap-2 opacity-60">
                <span className="material-symbols-outlined text-sm">lock</span>
                <span className="text-[10px] uppercase tracking-tighter">Zero-Knowledge Storage</span>
              </div>
              <button onClick={() => navigate('/')} className="text-[10px] uppercase tracking-tighter hover:text-primary transition-colors font-bold">
                Back to Login
              </button>
            </div>
          </div>

          {/* Success overlay */}
          {done && (
            <div className="absolute inset-0 bg-surface z-20 flex flex-col items-center justify-center p-12 text-center">
              <div className="w-24 h-24 rounded-full kinetic-gradient flex items-center justify-center mb-8 shadow-[0_0_40px_rgba(133,173,255,0.5)]">
                <span className="material-symbols-outlined text-4xl text-on-primary-container" style={{ fontVariationSettings: '"FILL" 1' }}>verified</span>
              </div>
              <h2 className="text-4xl font-black mb-4">Welcome, Curator!</h2>
              <p className="text-on-surface-variant max-w-sm mb-12">
                Your private intelligence vault is now initialized and ready for deep indexing.
              </p>
              <button
                onClick={() => navigate('/search')}
                className="px-10 py-4 rounded-full border-2 border-primary text-primary font-bold hover:bg-primary/10 transition-all flex items-center gap-3"
              >
                Start Building My Index
                <span className="material-symbols-outlined">database</span>
              </button>
            </div>
          )}
        </section>
      </main>
    </div>
  )
}
