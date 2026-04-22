import { useState } from "react";
import { API_BASE } from "../api";
import SearchSidebar from "../components/SearchSidebar";
import { useSidebar } from "../context/SidebarContext";

export default function TriChefSearch() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState(null);
  const [loading, setLoading] = useState(false);
  const [stats, setStats] = useState(null);
  const [error, setError] = useState("");
  const { open } = useSidebar();

  async function runSearch() {
    if (!query.trim()) return;
    setLoading(true);
    setResults(null);
    setStats(null);
    setError("");
    try {
      const r = await fetch(`${API_BASE}/api/trichef/search`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query, topk: 10, domains: ["image", "doc_page"] }),
      });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || "검색 실패");
      setResults(j.top);
      setStats(j.stats);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  async function runReindex() {
    if (!confirm("전체 재임베딩을 시작합니다. 시간이 오래 걸릴 수 있습니다. 계속하시겠습니까?")) return;
    setLoading(true);
    setError("");
    try {
      const r = await fetch(`${API_BASE}/api/trichef/reindex`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scope: "all" }),
      });
      const j = await r.json();
      alert("재임베딩 완료: " + JSON.stringify(j, null, 2));
    } catch (e) {
      setError("재임베딩 실패: " + e.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <SearchSidebar />
      <main
        className={`transition-all duration-300 min-h-screen bg-void pt-8 ${open ? "pl-64" : "pl-0"}`}
      >
        <div className="p-6 max-w-5xl mx-auto">
          {/* 헤더 */}
          <div className="flex items-center justify-between mb-6">
            <div>
              <h1 className="text-2xl font-black text-[#dfe4fe]">TRI-CHEF 통합 검색</h1>
              <p className="text-xs text-on-surface-variant mt-1">
                3축 복소수 벡터 검색 · SigLIP2 + e5-large + DINOv2
              </p>
            </div>
            <button
              onClick={runReindex}
              disabled={loading}
              className="px-4 py-2 text-xs rounded-xl border border-outline-variant/30 text-on-surface-variant hover:text-primary hover:border-primary/40 disabled:opacity-40 transition-all"
            >
              재임베딩
            </button>
          </div>

          {/* 검색 입력 */}
          <div className="flex gap-2 mb-6">
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && runSearch()}
              placeholder="자연어로 검색… (예: 해변의 일몰, 매출 차트)"
              className="flex-1 px-4 py-3 bg-surface-container-high border border-outline-variant/20 rounded-xl text-on-surface placeholder-on-surface-variant/50 focus:outline-none focus:border-primary/50 transition-colors"
            />
            <button
              onClick={runSearch}
              disabled={loading || !query.trim()}
              className="px-6 py-3 bg-primary text-on-primary rounded-xl disabled:opacity-40 hover:bg-primary/90 transition-colors font-bold"
            >
              {loading ? "검색 중…" : "검색"}
            </button>
          </div>

          {/* 오류 */}
          {error && (
            <div className="mb-4 px-4 py-3 bg-error/10 border border-error/20 rounded-xl text-error text-sm">
              {error}
            </div>
          )}

          {/* 통계 */}
          {stats && (
            <div className="mb-5 flex flex-wrap gap-4 text-xs text-on-surface-variant">
              {Object.entries(stats.per_domain).map(([d, s]) => (
                <div key={d} className="px-3 py-2 bg-surface-container-high rounded-lg border border-outline-variant/10">
                  <span className="text-primary font-bold uppercase">{d}</span>
                  {s.error ? (
                    <span className="ml-2 text-error">{s.error}</span>
                  ) : (
                    <span className="ml-2">
                      {s.count}건 · μ={s.mu_null} · σ={s.sigma_null} · thr={s.abs_threshold}
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* 결과 그리드 */}
          {results !== null && results.length === 0 && (
            <div className="text-center py-16 text-on-surface-variant">
              임계값 이상의 결과가 없습니다.
            </div>
          )}
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
            {results?.map((it) => (
              <div
                key={`${it.domain}-${it.id}`}
                className="bg-surface-container-high border border-outline-variant/10 rounded-2xl overflow-hidden hover:border-primary/30 transition-colors"
              >
                <div className="relative">
                  <img
                    src={`${API_BASE}${it.preview_url}`}
                    alt={it.id}
                    className="w-full h-36 object-cover"
                    onError={(e) => { e.target.style.display = "none"; }}
                  />
                  <div className="absolute top-1 left-1 px-1.5 py-0.5 rounded text-[0.6rem] font-bold bg-black/60 text-white">
                    #{it.global_rank}
                  </div>
                </div>
                <div className="p-2">
                  <div className="flex justify-between items-center text-[0.65rem] text-on-surface-variant mb-1">
                    <span className="uppercase text-primary/80">{it.domain}</span>
                    <span>conf {it.confidence}</span>
                  </div>
                  <div className="text-[0.7rem] text-on-surface truncate" title={it.id}>
                    {it.id.split("/").pop()}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </main>
    </>
  );
}
