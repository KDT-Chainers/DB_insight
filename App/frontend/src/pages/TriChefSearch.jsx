import { useState, useRef } from "react";
import { API_BASE } from "../api";
import SearchSidebar from "../components/SearchSidebar";
import { useSidebar } from "../context/SidebarContext";

export default function TriChefSearch() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState(null);
  const [loading, setLoading] = useState(false);
  const [stats, setStats] = useState(null);
  const [error, setError] = useState("");
  const [mode, setMode] = useState("text"); // "text" | "image"
  const [imagePreview, setImagePreview] = useState(null);
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef(null);
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

  async function runImageSearch(file) {
    if (!file) return;
    setLoading(true);
    setResults(null);
    setStats(null);
    setError("");
    const formData = new FormData();
    formData.append("image", file);
    formData.append("domain", "image");
    formData.append("topk", "20");
    try {
      const r = await fetch(`${API_BASE}/api/admin/search-by-image`, {
        method: "POST",
        body: formData,
      });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || "이미지 검색 실패");
      // admin 엔드포인트 응답을 trichef 결과 형식으로 변환
      setResults(j.results.map((it) => ({
        ...it,
        domain: "image",
        global_rank: j.results.indexOf(it) + 1,
        preview_url: `/api/admin/file?domain=image&id=${encodeURIComponent(it.id)}`,
      })));
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  function handleFile(file) {
    if (!file || !file.type.startsWith("image/")) return;
    setImagePreview(URL.createObjectURL(file));
    runImageSearch(file);
  }

  function handleDrop(e) {
    e.preventDefault();
    setDragOver(false);
    handleFile(e.dataTransfer.files[0]);
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

          {/* 모드 탭 */}
          <div className="flex gap-1 mb-4 p-1 bg-surface-container-high rounded-xl w-fit border border-outline-variant/10">
            <button
              onClick={() => { setMode("text"); setResults(null); setImagePreview(null); }}
              className={`px-4 py-1.5 rounded-lg text-sm font-semibold transition-colors ${mode === "text" ? "bg-primary text-on-primary" : "text-on-surface-variant hover:text-on-surface"}`}
            >
              텍스트
            </button>
            <button
              onClick={() => { setMode("image"); setResults(null); }}
              className={`px-4 py-1.5 rounded-lg text-sm font-semibold transition-colors ${mode === "image" ? "bg-primary text-on-primary" : "text-on-surface-variant hover:text-on-surface"}`}
            >
              이미지
            </button>
          </div>

          {/* 텍스트 검색 입력 */}
          {mode === "text" && (
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
          )}

          {/* 이미지 검색 드롭존 */}
          {mode === "image" && (
            <div className="mb-6">
              <div
                onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
                onDragLeave={() => setDragOver(false)}
                onDrop={handleDrop}
                onClick={() => fileInputRef.current?.click()}
                className={`relative flex flex-col items-center justify-center h-40 rounded-2xl border-2 border-dashed cursor-pointer transition-colors
                  ${dragOver ? "border-primary bg-primary/10" : "border-outline-variant/30 bg-surface-container-high hover:border-primary/40 hover:bg-primary/5"}`}
              >
                {imagePreview ? (
                  <img src={imagePreview} alt="preview" className="h-full w-full object-contain rounded-2xl p-2" />
                ) : (
                  <>
                    <span className="text-2xl mb-2">🖼️</span>
                    <p className="text-sm text-on-surface-variant">이미지를 드래그하거나 클릭해서 업로드</p>
                    <p className="text-xs text-on-surface-variant/50 mt-1">JPG · PNG · WEBP</p>
                  </>
                )}
                {loading && (
                  <div className="absolute inset-0 flex items-center justify-center bg-black/40 rounded-2xl">
                    <span className="text-white text-sm font-bold">검색 중…</span>
                  </div>
                )}
              </div>
              {imagePreview && !loading && (
                <button
                  onClick={() => { setImagePreview(null); setResults(null); }}
                  className="mt-2 text-xs text-on-surface-variant hover:text-error transition-colors"
                >
                  초기화
                </button>
              )}
              <input
                ref={fileInputRef}
                type="file"
                accept="image/*"
                className="hidden"
                onChange={(e) => handleFile(e.target.files[0])}
              />
            </div>
          )}

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
