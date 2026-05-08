import { useCallback, useEffect, useState } from "react";

/**
 * MainAI 내부 뷰(home/results/detail)와 브라우저 히스토리 동기화 전용 훅.
 * 기존 MainAI의 pushState/popstate 동작을 그대로 유지한다.
 */
export function useAIMainViewState({
  onPopToResults,
  onPopToHome,
  detailExitDelayMs = 320,
} = {}) {
  const [view, setView] = useState("home");

  const pushView = useCallback((nextView) => {
    setView(nextView);
    try {
      window.history.pushState({ view: nextView }, "");
    } catch {}
  }, []);

  const pushHistory = useCallback((viewName) => {
    try {
      window.history.pushState({ view: viewName }, "");
    } catch {}
  }, []);

  useEffect(() => {
    const handlePopState = () => {
      if (view === "detail") {
        onPopToResults?.();
        setTimeout(() => setView("results"), detailExitDelayMs);
      } else if (view === "results") {
        onPopToHome?.();
        setView("home");
      }
    };

    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, [view, onPopToResults, onPopToHome, detailExitDelayMs]);

  return {
    view,
    setView,
    pushView,
    pushHistory,
  };
}
