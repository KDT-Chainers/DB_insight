import { useNavigate } from "react-router-dom";
import { useState, useEffect, useCallback, useMemo } from "react";
import { useScale } from "../context/ScaleContext";
import { API_BASE } from "../api";
import WindowControls from "../components/WindowControls";
import StudioThreePaneShell from "../components/StudioThreePaneShell";

export default function Settings() {
  const navigate = useNavigate();
  const [cloudSync, setCloudSync] = useState(true);
  const [neuralFeedback, setNeuralFeedback] = useState(false);
  const { scale, setScale, MIN_SCALE, MAX_SCALE, STEP } = useScale();

  // ── BGM API 스위치 ───────────────────────────────────────
  const [bgmStatus, setBgmStatus] = useState(null);
  const [bgmHost, setBgmHost] = useState("");
  const [bgmKey, setBgmKey] = useState("");
  const [bgmSecret, setBgmSecret] = useState("");
  const [bgmTesting, setBgmTesting] = useState(false);
  const [bgmSyncing, setBgmSyncing] = useState(false);
  const [bgmMsg, setBgmMsg] = useState("");

  const refreshBgmStatus = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/bgm/api_status`);
      if (res.ok) {
        const d = await res.json();
        setBgmStatus(d);
        setBgmHost(d.host || "");
      }
    } catch {
      /* 백엔드 비동작 시 무시 */
    }
  }, []);
  useEffect(() => {
    refreshBgmStatus();
  }, [refreshBgmStatus]);

  const updateBgmApi = async (patch) => {
    setBgmMsg("");
    try {
      const res = await fetch(`${API_BASE}/api/bgm/api_toggle`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch),
      });
      const d = await res.json();
      setBgmStatus(d);
      setBgmHost(d.host || "");
      // 키 입력 필드는 보안상 패치 후 비움 (마스킹 표시는 status로 확인)
      if (patch.access_key !== undefined) setBgmKey("");
      if (patch.access_secret !== undefined) setBgmSecret("");
      setBgmMsg(`설정 갱신: api_enabled=${d.api_enabled}`);
    } catch (e) {
      setBgmMsg(`갱신 실패: ${e.message}`);
    }
  };

  const handleSyncCatalog = async () => {
    setBgmSyncing(true);
    setBgmMsg("카탈로그 동기화 중...");
    try {
      const res = await fetch(`${API_BASE}/api/bgm/catalog_sync`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ only_missing: true }),
      });
      const d = await res.json();
      if (d.error) setBgmMsg(`실패: ${d.error}`);
      else setBgmMsg(`완료: ${d.synced}곡 메타 보강`);
    } catch (e) {
      setBgmMsg(`실패: ${e.message}`);
    } finally {
      setBgmSyncing(false);
    }
  };

  const [modalOpen, setModalOpen] = useState(false);
  const [currentPw, setCurrentPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [confirmPw, setConfirmPw] = useState("");
  const [modalError, setModalError] = useState("");
  const [modalSuccess, setModalSuccess] = useState(false);
  const [loading, setLoading] = useState(false);

  const openModal = () => {
    setCurrentPw("");
    setNewPw("");
    setConfirmPw("");
    setModalError("");
    setModalSuccess(false);
    setModalOpen(true);
  };
  const closeModal = () => {
    if (!loading) setModalOpen(false);
  };

  const handlePasswordChange = async (e) => {
    e.preventDefault();
    setModalError("");
    if (newPw !== confirmPw) {
      setModalError("새 비밀번호가 일치하지 않습니다.");
      return;
    }
    if (newPw.length < 1) {
      setModalError("새 비밀번호를 입력하세요.");
      return;
    }
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/auth/reset`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          current_password: currentPw,
          new_password: newPw,
        }),
      });
      const data = await res.json();
      if (!res.ok) setModalError(data.error || "변경에 실패했습니다.");
      else {
        setModalSuccess(true);
        setTimeout(() => setModalOpen(false), 1200);
      }
    } catch {
      setModalError("서버에 연결할 수 없습니다.");
    } finally {
      setLoading(false);
    }
  };

  const navItems = useMemo(
    () => [
      {
        key: "ws",
        icon: "database",
        label: "워크스페이스",
        subtitle: "검색 · 기록",
        active: false,
        onClick: () => navigate("/search"),
      },
      {
        key: "data",
        icon: "account_tree",
        label: "데이터",
        subtitle: "소스 · 인덱싱 · 벡터",
        active: false,
        onClick: () => navigate("/data"),
      },
      {
        key: "settings",
        icon: "tune",
        label: "시스템 설정",
        subtitle: "보안 · 환경 · API",
        active: true,
        onClick: () => {},
      },
    ],
    [navigate],
  );

  const settingsBreadcrumb = useMemo(
    () => (
      <>
        <button
          type="button"
          onClick={() => navigate("/search")}
          className="shrink-0 rounded-lg px-1.5 py-0.5 text-white/48 transition hover:bg-white/[0.08] hover:text-white/88"
        >
          홈
        </button>
        <span className="material-symbols-outlined shrink-0 text-[15px] text-white/22">
          chevron_right
        </span>
        <span className="min-w-0 truncate font-medium text-white/88">시스템 설정</span>
      </>
    ),
    [navigate],
  );

  const settingsRightWidgets = useMemo(
    () => (
      <>
        <div className="apple-widget-card rounded-[18px] p-4">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-[11px] font-bold uppercase tracking-[0.14em] text-sky-200/85">
              보안
            </span>
            <span className="material-symbols-outlined text-lg text-white/28">shield</span>
          </div>
          <p className="text-[12px] leading-relaxed text-white/38">
            마스터 비밀번호는 로컬 DB 복호화에 사용됩니다. 상단 또는 본문에서 변경할 수
            있습니다.
          </p>
        </div>
        <div className="apple-widget-card rounded-[18px] p-4">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-[11px] font-bold uppercase tracking-[0.14em] text-white/55">
              BGM API
            </span>
            <span className="material-symbols-outlined text-lg text-white/28">music_note</span>
          </div>
          <p className="text-[12px] leading-relaxed text-white/38">
            외부 음원 인식은 끄면 호출이 발생하지 않습니다. 키 저장 후 카탈로그 동기화를
            실행하세요.
          </p>
        </div>
        <div className="apple-widget-card rounded-[18px] p-4">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-[11px] font-bold uppercase tracking-[0.14em] text-white/55">
              적용
            </span>
            <span className="material-symbols-outlined text-lg text-white/28">bolt</span>
          </div>
          <p className="text-[12px] leading-relaxed text-white/38">
            UI 배율은 즉시 반영됩니다. 위험 구역 작업은 되돌릴 수 없으니 신중히 진행하세요.
          </p>
        </div>
      </>
    ),
    [],
  );

  const settingsHero = useMemo(
    () => (
      <div className="min-w-0">
        <span className="inline-flex items-center rounded-full bg-white/[0.1] px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.12em] text-white/80 ring-1 ring-white/[0.12]">
          시스템
        </span>
        <h2 className="mt-2 text-[1.65rem] font-bold tracking-tight text-white sm:text-[1.85rem]">
          시스템 설정
        </h2>
        <p className="mt-2 max-w-3xl text-[14px] leading-relaxed text-white/56">
          DB_insight 노드 파라미터 및 보안 프로토콜을 관리합니다.
        </p>
      </div>
    ),
    [],
  );

  const settingsToolbarRight = (
    <button
      type="button"
      onClick={openModal}
      className="inline-flex h-9 items-center gap-1.5 rounded-full bg-white/[0.1] px-3.5 text-[12px] font-semibold text-white/90 ring-1 ring-white/[0.12] transition hover:bg-white/[0.14]"
    >
      <span className="material-symbols-outlined text-base text-white/70">key</span>
      비밀번호
    </button>
  );

  return (
    <div className="studio-bridge-bg relative flex h-screen overflow-hidden text-on-surface">
      <div className="pointer-events-none absolute inset-0 z-0 overflow-hidden">
        <div className="pointer-events-none absolute -left-[14%] -top-[22%] h-[min(520px,92vw)] w-[min(520px,92vw)] rounded-full bg-[rgba(22,62,198,0.34)] blur-[132px]" />
        <div className="pointer-events-none absolute -bottom-[10%] -right-[8%] h-[min(400px,72vw)] w-[min(400px,72vw)] rounded-full bg-[rgba(56,40,124,0.3)] blur-[118px]" />
        <div className="pointer-events-none absolute -bottom-[14%] left-1/4 right-1/4 h-[min(360px,45vh)] rounded-full bg-black/58 blur-[96px]" />
      </div>

      <div className="relative z-10 flex min-h-0 min-w-0 flex-1">
        <StudioThreePaneShell
          discoverTitle="설정"
          areaSubtitle="시스템 설정"
          navSectionLabel="메뉴"
          navItems={navItems}
          footerSub={
            <span className="text-[11px] text-white/40">심층 분석 접근 권한</span>
          }
          breadcrumb={settingsBreadcrumb}
          rightWidgets={settingsRightWidgets}
          titleBar={
            <header
              className="titlebar-chrome-studio z-40 flex h-8 shrink-0 items-center justify-end px-2"
              style={{ WebkitAppRegion: "drag" }}
            >
              <div style={{ WebkitAppRegion: "no-drag" }}>
                <WindowControls />
              </div>
            </header>
          }
          toolbarRight={settingsToolbarRight}
          hero={settingsHero}
          listSectionTitle={null}
        >
          <div className="relative z-10 mx-auto max-w-[46rem] px-4 py-5 sm:px-6 sm:py-6">
            <div className="flex flex-col gap-5">
              {/* 보안 */}
              <section className="di-glass-card settings-glass-strong rounded-md p-6">
                <div className="flex items-center gap-2 mb-5">
                  <span className="text-sm font-manrope uppercase tracking-[0.2em] text-primary font-bold">
                    보안 프로토콜
                  </span>
                  <div className="h-px flex-grow bg-outline-variant/20" />
                </div>
                <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
                  <div>
                    <h3 className="text-base font-semibold text-on-surface mb-1">
                      마스터 인증
                    </h3>
                    <p className="text-sm text-on-surface-variant">
                      마스터 비밀번호는 로컬 데이터베이스를 복호화합니다.
                    </p>
                  </div>
                  <button
                    onClick={openModal}
                    className="shrink-0 rounded-full border border-white/[0.16] bg-white/[0.08] px-6 py-2.5 text-lg font-bold text-white/90 shadow-[0_8px_24px_rgba(0,0,0,0.2),inset_0_1px_0_rgba(255,255,255,0.08)] transition-all duration-200 hover:bg-white/[0.12] active:scale-95 whitespace-nowrap"
                  >
                    비밀번호 변경
                  </button>
                </div>
              </section>

              {/* 환경설정 */}
              <section className="di-glass-card settings-glass-strong rounded-md p-6">
                <div className="flex items-center gap-2 mb-5">
                  <span className="text-sm font-manrope uppercase tracking-[0.2em] text-primary font-bold">
                    환경 설정
                  </span>
                  <div className="h-px flex-grow bg-outline-variant/20" />
                </div>
                <div className="space-y-6">
                  {/* 화면 크기 */}
                  <div>
                    <div className="flex items-center justify-between mb-3">
                      <label className="text-xs uppercase tracking-widest text-on-surface-variant font-bold">
                        화면 크기
                      </label>
                      <div className="flex items-center gap-1.5">
                        {[0.7, 0.8, 0.9, 1.0].map((v) => (
                          <button
                            key={v}
                            onClick={() => setScale(v)}
                            className={`px-2.5 py-1 rounded-lg text-lg font-bold transition-all
                              ${
                                Math.abs(scale - v) < 0.01
                                  ? "bg-primary/20 text-primary border border-primary/30"
                                  : "bg-surface-container-high text-on-surface-variant hover:text-on-surface border border-outline-variant/20"
                              }`}
                          >
                            {Math.round(v * 100)}%
                          </button>
                        ))}
                      </div>
                    </div>
                    <div className="flex items-center gap-3">
                      <span className="text-sm text-on-surface-variant/50 w-8">
                        {Math.round(MIN_SCALE * 100)}%
                      </span>
                      <input
                        type="range"
                        min={MIN_SCALE}
                        max={MAX_SCALE}
                        step={STEP}
                        value={scale}
                        onChange={(e) => setScale(parseFloat(e.target.value))}
                        className="flex-1 h-1.5 rounded-full appearance-none cursor-pointer bg-surface-container-highest
                          [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-4 [&::-webkit-slider-thumb]:h-4
                          [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-primary
                          [&::-webkit-slider-thumb]:shadow-[0_0_8px_rgba(133,173,255,0.5)] [&::-webkit-slider-thumb]:cursor-pointer"
                        style={{
                          background: `linear-gradient(to right, var(--md-sys-color-primary) 0%, var(--md-sys-color-primary) ${((scale - MIN_SCALE) / (MAX_SCALE - MIN_SCALE)) * 100}%, rgba(255,255,255,0.1) ${((scale - MIN_SCALE) / (MAX_SCALE - MIN_SCALE)) * 100}%, rgba(255,255,255,0.1) 100%)`,
                        }}
                      />
                      <span className="text-sm text-on-surface-variant/50 w-8 text-right">
                        {Math.round(MAX_SCALE * 100)}%
                      </span>
                      <span className="text-xs font-bold text-primary w-9 text-right">
                        {Math.round(scale * 100)}%
                      </span>
                    </div>
                    <p className="mt-2 text-base text-on-surface-variant/50">
                      앱 전체 UI 크기를 조절합니다. 즉시 적용됩니다.
                    </p>
                  </div>

                  {/* 토글들 */}
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    {[
                      {
                        label: "클라우드 동기화",
                        desc: "로컬 로그를 암호화된 클라우드에 동기화",
                        value: cloudSync,
                        onChange: () => setCloudSync((v) => !v),
                      },
                      {
                        label: "신경망 피드백",
                        desc: "햅틱 처리 신호 활성화",
                        value: neuralFeedback,
                        onChange: () => setNeuralFeedback((v) => !v),
                      },
                    ].map((item) => (
                      <div
                        key={item.label}
                        className="flex items-center justify-between gap-3 rounded-md border border-white/[0.08] bg-white/[0.04] p-4 backdrop-blur-md"
                      >
                        <div>
                          <p className="text-sm font-semibold text-on-surface">
                            {item.label}
                          </p>
                          <p className="text-xs text-on-surface-variant/80 mt-0.5">
                            {item.desc}
                          </p>
                        </div>
                        <button
                          onClick={item.onChange}
                          className={`shrink-0 w-10 h-5 rounded-full relative cursor-pointer p-1 transition-colors duration-300 ${item.value ? "bg-primary/30" : "bg-surface-container-highest"}`}
                        >
                          <div
                            className={`w-3 h-3 rounded-full absolute top-1 transition-all ${item.value ? "bg-primary right-1" : "bg-outline left-1"}`}
                          />
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              </section>

              {/* BGM 검색 — 외부 API 스위치 */}
              <section className="di-glass-card settings-glass-strong relative overflow-hidden rounded-md border border-pink-500/22 bg-pink-500/[0.04] p-6">
                <div className="absolute -right-16 -bottom-16 w-48 h-48 bg-pink-500/10 blur-[60px] rounded-full" />
                <div className="flex items-center gap-2 mb-5">
                  <span className="material-symbols-outlined text-pink-400">
                    music_note
                  </span>
                  <span className="text-sm font-manrope uppercase tracking-[0.2em] text-pink-400 font-bold">
                    BGM 검색
                  </span>
                  <div className="h-px flex-grow bg-pink-500/20" />
                </div>
                <div className="space-y-4 relative z-10">
                  <p className="text-sm text-on-surface-variant/85">
                    기본은 로컬 모델 (Chromaprint + CLAP)로 검색합니다. 외부
                    ACRCloud API를 켜면 메타데이터 보강 및 fallback으로 이용할
                    수 있습니다.
                  </p>

                  {/* 마스터 토글 */}
                  <div className="rounded-md border border-outline-variant/10 bg-surface-container-low p-4 flex items-center justify-between gap-3">
                    <div>
                      <p className="text-sm font-semibold text-on-surface">
                        외부 음원 인식 API 사용
                      </p>
                      <p className="text-xs text-on-surface-variant/80 mt-0.5">
                        OFF 상태에서는 외부 호출이 0건이며 로컬 모델만
                        사용합니다.
                      </p>
                    </div>
                    <button
                      onClick={() =>
                        updateBgmApi({ api_enabled: !bgmStatus?.api_enabled })
                      }
                      className={`shrink-0 w-10 h-5 rounded-full relative cursor-pointer p-1 transition-colors duration-300
                        ${bgmStatus?.api_enabled ? "bg-pink-400/40" : "bg-surface-container-highest"}`}
                    >
                      <div
                        className={`w-3 h-3 rounded-full absolute top-1 transition-all
                        ${bgmStatus?.api_enabled ? "bg-pink-400 right-1" : "bg-outline left-1"}`}
                      />
                    </button>
                  </div>

                  {/* API 활성 시 키 입력 + 액션 */}
                  {bgmStatus?.api_enabled && (
                    <div className="space-y-3 pl-3 border-l-2 border-pink-500/30">
                      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                        <input
                          type="text"
                          placeholder="ACR Host (예: identify-eu-west-1.acrcloud.com)"
                          value={bgmHost}
                          onChange={(e) => setBgmHost(e.target.value)}
                          className="bg-surface-container-high border border-outline-variant/30 rounded-lg px-3 py-2 text-sm text-on-surface focus:outline-none focus:border-pink-400/60 col-span-1 sm:col-span-3"
                        />
                        <input
                          type="text"
                          placeholder={
                            bgmStatus?.access_key_set
                              ? "access_key (저장됨, 변경 시 입력)"
                              : "access_key"
                          }
                          value={bgmKey}
                          onChange={(e) => setBgmKey(e.target.value)}
                          className="bg-surface-container-high border border-outline-variant/30 rounded-lg px-3 py-2 text-sm text-on-surface focus:outline-none focus:border-pink-400/60"
                        />
                        <input
                          type="password"
                          placeholder={
                            bgmStatus?.access_secret_set
                              ? "access_secret (저장됨)"
                              : "access_secret"
                          }
                          value={bgmSecret}
                          onChange={(e) => setBgmSecret(e.target.value)}
                          className="bg-surface-container-high border border-outline-variant/30 rounded-lg px-3 py-2 text-sm text-on-surface focus:outline-none focus:border-pink-400/60"
                        />
                        <button
                          type="button"
                          onClick={() =>
                            updateBgmApi({
                              host: bgmHost,
                              ...(bgmKey ? { access_key: bgmKey } : {}),
                              ...(bgmSecret
                                ? { access_secret: bgmSecret }
                                : {}),
                            })
                          }
                          className="px-4 py-2 rounded-lg bg-pink-500/20 text-pink-300 border border-pink-400/40 text-sm font-bold hover:bg-pink-500/30 transition"
                        >
                          저장
                        </button>
                      </div>

                      <div className="flex items-center gap-2 text-xs text-on-surface-variant">
                        <span className="material-symbols-outlined text-base">
                          {bgmStatus?.api_configured ? "check_circle" : "error"}
                        </span>
                        {bgmStatus?.api_configured
                          ? "자격증명 등록됨"
                          : "자격증명 미등록 — 키 입력 후 저장하세요"}
                      </div>

                      <div className="flex flex-wrap gap-2">
                        <button
                          type="button"
                          disabled={!bgmStatus?.api_configured || bgmSyncing}
                          onClick={handleSyncCatalog}
                          className="px-4 py-2 rounded-full bg-gradient-to-r from-pink-500 to-rose-500 text-white text-sm font-bold disabled:opacity-40 disabled:cursor-not-allowed hover:shadow-lg hover:shadow-pink-500/30 transition"
                        >
                          {bgmSyncing
                            ? "동기화 중..."
                            : "음원 카탈로그 동기화 (102곡)"}
                        </button>
                        <button
                          type="button"
                          onClick={() =>
                            updateBgmApi({
                              fallback_to_local: !bgmStatus?.fallback_to_local,
                            })
                          }
                          className="px-4 py-2 rounded-full bg-white/5 border border-outline-variant/30 text-on-surface text-sm font-bold hover:bg-white/10 transition"
                        >
                          로컬 fallback:{" "}
                          {bgmStatus?.fallback_to_local ? "ON" : "OFF"}
                        </button>
                        <button
                          type="button"
                          onClick={() =>
                            updateBgmApi({
                              auto_enrich_catalog: !bgmStatus?.auto_enrich,
                            })
                          }
                          className="px-4 py-2 rounded-full bg-white/5 border border-outline-variant/30 text-on-surface text-sm font-bold hover:bg-white/10 transition"
                        >
                          자동 메타 보강:{" "}
                          {bgmStatus?.auto_enrich ? "ON" : "OFF"}
                        </button>
                      </div>
                    </div>
                  )}

                  {bgmMsg && (
                    <div className="text-xs text-on-surface-variant px-2 py-1 bg-white/5 rounded">
                      {bgmMsg}
                    </div>
                  )}
                </div>
              </section>

              {/* 위험 구역 */}
              <section className="di-glass-card settings-glass-strong relative overflow-hidden rounded-md border border-red-500/30 bg-red-500/[0.06] p-6">
                <div className="absolute -right-16 -bottom-16 w-48 h-48 bg-red-500/10 blur-[60px] rounded-full" />
                <div className="flex items-center gap-2 mb-5">
                  <span className="text-sm font-manrope uppercase tracking-[0.2em] text-red-400 font-bold">
                    위험 구역
                  </span>
                  <div className="h-px flex-grow bg-red-500/20" />
                </div>
                <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 relative z-10">
                  <div>
                    <h3 className="text-base font-semibold text-red-400 mb-1">
                      공장 초기화 및 데이터 삭제
                    </h3>
                    <p className="text-sm text-on-surface-variant">
                      모든 인덱스, 로컬 파일, 설정을 영구적으로 삭제합니다.
                    </p>
                  </div>
                  <button className="shrink-0 border border-red-500/40 text-red-400 font-bold py-2.5 px-6 rounded-full text-lg hover:bg-red-500 hover:text-white transition-all duration-200 active:scale-95 whitespace-nowrap">
                    앱 및 데이터 삭제
                  </button>
                </div>
              </section>
            </div>
          </div>
        </StudioThreePaneShell>
      </div>

      {/* ── 비밀번호 변경 모달 ── */}
      {modalOpen && (
        <div className="fixed inset-0 z-[9999] flex items-center justify-center">
          <div
            className="absolute inset-0 bg-black/55 backdrop-blur-md"
            onClick={closeModal}
          />
          <div className="di-glass-card settings-glass-strong relative mx-4 w-full max-w-md rounded-lg p-8 shadow-[0_0_48px_rgba(0,0,0,0.5)]">
            <button
              onClick={closeModal}
              disabled={loading}
              className="absolute top-4 right-4 text-on-surface-variant hover:text-on-surface transition-colors"
            >
              <span className="material-symbols-outlined">close</span>
            </button>
            <h3 className="text-lg font-bold text-on-surface mb-1">
              마스터 비밀번호 변경
            </h3>
            <p className="text-xs text-on-surface-variant mb-6">
              현재 비밀번호를 확인한 후 새 비밀번호로 변경합니다.
            </p>
            {modalSuccess ? (
              <div className="flex flex-col items-center gap-3 py-6">
                <span className="material-symbols-outlined text-4xl text-primary">
                  check_circle
                </span>
                <p className="text-sm font-bold text-on-surface">
                  비밀번호가 변경되었습니다.
                </p>
              </div>
            ) : (
              <form
                onSubmit={handlePasswordChange}
                className="flex flex-col gap-4"
              >
                {[
                  {
                    label: "현재 비밀번호",
                    value: currentPw,
                    onChange: (e) => setCurrentPw(e.target.value),
                    placeholder: "현재 비밀번호 입력",
                  },
                  {
                    label: "새 비밀번호",
                    value: newPw,
                    onChange: (e) => setNewPw(e.target.value),
                    placeholder: "새 비밀번호 입력",
                  },
                  {
                    label: "새 비밀번호 확인",
                    value: confirmPw,
                    onChange: (e) => setConfirmPw(e.target.value),
                    placeholder: "새 비밀번호 다시 입력",
                  },
                ].map((f) => (
                  <div key={f.label} className="flex flex-col gap-1.5">
                    <label className="text-sm uppercase tracking-widest text-on-surface-variant font-bold">
                      {f.label}
                    </label>
                    <input
                      type="password"
                      value={f.value}
                      onChange={f.onChange}
                      required
                      disabled={loading}
                      placeholder={f.placeholder}
                      className="bg-surface-container-high border border-outline-variant/30 rounded-xl px-4 py-2.5 text-lg text-on-surface focus:outline-none focus:border-primary/60 transition-colors disabled:opacity-50"
                    />
                  </div>
                ))}
                {modalError && (
                  <p className="text-xs text-red-400 font-medium">
                    {modalError}
                  </p>
                )}
                <div className="flex gap-3 pt-1">
                  <button
                    type="button"
                    onClick={closeModal}
                    disabled={loading}
                    className="flex-1 py-2.5 rounded-full border border-outline-variant/30 text-lg font-bold text-on-surface-variant hover:text-on-surface transition-all disabled:opacity-50"
                  >
                    취소
                  </button>
                  <button
                    type="submit"
                    disabled={loading}
                    className="flex-1 py-2.5 rounded-full bg-gradient-to-tr from-primary to-secondary text-on-primary text-lg font-bold hover:brightness-110 active:scale-95 transition-all disabled:opacity-50"
                  >
                    {loading ? "변경 중..." : "변경"}
                  </button>
                </div>
              </form>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
