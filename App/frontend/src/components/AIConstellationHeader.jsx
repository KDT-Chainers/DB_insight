import {
  useRef,
  useLayoutEffect,
  useEffect,
  useState,
  useId,
  useMemo,
} from "react";
import { createPortal } from "react-dom";

/**
 * AI 홈 상단 — 별자리(선 + 별). 이탈 시 핵심 별이 Orb 중심으로 빨려 들어감.
 */
const VIEW_W = 520;
const VIEW_H = 132;

const STARS = [
  { x: 28, y: 98, r: 1.1, o: 0.35 },
  { x: 72, y: 76, r: 1.4, o: 0.55 },
  { x: 118, y: 58, r: 1.8, o: 0.85 },
  { x: 168, y: 72, r: 1.2, o: 0.45 },
  { x: 212, y: 44, r: 2, o: 0.95 },
  { x: 258, y: 62, r: 1.3, o: 0.5 },
  { x: 302, y: 38, r: 1.6, o: 0.7 },
  { x: 348, y: 54, r: 1.1, o: 0.4 },
  { x: 392, y: 88, r: 1.5, o: 0.6 },
  { x: 438, y: 48, r: 1.2, o: 0.48 },
  { x: 478, y: 72, r: 1.7, o: 0.78 },
  { x: 320, y: 102, r: 1, o: 0.32 },
  { x: 156, y: 104, r: 0.9, o: 0.28 },
];

/** Orb로 흡수되는 밝은 별(인덱스) */
const CORE_STAR_INDICES = [2, 4, 6, 9, 10];

const EDGES = [
  [0, 1],
  [1, 2],
  [2, 3],
  [2, 4],
  [4, 5],
  [4, 6],
  [6, 7],
  [7, 9],
  [9, 8],
  [8, 10],
  [9, 10],
  [5, 11],
  [3, 12],
  [12, 0],
];

export default function AIConstellationHeader({
  className = "",
  absorbing = false,
  sinkRef,
}) {
  const gradId = useId().replace(/:/g, "");
  const wrapRef = useRef(null);
  const [reduceMotion] = useState(
    () =>
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  );
  const [particles, setParticles] = useState(null);
  const [burst, setBurst] = useState(false);

  const coreSet = useMemo(() => new Set(CORE_STAR_INDICES), []);

  useLayoutEffect(() => {
    if (typeof window === "undefined") return;
    if (!absorbing || reduceMotion) {
      setParticles(null);
      setBurst(false);
      return;
    }
    const sinkEl = sinkRef?.current;
    const root = wrapRef.current;
    if (!sinkEl || !root) return;

    const sinkRect = sinkEl.getBoundingClientRect();
    const scx = sinkRect.left + sinkRect.width / 2;
    const scy = sinkRect.top + sinkRect.height / 2;

    const items = [];
    for (const idx of CORE_STAR_INDICES) {
      const el = root.querySelector(`[data-star-idx="${idx}"]`);
      if (!el) continue;
      const r = el.getBoundingClientRect();
      const cx = r.left + r.width / 2;
      const cy = r.top + r.height / 2;
      const size = Math.max(3, (r.width + r.height) / 2);
      items.push({
        idx,
        cx,
        cy,
        dx: scx - cx,
        dy: scy - cy,
        size,
        o: STARS[idx].o,
      });
    }
    setParticles(items.length ? { items } : null);
    setBurst(false);
  }, [absorbing, reduceMotion, sinkRef]);

  useEffect(() => {
    if (!particles?.items?.length) return;
    const id = requestAnimationFrame(() => {
      requestAnimationFrame(() => setBurst(true));
    });
    return () => cancelAnimationFrame(id);
  }, [particles]);

  const showPortal =
    absorbing && !reduceMotion && particles?.items?.length > 0;

  const portal =
    showPortal &&
    typeof document !== "undefined" &&
    createPortal(
      <div
        className="pointer-events-none fixed inset-0 z-[200]"
        aria-hidden
      >
        {particles.items.map((p, i) => (
          <div
            key={p.idx}
            className="rounded-full bg-[#ede9fe] shadow-[0_0_12px_rgba(167,139,250,0.9)]"
            style={{
              position: "fixed",
              left: p.cx,
              top: p.cy,
              width: p.size,
              height: p.size,
              marginLeft: -p.size / 2,
              marginTop: -p.size / 2,
              opacity: burst ? 0 : p.o,
              transform: burst
                ? `translate(${p.dx}px, ${p.dy}px) scale(0.04)`
                : "translate(0,0) scale(1)",
              transition: burst
                ? `transform 0.5s cubic-bezier(0.52, 0, 0.78, 0.38) ${i * 30}ms, opacity 0.28s ease-in ${i * 30 + 220}ms`
                : "none",
            }}
          />
        ))}
      </div>,
      document.body,
    );

  const svgFaded = absorbing && reduceMotion;

  return (
    <div
      ref={wrapRef}
      className={`pointer-events-none select-none ${className}`}
      aria-hidden
    >
      {portal}
      <svg
        viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
        className={`mx-auto h-[min(22vh,168px)] w-full max-w-xl transition-opacity duration-300 motion-reduce:transition-none ${
          svgFaded ? "opacity-0" : "opacity-[0.72] motion-reduce:opacity-50"
        }`}
        preserveAspectRatio="xMidYMid meet"
      >
        <defs>
          <linearGradient
            id={`ai-constellation-line-${gradId}`}
            x1="0%"
            y1="0%"
            x2="100%"
            y2="0%"
          >
            <stop
              offset="0%"
              stopColor="rgb(167, 139, 250)"
              stopOpacity="0.08"
            />
            <stop
              offset="50%"
              stopColor="rgb(196, 181, 253)"
              stopOpacity="0.22"
            />
            <stop
              offset="100%"
              stopColor="rgb(167, 139, 250)"
              stopOpacity="0.08"
            />
          </linearGradient>
        </defs>
        <g
          stroke={`url(#ai-constellation-line-${gradId})`}
          strokeWidth="0.85"
          strokeLinecap="round"
          className="transition-opacity duration-200"
          style={{ opacity: absorbing ? 0 : 1 }}
        >
          {EDGES.map(([a, b], i) => {
            const p = STARS[a];
            const q = STARS[b];
            return (
              <line key={`e-${i}`} x1={p.x} y1={p.y} x2={q.x} y2={q.y} />
            );
          })}
        </g>
        {STARS.map((s, i) => {
          const isCore = coreSet.has(i);
          const hideCore = showPortal && isCore;
          const dim =
            absorbing && !reduceMotion && !isCore && !hideCore;
          return (
            <circle
              key={`s-${i}`}
              data-star-idx={i}
              cx={s.x}
              cy={s.y}
              r={s.r}
              fill="rgb(237, 233, 254)"
              fillOpacity={hideCore ? 0 : dim ? s.o * 0.2 : s.o}
              className="transition-[fill-opacity] duration-200"
            />
          );
        })}
        <circle
          cx={STARS[4].x}
          cy={STARS[4].y}
          r={4}
          fill="rgb(167, 139, 250)"
          fillOpacity={absorbing ? 0 : 0.12}
          className="motion-reduce:hidden transition-opacity duration-200"
        />
      </svg>
    </div>
  );
}
