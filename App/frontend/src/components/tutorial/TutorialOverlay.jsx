import { useEffect, useMemo, useState } from "react";
import AnimatedOrb from "../AnimatedOrb";

function useTargetRect(selector, enabled) {
  const [rect, setRect] = useState(null);

  useEffect(() => {
    if (!enabled || !selector) {
      setRect(null);
      return;
    }

    let rafId = null;
    const update = () => {
      const el = document.querySelector(selector);
      if (!el) {
        setRect(null);
        return;
      }
      const r = el.getBoundingClientRect();
      const next = {
        top: r.top,
        left: r.left,
        width: r.width,
        height: r.height,
      };
      // 미세한 sub-pixel 변동으로 생기는 깜빡임 억제
      setRect((prev) => {
        if (!prev) return next;
        const drift =
          Math.abs(prev.top - next.top) +
          Math.abs(prev.left - next.left) +
          Math.abs(prev.width - next.width) +
          Math.abs(prev.height - next.height);
        return drift < 1.2 ? prev : next;
      });
    };

    const scheduleUpdate = () => {
      if (rafId != null) return;
      rafId = window.requestAnimationFrame(() => {
        rafId = null;
        update();
      });
    };

    update();
    window.addEventListener("resize", scheduleUpdate);
    window.addEventListener("scroll", scheduleUpdate, true);
    // 버튼 라벨/상태 변경으로 위치가 미세 이동할 수 있어 저주기로 재동기화.
    const intervalId = window.setInterval(scheduleUpdate, 420);

    return () => {
      window.removeEventListener("resize", scheduleUpdate);
      window.removeEventListener("scroll", scheduleUpdate, true);
      window.clearInterval(intervalId);
      if (rafId != null) window.cancelAnimationFrame(rafId);
    };
  }, [selector, enabled]);

  return rect;
}

export default function TutorialOverlay({
  open,
  stepIndex,
  steps,
  onNext,
  onSkip,
}) {
  const step = steps[stepIndex];
  const targetRect = useTargetRect(step?.selector, open);
  const introLines = Array.isArray(step?.introLines) ? step.introLines : null;
  const isCenteredStep = Boolean(step?.center);
  const [introLineIdx, setIntroLineIdx] = useState(0);
  const [orbPopping, setOrbPopping] = useState(false);
  const displayTitle = introLines ? introLines[introLineIdx] : step?.title;
  const displayDescription = step?.description || "";

  const canGoNext = typeof onNext === "function";

  useEffect(() => {
    setIntroLineIdx(0);
    setOrbPopping(false);
  }, [stepIndex, open]);

  useEffect(() => {
    if (!open || !step || !canGoNext) return;
    const handler = (e) => {
      const rawTarget = e.target;
      if (rawTarget instanceof Element && rawTarget.closest('[data-tutorial-ui="1"]')) {
        return;
      }
      if (introLines && !step.selector && introLineIdx < introLines.length - 1) {
        setIntroLineIdx((i) => Math.min(i + 1, introLines.length - 1));
        return;
      }
      if (step.selector) {
        const target = e.target;
        if (!(target instanceof Element)) return;
        if (!target.closest(step.selector)) return;
        onNext?.();
        return;
      }
      if (isCenteredStep) {
        setOrbPopping(true);
        window.setTimeout(() => onNext?.(), 220);
        return;
      }
      onNext?.();
    };
    document.addEventListener("click", handler, true);
    return () => document.removeEventListener("click", handler, true);
  }, [open, step, canGoNext, onNext, introLines, introLineIdx, isCenteredStep]);

  const cutoutRect = useMemo(() => {
    if (!targetRect) return null;
    return {
      top: Math.max(6, targetRect.top - 10),
      left: Math.max(6, targetRect.left - 10),
      width: targetRect.width + 20,
      height: targetRect.height + 20,
    };
  }, [targetRect]);

  const guideLayout = useMemo(() => {
    const vw = typeof window !== "undefined" ? window.innerWidth : 1280;
    const vh = typeof window !== "undefined" ? window.innerHeight : 720;
    const textLen = `${displayTitle ?? ""} ${displayDescription}`.trim().length;
    const autoWidth = Math.round(Math.max(220, Math.min(vw - 24, 140 + textLen * 4.4)));
    const width = Math.min(autoWidth, 320);

    if (isCenteredStep) {
      const orbX = Math.round(vw * 0.5);
      const bubbleWidth = Math.min(Math.max(300, width), 420);
      const bubbleTop = Math.max(24, Math.round(vh * 0.33));
      return {
        box: {
          left: Math.round((vw - bubbleWidth) / 2),
          top: bubbleTop,
          width: bubbleWidth,
        },
        orb: {
          x: orbX,
          y: Math.min(vh - 58, bubbleTop + 210),
        },
        tail: null,
      };
    }

    if (!targetRect) {
      const orbX = Math.max(140, Math.round(vw * 0.24));
      const orbY = Math.max(96, Math.round(vh * 0.38));
      const bubbleLeft = Math.min(vw - width - 12, orbX + 74);
      const bubbleTop = Math.max(12, Math.min(vh - 180, orbY - 58));
      return {
        box: {
          left: bubbleLeft,
          top: bubbleTop,
          width,
        },
        orb: {
          x: orbX,
          y: orbY,
        },
        tail: {
          side: "left",
          top: "50%",
        },
      };
    }

    const showRight = targetRect.left < vw * 0.56;
    const bubbleWidth = Math.min(width, 320);
    const bubbleHeightEstimate = displayDescription ? 176 : 124;
    const targetMidY = targetRect.top + targetRect.height * 0.5;
    const left = showRight
      ? Math.min(vw - bubbleWidth - 12, targetRect.left + targetRect.width + 16)
      : Math.max(12, targetRect.left - bubbleWidth - 16);
    const top = Math.max(
      12,
      Math.min(vh - bubbleHeightEstimate - 12, targetMidY - bubbleHeightEstimate * 0.48),
    );
    const tailTop = Math.max(
      18,
      Math.min(bubbleHeightEstimate - 18, targetMidY - top),
    );
    return {
      box: { left, top, width: bubbleWidth },
      orb: {
        // 타겟 안내 단계는 Orb를 말풍선 아래에 배치.
        x: left + bubbleWidth * 0.22,
        y: Math.min(vh - 42, top + 220),
      },
      tail: {
        side: showRight ? "left" : "right",
        top: `${tailTop}px`,
      },
    };
  }, [targetRect, displayTitle, displayDescription, isCenteredStep]);

  if (!open || !step) return null;

  return (
    <div className="pointer-events-none fixed inset-0 z-[12000]">
      {cutoutRect ? (
        <>
          <div
            className="absolute left-0 right-0 top-0 bg-[#020617]/38 backdrop-blur-[2px] transition-all duration-700"
            style={{ height: cutoutRect.top }}
          />
          <div
            className="absolute left-0 bg-[#020617]/38 backdrop-blur-[2px] transition-all duration-700"
            style={{
              top: cutoutRect.top,
              width: cutoutRect.left,
              height: cutoutRect.height,
            }}
          />
          <div
            className="absolute right-0 bg-[#020617]/38 backdrop-blur-[2px] transition-all duration-700"
            style={{
              top: cutoutRect.top,
              left: cutoutRect.left + cutoutRect.width,
              height: cutoutRect.height,
            }}
          />
          <div
            className="absolute bottom-0 left-0 right-0 bg-[#020617]/38 backdrop-blur-[2px] transition-all duration-700"
            style={{ top: cutoutRect.top + cutoutRect.height }}
          />
        </>
      ) : (
        <div className="absolute inset-0 bg-[#020617]/24 backdrop-blur-[1px]" />
      )}

      {targetRect && (
        <div
          className="pointer-events-none absolute rounded-2xl border border-sky-200/80 shadow-[0_0_0_1px_rgba(186,230,253,0.72),0_0_24px_rgba(56,189,248,0.2)] transition-all duration-700 ease-out"
          style={{
            top: Math.max(8, targetRect.top - 8),
            left: Math.max(8, targetRect.left - 8),
            width: targetRect.width + 16,
            height: targetRect.height + 16,
          }}
        />
      )}

      {targetRect && (
        <div
          className="pointer-events-none absolute rounded-2xl border border-sky-300/70 animate-pulse"
          style={{
            top: Math.max(6, targetRect.top - 10),
            left: Math.max(6, targetRect.left - 10),
            width: targetRect.width + 20,
            height: targetRect.height + 20,
          }}
        />
      )}

      <button
        type="button"
        onClick={onSkip}
        data-tutorial-ui="1"
        className="pointer-events-auto absolute right-4 top-4 rounded-full border border-white/20 bg-black/25 px-3 py-1 text-xs text-white/75 backdrop-blur-sm transition hover:bg-black/35 hover:text-white"
      >
        건너뛰기
      </button>

      <div
        className={`absolute transition-all duration-700 ${
          orbPopping
            ? "scale-[0.55] -translate-y-3 opacity-0 ease-[cubic-bezier(0.22,1,0.36,1)]"
            : "scale-100 translate-y-0 opacity-100 ease-out"
        }`}
        style={{
          left: guideLayout.orb.x,
          top: guideLayout.orb.y,
          transform: "translate(-50%, -50%)",
        }}
      >
        <div className="floating-orb-guide relative">
          <div className="pointer-events-none relative z-10">
            <AnimatedOrb size={86} interactive={false} hideCenterUI />
          </div>
          <div className="absolute inset-0 -z-10 animate-pulse rounded-full bg-sky-300/18 blur-2xl" />
          {orbPopping && (
            <div className="orb-pop-spark pointer-events-none absolute inset-[-18%] -z-20 rounded-full" />
          )}
        </div>
      </div>

      <div
        className="pointer-events-none absolute rounded-2xl border border-white/18 bg-[#0b1736]/58 px-4 py-3 shadow-[0_12px_30px_rgba(2,6,23,0.42)] backdrop-blur-xl transition-all duration-700 ease-out"
        style={guideLayout.box}
        data-tutorial-ui="1"
      >
        {guideLayout.tail && (
          <div
            className="absolute h-3.5 w-3.5 rotate-45 border-white/18 bg-[#0b1736]/75"
            style={{
              top: guideLayout.tail.top,
              left: guideLayout.tail.side === "left" ? "-7px" : "auto",
              right: guideLayout.tail.side === "right" ? "-7px" : "auto",
              transform: "translateY(-50%) rotate(45deg)",
              borderLeftWidth: guideLayout.tail.side === "left" ? "1px" : "0px",
              borderTopWidth: guideLayout.tail.side === "left" ? "1px" : "0px",
              borderRightWidth: guideLayout.tail.side === "right" ? "1px" : "0px",
              borderBottomWidth: guideLayout.tail.side === "right" ? "1px" : "0px",
              borderStyle: "solid",
            }}
          />
        )}
        <p className="text-[1.02rem] font-semibold tracking-tight text-white">
          {displayTitle}
        </p>
        {displayDescription && (
          <p className="mt-1.5 text-[13px] leading-relaxed text-slate-100/86">
            {displayDescription}
          </p>
        )}
        {!canGoNext && (
          <button
            type="button"
            onClick={onSkip}
            className="pointer-events-auto mt-2 rounded-full bg-white/10 px-2.5 py-1 text-xs text-white/80"
          >
            닫기
          </button>
        )}
      </div>

      <style>{`
        .floating-orb-guide {
          animation: dbi-orb-float 4.2s ease-in-out infinite;
        }
        .orb-pop-spark {
          background:
            radial-gradient(circle at 50% 50%, rgba(186, 230, 253, 0.75) 0%, rgba(125, 211, 252, 0.45) 30%, rgba(14, 165, 233, 0.08) 62%, transparent 78%);
          filter: blur(1px);
          animation: dbi-orb-pop-spark 520ms cubic-bezier(0.16, 1, 0.3, 1) forwards;
        }
        @keyframes dbi-orb-float {
          0% { transform: translateY(0px); }
          50% { transform: translateY(-10px); }
          100% { transform: translateY(0px); }
        }
        @keyframes dbi-orb-pop-spark {
          0% {
            opacity: 0;
            transform: scale(0.55);
          }
          28% {
            opacity: 0.95;
            transform: scale(1.04);
          }
          100% {
            opacity: 0;
            transform: scale(1.42);
          }
        }
      `}</style>
    </div>
  );
}
