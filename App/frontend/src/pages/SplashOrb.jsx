import AnimatedOrb from '../components/AnimatedOrb'

export default function SplashOrb() {
  return (
    <div className="relative h-screen w-screen overflow-hidden bg-[#070d1f]">
      <div className="studio-bridge-bg pointer-events-none absolute inset-0" />

      <div className="absolute inset-0 flex items-center justify-center">
        <div className="pointer-events-none absolute inset-0">
          <AnimatedOrb
            layout="fill"
            interactive={false}
            hideCenterUI
          />
        </div>
      </div>

      <div className="pointer-events-none absolute left-1/2 top-1/2 -translate-x-1/2 translate-y-[126px] text-center">
        <p id="splash-status" className="text-xs tracking-[0.08em] text-white/70">
          로딩중...
        </p>
      </div>
    </div>
  )
}
