import { useState, useRef, useEffect, useCallback } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import SearchSidebar from "../components/SearchSidebar";
import AnimatedOrb from "../components/AnimatedOrb";
import { useSidebar } from "../context/SidebarContext";
import { useSpeechRecognition } from "../hooks/useSpeechRecognition";
import { useMicLevelRef } from "../hooks/useMicLevelRef";
import { useAIMainViewState } from "../hooks/useAIMainViewState";
import { API_BASE } from "../api";

/** Orb `assembleIntro` 길이와 헤일로 PNG `ai-orbit-halo-emerge` 동기 (초) */
const AI_ORB_ASSEMBLE_SECONDS = 8;

const AI = {
  accent: "#8b5cf6",
  accentLight: "#a78bfa",
  accentDark: "#6d28d9",
  bg: "rgb(1,1,4)",
  leftBg: "rgb(1,1,4)",
  rightBg: "rgb(1,1,4)",
  card: "rgb(1,1,4)",
  border: "rgba(167,139,250,0.24)",
};

const TYPE_META = {
  doc: {
    icon: "description",
    color: "text-[#8cf2ff]",
    label: "문서",
    grad: "from-[#1e3a6e] to-[#5c9dff]",
  },
  video: {
    icon: "movie",
    color: "text-[#ff59e0]",
    label: "동영상",
    grad: "from-[#581c87] to-[#be185d]",
  },
  image: {
    icon: "image",
    color: "text-[#52fac7]",
    label: "이미지",
    grad: "from-[#0f766e] to-[#14b8a6]",
  },
  audio: {
    icon: "volume_up",
    color: "text-[#ff7a5c]",
    label: "음성",
    grad: "from-[#7c2d12] to-[#ea580c]",
  },
  movie: {
    icon: "movie",
    color: "text-[#ff59e0]",
    label: "동영상",
    grad: "from-[#581c87] to-[#be185d]",
  },
  music: {
    icon: "volume_up",
    color: "text-[#ff7a5c]",
    label: "음성",
    grad: "from-[#7c2d12] to-[#ea580c]",
  },
};
const getTypeMeta = (t) =>
  TYPE_META[t] ?? {
    icon: "insert_drive_file",
    color: "text-on-surface-variant",
    label: t ?? "파일",
    grad: "from-[#1c253e] to-[#263354]",
  };

function fmtTime(sec) {
  if (!sec && sec !== 0) return "0:00";
  const s = Math.floor(sec);
  const m = Math.floor(s / 60);
  return `${m}:${String(s % 60).padStart(2, "0")}`;
}

function avStreamUrl(result) {
  const domain =
    result.trichef_domain ?? (result.file_type === "video" ? "movie" : "music");
  return `${API_BASE}/api/admin/file?domain=${domain}&id=${encodeURIComponent(result.file_path)}`;
}

function AVDetailContent({ result }) {
  const isVideo = result.file_type === "video";
  const playerRef = useRef(null);
  const streamUrl = avStreamUrl(result);
  const segments = result.segments ?? [];

  const seekTo = (startSec) => {
    const p = playerRef.current;
    if (!p) return;
    p.currentTime = startSec;
    p.play().catch(() => {});
  };

  return (
    <div className="flex flex-1 flex-col">
      <div className="px-8 pb-4 pt-6">
        <div className="overflow-hidden rounded-xl border border-white/10 bg-black/60">
          {isVideo ? (
            <video
              ref={playerRef}
              src={streamUrl}
              controls
              preload="metadata"
              className="max-h-[280px] w-full object-contain"
              onError={() => {}}
            />
          ) : (
            <div className="flex flex-col items-center justify-center gap-3 p-6">
              <span
                className="material-symbols-outlined text-4xl text-amber-400"
                style={{ fontVariationSettings: '"FILL" 1' }}
              >
                volume_up
              </span>
              <audio
                ref={playerRef}
                src={streamUrl}
                controls
                preload="metadata"
                className="w-full"
                onError={() => {}}
              />
            </div>
          )}
        </div>
      </div>

      {segments.length > 0 && (
        <div className="flex-1 overflow-y-auto px-8 pb-4">
          <p className="mb-3 flex items-center gap-1 text-sm font-bold uppercase tracking-widest text-slate-400">
            <span className="material-symbols-outlined text-base">
              timeline
            </span>
            매칭 구간 ({segments.length}개)
          </p>
          <div className="space-y-2">
            {segments.map((seg, i) => {
              const t0 = seg.start ?? seg.start_sec ?? 0;
              const t1 = seg.end ?? seg.end_sec ?? 0;
              const sc = seg.score ?? 0;
              const text = seg.text || seg.caption || "";
              const pct = Math.round(sc * 100);
              return (
                <button
                  key={i}
                  type="button"
                  onClick={() => seekTo(t0)}
                  className="group/seg w-full rounded-xl border border-white/10 bg-white/[0.04] p-3 text-left transition hover:border-violet-400/40 hover:bg-violet-500/10"
                >
                  <div className="mb-1.5 flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="material-symbols-outlined text-base text-violet-300 transition-transform group-hover/seg:scale-110">
                        play_circle
                      </span>
                      <span className="font-mono text-lg font-bold text-violet-200">
                        {fmtTime(t0)}
                      </span>
                      <span className="text-sm text-slate-500">→</span>
                      <span className="font-mono text-lg text-slate-400">
                        {fmtTime(t1)}
                      </span>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <div className="h-1 w-16 overflow-hidden rounded-full bg-white/10">
                        <div
                          className="h-full rounded-full bg-gradient-to-r from-amber-500 to-violet-500"
                          style={{ width: `${Math.min(pct * 2, 100)}%` }}
                        />
                      </div>
                      <span className="font-mono text-sm tabular-nums text-slate-500">
                        {sc.toFixed(3)}
                      </span>
                    </div>
                  </div>
                  {text && (
                    <p className="line-clamp-2 pl-7 text-xs leading-relaxed text-slate-400">
                      {text}
                    </p>
                  )}
                </button>
              );
            })}
          </div>
        </div>
      )}

      {segments.length === 0 && (
        <div className="flex flex-1 items-center justify-center px-8 text-lg text-slate-500">
          세그먼트 정보 없음
        </div>
      )}
    </div>
  );
}

/** 우측 후보 패널 — 컴팩트 카드 (MainSearch ResultCard 단순화) */
function FileCard({ source, index, scanState, selected, onClick }) {
  const meta = getTypeMeta(source.file_type);
  const pct = (
    (source.confidence ?? source.similarity ?? 0) * 100 || 0
  ).toFixed(0);
  const isScanning = scanState === "scanning";
  const isFound = scanState === "found";
  const isNotFound = scanState === "not_found";

  // 상태별 보더/배경 — 스캔→발견→선택 흐름 시각화
  const stateClass = selected
    ? "border-violet-400/55 bg-violet-500/[0.12] shadow-[0_0_28px_rgba(139,92,246,0.28)]"
    : isFound
      ? "border-emerald-400/45 bg-emerald-500/[0.08] shadow-[0_0_18px_rgba(52,211,153,0.18)]"
      : isScanning
        ? "border-violet-300/40 bg-violet-500/[0.06]"
        : isNotFound
          ? "border-white/[0.06] bg-white/[0.02] opacity-50"
          : "border-white/[0.12] bg-white/[0.03] hover:border-violet-300/35 hover:bg-white/[0.05]";

  return (
    <button
      type="button"
      onClick={() => onClick(source)}
      className={`relative flex flex-col gap-2 overflow-hidden rounded-xl border p-3 text-left transition-all duration-300 ${stateClass}`}
    >
      {/* 스캔 중: 위→아래 스캔라인 (절대 위치 오버레이) */}
      {isScanning && (
        <>
          <div className="pointer-events-none absolute inset-0 bg-gradient-to-b from-transparent via-violet-400/15 to-transparent animate-[scanline_1.4s_ease-in-out_infinite]" />
          <div className="pointer-events-none absolute inset-x-0 top-0 h-[2px] bg-gradient-to-r from-transparent via-violet-300 to-transparent animate-[scanline_1.4s_ease-in-out_infinite] shadow-[0_0_12px_rgba(167,139,250,0.6)]" />
        </>
      )}
      {/* found 진입 시 글로우 펄스 */}
      {isFound && !selected && (
        <div className="pointer-events-none absolute -inset-px rounded-xl ring-1 ring-emerald-400/40 animate-pulse" />
      )}

      <div className="relative flex items-start justify-between gap-2">
        <span
          className={`material-symbols-outlined shrink-0 text-xl ${meta.color}`}
          style={{ fontVariationSettings: '"FILL" 1' }}
        >
          {meta.icon}
        </span>
        <div className="flex items-center gap-1">
          {isFound && (
            <span
              className="material-symbols-outlined text-base text-emerald-300"
              style={{ fontVariationSettings: '"FILL" 1' }}
            >
              check_circle
            </span>
          )}
          {isScanning && (
            <span className="material-symbols-outlined animate-spin text-base text-violet-300">
              progress_activity
            </span>
          )}
          <span
            className={`rounded-full px-2 py-0.5 text-[10px] font-bold text-white ${
              isFound
                ? "bg-emerald-500/95"
                : isScanning
                  ? "bg-violet-500/95"
                  : "bg-emerald-600/90"
            }`}
          >
            #{index + 1}
          </span>
        </div>
      </div>
      <div className="relative line-clamp-2 text-[12px] font-semibold text-slate-100">
        {source.file_name}
      </div>
      <div className="relative flex items-center justify-between text-[10px]">
        <span
          className={`uppercase tracking-wide ${
            isScanning
              ? "text-violet-300 font-bold"
              : isFound
                ? "text-emerald-300 font-bold"
                : isNotFound
                  ? "text-slate-600"
                  : "text-slate-500"
          }`}
        >
          {isScanning
            ? "스캔 중…"
            : isFound
              ? "✓ 매칭"
              : isNotFound
                ? "미매칭"
                : "대기"}
        </span>
        <span className="font-mono text-violet-200/90">{pct}%</span>
      </div>
    </button>
  );
}

// [legacy] aimodeAnswer 카드(turns.length===0 폴백)에서만 사용되는 평문화 폴리필.
function stripMarkdown(text) {
  if (!text) return text;
  return text
    .replace(/\*\*(.+?)\*\*/g, "$1")
    .replace(/(?<![*\w])\*(.+?)\*(?!\*)/g, "$1")
    .replace(/^#{1,6}\s+/gm, "")
    .replace(/`([^`\n]+)`/g, "$1")
    .replace(/^>\s+/gm, "")
    .replace(/^[-*_]{3,}\s*$/gm, "")
    .replace(/^(\s*)[-*]\s+/gm, "$1• ");
}

// [v3.2] 마크다운 → React 노드 렌더러 (## 헤딩, - 불릿, **굵게**, [출처N] 칩).
// 백엔드가 간결한 마크다운으로 답변하도록 프롬프팅됨.
function renderInlineMd(text, baseKey = "i") {
  if (!text) return null;
  // 1단계: [출처N] 토큰 분리
  const segments = text.split(/(\[출처\d+\])/g);
  const out = [];
  segments.forEach((seg, segIdx) => {
    if (/^\[출처\d+\]$/.test(seg)) {
      out.push(
        <span
          key={`${baseKey}-src-${segIdx}`}
          style={{
            background: "rgba(139,92,246,0.2)",
            color: "#a78bfa",
            border: "1px solid rgba(139,92,246,0.3)",
            fontWeight: 700,
            fontSize: 11,
            padding: "1px 6px",
            borderRadius: 5,
            margin: "0 2px",
            verticalAlign: "middle",
            display: "inline-block",
          }}
        >
          {seg}
        </span>,
      );
      return;
    }
    // 2단계: **bold** / `code` / *italic*
    const re = /(\*\*[^*\n]+\*\*)|(`[^`\n]+`)|(\*[^*\n]+\*)/g;
    let last = 0;
    let m;
    let tokIdx = 0;
    while ((m = re.exec(seg)) !== null) {
      if (m.index > last)
        out.push(
          <span key={`${baseKey}-${segIdx}-t${tokIdx++}`}>{seg.slice(last, m.index)}</span>,
        );
      const tok = m[0];
      if (tok.startsWith("**"))
        out.push(
          <strong
            key={`${baseKey}-${segIdx}-t${tokIdx++}`}
            style={{ color: "#f5f3ff", fontWeight: 700 }}
          >
            {tok.slice(2, -2)}
          </strong>,
        );
      else if (tok.startsWith("`"))
        out.push(
          <code
            key={`${baseKey}-${segIdx}-t${tokIdx++}`}
            style={{
              padding: "1px 6px",
              borderRadius: 4,
              background: "rgba(139,92,246,0.15)",
              border: "1px solid rgba(139,92,246,0.25)",
              color: "#e9d5ff",
              fontFamily: "ui-monospace, monospace",
              fontSize: "0.92em",
            }}
          >
            {tok.slice(1, -1)}
          </code>,
        );
      else
        out.push(
          <em
            key={`${baseKey}-${segIdx}-t${tokIdx++}`}
            style={{ color: "#e9d5ff", fontStyle: "italic" }}
          >
            {tok.slice(1, -1)}
          </em>,
        );
      last = m.index + tok.length;
    }
    if (last < seg.length)
      out.push(<span key={`${baseKey}-${segIdx}-t${tokIdx++}`}>{seg.slice(last)}</span>);
  });
  return out;
}

function MarkdownAnswer({ text }) {
  if (!text) return null;
  const lines = text.split("\n");
  const blocks = [];
  let para = [];
  let list = null;

  const flushPara = () => {
    if (para.length) {
      blocks.push(
        <p
          key={`p${blocks.length}`}
          style={{
            margin: "0 0 8px 0",
            lineHeight: 1.7,
          }}
        >
          {renderInlineMd(para.join(" "), `p${blocks.length}`)}
        </p>,
      );
      para = [];
    }
  };
  const flushList = () => {
    if (list && list.items.length) {
      const Tag = list.type === "ol" ? "ol" : "ul";
      blocks.push(
        <Tag
          key={`l${blocks.length}`}
          style={{
            margin: "4px 0 10px 0",
            paddingLeft: 22,
            lineHeight: 1.7,
          }}
        >
          {list.items.map((it, i) => (
            <li
              key={i}
              style={{
                marginBottom: 4,
                color: "#f1f5f9",
                paddingLeft: 4,
              }}
            >
              {renderInlineMd(it, `li${blocks.length}-${i}`)}
            </li>
          ))}
        </Tag>,
      );
      list = null;
    }
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trimEnd();
    if (!line.trim()) {
      flushPara();
      flushList();
      continue;
    }
    let m;
    // 헤딩
    if ((m = /^###\s+(.+)$/.exec(line))) {
      flushPara();
      flushList();
      blocks.push(
        <h4
          key={`h${blocks.length}`}
          style={{
            margin: "10px 0 6px 0",
            fontSize: 14,
            fontWeight: 700,
            color: "#c4b5fd",
          }}
        >
          {renderInlineMd(m[1], `h${blocks.length}`)}
        </h4>,
      );
      continue;
    }
    if ((m = /^##\s+(.+)$/.exec(line))) {
      flushPara();
      flushList();
      blocks.push(
        <h3
          key={`h${blocks.length}`}
          style={{
            margin: "12px 0 8px 0",
            fontSize: 15,
            fontWeight: 700,
            color: "#f5f3ff",
            paddingLeft: 8,
            borderLeft: "3px solid #a78bfa",
          }}
        >
          {renderInlineMd(m[1], `h${blocks.length}`)}
        </h3>,
      );
      continue;
    }
    if ((m = /^#\s+(.+)$/.exec(line))) {
      flushPara();
      flushList();
      blocks.push(
        <h3
          key={`h${blocks.length}`}
          style={{
            margin: "12px 0 8px 0",
            fontSize: 16,
            fontWeight: 700,
            color: "#f5f3ff",
          }}
        >
          {renderInlineMd(m[1], `h${blocks.length}`)}
        </h3>,
      );
      continue;
    }
    // 수평선
    if (/^[-*_]{3,}\s*$/.test(line)) {
      flushPara();
      flushList();
      blocks.push(
        <hr
          key={`hr${blocks.length}`}
          style={{
            margin: "10px 0",
            border: "none",
            borderTop: "1px solid rgba(139,92,246,0.2)",
          }}
        />,
      );
      continue;
    }
    // 순서 있는 리스트
    if ((m = /^\d+\.\s+(.+)$/.exec(line))) {
      flushPara();
      if (!list || list.type !== "ol") {
        flushList();
        list = { type: "ol", items: [] };
      }
      list.items.push(m[1]);
      continue;
    }
    // 순서 없는 리스트
    if ((m = /^[-*]\s+(.+)$/.exec(line))) {
      flushPara();
      if (!list || list.type !== "ul") {
        flushList();
        list = { type: "ul", items: [] };
      }
      list.items.push(m[1]);
      continue;
    }
    // 일반 문단
    flushList();
    para.push(line.trim());
  }
  flushPara();
  flushList();
  return <div>{blocks}</div>;
}

function isNoInfoCenterAlert(text) {
  if (!text) return false;
  const normalized = text.replace(/\s+/g, " ").trim();
  return /제공\s*문서에\s*해당\s*정보가\s*없습니다/.test(normalized);
}

// turn 초기값
const makeTurn = (id, query) => ({
  id,
  query,
  route: "", // 'rag' | 'chat' | 'followup' | 'qa_gen'
  intentMessage: "",
  fileKeywords: [],
  detailKeywords: [],
  candidates: [],
  scanStates: {},
  scanChunks: {},
  scannedCount: 0,
  foundCount: 0,
  sources: [],
  answer: "",
  streaming: true,
  done: false,
  error: null,
  // key_facts & generating
  keyFacts: [],
  generating: false,
  // qa_gen 전용
  qaGenerating: false,
  qaAttempt: 0,
  qaMax: 3,
  qaQuestion: "",
  qaAnswer: "",
  qaValid: false,
  qaIssues: [],
  qaSources: [],
  // 보안 모드: SecurityCritic 차단/마스킹 결과
  blocked: null, // { stage: 'stream'|'final', reason, pii_types }
  security: null, // { masked: bool, pii_types, reason }
});

// ── AI 아바타 ─────────────────────────────────────────────────────
// isLatest=true 이면 실제 AnimatedOrb, 아니면 CSS 버전
function AIAvatar({ isLatest, size = 30 }) {
  if (isLatest) {
    return (
      <div
        style={{
          position: "relative",
          width: size,
          height: size,
          borderRadius: "50%",
          overflow: "hidden",
          flexShrink: 0,
          marginTop: 4,
          boxShadow:
            "0 0 0 1px rgba(167,139,250,0.34), 0 0 16px rgba(139,92,246,0.3)",
        }}
      >
        <div
          style={{
            position: "absolute",
            inset: -2,
            borderRadius: "50%",
            border: "1px solid rgba(167,139,250,0.35)",
            animation: "ai-avatar-pulse 1.8s ease-in-out infinite",
            pointerEvents: "none",
            zIndex: 2,
          }}
        />
        <AnimatedOrb
          size={size}
          layout="fill"
          colorMode="ai"
          hideCenterUI
          interactive={false}
          aiHoverFx={false}
        />
      </div>
    );
  }
  return (
    <div
      style={{
        width: size,
        height: size,
        borderRadius: "50%",
        flexShrink: 0,
        marginTop: 4,
        background:
          "radial-gradient(circle at 36% 30%, #c4b5fd 0%, #7c3aed 50%, #3b0764 100%)",
        boxShadow:
          "0 0 8px rgba(139,92,246,0.45), inset 0 1px 0 rgba(255,255,255,0.15)",
      }}
    />
  );
}

// ── ScanLogItem ────────────────────────────────────────────────────
function ScanLogItem({ fileName, fileType, scanState }) {
  const meta = getTypeMeta(fileType);
  const isFound = scanState === "found",
    isNF = scanState === "not_found",
    isScan = scanState === "scanning";
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
        padding: "4px 10px",
        borderRadius: 7,
        background: isScan
          ? "rgba(139,92,246,0.07)"
          : isFound
            ? "rgba(16,185,129,0.07)"
            : "transparent",
        border: `1px solid ${isScan ? "rgba(139,92,246,0.2)" : isFound ? "rgba(16,185,129,0.2)" : "transparent"}`,
        opacity: isNF ? 0.35 : 1,
        transition: "all 0.3s",
      }}
    >
      <span
        className="material-symbols-outlined"
        style={{
          fontSize: 13,
          color: meta.color,
          flexShrink: 0,
          fontVariationSettings: '"FILL" 1',
        }}
      >
        {meta.icon}
      </span>
      <span
        style={{
          flex: 1,
          fontSize: 12.5,
          color: "#94a3b8",
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}
      >
        {fileName}
      </span>
      <span
        style={{
          fontSize: 11,
          fontWeight: 700,
          flexShrink: 0,
          display: "flex",
          alignItems: "center",
          gap: 3,
          color: isScan ? "#a78bfa" : isFound ? "#10b981" : "#475569",
        }}
      >
        {isScan && (
          <span
            className="material-symbols-outlined ai-spin"
            style={{ fontSize: 10 }}
          >
            progress_activity
          </span>
        )}
        {isFound && (
          <span className="material-symbols-outlined" style={{ fontSize: 10 }}>
            check_circle
          </span>
        )}
        {isNF && (
          <span className="material-symbols-outlined" style={{ fontSize: 10 }}>
            cancel
          </span>
        )}
        {isScan ? "스캔 중" : isFound ? "발견됨" : isNF ? "없음" : "대기"}
      </span>
    </div>
  );
}

// ── QACard — 문제/정답 카드 ───────────────────────────────────────
function QACard({
  question,
  answer,
  attempt,
  qaMax,
  valid,
  issues,
  sources,
  generating,
}) {
  if (generating) {
    return (
      <div
        style={{
          padding: "16px 18px",
          borderRadius: 12,
          background: "rgba(234,179,8,0.06)",
          border: "1px solid rgba(234,179,8,0.2)",
          display: "flex",
          alignItems: "center",
          gap: 10,
          marginBottom: 6,
        }}
      >
        <span
          className="material-symbols-outlined ai-spin"
          style={{ fontSize: 16, color: "#eab308" }}
        >
          progress_activity
        </span>
        <div>
          <div
            style={{
              fontSize: 11,
              fontWeight: 700,
              color: "#eab308",
              marginBottom: 2,
            }}
          >
            문제 생성 중… ({attempt}/{qaMax}회 시도)
          </div>
          <div style={{ fontSize: 10, color: "#78716c" }}>
            문서 표현 기반 QA 생성 + 검증 중
          </div>
        </div>
      </div>
    );
  }
  if (!question && !answer) return null;
  return (
    <div style={{ marginBottom: 6 }}>
      {/* 질문 카드 */}
      <div
        style={{
          padding: "14px 16px",
          borderRadius: "12px 12px 4px 4px",
          marginBottom: 3,
          background:
            "linear-gradient(135deg, rgba(234,179,8,0.1), rgba(234,179,8,0.06))",
          border: "1px solid rgba(234,179,8,0.3)",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            marginBottom: 8,
          }}
        >
          <span
            className="material-symbols-outlined"
            style={{
              fontSize: 13,
              color: "#eab308",
              fontVariationSettings: '"FILL" 1',
            }}
          >
            quiz
          </span>
          <span
            style={{
              fontSize: 10,
              fontWeight: 800,
              color: "#eab308",
              letterSpacing: "0.1em",
              textTransform: "uppercase",
            }}
          >
            문제
          </span>
          <span
            style={{
              fontSize: 9,
              marginLeft: "auto",
              color: "#78716c",
              fontWeight: 600,
            }}
          >
            시도 {attempt}회
          </span>
          {valid ? (
            <span
              style={{
                display: "flex",
                alignItems: "center",
                gap: 2,
                fontSize: 9,
                fontWeight: 700,
                color: "#22c55e",
              }}
            >
              <span
                className="material-symbols-outlined"
                style={{ fontSize: 10 }}
              >
                verified
              </span>
              검증 통과
            </span>
          ) : (
            <span
              style={{
                display: "flex",
                alignItems: "center",
                gap: 2,
                fontSize: 9,
                fontWeight: 700,
                color: "#f59e0b",
              }}
            >
              <span
                className="material-symbols-outlined"
                style={{ fontSize: 10 }}
              >
                warning
              </span>
              최선 결과
            </span>
          )}
        </div>
        <p
          style={{
            fontSize: 13.5,
            color: "#fef3c7",
            lineHeight: 1.7,
            margin: 0,
            fontWeight: 500,
          }}
        >
          {question}
        </p>
      </div>
      {/* 정답 카드 */}
      <div
        style={{
          padding: "14px 16px",
          borderRadius: "4px 4px 12px 12px",
          background: "rgba(16,185,129,0.06)",
          border: "1px solid rgba(16,185,129,0.22)",
          borderTop: "none",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            marginBottom: 8,
          }}
        >
          <span
            className="material-symbols-outlined"
            style={{
              fontSize: 13,
              color: "#10b981",
              fontVariationSettings: '"FILL" 1',
            }}
          >
            lightbulb
          </span>
          <span
            style={{
              fontSize: 10,
              fontWeight: 800,
              color: "#10b981",
              letterSpacing: "0.1em",
              textTransform: "uppercase",
            }}
          >
            모범 답안
          </span>
        </div>
        <p
          style={{
            fontSize: 13,
            color: "#d1fae5",
            lineHeight: 1.85,
            margin: 0,
            whiteSpace: "pre-wrap",
          }}
        >
          {answer}
        </p>
      </div>
      {/* 출처 + 검증 이슈 */}
      {(sources?.length > 0 || issues?.length > 0) && (
        <div
          style={{ marginTop: 6, display: "flex", flexWrap: "wrap", gap: 5 }}
        >
          {sources?.map((s, i) => (
            <span
              key={i}
              style={{
                fontSize: 9,
                fontWeight: 700,
                padding: "2px 8px",
                borderRadius: 999,
                background: "rgba(234,179,8,0.1)",
                color: "#ca8a04",
                border: "1px solid rgba(234,179,8,0.2)",
              }}
            >
              📄 {s}
            </span>
          ))}
          {issues?.map((iss, i) => (
            <span
              key={`iss-${i}`}
              style={{
                fontSize: 9,
                padding: "2px 8px",
                borderRadius: 999,
                background: "rgba(239,68,68,0.08)",
                color: "#f87171",
                border: "1px solid rgba(239,68,68,0.15)",
              }}
            >
              ⚠ {iss}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

// ── TurnView (하나의 대화 턴) ──────────────────────────────────────
function TurnView({ turn, isLatest, onClickSource, onClickFile }) {
  // [v3 chat] turn 객체가 누락 필드를 가질 수 있어 default 값 안전 가드.
  // 채팅방 복원 시 또는 v3 done 핸들러가 push 한 turn 은 일부 필드만 채움.
  const {
    query           = "",
    route           = "",
    intentMessage   = "",
    fileKeywords    = [],
    detailKeywords  = [],
    candidates      = [],
    scanStates      = {},
    scanChunks      = {},
    scannedCount    = 0,
    foundCount      = 0,
    sources         = [],
    answer          = "",
    streaming       = false,
    done            = true,
    error           = null,
    keyFacts        = [],
    generating      = false,
    qaGenerating    = false,
    qaAttempt       = 0,
    qaMax           = 0,
    qaQuestion      = "",
    qaAnswer        = "",
    qaValid         = false,
    qaIssues        = [],
    qaSources       = [],
    blocked         = null,
    security        = null,
    references      = [],   // [v3 chat] turn 의 원본 위치 references (extract 노드)
  } = turn || {};
  const isChatMode = route === "chat";
  const isQaMode = route === "qa_gen";
  const showCenterNotice = done && !streaming && isNoInfoCenterAlert(answer);
  const shouldRenderInlineAnswer =
    answer && !isQaMode && !blocked && !showCenterNotice;
  const hasAiBlockContent =
    intentMessage ||
    candidates.length > 0 ||
    shouldRenderInlineAnswer ||
    error ||
    blocked ||
    security?.masked ||
    (done && sources.length > 0) ||
    (!isChatMode && !isQaMode && generating && !answer) ||
    (isQaMode && (qaGenerating || qaQuestion)) ||
    (!isChatMode && !isQaMode && keyFacts && keyFacts.length > 0);

  return (
    <div style={{ marginBottom: 28 }}>
      {/* 사용자 버블 */}
      <div
        style={{
          display: "flex",
          justifyContent: "flex-end",
          marginBottom: 16,
        }}
      >
        <div
          style={{
            maxWidth: "78%",
            padding: "11px 16px",
            background:
              "linear-gradient(135deg, rgba(91,33,182,0.58), rgba(109,40,217,0.46), rgba(124,58,237,0.56))",
            borderRadius: "18px 18px 4px 18px",
            fontSize: 15,
            color: "#f5f3ff",
            lineHeight: 1.7,
            boxShadow:
              "0 10px 28px rgba(76,29,149,0.3), inset 0 1px 0 rgba(255,255,255,0.22)",
            border: "1px solid rgba(196,181,253,0.26)",
            backdropFilter: "blur(10px) saturate(1.08)",
            letterSpacing: "-0.01em",
          }}
        >
          {query}
        </div>
      </div>

      {/* AI 응답 블록 */}
      {hasAiBlockContent && (
        <div style={{ display: "flex", gap: 10 }}>
          {/* 아바타 (실제 오브 또는 CSS 오브) */}
          <AIAvatar isLatest={isLatest} size={28} />

          <div style={{ flex: 1, minWidth: 0 }}>
            {/* route 뱃지 */}
            {route === "chat" && (
              <div
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 5,
                  marginBottom: 8,
                  padding: "3px 10px",
                  borderRadius: 999,
                  fontSize: 10,
                  fontWeight: 700,
                  letterSpacing: "0.08em",
                  textTransform: "uppercase",
                  background: "rgba(16,185,129,0.1)",
                  color: "#10b981",
                  border: "1px solid rgba(16,185,129,0.2)",
                }}
              >
                <span
                  style={{
                    width: 4,
                    height: 4,
                    borderRadius: "50%",
                    background: "currentColor",
                    flexShrink: 0,
                  }}
                />
                Chat · 일반 대화
              </div>
            )}
            {route === "followup" && (
              <div
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 5,
                  marginBottom: 8,
                  padding: "3px 10px",
                  borderRadius: 999,
                  fontSize: 10,
                  fontWeight: 700,
                  letterSpacing: "0.08em",
                  textTransform: "uppercase",
                  background: "rgba(6,182,212,0.1)",
                  color: "#06b6d4",
                  border: "1px solid rgba(6,182,212,0.2)",
                }}
              >
                <span
                  style={{
                    width: 4,
                    height: 4,
                    borderRadius: "50%",
                    background: "currentColor",
                    flexShrink: 0,
                  }}
                />
                Followup · 이전 파일 재사용
              </div>
            )}
            {route === "qa_gen" && (
              <div
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 5,
                  marginBottom: 8,
                  padding: "3px 10px",
                  borderRadius: 999,
                  fontSize: 10,
                  fontWeight: 700,
                  letterSpacing: "0.08em",
                  textTransform: "uppercase",
                  background: "rgba(234,179,8,0.1)",
                  color: "#eab308",
                  border: "1px solid rgba(234,179,8,0.25)",
                }}
              >
                <span
                  style={{
                    width: 4,
                    height: 4,
                    borderRadius: "50%",
                    background: "currentColor",
                    flexShrink: 0,
                  }}
                />
                QA Gen · 문제 생성
              </div>
            )}

            {/* 의도 + 키워드 */}
            {!isChatMode && intentMessage && (
              <div
                style={{
                  display: "inline-block",
                  width: "fit-content",
                  maxWidth: "92%",
                  padding: "11px 15px",
                  marginBottom: 8,
                  background: "rgba(109,40,217,0.08)",
                  border: "1px solid rgba(167,139,250,0.28)",
                  borderRadius: "4px 16px 16px 16px",
                  fontSize: 14.5,
                  color: "#c4b5fd",
                  lineHeight: 1.65,
                  fontWeight: 500,
                  backdropFilter: "blur(8px) saturate(1.06)",
                }}
              >
                {intentMessage}
                {(fileKeywords.length > 0 || detailKeywords.length > 0) && (
                  <div
                    style={{
                      display: "flex",
                      flexWrap: "wrap",
                      gap: 5,
                      marginTop: 9,
                    }}
                  >
                    {fileKeywords.map((kw, i) => (
                      <span
                        key={`f${i}`}
                        style={{
                          display: "inline-flex",
                          alignItems: "center",
                          gap: 3,
                          padding: "3px 10px",
                          borderRadius: 999,
                          fontSize: 11,
                          fontWeight: 700,
                          background: "rgba(139,92,246,0.15)",
                          color: AI.accentLight,
                          border: `1px solid ${AI.border}`,
                        }}
                      >
                        <span
                          className="material-symbols-outlined"
                          style={{ fontSize: 11 }}
                        >
                          folder_search
                        </span>
                        {kw}
                      </span>
                    ))}
                    {detailKeywords.map((kw, i) => (
                      <span
                        key={`d${i}`}
                        style={{
                          display: "inline-flex",
                          alignItems: "center",
                          gap: 3,
                          padding: "3px 10px",
                          borderRadius: 999,
                          fontSize: 11,
                          fontWeight: 700,
                          background: "rgba(16,185,129,0.1)",
                          color: "#34d399",
                          border: "1px solid rgba(16,185,129,0.2)",
                        }}
                      >
                        <span
                          className="material-symbols-outlined"
                          style={{ fontSize: 11 }}
                        >
                          manage_search
                        </span>
                        {kw}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* 스캔 로그 — chat 모드에서는 숨김 */}
            {!isChatMode && candidates.length > 0 && (
              <div
                style={{
                  marginBottom: 8,
                  padding: "10px 12px",
                  background: "rgba(8,5,20,0.5)",
                  border: `1px solid ${AI.border}`,
                  borderRadius: 10,
                }}
              >
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    marginBottom: 6,
                  }}
                >
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 5,
                      fontSize: 10,
                      fontWeight: 700,
                      color: AI.accentLight,
                    }}
                  >
                    <span
                      className="material-symbols-outlined"
                      style={{ fontSize: 12 }}
                    >
                      radar
                    </span>
                    파일 스캔 {scannedCount}/{candidates.length}
                  </div>
                  {foundCount > 0 && (
                    <span
                      style={{
                        fontSize: 10,
                        color: "#10b981",
                        fontWeight: 700,
                      }}
                    >
                      {foundCount}개 발견
                    </span>
                  )}
                </div>
                <div
                  style={{ display: "flex", flexDirection: "column", gap: 2 }}
                >
                  {candidates.map((src, i) => {
                    const fid = src.trichef_id || src.file_name || String(i);
                    return (
                      <ScanLogItem
                        key={fid}
                        fileName={src.file_name || "?"}
                        fileType={src.file_type || ""}
                        scanState={scanStates[fid] || "idle"}
                      />
                    );
                  })}
                </div>
                {candidates.length > 0 && (
                  <div
                    style={{
                      marginTop: 7,
                      height: 2,
                      borderRadius: 999,
                      background: "rgba(139,92,246,0.08)",
                      overflow: "hidden",
                    }}
                  >
                    <div
                      style={{
                        height: "100%",
                        borderRadius: 999,
                        transition: "width 0.4s ease",
                        width: `${candidates.length > 0 ? (scannedCount / candidates.length) * 100 : 0}%`,
                        background:
                          "linear-gradient(90deg,#6d28d9,#8b5cf6,#a78bfa)",
                      }}
                    />
                  </div>
                )}
              </div>
            )}

            {/* QA 생성 카드 (qa_gen 모드) */}
            {isQaMode && (qaGenerating || qaQuestion) && (
              <QACard
                question={qaQuestion}
                answer={qaAnswer}
                attempt={qaAttempt}
                qaMax={qaMax}
                valid={qaValid}
                issues={qaIssues}
                sources={qaSources}
                generating={qaGenerating}
              />
            )}

            {/* 📌 핵심 인용 — key_facts (rag 모드, 스캔 후 생성 전) */}
            {!isChatMode && !isQaMode && keyFacts && keyFacts.length > 0 && (
              <div
                style={{
                  marginBottom: 8,
                  padding: "10px 14px",
                  background: "rgba(16,185,129,0.05)",
                  border: "1px solid rgba(16,185,129,0.22)",
                  borderRadius: 10,
                }}
              >
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 5,
                    marginBottom: 8,
                  }}
                >
                  <span
                    className="material-symbols-outlined"
                    style={{
                      fontSize: 13,
                      color: "#10b981",
                      fontVariationSettings: '"FILL" 1',
                    }}
                  >
                    format_quote
                  </span>
                  <span
                    style={{
                      fontSize: 10,
                      fontWeight: 800,
                      color: "#10b981",
                      letterSpacing: "0.1em",
                      textTransform: "uppercase",
                    }}
                  >
                    핵심 인용
                  </span>
                  <span
                    style={{
                      fontSize: 9,
                      color: "#475569",
                      marginLeft: "auto",
                    }}
                  >
                    문서에서 직접 추출
                  </span>
                </div>
                <div
                  style={{ display: "flex", flexDirection: "column", gap: 5 }}
                >
                  {keyFacts.map((fact, i) => (
                    <div
                      key={i}
                      style={{
                        padding: "6px 10px",
                        borderRadius: 7,
                        background: "rgba(16,185,129,0.07)",
                        border: "1px solid rgba(16,185,129,0.15)",
                        fontSize: 11.5,
                        color: "#a7f3d0",
                        lineHeight: 1.6,
                        borderLeft: "3px solid rgba(16,185,129,0.5)",
                      }}
                    >
                      "{fact}"
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* 답변 생성 중 인디케이터 */}
            {!isChatMode && !isQaMode && generating && !answer && (
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  padding: "10px 14px",
                  marginBottom: 6,
                  background: "rgba(109,40,217,0.07)",
                  border: "1px solid rgba(139,92,246,0.2)",
                  borderRadius: 10,
                }}
              >
                <span
                  className="material-symbols-outlined ai-spin"
                  style={{ fontSize: 14, color: AI.accentLight }}
                >
                  progress_activity
                </span>
                <span
                  style={{
                    fontSize: 12,
                    color: AI.accentLight,
                    fontWeight: 600,
                  }}
                >
                  답변 생성 중…
                </span>
              </div>
            )}

            {/* 보안 차단 안내 */}
            {blocked && (
              <div
                style={{
                  padding: "10px 14px",
                  marginBottom: 6,
                  background: "rgba(127,29,29,0.18)",
                  border: "1px solid rgba(248,113,113,0.4)",
                  borderRadius: 10,
                  fontSize: 13,
                  color: "#fecaca",
                  display: "flex",
                  alignItems: "flex-start",
                  gap: 8,
                  lineHeight: 1.6,
                }}
              >
                <span
                  className="material-symbols-outlined"
                  style={{
                    fontSize: 18,
                    color: "#f87171",
                    marginTop: 1,
                    fontVariationSettings: '"FILL" 1',
                  }}
                >
                  shield
                </span>
                <div>
                  <div style={{ fontWeight: 600, marginBottom: 2 }}>
                    보안 모드: 응답이 차단되었습니다
                  </div>
                  <div style={{ opacity: 0.9 }}>{blocked.reason}</div>
                  {blocked.pii_types && blocked.pii_types.length > 0 && (
                    <div style={{ marginTop: 4, fontSize: 11, opacity: 0.7 }}>
                      탐지: {blocked.pii_types.join(", ")} · 단계:{" "}
                      {blocked.stage}
                    </div>
                  )}
                </div>
              </div>
            )}
            {/* 보안 마스킹 안내 */}
            {security?.masked && !blocked && (
              <div
                style={{
                  padding: "8px 12px",
                  marginBottom: 6,
                  background: "rgba(120,53,15,0.18)",
                  border: "1px solid rgba(251,191,36,0.35)",
                  borderRadius: 10,
                  fontSize: 12,
                  color: "#fde68a",
                  display: "flex",
                  alignItems: "center",
                  gap: 6,
                }}
              >
                <span
                  className="material-symbols-outlined"
                  style={{
                    fontSize: 16,
                    color: "#fbbf24",
                    fontVariationSettings: '"FILL" 1',
                  }}
                >
                  shield
                </span>
                <span>
                  보안 모드: 개인정보({(security.pii_types || []).join(", ")})가
                  마스킹되었습니다.
                </span>
              </div>
            )}
            {/* [v3 chat] 원본 위치 references — **답변 위에 먼저 표시** (출처가 답변 근거).
                streaming 중에도 references 채워지면 표시 (extract 이벤트가 generate 이전). */}
            {references.length > 0 && (
              <div
                style={{
                  marginBottom: 10,
                  display: "flex",
                  flexDirection: "column",
                  gap: 6,
                }}
              >
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 6,
                    color: "#6ee7b7",
                    fontSize: 10.5,
                    fontWeight: 700,
                    letterSpacing: "0.14em",
                    textTransform: "uppercase",
                  }}
                >
                  <span
                    className="material-symbols-outlined"
                    style={{ fontSize: 14, fontVariationSettings: '"FILL" 1' }}
                  >
                    bookmark
                  </span>
                  출처 ({references.length})
                </div>
                <div
                  style={{
                    display: "flex",
                    flexWrap: "wrap",
                    gap: 6,
                  }}
                >
                  {references.slice(0, 10).map((ref, i) => {
                    const tag =
                      ref.page != null
                        ? `${ref.page}페이지`
                        : ref.timestamp
                          ? ref.timestamp
                          : "";
                    return (
                      <button
                        key={i}
                        type="button"
                        onClick={() => {
                          // [v3.1] sources 중 file_name 일치하는 source 찾아서 보강 → handleSelectFile 가 detail fetch 가능
                          const matched = sources.find(
                            (s) =>
                              s.file_name === ref.src ||
                              s.file_name?.includes(ref.src),
                          );
                          onClickSource?.({
                            ...(matched || {}),
                            file_name:    ref.src,
                            page_num:     ref.page,
                            timestamp:    ref.timestamp,
                            snippet:      ref.snippet,
                            trichef_id:   ref.trichef_id || matched?.trichef_id,
                            file_path:    ref.file_path  || matched?.file_path,
                            selected_page: ref.page,
                            _from_ref:    true,
                          });
                        }}
                        title={ref.snippet || ""}
                        style={{
                          display: "inline-flex",
                          alignItems: "center",
                          gap: 6,
                          padding: "4px 10px",
                          borderRadius: 9,
                          fontSize: 11,
                          fontWeight: 600,
                          color: "#bbf7d0",
                          background: "rgba(16,185,129,0.12)",
                          border: "1px solid rgba(16,185,129,0.30)",
                          cursor: "pointer",
                          transition: "all 0.15s",
                        }}
                        onMouseEnter={(e) => {
                          e.currentTarget.style.background = "rgba(16,185,129,0.25)";
                          e.currentTarget.style.borderColor = "rgba(16,185,129,0.55)";
                        }}
                        onMouseLeave={(e) => {
                          e.currentTarget.style.background = "rgba(16,185,129,0.12)";
                          e.currentTarget.style.borderColor = "rgba(16,185,129,0.30)";
                        }}
                      >
                        {/* [v3.1] 순서 변경: 파일 → 페이지 */}
                        <span
                          style={{
                            opacity: 0.92,
                            maxWidth: 180,
                            overflow: "hidden",
                            textOverflow: "ellipsis",
                            whiteSpace: "nowrap",
                          }}
                        >
                          {ref.src}
                        </span>
                        {tag && (
                          <span
                            style={{
                              fontWeight: 700,
                              padding: "1px 6px",
                              borderRadius: 4,
                              background: "rgba(16,185,129,0.25)",
                              color: "#86efac",
                            }}
                          >
                            {tag}
                          </span>
                        )}
                      </button>
                    );
                  })}
                </div>
              </div>
            )}

            {/* 답변 (qa_gen이 아닌 경우만 표시) */}
            {shouldRenderInlineAnswer && (
              <div
                style={{
                  display: "inline-block",
                  width: "fit-content",
                  maxWidth: "92%",
                  padding: "13px 16px",
                  marginBottom: 6,
                  background: isChatMode
                    ? "rgba(6,3,15,0.5)"
                    : "rgba(109,40,217,0.07)",
                  border: `1px solid ${isChatMode ? "rgba(139,92,246,0.1)" : AI.border}`,
                  borderRadius: 10,
                  fontSize: 15,
                  color: "#f1f5f9",
                  lineHeight: 1.85,
                  letterSpacing: "-0.01em",
                  backdropFilter: "blur(8px) saturate(1.05)",
                  boxShadow: "inset 0 1px 0 rgba(255,255,255,0.08)",
                }}
              >
                <MarkdownAnswer text={answer} />
                {streaming && (
                  <span
                    style={{
                      display: "inline-block",
                      width: 2,
                      height: 16,
                      background: AI.accentLight,
                      marginLeft: 2,
                      verticalAlign: "text-bottom",
                      animation: "ai-blink 0.9s infinite",
                    }}
                  />
                )}
              </div>
            )}

            {/* [v3.1] sources list (출처1, 출처2, ...) 는 위의 references chip 으로 대체됨 — 중복 표시 제거 */}

            {/* 에러 */}
            {error && (
              <div
                style={{
                  padding: "8px 12px",
                  borderRadius: 10,
                  fontSize: 12,
                  color: "#fca5a5",
                  background: "rgba(239,68,68,0.1)",
                  border: "1px solid rgba(239,68,68,0.2)",
                }}
              >
                {error}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ── AI 탐색 과정 패널 ─────────────────────────────────────────
function AIIterationPanel({
  iterationData,
  domainSelection,
  streaming,
  hasLLM,
}) {
  const [collapsed, setCollapsed] = useState(false);

  if (!iterationData.length && !streaming) return null;

  const focusedCount = iterationData.filter((it) => it.iteration > 0).length;

  return (
    <div
      className="mb-6 rounded-xl overflow-hidden"
      style={{ border: `1px solid ${AI.border}`, background: AI.card }}
    >
      {/* 패널 헤더 */}
      <button
        onClick={() => setCollapsed((c) => !c)}
        className="w-full flex items-center justify-between px-5 py-3 hover:brightness-110 transition-all"
        style={{ background: "rgba(109,40,217,0.15)" }}
      >
        <div className="flex items-center gap-2.5">
          <span
            className="material-symbols-outlined text-lg"
            style={{ color: AI.accentLight, fontVariationSettings: '"FILL" 1' }}
          >
            {streaming ? "psychology" : "auto_awesome"}
          </span>
          <span className="text-sm font-bold" style={{ color: AI.accentLight }}>
            AI 탐색 과정
          </span>
          <span
            className="text-[10px] px-2 py-0.5 rounded-full font-bold"
            style={{
              background: "rgba(139,92,246,0.15)",
              color: AI.accentLight,
              border: `1px solid ${AI.border}`,
            }}
          >
            {iterationData.length}단계
          </span>
          {hasLLM !== undefined && (
            <span
              className="text-[10px] px-2 py-0.5 rounded-full font-bold"
              style={{
                background: hasLLM
                  ? "rgba(139,92,246,0.1)"
                  : "rgba(100,116,139,0.1)",
                color: hasLLM ? AI.accentLight : "#94a3b8",
                border: `1px solid ${hasLLM ? AI.border : "rgba(100,116,139,0.15)"}`,
              }}
            >
              {hasLLM ? "🤖 LLM" : "⚙️ 휴리스틱"}
            </span>
          )}
          {streaming && (
            <span
              className="material-symbols-outlined text-base animate-spin"
              style={{ color: AI.accent }}
            >
              progress_activity
            </span>
          )}
        </div>
        <span className="material-symbols-outlined text-sm text-on-surface-variant/50">
          {collapsed ? "expand_more" : "expand_less"}
        </span>
      </button>

      {!collapsed && (
        <div className="p-4 space-y-3">
          {iterationData.map((step, idx) => {
            const isGlobal = step.iteration === 0;
            const dc = DOMAIN_META[step.domain] ?? DOMAIN_META.all;

            return (
              <div key={idx}>
                {/* 도메인 선택 안내 배너 (전체→집중 전환 시) */}
                {!isGlobal &&
                  idx > 0 &&
                  iterationData[idx - 1]?.iteration === 0 &&
                  domainSelection && (
                    <div
                      className="flex items-start gap-2 mb-2 px-3 py-2 rounded-lg"
                      style={{
                        background: "rgba(109,40,217,0.08)",
                        border: `1px dashed ${AI.border}`,
                      }}
                    >
                      <span
                        className="material-symbols-outlined text-sm shrink-0 mt-0.5"
                        style={{ color: AI.accent }}
                      >
                        arrow_forward
                      </span>
                      <div>
                        <span
                          className="text-[11px] font-bold"
                          style={{ color: AI.accentLight }}
                        >
                          {dc.label} 도메인으로 집중합니다
                        </span>
                        <span className="text-[11px] text-on-surface-variant/50 ml-2">
                          {domainSelection.reason}
                        </span>
                      </div>
                    </div>
                  )}

                {/* 단계 카드 */}
                <div
                  className="rounded-xl overflow-hidden"
                  style={{
                    border: `1.5px solid ${dc.border}28`,
                    background: "rgba(13, 7, 24, 0.5)",
                    backdropFilter: "blur(12px)",
                    boxShadow: `0 4px 16px rgba(0, 0, 0, 0.2), inset 0 1px 2px rgba(255, 255, 255, 0.08), inset 0 -1px 2px rgba(0, 0, 0, 0.3)`,
                  }}
                >
                  {/* 단계 헤더 */}
                  <div
                    className="flex items-center gap-2 px-3 py-2"
                    style={{
                      background: `rgba(13, 7, 24, 0.6)`,
                      backdropFilter: "blur(12px)",
                      borderBottom: `1.5px solid ${dc.border}28`,
                    }}
                  >
                    <div
                      className="w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold text-white shrink-0"
                      style={{
                        background: step.done
                          ? `linear-gradient(135deg,${ORB.mint},#0d9488)`
                          : isGlobal
                            ? "rgba(140,242,255,0.35)"
                            : AI.rankBg,
                      }}
                    >
                      {isGlobal ? "①" : step.iteration}
                    </div>
                    <span className="text-[11px] font-mono font-bold text-on-surface/80 flex-1 truncate">
                      "{step.query}"
                    </span>
                    <span
                      className="text-[9px] px-1.5 py-0.5 rounded-full font-bold border shrink-0"
                      style={{
                        background: dc.bg,
                        color: dc.text,
                        borderColor: dc.border,
                      }}
                    >
                      {dc.label}
                    </span>
                    <span className="text-[10px] text-on-surface-variant/40 shrink-0">
                      {step.count ?? step.items?.length ?? 0}건
                    </span>
                  </div>

                  {/* 결과 미리보기 카드 (top 3) */}
                  {step.items?.length > 0 && (
                    <div
                      className="px-3 py-2.5 flex gap-2 overflow-x-auto"
                      style={{
                        scrollbarWidth: "thin",
                        scrollbarColor: `${AI.border} transparent`,
                      }}
                    >
                      {step.items.slice(0, 5).map((item, i) => (
                        <MiniResultPill key={i} item={item} rank={i + 1} />
                      ))}
                      {step.items.length > 5 && (
                        <div className="shrink-0 flex items-center text-[10px] text-on-surface-variant/30 pl-1 whitespace-nowrap">
                          +{step.items.length - 5}건
                        </div>
                      )}
                    </div>
                  )}

                  {/* AI 사고 */}
                  {step.thought && (
                    <div
                      className="px-3 py-2 flex items-start gap-2"
                      style={{ borderTop: "1px solid rgba(109,40,217,0.08)" }}
                    >
                      <span
                        className="material-symbols-outlined text-sm shrink-0 mt-0.5"
                        style={{
                          color: step.done ? ORB.mint : AI.accent,
                          fontVariationSettings: '"FILL" 1',
                        }}
                      >
                        {step.done ? "check_circle" : "psychology"}
                      </span>
                      <p className="text-[11px] text-on-surface-variant/65 leading-relaxed">
                        {step.thought}
                      </p>
                    </div>
                  )}
                </div>
              </div>
            );
          })}

          {/* 스트리밍 대기 표시 */}
          {streaming && (
            <div
              className="flex items-center gap-2 px-3 py-2 rounded-lg"
              style={{
                border: `1px dashed ${AI.border}`,
                background: "rgba(109,40,217,0.05)",
              }}
            >
              <span
                className="material-symbols-outlined text-sm animate-spin"
                style={{ color: AI.accentLight }}
              >
                progress_activity
              </span>
              <span className="text-[11px] text-on-surface-variant/40 animate-pulse">
                AI가 결과를 분석하는 중...
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── 메인 컴포넌트 ─────────────────────────────────────────────
export default function MainAI() {
  const navigate = useNavigate();
  const location = useLocation();
  const { open } = useSidebar();

  const { view, setView, pushView, pushHistory } = useAIMainViewState({
    onPopToResults: () => setDetailVisible(false),
    onPopToHome: () => {
      setDetailVisible(false);
      setResultsReady(false);
    },
  });
  const [query, setQuery] = useState("");
  const [inputValue, setInputValue] = useState("");
  const [selectedFile, setSelectedFile] = useState(null);
  const [fileDetail, setFileDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);

  // AI 에이전트 상태
  const [streaming, setStreaming] = useState(false);
  const [results, setResults] = useState([]);
  const [iterationData, setIterationData] = useState([]);
  const [domainSelection, setDomainSelection] = useState(null);
  const [aiError, setAiError] = useState("");
  const [finalQuery, setFinalQuery] = useState("");
  const [hasLLM, setHasLLM] = useState(undefined);

  // ── AIMODE 시각화 4-step 상태 ─────────────────────────────
  const [aimodeSteps, setAimodeSteps] = useState([]);
  const [aimodeQuery, setAimodeQuery] = useState("");
  const [aimodeContentKws, setAimodeContentKws] = useState([]);
  const [aimodeDetailKws, setAimodeDetailKws] = useState([]);
  const [aimodeMode, setAimodeMode] = useState(""); // [v3] "structured" | "open" | "followup" | ""
  const [aimodeReferences, setAimodeReferences] = useState([]); // [v3] extract 노드 references
  const [chatThreadId, setChatThreadId] = useState(null); // [v3 chat] 현재 채팅방 thread_id (사이드바 active 표시용)
  const [chatRefreshTrigger, setChatRefreshTrigger] = useState(0); // [v3 chat] 사이드바 채팅방 목록 새로고침 트리거 (done 시 ++)
  const [zoomImage, setZoomImage] = useState(null); // [v3.1] 페이지 이미지 확대 modal {src, title}
  const [pdfExporting, setPdfExporting] = useState(false); // [v3.2] 대화 → PDF 정리 export 진행 중 여부

  // [v3.1] ESC 로 zoom modal 닫기
  useEffect(() => {
    if (!zoomImage) return;
    const onKey = (e) => { if (e.key === "Escape") setZoomImage(null); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [zoomImage]);
  const [aimodeSources, setAimodeSources] = useState([]);
  const [aimodeSelected, setAimodeSelected] = useState(null);
  const [aimodeAnswer, setAimodeAnswer] = useState("");
  const [aimodeDone, setAimodeDone] = useState(false);
  const [aimodeScanStates, setAimodeScanStates] = useState({}); // fid → 'scanning'|'found'|'not_found'
  const [aimodeStage, setAimodeStage] = useState("idle"); // 'intent'|'searching'|'scanning'|'generating'|'idle'
  // 보안 모드: SecurityCritic 차단/마스킹 결과
  const [aimodeBlocked, setAimodeBlocked] = useState(null); // {stage, reason, pii_types}
  const [aimodeSecurity, setAimodeSecurity] = useState(null); // {masked, pii_types, reason}
  const [useAimode, setUseAimode] = useState(true);
  const [topK, setTopK] = useState(20);
  const [maxIter, setMaxIter] = useState(5);
  const abortRef = useRef(null);
  const activeQueryRef = useRef("");

  const dispatchAiSidebarView = useCallback((viewName) => {
    try {
      window.dispatchEvent(
        new CustomEvent("ai-sidebar-view-changed", {
          detail: { view: viewName },
        }),
      );
    } catch {}
  }, []);

  // 애니메이션
  const [homeExiting, setHomeExiting] = useState(false);
  const [resultsReady, setResultsReady] = useState(false);
  const [detailVisible, setDetailVisible] = useState(false);
  const [aiHomeInputFocused, setAiHomeInputFocused] = useState(false);
  const [homeInputOverflow, setHomeInputOverflow] = useState(false);
  const [homeInputExpandedLocked, setHomeInputExpandedLocked] = useState(false);

  const [aiHomeEntranceOn, setAiHomeEntranceOn] = useState(
    () =>
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  );

  // 포털 전환
  const [searchTransitioning, setSearchTransitioning] = useState(false);
  const [ripplePos, setRipplePos] = useState({ x: "50%", y: "50%" });
  const [aiDockExpanded, setAiDockExpanded] = useState(false);
  const btnRef = useRef(null);
  const formRef = useRef(null);
  const homeInputRef = useRef(null);
  const chatInputRef = useRef(null);
  const orbSinkRef = useRef(null);
  const orbVoiceRef = useRef(0);
  const conversationEndRef = useRef(null);
  const submitGuardRef = useRef({ q: "", ts: 0 });

  const [turns, setTurns] = useState([]);
  const [rightMode, setRightMode] = useState("cards");
  const [selectedScanChunks, setSelectedScanChunks] = useState({});
  const [securityMode, setSecurityMode] = useState(false);

  // aiHomeEntranceOn 제어
  useEffect(() => {
    if (view !== "home") {
      setAiHomeEntranceOn(false);
      return;
    }
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setAiHomeEntranceOn(true);
      return;
    }
    setAiHomeEntranceOn(false);
    const t = window.setTimeout(() => setAiHomeEntranceOn(true), 180);
    return () => clearTimeout(t);
  }, [view]);

  // 뷰 변경 시 검색창 자동 포커스 (detail 제외 모든 뷰)
  useEffect(() => {
    if (view !== "detail") {
      const t = setTimeout(() => {
        if (view === "home") homeInputRef.current?.focus();
        else chatInputRef.current?.focus();
      }, 150);
      return () => clearTimeout(t);
    }
  }, [view]);

  useEffect(() => {
    if (view !== "home") {
      setHomeInputOverflow(false);
      return;
    }
    const el = homeInputRef.current;
    if (!el) return;
    const checkOverflow = () => {
      // input 내부 실제 문자열 렌더 폭이 visible 폭보다 큰지 확인
      setHomeInputOverflow(el.scrollWidth - el.clientWidth > 2);
    };
    checkOverflow();
    window.addEventListener("resize", checkOverflow);
    return () => window.removeEventListener("resize", checkOverflow);
  }, [view, inputValue, aiHomeInputFocused]);

  useEffect(() => {
    if (view !== "home") {
      setHomeInputExpandedLocked(false);
      return;
    }
    if (!inputValue.trim()) {
      setHomeInputExpandedLocked(false);
      return;
    }
    if (aiHomeInputFocused && homeInputOverflow) {
      setHomeInputExpandedLocked(true);
    }
  }, [view, inputValue, aiHomeInputFocused, homeInputOverflow]);

  const ml = open ? "ml-[var(--sidebar-width,16rem)]" : "ml-0";
  const leftEdge = open ? "left-[var(--sidebar-width,16rem)]" : "left-0";
  const sidebarPx = open ? 256 : 0;
  const homeInputExpanded = view === "home" && homeInputExpandedLocked;

  // STT
  const doSearchRef = useRef(null);
  // AI 사이드바 기록 클릭 콜백 — prop으로 SearchSidebar에 직접 전달 (CustomEvent 폴백용)
  const onAiQuery = useCallback((q) => doSearchRef.current?.(q), []);
  const {
    listening,
    interim,
    toggle: toggleMic,
    stop: stopMic,
  } = useSpeechRecognition({
    onFinal: useCallback((text) => {
      setInputValue(text);
      setTimeout(() => doSearchRef.current?.(text), 80);
    }, []),
  });

  useMicLevelRef(view === "home" && listening, orbVoiceRef, {
    startDelayMs: 420,
  });

  useEffect(() => {
    if (view !== "home") stopMic();
  }, [view, stopMic]);

  useEffect(() => {
    if (view !== "results" && aiDockExpanded) setAiDockExpanded(false);
  }, [view, aiDockExpanded]);

  // 사이드바 검색 기록 클릭 (navigate 경유)
  useEffect(() => {
    const q = location.state?.query;
    if (q) {
      window.history.replaceState({}, "");
      doSearchRef.current?.(q);
    }
  }, [location.state]);

  // 사이드바 검색 기록 클릭 (CustomEvent 경유 — navigate race condition 방지)
  useEffect(() => {
    const handler = (e) => doSearchRef.current?.(e.detail.query);
    window.addEventListener('ai-sidebar-query', handler);
    return () => window.removeEventListener('ai-sidebar-query', handler);
  }, []);

  // ── SSE 실행 (AIMODE 시각화 또는 기존 에이전트) ─────────────
  const runAISearch = useCallback(
    async (q) => {
      if (abortRef.current) abortRef.current.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      setStreaming(true);
      setResults([]);
      // [v3 chat] turns 는 검색 시작 시 초기화 X — 같은 thread 안에서 누적.
      // 새 채팅(새 thread_id)일 때만 사이드바의 "새 채팅" 버튼에서 명시적으로 초기화.
      setIterationData([]);
      setDomainSelection(null);
      setAiError("");
      setFinalQuery(q);
      activeQueryRef.current = q;
      setHasLLM(undefined);

      // [v3 chat] 진행 중 turn 의 시각화 상태만 초기화 — 이전 turn 들은 turns 배열에 보존.
      setAimodeSteps([]);
      setAimodeQuery("");
      setAimodeContentKws([]);
      setAimodeDetailKws([]);
      setAimodeMode("");
      setAimodeReferences([]);
      setAimodeSources([]);
      setAimodeSelected(null);
      setAimodeAnswer("");
      setAimodeDone(false);
      setAimodeBlocked(null);
      setAimodeSecurity(null);
      setAimodeScanStates({});
      setSelectedScanChunks({});
      setAimodeStage("intent");

      const endpoint = useAimode
        ? `${API_BASE}/api/aimode/chat`
        : `${API_BASE}/api/ai/search`;
      // LangGraph thread_id — localStorage 영속 (24h TTL)
      let tid = null;
      try {
        const raw = localStorage.getItem("aimode_thread_id");
        if (raw) {
          const obj = JSON.parse(raw);
          if (obj?.id && obj?.expires > Date.now()) tid = obj.id;
        }
      } catch {}
      if (!tid) {
        tid = `t_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
        try {
          localStorage.setItem(
            "aimode_thread_id",
            JSON.stringify({
              id: tid,
              expires: Date.now() + 24 * 3600 * 1000,
            }),
          );
        } catch {}
      }
      window.__aimodeThreadId = tid;
      // [v3 chat] 사이드바 active 상태 동기화
      setChatThreadId(tid);
      const body = useAimode
        ? { query: q, topk: topK, thread_id: tid, secure: securityMode }
        : {
            query: q,
            topk: topK,
            max_iterations: maxIter,
            secure: securityMode,
          };

      try {
        const res = await fetch(endpoint, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
          signal: controller.signal,
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop();

          for (const line of lines) {
            if (!line.startsWith("data: ")) continue;
            try {
              const ev = JSON.parse(line.slice(6));
              handleSSEEvent(ev);
            } catch {}
          }
        }
      } catch (e) {
        if (e.name !== "AbortError") setAiError(e.message);
      } finally {
        setStreaming(false);
      }
    },
    [topK, maxIter, useAimode],
  );

  const mapItem = (item) => {
    const dom =
      item.domain ??
      item.trichef_domain ??
      (item.file_type === "doc"
        ? "doc_page"
        : item.file_type === "video"
          ? "movie"
          : item.file_type === "audio"
            ? "music"
            : item.file_type === "image"
              ? "image"
              : null);
    const isDocPage = dom === "doc_page";
    const pathKey =
      item.file_path || item.source_path || item.id || item.trichef_id || "";
    const idKey = item.trichef_id ?? item.id ?? pathKey;
    let ft = item.file_type;
    if (!ft && dom === "image") ft = "image";
    else if (!ft && isDocPage) ft = "doc";
    else if (!ft && dom === "movie") ft = "video";
    else if (!ft && dom === "music") ft = "audio";
    else if (!ft) ft = "doc";
    const conf = item.confidence ?? item.similarity ?? 0;
    return {
      file_path: pathKey,
      trichef_id: idKey,
      file_name: item.file_name || String(pathKey).split(/[/\\]/).pop() || "?",
      page_num: item.page_num ?? null,
      file_type: ft,
      confidence: conf,
      similarity: item.similarity ?? conf,
      dense: item.dense ?? 0,
      lexical: item.lexical ?? null,
      asf: item.asf ?? null,
      snippet: item.snippet ?? "",
      preview_url: item.preview_url ?? null,
      segments: item.segments ?? [],
      low_confidence: item.low_confidence ?? false,
      trichef_domain: dom ?? undefined,
      rerank_score: item.rerank_score ?? item.rerank ?? null,
      z_score: item.z_score ?? null,
    };
  };

  const handleSSEEvent = (ev) => {
    switch (ev.type) {
      // ── AIMODE 시각화 이벤트 (/api/aimode/chat) ─────────────
      case "step":
        setAimodeSteps((prev) => {
          const idx = prev.findIndex((s) => s.step === ev.step);
          const entry = {
            step: ev.step,
            label: ev.label,
            done: ev.done === true,
            query: ev.query,
            selected_idx: ev.selected_idx,
          };
          if (idx >= 0) {
            const next = [...prev];
            next[idx] = { ...next[idx], ...entry };
            return next;
          }
          return [...prev, entry];
        });
        if (ev.step === 1 && ev.done) {
          if (ev.query) setAimodeQuery(ev.query);
          if (ev.content_keywords) setAimodeContentKws(ev.content_keywords);
          if (ev.detail_keywords) setAimodeDetailKws(ev.detail_keywords);
        }
        if (ev.step === 3 && typeof ev.selected_idx === "number") {
          setAimodeSelected(ev.selected_idx);
          // Step 3 완료 — LangGraph 가 선택한 카드 자동 클릭 (1.4s 딜레이 후)
          setAimodeSources((prev) => {
            const file = prev[ev.selected_idx];
            if (file) {
              setTimeout(() => handleSelectFile(file), 1400);
            }
            return prev;
          });
        }
        break;

      case "candidates":
      case "sources": {
        // AIMODE 검색 결과 — 작은 단계 패널용 + MainSearch 와 동일한 큰 카드 그리드용
        const items = ev.items || [];
        const mapped = items.map(mapItem);
        setAimodeSources(mapped);
        // [v3 chat] 마지막 streaming turn 의 sources + candidates 도 즉시 동기화
        // candidates 필드도 채워야 selected 이벤트 후에도 우측 패널에 후보 전체 표시됨
        setTurns((prev) => {
          if (prev.length === 0) return prev;
          const last = prev[prev.length - 1];
          if (!last.streaming) return prev;
          return [
            ...prev.slice(0, -1),
            { ...last, sources: [...mapped], candidates: [...mapped] },
          ];
        });
        // ★ 동일 데이터를 큰 카드 그리드로도 렌더 (MainSearch 와 동일한 UX)
        setResults(mapped);
        const histQ = activeQueryRef.current || ev.query || finalQuery || "";
        // 검색 기록 저장
        fetch(`${API_BASE}/api/history`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            query: histQ,
            method: "aimode",
            result_count: mapped.length,
          }),
        })
          .then(() => {
            window.dispatchEvent(new Event("history-updated"));
          })
          .catch(() => {});
        break;
      }

      case "intent":
        if (ev.message) setAimodeQuery(ev.message);
        if (ev.file_keywords) setAimodeContentKws(ev.file_keywords);
        if (ev.detail_keywords) setAimodeDetailKws(ev.detail_keywords);
        if (ev.mode) setAimodeMode(ev.mode); // [v3] structured | open | followup
        setAimodeStage("searching");
        break;

      case "extract":
        // [v3] extract 노드 references — UI 패널 + 답변 인용 chip 매핑
        if (Array.isArray(ev.references)) {
          setAimodeReferences(ev.references);
          // [v3 chat] 마지막 streaming turn 의 references 도 즉시 update.
          // (done 이벤트가 setAimodeReferences 비동기 setState 보다 먼저 처리되면
          //  stale 값으로 turn 채워서 references 누락. 여기서 직접 update.)
          setTurns((prev) => {
            if (prev.length === 0) return prev;
            const last = prev[prev.length - 1];
            if (!last.streaming) return prev;
            return [
              ...prev.slice(0, -1),
              { ...last, references: [...ev.references] },
            ];
          });
        }
        break;

      case "scanning":
        setAimodeStage("scanning");
        if (ev.file_id) {
          setAimodeScanStates((prev) => ({
            ...prev,
            [ev.file_id]: "scanning",
          }));
        }
        break;

      case "scan_result":
        if (ev.file_id) {
          setAimodeScanStates((prev) => ({
            ...prev,
            [ev.file_id]: ev.found ? "found" : "not_found",
          }));
          // 문서 매칭 청크 저장 — 대화 영역 "검색어 위치" 표시용
          if (ev.found && ev.chunks?.length) {
            setSelectedScanChunks((prev) => ({
              ...prev,
              [ev.file_id]: ev.chunks,
            }));
          }
        }
        break;

      case "selected": {
        // 백엔드 select_node — found:true 인 파일들만 추려서 sources 로 송출.
        // [v3.2 fix] 우측 후보 목록을 덮어쓰지 않음 — 매칭은 sources(turn.sources) 에만 반영,
        // 우측 패널의 rightCandidates 는 candidates 이벤트가 채운 전체 목록 그대로 유지.
        // 사용자는 우측에서 후보 카드 + 매칭 여부(scanStates) 둘 다 볼 수 있음.
        const items = ev.sources || [];
        if (items.length > 0) {
          const mapped = items.map(mapItem);
          setAimodeSources(mapped);   // 매칭된 sources (답변에서 인용할 것)
          // setResults 와 turn.candidates 는 건드리지 않음 (전체 후보 유지)
          // 마지막 turn 의 sources 만 update — 매칭된 1~N개만
          setTurns((prev) => {
            if (prev.length === 0) return prev;
            const last = prev[prev.length - 1];
            if (!last.streaming) return prev;
            return [
              ...prev.slice(0, -1),
              { ...last, sources: [...mapped] },
            ];
          });
        }
        break;
      }

      case "generating":
        setAimodeStage("generating");
        break;

      case "token": {
        const piece = ev.text || "";
        setAimodeAnswer((prev) => prev + piece);
        // [v3 chat] 마지막 streaming turn 의 answer 도 실시간 누적 (말풍선 안에 표시)
        setTurns((prev) => {
          if (prev.length === 0) return prev;
          const last = prev[prev.length - 1];
          if (!last.streaming) return prev;
          return [
            ...prev.slice(0, -1),
            { ...last, answer: (last.answer || "") + piece },
          ];
        });
        break;
      }

      case "done": {
        setAimodeDone(true);
        setAimodeStage("idle");
        const finalAnswer = ev.answer || aimodeAnswer;
        if (ev.answer) setAimodeAnswer(ev.answer);
        if (ev.security) setAimodeSecurity(ev.security);
        if (typeof ev.selected_idx === "number")
          setAimodeSelected(ev.selected_idx);
        // [v3 chat] 사이드바 채팅방 목록 새로고침 트리거 — done 후 백엔드에 새 thread 저장됨
        setChatRefreshTrigger((t) => t + 1);
        // [v3 chat] submitQuery 가 만든 streaming turn 의 완료 처리.
        // 새 turn push 가 아니라 마지막 streaming turn 을 update.
        // 주의: references / sources 는 extract / selected 핸들러가 이미 직접 채웠을 수 있음.
        //       last.X 가 비어있을 때만 state fallback 사용 (stale state 덮어쓰기 방지).
        setTurns((prev) => {
          if (prev.length === 0) return prev;
          const last = prev[prev.length - 1];
          if (!last.streaming) return prev;
          const lastRefs = (last.references && last.references.length > 0)
            ? last.references
            : [...(aimodeReferences || [])];
          const lastSrcs = (last.sources && last.sources.length > 0)
            ? last.sources
            : [...(aimodeSources || [])];
          return [
            ...prev.slice(0, -1),
            {
              ...last,
              answer:         finalAnswer || last.answer,
              route:          "rag",
              intentMessage:  aimodeQuery || last.intentMessage,
              fileKeywords:   [...(aimodeContentKws || [])],
              detailKeywords: [...(aimodeDetailKws || [])],
              sources:        lastSrcs,
              references:     lastRefs,
              mode:           aimodeMode,
              streaming:      false,
              done:           true,
              generating:     false,
              security:       ev.security || null,
            },
          ];
        });
        break;
      }

      case "blocked":
        setAimodeDone(true);
        setAimodeBlocked({
          stage: ev.stage || "final",
          reason: ev.reason || "보안 정책상 응답이 차단되었습니다.",
          pii_types: ev.pii_types || [],
        });
        break;

      case "error":
        // 백엔드가 즉시 끊고 error 이벤트 1개만 보내는 경우(Ollama 미연결/모델 미설치 등)
        // 진행 단계 스피너가 "의도 분석"에서 멈춘 것처럼 보여 오해 유발 → idle 로 복귀.
        // 주의: aimodeDone 은 정상 완료 의미라 "완료" 뱃지가 켜지므로 여기선 건드리지 않음.
        setAiError(ev.message || "오류");
        setAimodeStage("idle");
        break;

      // ── 기존 ai_search 이벤트 (fallback) ─────────────────────
      case "info":
        setHasLLM(ev.has_llm);
        break;

      case "iteration_results":
        // 각 단계 결과 카드 저장/업데이트
        setIterationData((prev) => {
          const idx = prev.findIndex((it) => it.iteration === ev.iteration);
          const entry = {
            iteration: ev.iteration,
            query: ev.query,
            domain: ev.domain,
            items: ev.items ?? [],
            count: ev.items?.length ?? 0,
            thought: "",
            done: false,
          };
          if (idx >= 0) {
            const next = [...prev];
            next[idx] = { ...next[idx], ...entry };
            return next;
          }
          return [...prev, entry];
        });
        break;

      case "domain_selected":
        setDomainSelection({ domain: ev.domain, reason: ev.reason });
        break;

      case "thought":
        // 마지막 focused 단계(iteration>0)의 thought 업데이트
        setIterationData((prev) => {
          if (!prev.length) return prev;
          const updated = [...prev];
          // 뒤에서부터 iteration>0인 항목 찾기
          for (let i = updated.length - 1; i >= 0; i--) {
            if (updated[i].iteration > 0) {
              updated[i] = { ...updated[i], thought: ev.text, done: ev.done };
              return updated;
            }
          }
          return prev;
        });
        break;

      case "results": {
        const mapped = (ev.items ?? []).map(mapItem);
        setResults(mapped);
        setFinalQuery(ev.final_query || ev.query);
        // 최종 history로 iterationData thought/done 동기화
        if (ev.history?.length) {
          setIterationData((prev) => {
            const updated = [...prev];
            ev.history.forEach((h, hi) => {
              const idx = updated.findIndex((it) => it.iteration === hi + 1);
              if (idx >= 0) {
                updated[idx] = {
                  ...updated[idx],
                  thought: h.thought,
                  done: h.done,
                  count: h.count,
                };
              }
            });
            return updated;
          });
        }
        break;
      }
      // case 'error' 는 위쪽에 이미 정의 (AIMODE/legacy 공용)
    }
  };

  const doSearch = (q) => {
    const searchQ = String(q ?? "").trim();
    if (!searchQ || searchTransitioning || homeExiting) return;
    setQuery(searchQ);
    // [v3 chat] 입력창은 submitQuery 가 이미 비웠음. doSearch 가 다시 채우면 안 됨
    // (예전엔 results view 의 검색창에 query 표시 목적이었으나, 채팅 UX 에선 비우는 게 우선).

    if (view === "home") {
      setHomeExiting(true);
      setTimeout(() => {
        setHomeExiting(false);
        setResultsReady(false);
        pushView("results");
        // 검색 실행은 UI 보조 로직보다 우선 보장
        runAISearch(searchQ);
        dispatchAiSidebarView("results");
        requestAnimationFrame(() => setResultsReady(true));
      }, 420);
    } else {
      pushView("results");
      runAISearch(searchQ);
      dispatchAiSidebarView("results");
    }
  };

  doSearchRef.current = doSearch;

  useEffect(() => {
    doSearchRef.current = doSearch;
  });

  const submitQuery = (raw) => {
    const q = String(raw ?? "").trim();
    if (!q) return;
    const now = Date.now();
    const prev = submitGuardRef.current;
    // Enter keydown + form submit 중복 호출 방지
    if (prev.q === q && now - prev.ts < 450) return;
    submitGuardRef.current = { q, ts: now };
    setHomeInputExpandedLocked(false);
    // [v3 chat] 전송 후 입력창 비우기 — 사용자 의도 확실
    setInputValue("");
    // [v3 chat] **즉시** turn push — 사용자 말풍선 입력 직후 화면 위로 올라가게.
    // token 이벤트마다 마지막 turn 의 answer 누적, done 에서 완료 처리.
    setTurns((t) => [
      ...t,
      {
        id:             `turn_pending_${now}`,
        query:          q,
        answer:         "",
        route:          "",
        intentMessage:  "",
        fileKeywords:   [],
        detailKeywords: [],
        candidates:     [],
        scanStates:     {},
        scanChunks:     {},
        scannedCount:   0,
        foundCount:     0,
        sources:        [],
        streaming:      true,
        done:           false,
        error:          null,
        keyFacts:       [],
        generating:     true,
        blocked:        null,
        security:       null,
        references:     [],
        mode:           "",
        ts:             now,
      },
    ]);
    doSearch(q);
  };

  // [v3 chat] 새 채팅 시작 — turns 초기화 + 새 thread_id 발급
  const startNewChat = useCallback(() => {
    // 현재 turn 진행 중이면 abort
    if (abortRef.current) {
      try { abortRef.current.abort(); } catch {}
    }
    // 새 thread_id 발급
    const newTid = `t_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
    try {
      localStorage.setItem("aimode_thread_id", JSON.stringify({
        id: newTid,
        expires: Date.now() + 24 * 3600 * 1000,
      }));
    } catch {}
    window.__aimodeThreadId = newTid;
    setChatThreadId(newTid);
    // turns + 진행 중 시각화 상태 초기화
    setTurns([]);
    setAimodeSteps([]);
    setAimodeQuery("");
    setAimodeContentKws([]);
    setAimodeDetailKws([]);
    setAimodeMode("");
    setAimodeReferences([]);
    setAimodeSources([]);
    setAimodeSelected(null);
    setAimodeAnswer("");
    setAimodeDone(false);
    setAimodeBlocked(null);
    setAimodeSecurity(null);
    setAimodeScanStates({});
    setAimodeStage("idle");
    setStreaming(false);
    setResults([]);
    setIterationData([]);
    setDomainSelection(null);
    setAiError("");
    setFinalQuery("");
    setInputValue("");
    activeQueryRef.current = "";
    // 홈으로 (입력 박스 큰 화면)
    setView("home");
  }, []);

  // [v3.2] 대화 → AI 정리·요약 → PDF 다운로드
  const handleExportPdf = useCallback(async () => {
    const tid = window.__aimodeThreadId || chatThreadId;
    if (!tid) {
      alert("저장할 대화가 없습니다.");
      return;
    }
    if (pdfExporting) return;
    setPdfExporting(true);
    try {
      const r = await fetch(`${API_BASE}/api/aimode/export-pdf`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ thread_id: tid }),
      });
      if (!r.ok) {
        let msg = `HTTP ${r.status}`;
        try {
          const j = await r.json();
          msg = j.error || j.hint || msg;
          if (j.hint) msg += `\n${j.hint}`;
        } catch {}
        alert(`PDF 생성 실패:\n${msg}`);
        return;
      }
      // 헤더에서 파일명 추출
      const cd = r.headers.get("Content-Disposition") || "";
      let fname = "chat.pdf";
      // RFC5987 filename*=UTF-8''...
      const mStar = cd.match(/filename\*\s*=\s*UTF-8''([^;]+)/i);
      if (mStar) {
        try { fname = decodeURIComponent(mStar[1]); } catch {}
      } else {
        const m = cd.match(/filename\s*=\s*"?([^";]+)"?/i);
        if (m) fname = m[1];
      }
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = fname;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) {
      console.warn("[export-pdf]", e);
      alert(`PDF 생성 실패: ${e.message || e}`);
    } finally {
      setPdfExporting(false);
    }
  }, [chatThreadId, pdfExporting]);

  // [v3 chat] 사이드바에서 채팅방 선택 — history 복원 + thread_id 전환
  const selectThread = useCallback(async (targetTid) => {
    if (!targetTid) return;
    if (abortRef.current) {
      try { abortRef.current.abort(); } catch {}
    }
    // thread_id 전환
    try {
      localStorage.setItem("aimode_thread_id", JSON.stringify({
        id: targetTid,
        expires: Date.now() + 24 * 3600 * 1000,
      }));
    } catch {}
    window.__aimodeThreadId = targetTid;
    setChatThreadId(targetTid);
    // 진행 중 시각화 초기화
    setAimodeSteps([]);
    setAimodeQuery("");
    setAimodeContentKws([]);
    setAimodeDetailKws([]);
    setAimodeMode("");
    setAimodeReferences([]);
    setAimodeSources([]);
    setAimodeAnswer("");
    setAimodeDone(false);
    setAimodeBlocked(null);
    setAimodeStage("idle");
    setStreaming(false);
    setInputValue("");
    // [v3.3] 우측 페이지 detail 패널도 초기화 (다른 대화방 들어왔는데 이전 페이지 남는 문제)
    setRightMode("cards");
    setSelectedFile(null);
    setSelectedScanChunks({});
    if (typeof setFileDetail === "function") setFileDetail(null);
    // history fetch → turns 복원
    // [v3.3] backend 가 extra 컬럼에 sources + references JSON 저장해뒀음.
    //        파싱해서 turn 의 sources/references 채워줘야 chip·페이지 이미지 복원됨.
    try {
      const r = await fetch(`${API_BASE}/api/aimode/history/${targetTid}`);
      if (r.ok) {
        const d = await r.json();
        const h = d.history || [];
        const restored = [];
        let lastSources = [];
        let lastReferences = [];
        for (let i = 0; i < h.length - 1; i += 2) {
          if (h[i].role === "user" && h[i + 1].role === "assistant") {
            // assistant 메시지의 extra 에서 sources/references 복원
            const extra = h[i + 1].extra || {};
            const srcs = Array.isArray(extra.sources) ? extra.sources : [];
            const refs = Array.isArray(extra.references) ? extra.references : [];
            restored.push({
              id:             `restored_${i}_${targetTid.slice(-6)}`,
              query:          h[i].content,
              answer:         h[i + 1].content,
              route:          "rag",
              intentMessage:  "",
              fileKeywords:   [],
              detailKeywords: [],
              candidates:     srcs,   // 후보 패널도 sources 로 채워 visual 동일하게
              scanStates:     {},
              scanChunks:     {},
              scannedCount:   srcs.length,
              foundCount:     srcs.length,
              sources:        srcs,      // 출처 chip 용
              streaming:      false,
              done:           true,
              error:          null,
              keyFacts:       [],
              generating:     false,
              blocked:        null,
              security:       null,
              references:     refs,      // 페이지·snippet chip 클릭 시 우측에 표시
              mode:           "",
              ts:             Date.parse(h[i + 1].created_at) || Date.now(),
              restored:       true,
            });
            lastSources    = srcs;
            lastReferences = refs;
          }
        }
        setTurns(restored);
        // 마지막 turn 의 sources/references 를 state 에도 반영 → 우측 패널 즉시 표시
        if (lastSources.length)    setAimodeSources(lastSources);
        if (lastReferences.length) setAimodeReferences(lastReferences);
      } else {
        setTurns([]);
      }
    } catch (e) {
      console.warn("[selectThread] history fetch 실패", e);
      setTurns([]);
    }
    // 채팅방 진입 = results view (turn 들 표시)
    setView("results");
  }, []);

  const handleSearch = (e) => {
    e?.preventDefault();
    // 폼 submit 단일 경로: 해당 form의 query input 값을 1순위로 사용
    const formInput = e?.currentTarget?.elements?.query?.value;
    const liveValue =
      formInput ??
      (view === "home"
        ? homeInputRef.current?.value
        : chatInputRef.current?.value) ??
      inputValue;
    submitQuery(liveValue);
  };

  const handleSelectFile = (file) => {
    setSelectedFile(file);
    setRightMode("detail");
    setSelectedScanChunks(latestTurn?.scanChunks ?? {});
    setFileDetail(null);
    setDetailVisible(false);
    pushView("detail");
    dispatchAiSidebarView("detail");
    requestAnimationFrame(() =>
      requestAnimationFrame(() => setDetailVisible(true)),
    );
    const isAV = file.file_type === "video" || file.file_type === "audio";
    if (!isAV) {
      setDetailLoading(true);
      fetch(
        `${API_BASE}/api/files/detail?path=${encodeURIComponent(file.file_path)}`,
      )
        .then((r) => r.json())
        .then((d) => {
          setFileDetail(d);
          setDetailLoading(false);
        })
        .catch(() => setDetailLoading(false));
    }
  };

  const handleBackToResults = () => {
    setRightMode("cards");
    setDetailVisible(false);
    pushHistory("results");
    dispatchAiSidebarView("results");
    setTimeout(() => setView("results"), 320);
  };

  // 새 대화 — 서버 history + localStorage thread_id 모두 비움
  const handleNewConversation = useCallback(async () => {
    if (abortRef.current) abortRef.current.abort();
    const tid = window.__aimodeThreadId;
    if (tid) {
      try {
        await fetch(`${API_BASE}/api/aimode/chat/${encodeURIComponent(tid)}`, {
          method: "DELETE",
        });
      } catch {}
    }
    try {
      localStorage.removeItem("aimode_thread_id");
    } catch {}
    window.__aimodeThreadId = null;
    setAimodeSteps([]);
    setAimodeQuery("");
    setAimodeContentKws([]);
    setAimodeDetailKws([]);
    setAimodeMode("");
    setAimodeReferences([]);
    setAimodeSources([]);
    setAimodeSelected(null);
    setAimodeAnswer("");
    setAimodeDone(false);
    setAimodeBlocked(null);
    setAimodeSecurity(null);
    setResults([]);
    setIterationData([]);
    setTurns([]);
    setRightMode("cards");
    setSelectedScanChunks({});
    setSelectedFile(null);
    setFileDetail(null);
    setAiError("");
    setView("home");
    setInputValue("");
    setHomeInputExpandedLocked(false);
  }, []);

  const handleGoToSearch = () => {
    const rect = btnRef.current?.getBoundingClientRect();
    if (rect)
      setRipplePos({
        x: `${rect.left + rect.width / 2}px`,
        y: `${rect.top + rect.height / 2}px`,
      });
    setSearchTransitioning(true);
    setTimeout(() => navigate("/search"), 900);
  };

  const latestTurn = turns.length ? turns[turns.length - 1] : null;
  const isAnyStreaming = streaming || turns.some((t) => t.streaming);

  // 우측 패널: 에이전트 턴 후보 → 없으면 AIMODE `results` 폴백
  const rightCandidates = latestTurn?.candidates?.length
    ? latestTurn.candidates
    : results;
  // legacy turns 의 scanStates 가 있으면 우선, 없으면 AIMODE 의 aimodeScanStates
  const rightScanStates =
    latestTurn?.scanStates && Object.keys(latestTurn.scanStates).length
      ? latestTurn.scanStates
      : aimodeScanStates;
  const shouldShowCenterNoInfoAlert =
    latestTurn?.done &&
    !latestTurn?.streaming &&
    isNoInfoCenterAlert(latestTurn?.answer);

  // ── Render ──────────────────────────────────────────────────────
  return (
    <div
      className={
        view === "home"
          ? "overflow-hidden h-screen relative"
          : "min-h-screen relative text-on-surface"
      }
      style={{
        height: "100vh",
        background: AI.bg,
        backgroundImage:
          view === "home"
            ? "radial-gradient(120% 90% at 0% 100%, rgba(109,40,217,0.1) 0%, transparent 60%), radial-gradient(100% 80% at 100% 0%, rgba(59,130,246,0.08) 0%, transparent 58%)"
            : "none",
        overflow: "hidden",
      }}
    >
      {searchTransitioning && (
        <div className="fixed inset-0 z-[9999] pointer-events-none overflow-hidden">
          <div
            className="portal-overlay absolute rounded-full"
            style={{
              width: "80px",
              height: "80px",
              left: ripplePos.x,
              top: ripplePos.y,
              transform: "translate(-50%, -50%)",
              background:
                "radial-gradient(circle, #1c253e 0%, #0c1326 60%, #070d1f 100%)",
              boxShadow: "0 0 30px 10px rgba(133,173,255,0.15)",
            }}
          />
          {[0, 200].map((delay, i) => (
            <div
              key={i}
              className="portal-ring absolute rounded-full border border-[#8cf2ff]/28"
              style={{
                width: "160px",
                height: "160px",
                left: ripplePos.x,
                top: ripplePos.y,
                transform: "translate(-50%, -50%)",
                animationDelay: `${delay}ms`,
              }}
            />
          ))}
          <div className="portal-text absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 flex flex-col items-center gap-2">
            <span
              className="material-symbols-outlined text-[#a5aac2] text-4xl"
              style={{ fontVariationSettings: '"FILL" 1' }}
            >
              database
            </span>
            <span className="font-manrope uppercase tracking-[0.25em] text-base text-[#a5aac2]">
              검색 모드
            </span>
          </div>
        </div>
      )}

      {/* 사이드바 — 기존 SearchSidebar 유지 (디자인·닫기 버튼 그대로) */}
      <SearchSidebar
        entranceOn={view === "home" ? aiHomeEntranceOn : undefined}
        onAiQuery={onAiQuery}
        onAiNewChat={startNewChat}
        currentChatThreadId={chatThreadId}
        onSelectAiThread={(tid) => {
          setChatThreadId(tid);
          selectThread(tid);
        }}
        aiChatRefreshTrigger={chatRefreshTrigger}
      />

      {/* ════ HOME VIEW ════ */}
      {view === "home" && (
        <>
          <main
            className={`${ml} relative flex h-full min-h-0 w-full flex-col overflow-x-visible overflow-y-auto bg-transparent transition-[margin] duration-300 pt-8`}
          >
            <div
              className={`ai-home-orbit-bg pointer-events-none absolute top-0 bottom-0 z-0 min-h-0 ${open ? "-left-64 w-[calc(100%+16rem)]" : "inset-x-0"}`}
              style={{ "--ai-orbit-assemble": `${AI_ORB_ASSEMBLE_SECONDS}s` }}
              aria-hidden
            />
            {/* Orb */}
            <div
              ref={orbSinkRef}
              className={`absolute top-0 bottom-0 z-0 min-h-0 ${open ? "-left-64 w-[calc(100%+16rem)]" : "inset-x-0"} `}
              aria-hidden
            >
              <AnimatedOrb
                layout="fill"
                colorMode="ai"
                hideCenterUI
                interactive={false}
                aiHoverFx
                pointScaleMul={1.45}
                particleCount={11000}
                size={720}
                assembleIntro
                assembleDuration={AI_ORB_ASSEMBLE_SECONDS}
                voiceLevelRef={orbVoiceRef}
              />
            </div>

            <div
              className={`pointer-events-none relative z-10 flex h-full min-h-0 w-full flex-col ${open ? "-translate-x-32" : ""} ${aiHomeEntranceOn ? "main-search-entrance-on" : "main-search-entrance-off"}`}
            >
              <div className="relative z-10 flex min-h-0 flex-1 flex-col items-center justify-center overflow-y-auto px-6 py-8 md:px-8">
                <div className="relative flex w-full max-w-lg flex-col items-center justify-center">
                  <div className="relative z-10 flex w-full flex-col items-center gap-9 text-center md:gap-10">
                    <div
                      className={`mse-hero-down pointer-events-auto max-w-lg shrink-0 transition-all duration-300 ${homeExiting ? "opacity-0 -translate-y-6" : ""}`}
                    >
                      <h2 className="font-headline inline-flex flex-wrap items-baseline justify-center gap-0 text-4xl font-semibold tracking-tight md:text-5xl lg:text-6xl">
                        <span className="font-headline inline-block bg-gradient-to-r from-[#5e5a52] from-[6%] via-[#b8b0a2] to-[#d4cec2] bg-clip-text text-transparent">
                          B
                        </span>
                        <span className="font-headline text-[#cbc4b6] drop-shadow-[0_1px_5px_rgba(18,16,14,0.18)]">
                          eyond Smarte
                        </span>
                        <span className="font-headline inline-block bg-gradient-to-r from-[#d4cec2] via-[#9e978a] to-[#45423c] to-[90%] bg-clip-text text-transparent">
                          r
                        </span>
                      </h2>
                    </div>
                    <form
                      onSubmit={handleSearch}
                      className={`mse-search-up group pointer-events-auto relative z-10 w-full shrink-0 transition-[max-width] duration-300 ${
                        homeInputExpanded
                          ? "max-w-[min(96vw,46rem)] md:max-w-[min(86vw,56rem)]"
                          : "max-w-[min(90vw,22rem)] md:max-w-[24rem]"
                      }`}
                      style={homeExiting ? { visibility: "hidden" } : {}}
                    >
                      <div className="pointer-events-none absolute -inset-[2px] rounded-full bg-gradient-to-r from-fuchsia-500/0 via-violet-400/25 to-fuchsia-500/0 opacity-0 blur-md transition-opacity duration-500 group-focus-within:opacity-100" />
                      <div className="relative flex items-center gap-2 rounded-full border border-violet-200/[0.14] bg-gradient-to-b from-violet-100/[0.09] to-violet-950/[0.28] px-1.5 py-1.5 shadow-[inset_0_1px_0_rgba(255,255,255,0.16),inset_0_-1px_0_rgba(0,0,0,0.22),0_10px_44px_rgba(32,12,58,0.5)] backdrop-blur-2xl transition-all duration-300 group-focus-within:border-violet-200/25 group-focus-within:from-violet-100/[0.12] group-focus-within:to-violet-950/[0.34]">
                        <button
                          type="button"
                          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-violet-900 to-purple-600 text-violet-50 shadow-[0_0_20px_rgba(124,58,237,0.32),inset_0_1px_0_rgba(255,255,255,0.18)] transition-transform hover:from-violet-800 hover:to-purple-500 active:scale-90"
                        >
                          <span className="material-symbols-outlined text-[20px] font-bold">
                            add
                          </span>
                        </button>
                        <input
                          ref={homeInputRef}
                          name="query"
                          type="text"
                          value={inputValue}
                          onChange={(e) => setInputValue(e.target.value)}
                          onFocus={() => setAiHomeInputFocused(true)}
                          onBlur={() => setAiHomeInputFocused(false)}
                          placeholder={
                            listening ? "듣는 중…" : "Anything you need"
                          }
                          className="min-w-0 flex-1 border-none bg-transparent py-2 font-manrope text-sm text-violet-100/90 outline-none ring-0 placeholder:text-violet-300/45 md:py-2.5 md:text-base"
                        />
                        <button
                          type="button"
                          onClick={toggleMic}
                          aria-pressed={listening}
                          aria-label={
                            listening ? "음성 입력 끄기" : "음성 입력"
                          }
                          className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full border backdrop-blur-md transition-colors ${
                            listening
                              ? "border-rose-400/35 bg-rose-950/40 text-rose-200 shadow-[0_0_16px_rgba(251,113,133,0.25)]"
                              : "border-violet-300/18 bg-violet-950/35 text-violet-200/80 hover:border-violet-200/30 hover:bg-violet-900/40 hover:text-violet-100"
                          }`}
                        >
                          <span className="material-symbols-outlined text-[20px]">
                            mic
                          </span>
                        </button>
                      </div>
                      <button
                        type="submit"
                        aria-hidden
                        className="hidden"
                        tabIndex={-1}
                      />
                    </form>
                  </div>
                </div>
              </div>

              <div
                className="mse-search-up mse-search-up-delay-1 pointer-events-auto flex shrink-0 flex-col items-center justify-end px-6 pb-10 pt-2 md:px-8"
                style={homeExiting ? { visibility: "hidden" } : {}}
              >
                <button
                  ref={btnRef}
                  onClick={handleGoToSearch}
                  disabled={searchTransitioning}
                  type="button"
                  className="ai-home-search-mode-btn group flex items-center gap-3 rounded-full border border-white/20 px-8 py-3 text-sm font-bold uppercase tracking-widest text-neutral-300 transition-all duration-300 hover:border-white/40 hover:text-white hover:shadow-lg disabled:pointer-events-none"
                  style={{
                    background: "rgba(255, 255, 255, 0.1)",
                    backdropFilter: "blur(10px)",
                    boxShadow:
                      "0 8px 32px rgba(139, 92, 246, 0.1), inset 0 1px 1px rgba(255, 255, 255, 0.2)",
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.background =
                      "rgba(255, 255, 255, 0.15)";
                    e.currentTarget.style.boxShadow =
                      "0 8px 32px rgba(139, 92, 246, 0.3), inset 0 1px 1px rgba(255, 255, 255, 0.3), 0 0 30px rgba(139, 92, 246, 0.25)";
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.background =
                      "rgba(255, 255, 255, 0.1)";
                    e.currentTarget.style.boxShadow =
                      "0 8px 32px rgba(139, 92, 246, 0.1), inset 0 1px 1px rgba(255, 255, 255, 0.2)";
                  }}
                >
                  <span
                    className="h-2 w-2 animate-pulse rounded-full bg-violet-500"
                    style={{ boxShadow: "0 0 6px rgba(139, 92, 246, 0.9)" }}
                  />
                  검색 모드로 전환
                  <span className="material-symbols-outlined text-lg transition-transform group-hover:translate-x-1">
                    arrow_forward
                  </span>
                </button>
              </div>
            </div>
          </main>
        </>
      )}

      {/* ══ CHAT ══ (검색/대화 결과 — doSearch·popstate 에서는 'results' 사용) */}
      {(view === "chat" || view === "results" || view === "detail") && (
        <div
          className={`${ml} min-h-0 ${open ? "w-[calc(100%-var(--sidebar-width,16rem))]" : "w-full"} transition-[margin,width] duration-300`}
          style={{
            display: "flex",
            flexDirection: "column",
            height: "100%",
            overflow: "hidden",
          }}
        >
          {/* SearchSidebar 타이틀바(fixed h-8=32px)를 위한 여백 */}
          <div style={{ height: 32, flexShrink: 0 }} />

          {/* Header */}
          <header
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              padding: "0 18px",
              height: 52,
              flexShrink: 0,
              background: "rgb(1,1,4)",
              backdropFilter: "none",
              borderBottom: "1px solid rgba(255,255,255,0.08)",
              boxShadow: "none",
              position: "relative",
              zIndex: 10,
            }}
          >
            <button
              type="button"
              onClick={() => {
                setView("home");
                setTurns([]);
                setInputValue("");
              }}
              title="AI 모드 홈으로 이동"
              className="inline-flex h-8 w-8 items-center justify-center rounded-full bg-white/[0.08] text-white/80 ring-1 ring-white/[0.12] transition hover:bg-white/[0.14] hover:text-white"
            >
              <span className="material-symbols-outlined text-[18px]">
                arrow_back
              </span>
            </button>
            <button
              onClick={() => {
                setView("home");
                setTurns([]);
                setInputValue("");
              }}
              style={{
                fontWeight: 800,
                fontSize: 15,
                letterSpacing: -0.5,
                flexShrink: 0,
                background: "linear-gradient(to right,#c4b5fd,#e879f9)",
                WebkitBackgroundClip: "text",
                WebkitTextFillColor: "transparent",
                cursor: "pointer",
                border: "none",
                padding: 0,
              }}
            >
              Insight AI
            </button>

            {/* 현재 route 뱃지 */}
            {latestTurn?.route === "chat" && (
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 4,
                  fontSize: 10,
                  fontWeight: 700,
                  letterSpacing: "0.08em",
                  textTransform: "uppercase",
                  color: "#e5e7eb",
                  background: "rgb(1,1,4)",
                  border: "1px solid rgb(1,1,4)",
                  padding: "3px 10px",
                  borderRadius: 999,
                  flexShrink: 0,
                }}
              >
                💬 Chat
              </div>
            )}
            {latestTurn?.route === "followup" && (
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 4,
                  fontSize: 10,
                  fontWeight: 700,
                  letterSpacing: "0.08em",
                  textTransform: "uppercase",
                  color: "#e5e7eb",
                  background: "rgb(1,1,4)",
                  border: "1px solid rgb(1,1,4)",
                  padding: "3px 10px",
                  borderRadius: 999,
                  flexShrink: 0,
                }}
              >
                🔗 Followup
              </div>
            )}
            {latestTurn?.route === "qa_gen" && (
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 4,
                  fontSize: 10,
                  fontWeight: 700,
                  letterSpacing: "0.08em",
                  textTransform: "uppercase",
                  color: "#e5e7eb",
                  background: "rgb(1,1,4)",
                  border: "1px solid rgb(1,1,4)",
                  padding: "3px 10px",
                  borderRadius: 999,
                  flexShrink: 0,
                }}
              >
                📝 QA Gen
              </div>
            )}

            {/* AIMODE 스테이지 뱃지 — 진행 중 (단계별 아이콘+라벨) */}
            {isAnyStreaming &&
              (() => {
                const stageMeta = {
                  intent: { icon: "psychology", label: "의도 분석" },
                  searching: { icon: "travel_explore", label: "벡터 검색" },
                  scanning: { icon: "document_scanner", label: "문서 스캔" },
                  generating: { icon: "auto_awesome", label: "답변 생성" },
                  idle: { icon: "progress_activity", label: "처리 중" },
                };
                const m = stageMeta[aimodeStage] || stageMeta.idle;
                return (
                  <div className="relative flex items-center gap-1.5 rounded-full border border-violet-400/30 bg-violet-500/[0.08] px-3 py-1 flex-shrink-0 overflow-hidden">
                    {/* 글로우 펄스 백그라운드 */}
                    <div className="pointer-events-none absolute inset-0 bg-gradient-to-r from-transparent via-violet-400/15 to-transparent animate-pulse" />
                    <span
                      className={`material-symbols-outlined text-violet-200 relative ${aimodeStage === "idle" ? "animate-spin" : "animate-pulse"}`}
                      style={{
                        fontSize: 14,
                        fontVariationSettings: '"FILL" 1',
                      }}
                    >
                      {m.icon}
                    </span>
                    <span className="relative text-[10px] font-bold uppercase tracking-[0.14em] text-violet-100">
                      {m.label}
                    </span>
                    <span className="relative inline-flex gap-0.5 ml-0.5">
                      <span
                        className="h-1 w-1 rounded-full bg-violet-300 animate-bounce"
                        style={{ animationDelay: "0ms" }}
                      />
                      <span
                        className="h-1 w-1 rounded-full bg-violet-300 animate-bounce"
                        style={{ animationDelay: "150ms" }}
                      />
                      <span
                        className="h-1 w-1 rounded-full bg-violet-300 animate-bounce"
                        style={{ animationDelay: "300ms" }}
                      />
                    </span>
                  </div>
                );
              })()}
            {/* AIMODE 완료 뱃지 — turns 또는 aimodeDone 둘 다 인식 */}
            {!isAnyStreaming && (latestTurn?.done || aimodeDone) && (
              <div className="flex items-center gap-1.5 rounded-full border border-emerald-400/35 bg-emerald-500/[0.08] px-3 py-1 flex-shrink-0">
                <span
                  className="material-symbols-outlined text-emerald-300"
                  style={{ fontSize: 14, fontVariationSettings: '"FILL" 1' }}
                >
                  check_circle
                </span>
                <span className="text-[10px] font-bold uppercase tracking-[0.14em] text-emerald-200">
                  완료
                </span>
              </div>
            )}

            <div style={{ flex: 1 }} />
          </header>

          {/* Two-panel */}
          <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>
            {/* ── LEFT: conversation ── */}
            <div
              style={{
                width: "60%",
                display: "flex",
                flexDirection: "column",
                borderRight: "1px solid rgba(167,139,250,0.14)",
                background: AI.leftBg,
                backdropFilter: "blur(10px) saturate(1.06)",
                position: "relative",
                boxShadow: "inset -1px 0 0 rgba(255,255,255,0.04)",
              }}
            >
              <div
                style={{
                  flex: 1,
                  overflowY: "auto",
                  padding: "20px 16px 8px",
                }}
              >
                {turns.map((turn, i) => (
                  <TurnView
                    key={turn.id}
                    turn={turn}
                    isLatest={i === turns.length - 1}
                    onClickSource={handleSelectFile}
                    onClickFile={handleSelectFile}
                  />
                ))}

                {/* ════ AIMODE: 인텐트 헤더 (질문 의도 + 키워드 칩 + [v3] mode 배지) ════ */}
                {useAimode && aimodeQuery && turns.length === 0 && (
                  <div className="mb-4 rounded-2xl border border-violet-400/20 bg-gradient-to-br from-violet-500/[0.06] via-transparent to-fuchsia-500/[0.06] px-4 py-3">
                    <div className="flex items-center gap-2 mb-2">
                      <span
                        className="material-symbols-outlined text-base"
                        style={{
                          color: AI.accentLight,
                          fontVariationSettings: '"FILL" 1',
                        }}
                      >
                        psychology
                      </span>
                      <span
                        className="text-[10px] font-bold uppercase tracking-[0.18em]"
                        style={{ color: AI.accentLight }}
                      >
                        질문 의도 분석
                      </span>
                      {/* [v3] mode 배지 — structured / open / followup */}
                      {aimodeMode && (
                        <span
                          className={`ml-auto rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-[0.12em] border ${
                            aimodeMode === "open"
                              ? "border-emerald-400/40 bg-emerald-500/15 text-emerald-200"
                              : aimodeMode === "followup"
                                ? "border-amber-400/40 bg-amber-500/15 text-amber-200"
                                : "border-sky-400/40 bg-sky-500/15 text-sky-200"
                          }`}
                          title={
                            aimodeMode === "open"
                              ? "키워드로 모든 자료에서 검색"
                              : aimodeMode === "followup"
                                ? "이전 대화 파일에서 후속 검색"
                                : "구조형 검색 (파일 한정 + 내용)"
                          }
                        >
                          {aimodeMode === "open"
                            ? "🔍 키워드 검색"
                            : aimodeMode === "followup"
                              ? "↩ 후속 질문"
                              : "📂 구조 검색"}
                        </span>
                      )}
                    </div>
                    <p className="text-[13px] text-violet-50/95 leading-relaxed mb-2">
                      {aimodeQuery}
                    </p>
                    {(aimodeContentKws.length > 0 ||
                      aimodeDetailKws.length > 0) && (
                      <div className="flex flex-wrap gap-1.5">
                        {aimodeContentKws.map((kw, i) => (
                          <span
                            key={`c-${i}`}
                            className="rounded-full border border-violet-400/30 bg-violet-500/15 px-2.5 py-0.5 text-[10px] font-medium text-violet-200"
                          >
                            {kw}
                          </span>
                        ))}
                        {aimodeDetailKws.map((kw, i) => (
                          <span
                            key={`d-${i}`}
                            className="rounded-full border border-fuchsia-400/25 bg-fuchsia-500/10 px-2.5 py-0.5 text-[10px] font-medium text-fuchsia-200"
                          >
                            {kw}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                {/* [v3.1] References 패널은 답변 카드 아래로 이동 (옵션 A) */}

                {/* ════ AIMODE: 처리중 인디케이터 (눈에 띄게) ════ */}
                {useAimode && streaming && !aimodeAnswer && !aimodeBlocked && turns.length === 0 && (
                  <div className="relative mb-4 overflow-hidden rounded-2xl border border-violet-400/30 bg-gradient-to-br from-violet-600/15 via-fuchsia-600/10 to-violet-600/15 px-5 py-6">
                    {/* 백그라운드 펄스 */}
                    <div className="pointer-events-none absolute inset-0 opacity-60">
                      <div className="absolute -inset-1 animate-pulse bg-gradient-to-r from-transparent via-violet-500/15 to-transparent blur-xl" />
                    </div>
                    <div className="relative flex items-center gap-4">
                      {/* 회전 오브 */}
                      <div className="relative h-12 w-12 shrink-0">
                        <div className="absolute inset-0 rounded-full border-2 border-violet-400/30" />
                        <div className="absolute inset-0 rounded-full border-2 border-transparent border-t-violet-300 animate-spin" />
                        <div className="absolute inset-2 rounded-full bg-gradient-to-br from-violet-400/40 to-fuchsia-400/40 animate-pulse" />
                        <span
                          className="material-symbols-outlined absolute inset-0 m-auto h-fit w-fit text-violet-100"
                          style={{
                            fontSize: 20,
                            fontVariationSettings: '"FILL" 1',
                          }}
                        >
                          {aimodeStage === "generating"
                            ? "auto_awesome"
                            : aimodeStage === "scanning"
                              ? "document_scanner"
                              : aimodeStage === "searching"
                                ? "travel_explore"
                                : "psychology"}
                        </span>
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="text-[11px] font-bold uppercase tracking-[0.2em] text-violet-300 mb-1">
                          {aimodeStage === "generating"
                            ? "답변 생성"
                            : aimodeStage === "scanning"
                              ? "문서 스캔"
                              : aimodeStage === "searching"
                                ? "벡터 검색"
                                : "의도 분석"}
                        </div>
                        <div className="text-[14px] font-semibold text-violet-50">
                          {aimodeStage === "generating"
                            ? "AI 가 답변을 작성하고 있어요"
                            : aimodeStage === "scanning"
                              ? "관련 문서에서 핵심 구절을 찾고 있어요"
                              : aimodeStage === "searching"
                                ? "의미적으로 관련된 파일을 찾고 있어요"
                                : "질문을 이해하는 중이에요"}
                          <span className="inline-flex ml-1 gap-0.5">
                            <span
                              className="h-1 w-1 rounded-full bg-violet-300 animate-bounce"
                              style={{ animationDelay: "0ms" }}
                            />
                            <span
                              className="h-1 w-1 rounded-full bg-violet-300 animate-bounce"
                              style={{ animationDelay: "150ms" }}
                            />
                            <span
                              className="h-1 w-1 rounded-full bg-violet-300 animate-bounce"
                              style={{ animationDelay: "300ms" }}
                            />
                          </span>
                        </div>
                      </div>
                    </div>
                  </div>
                )}

                {/* ════ AIMODE: 백엔드 에러 박스 ════
                    백엔드가 즉시 끊고 error 이벤트 1개만 보내는 케이스(Ollama 미연결,
                    필수 Gemma 모델 미설치 등)에서 사용자에게 명확한 원인/조치를 노출.
                    메시지에 'ollama' / 'gemma' 가 포함되면 설치 명령을 안내한다. */}
                {useAimode && aiError && !aimodeBlocked && (() => {
                  const lower = String(aiError).toLowerCase();
                  const isModelMissing =
                    lower.includes("ollama") ||
                    lower.includes("gemma") ||
                    lower.includes("모델");
                  return (
                    <div className="mb-4 relative overflow-hidden rounded-2xl border border-amber-500/40 bg-amber-500/10 px-4 py-3">
                      <div className="flex items-center gap-2 text-amber-200">
                        <span
                          className="material-symbols-outlined text-lg"
                          style={{ fontVariationSettings: '"FILL" 1' }}
                        >
                          {isModelMissing ? "download" : "error"}
                        </span>
                        <span className="text-sm font-bold">
                          {isModelMissing
                            ? "AI 모델이 설치되어 있지 않습니다"
                            : "AI 응답을 가져오지 못했습니다"}
                        </span>
                      </div>
                      <p className="mt-1 text-xs text-amber-200/85 whitespace-pre-wrap">
                        {aiError}
                      </p>
                      {isModelMissing && (
                        <div className="mt-2 rounded-md border border-amber-300/30 bg-black/30 px-3 py-2 font-mono text-[11px] text-amber-100/90 leading-relaxed select-text">
                          <div>ollama pull gemma:12b</div>
                          <div>ollama pull gemma:4b</div>
                        </div>
                      )}
                      {isModelMissing && (
                        <p className="mt-2 text-[11px] text-amber-200/60">
                          위 명령으로 모델 설치 후 검색을 다시 시도해 주세요.
                          이미 다른 버전(예: gemma3)이 설치되어 있더라도 백엔드는
                          gemma:12b / gemma:4b 이름의 모델을 요구합니다.
                        </p>
                      )}
                    </div>
                  );
                })()}

                {/* ════ AIMODE: 보안 차단 박스 ════ */}
                {useAimode && aimodeBlocked && (
                  <div className="mb-4 relative overflow-hidden rounded-2xl border border-rose-500/40 bg-rose-500/10 px-4 py-3">
                    <div className="flex items-center gap-2 text-rose-200">
                      <span
                        className="material-symbols-outlined text-lg"
                        style={{ fontVariationSettings: '"FILL" 1' }}
                      >
                        shield
                      </span>
                      <span className="text-sm font-bold">
                        보안 모드: 응답이 차단되었습니다
                      </span>
                    </div>
                    <p className="mt-1 text-xs text-rose-200/85">
                      {aimodeBlocked.reason}
                    </p>
                    {aimodeBlocked.pii_types?.length > 0 && (
                      <p className="mt-1 text-[11px] text-rose-200/60">
                        탐지: {aimodeBlocked.pii_types.join(", ")} · 단계:{" "}
                        {aimodeBlocked.stage}
                      </p>
                    )}
                  </div>
                )}

                {/* ════ AIMODE: 마스킹 안내 ════ */}
                {useAimode && aimodeSecurity?.masked && !aimodeBlocked && (
                  <div className="mb-4 rounded-lg border border-amber-500/35 bg-amber-500/10 px-3 py-2 text-xs text-amber-200 flex items-center gap-2">
                    <span
                      className="material-symbols-outlined text-base"
                      style={{ fontVariationSettings: '"FILL" 1' }}
                    >
                      shield
                    </span>
                    보안 모드: 개인정보(
                    {(aimodeSecurity.pii_types || []).join(", ")})가
                    마스킹되었습니다.
                  </div>
                )}

                {/* ════ AIMODE: 답변 카드 (좌측으로 이동) ════
                    [v3 chat] turn 안의 답변과 중복 방지 — TurnView 가 답변을 렌더하면 이 카드 숨김 */}
                {useAimode && aimodeAnswer && !aimodeBlocked && turns.length === 0 && (
                  <div className="mb-4 relative overflow-hidden rounded-2xl border border-violet-400/25 bg-gradient-to-br from-white/[0.04] via-violet-500/[0.03] to-fuchsia-500/[0.04] shadow-[0_8px_32px_rgba(139,92,246,0.12)]">
                    <div className="pointer-events-none absolute inset-0 bg-gradient-to-br from-fuchsia-500/[0.06] via-transparent to-violet-500/[0.08]" />
                    <div className="relative flex items-center gap-3 border-b border-violet-400/15 px-4 py-3">
                      <span
                        className="material-symbols-outlined text-xl"
                        style={{
                          color: AI.accentLight,
                          fontVariationSettings: '"FILL" 1',
                        }}
                      >
                        auto_awesome
                      </span>
                      <span
                        className="text-[11px] font-bold uppercase tracking-[0.18em]"
                        style={{ color: AI.accentLight }}
                      >
                        AI 답변
                      </span>
                      {aimodeDone ? (
                        <span className="ml-auto flex items-center gap-1 text-[11px] text-[#7af5d9]">
                          <span
                            className="material-symbols-outlined text-base"
                            style={{ fontVariationSettings: '"FILL" 1' }}
                          >
                            check_circle
                          </span>{" "}
                          완료
                        </span>
                      ) : (
                        <span
                          className="ml-auto flex items-center gap-1 text-[11px]"
                          style={{ color: AI.accentLight }}
                        >
                          <span className="material-symbols-outlined animate-spin text-base">
                            progress_activity
                          </span>
                          작성 중
                        </span>
                      )}
                    </div>
                    <div className="relative px-5 py-4 text-[14px] leading-[1.7] text-violet-50/95 whitespace-pre-wrap">
                      {(() => {
                        // [v3] 답변 본문의 (XX페이지) / [MM:SS] 자동 감지 → 클릭 chip 렌더.
                        const text = stripMarkdown(aimodeAnswer);
                        const CITE_RE = /(\((\d{1,4})\s*페이지\))|(\[(\d{1,2}:\d{2}(?::\d{2})?)\])/g;
                        const parts = [];
                        let lastIdx = 0;
                        let match;
                        let key = 0;
                        while ((match = CITE_RE.exec(text)) !== null) {
                          if (match.index > lastIdx) {
                            parts.push(
                              <span key={`t-${key++}`}>
                                {text.slice(lastIdx, match.index)}
                              </span>,
                            );
                          }
                          const isPage = !!match[1];
                          const tagLabel = match[0];
                          const value = isPage ? parseInt(match[2], 10) : match[4];
                          const ref = aimodeReferences.find((r) =>
                            isPage ? r.page === value : r.timestamp === value,
                          );
                          const targetSrc = ref
                            ? aimodeSources.find(
                                (s) =>
                                  s.file_name === ref.src ||
                                  s.file_name?.includes(ref.src),
                              )
                            : null;
                          parts.push(
                            <button
                              key={`c-${key++}`}
                              type="button"
                              onClick={() => {
                                if (targetSrc) handleSelectFile(targetSrc);
                              }}
                              disabled={!targetSrc}
                              title={ref?.snippet || ""}
                              className={`inline-flex items-center mx-0.5 px-1.5 py-[1px] rounded-md border text-[11px] font-bold align-baseline transition-colors ${
                                isPage
                                  ? "border-emerald-400/40 bg-emerald-500/15 text-emerald-200"
                                  : "border-amber-400/40 bg-amber-500/15 text-amber-200"
                              } ${
                                targetSrc
                                  ? "cursor-pointer hover:bg-emerald-500/25"
                                  : "cursor-default opacity-70"
                              }`}
                            >
                              {tagLabel}
                            </button>,
                          );
                          lastIdx = match.index + match[0].length;
                        }
                        if (lastIdx < text.length) {
                          parts.push(
                            <span key={`t-${key++}`}>{text.slice(lastIdx)}</span>,
                          );
                        }
                        return parts;
                      })()}
                      {!aimodeDone && (
                        <span className="inline-block w-2 h-5 bg-violet-300 ml-1 animate-pulse align-middle rounded-sm" />
                      )}
                    </div>
                    {/* 매칭 출처 표시:
                        - 문서/이미지: 파일명 + 매칭 청크(검색어 위치 텍스트) 표시. AV 플레이어 없음.
                        - 순수 영상/음성 쿼리: AV 플레이어 자동 표시 */}
                    {(() => {
                      const docSrcs = aimodeSources.filter(
                        (s) => s.file_type === "doc" || s.file_type === "image",
                      );
                      // ── 문서/이미지 쿼리: 청크 표시, AV 플레이어 없음 ──
                      if (docSrcs.length > 0) {
                        return (
                          <div style={{ marginBottom: 13, display: "flex", flexDirection: "column", gap: 8 }}>
                            {docSrcs.map((src, i) => {
                              const fid = src.trichef_id || src.file_name;
                              const chunks = selectedScanChunks?.[fid] || [];
                              const pageNum = src.page_num;
                              const snippet = src.snippet;
                              const displayChunks = chunks.length > 0 ? chunks : snippet ? [snippet] : [];
                              return (
                                <div key={i} style={{
                                  borderRadius: 9,
                                  overflow: "hidden",
                                  border: "1px solid rgba(99,102,241,0.25)",
                                  background: "rgba(99,102,241,0.05)",
                                }}>
                                  {/* 파일명 + 페이지 */}
                                  <div style={{
                                    padding: "6px 11px",
                                    borderBottom: displayChunks.length > 0 ? "1px solid rgba(99,102,241,0.15)" : undefined,
                                    display: "flex", alignItems: "center", gap: 6,
                                    fontSize: 10, fontWeight: 700, color: "#818cf8",
                                  }}>
                                    <span className="material-symbols-outlined" style={{ fontSize: 12 }}>
                                      {src.file_type === "image" ? "image" : "description"}
                                    </span>
                                    {src.file_name}
                                    {pageNum != null && (
                                      <span style={{ marginLeft: 4, color: "#94a3b8", fontWeight: 400 }}>
                                        · {pageNum}페이지
                                      </span>
                                    )}
                                  </div>
                                  {/* 매칭 청크 */}
                                  {displayChunks.map((ck, j) => (
                                    <div key={j} style={{
                                      padding: "7px 11px",
                                      fontSize: 11, color: "#94a3b8", lineHeight: 1.6,
                                      borderTop: j > 0 ? "1px solid rgba(99,102,241,0.08)" : undefined,
                                    }}>
                                      …{String(ck).slice(0, 300)}…
                                    </div>
                                  ))}
                                </div>
                              );
                            })}
                          </div>
                        );
                      }
                      // ── 순수 AV 쿼리: 우측 패널에서 직접 선택 시에만 플레이어 표시 ──
                      // (자동 표시 제거 — 문서 쿼리에서 무관한 영상이 auto-show 되는 문제 방지)
                      const avSrc =
                        selectedFile &&
                        ["video", "audio", "movie", "music"].includes(selectedFile.file_type) &&
                        aimodeSources.some(
                          (s) => s.trichef_id === selectedFile.trichef_id || s.file_name === selectedFile.file_name,
                        )
                          ? selectedFile
                          : null;
                      return avSrc ? (
                        <div style={{ marginBottom: 13 }}>
                          <AVDetailContent result={avSrc} />
                        </div>
                      ) : null;
                    })()}
                  </div>
                )}

                {/* ════ [v3.1] AIMODE: References 패널 (답변 카드 아래) ════
                    extract 노드가 만든 references — 페이지/타임스탬프 클릭 시 detail 열기.
                    옵션 A: 답변 위에서 답변 아래로 이동 (답변 → 출처 흐름이 자연스러움). */}
                {useAimode &&
                  aimodeReferences.length > 0 &&
                  aimodeAnswer &&
                  !aimodeBlocked &&
                  turns.length === 0 && (
                    <div className="mb-4 rounded-2xl border border-emerald-400/20 bg-emerald-500/[0.04] px-4 py-3">
                      <div className="flex items-center gap-2 mb-2">
                        <span
                          className="material-symbols-outlined text-base text-emerald-300"
                          style={{ fontVariationSettings: '"FILL" 1' }}
                        >
                          bookmark
                        </span>
                        <span className="text-[10px] font-bold uppercase tracking-[0.18em] text-emerald-200">
                          원본 위치 ({aimodeReferences.length})
                        </span>
                      </div>
                      <div className="flex flex-col gap-1.5 max-h-[220px] overflow-y-auto pr-1">
                        {aimodeReferences.slice(0, 12).map((ref, i) => {
                          const tag =
                            ref.page != null
                              ? `${ref.page}페이지`
                              : ref.timestamp
                                ? ref.timestamp
                                : "";
                          const src = aimodeSources.find(
                            (s) =>
                              s.file_name === ref.src ||
                              s.file_name?.includes(ref.src),
                          );
                          const clickable = !!src;
                          return (
                            <button
                              key={i}
                              type="button"
                              onClick={() => {
                                if (clickable) handleSelectFile(src);
                              }}
                              disabled={!clickable}
                              className={`flex items-start gap-2 rounded-lg px-2.5 py-1.5 text-left transition-colors ${
                                clickable
                                  ? "border border-emerald-400/20 bg-emerald-500/[0.06] hover:bg-emerald-500/15 cursor-pointer"
                                  : "border border-emerald-400/10 bg-emerald-500/[0.02] cursor-default opacity-70"
                              }`}
                              title={ref.snippet || ""}
                            >
                              {tag && (
                                <span className="shrink-0 rounded-md border border-emerald-400/40 bg-emerald-500/15 px-1.5 py-0.5 text-[10px] font-bold text-emerald-100">
                                  {tag}
                                </span>
                              )}
                              <span className="flex-1 min-w-0">
                                <span className="block text-[11px] font-semibold text-emerald-100 truncate">
                                  {ref.src}
                                </span>
                                <span className="block text-[10px] text-emerald-200/70 line-clamp-2 mt-0.5">
                                  {(ref.snippet || "").slice(0, 100)}
                                </span>
                              </span>
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  )}

                <div ref={conversationEndRef} />
              </div>
              {shouldShowCenterNoInfoAlert && (
                <div
                  style={{
                    position: "absolute",
                    inset: 0,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    pointerEvents: "none",
                    zIndex: 4,
                    padding: 20,
                  }}
                >
                  <div
                    style={{
                      maxWidth: 460,
                      width: "min(92%, 460px)",
                      textAlign: "center",
                      padding: "14px 18px",
                      borderRadius: 14,
                      background: "rgba(17,10,35,0.78)",
                      border: "1px solid rgba(167,139,250,0.34)",
                      color: "#f5f3ff",
                      fontSize: 16,
                      fontWeight: 650,
                      lineHeight: 1.45,
                      backdropFilter: "blur(10px)",
                      boxShadow: "0 14px 34px rgba(6,3,15,0.45)",
                    }}
                  >
                    제공 문서에 해당 정보가 없습니다
                  </div>
                </div>
              )}

              {/* 입력창 */}
              <div
                style={{
                  padding: "10px 14px",
                  flexShrink: 0,
                  borderTop: "1px solid rgba(139,92,246,0.07)",
                  background: "rgba(10,6,24,0.78)",
                  backdropFilter: "blur(12px) saturate(1.06)",
                  boxShadow: "inset 0 1px 0 rgba(255,255,255,0.06)",
                }}
              >
                <form
                  onSubmit={handleSearch}
                  style={{ display: "flex", gap: 8, alignItems: "flex-end" }}
                >
                  <div
                    style={{
                      flex: 1,
                      display: "flex",
                      alignItems: "center",
                      gap: 8,
                      background: AI.card,
                      border: `1px solid ${AI.border}`,
                      borderRadius: 24,
                      padding: "8px 14px",
                      backdropFilter: "blur(12px) saturate(1.08)",
                      boxShadow:
                        "inset 0 1px 0 rgba(255,255,255,0.12), 0 8px 24px rgba(6,3,15,0.3)",
                      transition: "border-color 0.2s",
                    }}
                  >
                    <input
                      ref={chatInputRef}
                      name="query"
                      type="text"
                      value={listening ? "" : inputValue}
                      onChange={(e) =>
                        !listening && setInputValue(e.target.value)
                      }
                      readOnly={listening}
                      placeholder={
                        listening ? "듣는 중…" : "메시지를 입력하세요..."
                      }
                      style={{
                        flex: 1,
                        background: "transparent",
                        border: "none",
                        outline: "none",
                        fontSize: 14,
                        color: "#f1f5f9",
                        caretColor: AI.accentLight,
                        fontFamily: "inherit",
                        letterSpacing: "-0.01em",
                      }}
                    />
                    <button
                      type="button"
                      onClick={toggleMic}
                      style={{
                        background: "none",
                        border: "none",
                        cursor: "pointer",
                        padding: 0,
                        flexShrink: 0,
                        color: listening
                          ? AI.accentLight
                          : "rgba(139,92,246,0.3)",
                        transition: "color 0.2s",
                      }}
                    >
                      <span
                        className="material-symbols-outlined"
                        style={{
                          fontSize: 16,
                          fontVariationSettings: listening
                            ? '"FILL" 1'
                            : '"FILL" 0',
                        }}
                      >
                        mic
                      </span>
                    </button>
                    <button
                      type="button"
                      onClick={() => setSecurityMode((v) => !v)}
                      title={
                        securityMode
                          ? "보안 모드 켜짐: LLM 응답이 SecurityCritic 통과 후 송출됨"
                          : "보안 모드 꺼짐"
                      }
                      style={{
                        background: "none",
                        border: "none",
                        cursor: "pointer",
                        padding: 0,
                        flexShrink: 0,
                        color: securityMode
                          ? "#f87171"
                          : "rgba(139,92,246,0.3)",
                        transition: "color 0.2s",
                      }}
                    >
                      <span
                        className="material-symbols-outlined"
                        style={{
                          fontSize: 16,
                          fontVariationSettings: securityMode
                            ? '"FILL" 1'
                            : '"FILL" 0',
                          filter: securityMode
                            ? "drop-shadow(0 0 6px rgba(248,113,113,0.6))"
                            : "none",
                        }}
                      >
                        shield
                      </span>
                    </button>
                    {/* [v3.2] 대화 → PDF 정리·저장 (입력창 내부 아이콘) */}
                    <button
                      type="button"
                      onClick={handleExportPdf}
                      disabled={pdfExporting || turns.length === 0 || isAnyStreaming}
                      title={
                        turns.length === 0
                          ? "대화가 시작되면 PDF로 저장할 수 있어요"
                          : pdfExporting
                          ? "PDF 생성 중…"
                          : "대화를 AI가 정리해서 PDF로 저장"
                      }
                      style={{
                        background: "none",
                        border: "none",
                        cursor:
                          pdfExporting || turns.length === 0 || isAnyStreaming
                            ? "default"
                            : "pointer",
                        padding: 0,
                        flexShrink: 0,
                        color:
                          turns.length === 0 || isAnyStreaming
                            ? "rgba(139,92,246,0.25)"
                            : AI.accentLight,
                        transition: "color 0.2s",
                        opacity: pdfExporting ? 0.6 : 1,
                      }}
                    >
                      <span
                        className="material-symbols-outlined"
                        style={{
                          fontSize: 16,
                          fontVariationSettings:
                            turns.length > 0 && !isAnyStreaming
                              ? '"FILL" 1'
                              : '"FILL" 0',
                          animation: pdfExporting
                            ? "spin 0.9s linear infinite"
                            : "none",
                        }}
                      >
                        {pdfExporting ? "progress_activity" : "picture_as_pdf"}
                      </span>
                    </button>
                  </div>
                  <button
                    type="submit"
                    disabled={!inputValue.trim() && !listening}
                    style={{
                      width: 38,
                      height: 38,
                      borderRadius: "50%",
                      flexShrink: 0,
                      border: "none",
                      background: inputValue.trim()
                        ? "linear-gradient(135deg,rgba(109,40,217,0.95),rgba(124,58,237,0.88))"
                        : "rgba(139,92,246,0.08)",
                      cursor: inputValue.trim() ? "pointer" : "default",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      transition: "all 0.2s",
                      boxShadow: inputValue.trim()
                        ? "0 4px 14px rgba(109,40,217,0.35)"
                        : "none",
                    }}
                  >
                    <span
                      className="material-symbols-outlined"
                      style={{
                        fontSize: 16,
                        color: inputValue.trim() ? "#fff" : "#1a1030",
                      }}
                    >
                      send
                    </span>
                  </button>
                </form>
              </div>
            </div>

            {/* ── RIGHT: cards / detail ── */}
            <div
              style={{
                width: "40%",
                display: "flex",
                flexDirection: "column",
                background: AI.rightBg,
                backdropFilter: "blur(10px) saturate(1.06)",
                overflow: "hidden",
                boxShadow: "inset 1px 0 0 rgba(255,255,255,0.04)",
              }}
            >
              {rightMode === "cards" ? (
                <div
                  style={{ flex: 1, overflowY: "auto", padding: "16px 12px" }}
                >
                  {rightCandidates.length === 0 ? (
                    <div
                      style={{
                        height: "100%",
                        display: "flex",
                        flexDirection: "column",
                        alignItems: "center",
                        justifyContent: "center",
                        gap: 14,
                        padding: 40,
                      }}
                    >
                      {streaming ? (
                        // 검색 중 — 회전 오브 + 스캔 메시지
                        <>
                          <div className="relative h-16 w-16">
                            <div className="absolute inset-0 rounded-full border-2 border-violet-400/20" />
                            <div className="absolute inset-0 rounded-full border-2 border-transparent border-t-violet-400 border-r-fuchsia-400 animate-spin" />
                            <div className="absolute inset-3 rounded-full bg-gradient-to-br from-violet-500/30 to-fuchsia-500/30 animate-pulse" />
                            <span
                              className="material-symbols-outlined absolute inset-0 m-auto h-fit w-fit text-violet-200"
                              style={{
                                fontSize: 22,
                                fontVariationSettings: '"FILL" 1',
                              }}
                            >
                              travel_explore
                            </span>
                          </div>
                          <div className="text-center">
                            <p className="text-[11px] font-bold uppercase tracking-[0.18em] text-violet-300 mb-1">
                              벡터 검색 중
                            </p>
                            <p className="text-[12px] text-violet-100/75">
                              관련 파일을 찾고 있어요
                            </p>
                          </div>
                        </>
                      ) : (
                        <>
                          <span
                            className="material-symbols-outlined"
                            style={{
                              fontSize: 40,
                              color: "rgba(167,139,250,0.22)",
                            }}
                          >
                            folder_open
                          </span>
                          <p
                            style={{
                              fontSize: 11,
                              color: "#94a3b8",
                              textAlign: "center",
                            }}
                          >
                            후보 파일이 여기 표시됩니다
                          </p>
                        </>
                      )}
                    </div>
                  ) : (
                    <>
                      {/* 헤더 — 스캔 진행상태 함께 표시 */}
                      {(() => {
                        const total = rightCandidates.length;
                        const scanned = rightCandidates.reduce(
                          (acc, src, i) => {
                            const fid =
                              src.trichef_id || src.file_name || String(i);
                            const st = rightScanStates[fid];
                            return (
                              acc +
                              (st === "found" || st === "not_found" ? 1 : 0)
                            );
                          },
                          0,
                        );
                        const found = rightCandidates.reduce((acc, src, i) => {
                          const fid =
                            src.trichef_id || src.file_name || String(i);
                          return (
                            acc + (rightScanStates[fid] === "found" ? 1 : 0)
                          );
                        }, 0);
                        const inProgress = scanned < total && streaming;
                        return (
                          <div className="mb-3 flex items-center justify-between gap-2 px-1">
                            <div className="flex items-center gap-2">
                              <span
                                className={`material-symbols-outlined text-base ${inProgress ? "text-violet-300 animate-pulse" : "text-violet-400/70"}`}
                              >
                                {inProgress
                                  ? "document_scanner"
                                  : "folder_managed"}
                              </span>
                              <span className="text-[10px] font-bold uppercase tracking-[0.14em] text-violet-300">
                                {inProgress
                                  ? `스캔 ${scanned}/${total}`
                                  : `후보 ${total}개`}
                              </span>
                              {found > 0 && (
                                <span className="rounded-full bg-emerald-500/15 border border-emerald-400/30 px-2 py-0.5 text-[10px] font-bold text-emerald-300">
                                  매칭 {found}
                                </span>
                              )}
                            </div>
                            {inProgress && (
                              <div className="flex-1 max-w-[80px] h-1 rounded-full bg-violet-950/60 overflow-hidden">
                                <div
                                  className="h-full bg-gradient-to-r from-violet-400 to-fuchsia-400 transition-all duration-500"
                                  style={{
                                    width: `${total > 0 ? (scanned / total) * 100 : 0}%`,
                                  }}
                                />
                              </div>
                            )}
                          </div>
                        );
                      })()}
                      <div
                        style={{
                          display: "grid",
                          gridTemplateColumns: "repeat(2,1fr)",
                          gap: 8,
                        }}
                      >
                        {rightCandidates.map((src, i) => {
                          const fid =
                            src.trichef_id || src.file_name || String(i);
                          return (
                            <FileCard
                              key={fid}
                              source={src}
                              index={i}
                              scanState={rightScanStates[fid] || "idle"}
                              selected={
                                selectedFile?.trichef_id === src.trichef_id &&
                                rightMode === "detail"
                              }
                              onClick={handleSelectFile}
                            />
                          );
                        })}
                      </div>
                    </>
                  )}
                </div>
              ) : (
                <div style={{ flex: 1, overflowY: "auto" }}>
                  <div
                    style={{
                      padding: "10px 13px",
                      borderBottom: "1px solid rgba(139,92,246,0.08)",
                      display: "flex",
                      alignItems: "center",
                      gap: 6,
                    }}
                  >
                    <button
                      onClick={() => setRightMode("cards")}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 4,
                        background: "none",
                        border: "none",
                        cursor: "pointer",
                        fontSize: 11,
                        color: "#475569",
                        padding: 0,
                      }}
                    >
                      <span
                        className="material-symbols-outlined"
                        style={{ fontSize: 14 }}
                      >
                        arrow_back
                      </span>
                      목록으로
                    </button>
                  </div>
                  {selectedFile && (
                    <div style={{ padding: "13px" }}>
                      <div
                        style={{
                          display: "flex",
                          gap: 10,
                          alignItems: "flex-start",
                          marginBottom: 13,
                          padding: "11px 12px",
                          background: "rgba(109,40,217,0.08)",
                          border: `1px solid ${AI.border}`,
                          borderRadius: 11,
                        }}
                      >
                        <div
                          style={{
                            width: 36,
                            height: 36,
                            borderRadius: 8,
                            flexShrink: 0,
                            background:
                              "linear-gradient(135deg,#6d28d9,#7c3aed)",
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "center",
                          }}
                        >
                          <span
                            className="material-symbols-outlined"
                            style={{
                              fontSize: 18,
                              color: "#fff",
                              fontVariationSettings: '"FILL" 1',
                            }}
                          >
                            {getTypeMeta(selectedFile.file_type).icon}
                          </span>
                        </div>
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div
                            style={{
                              fontSize: 12,
                              fontWeight: 700,
                              color: "#e2e8f0",
                              overflow: "hidden",
                              textOverflow: "ellipsis",
                              whiteSpace: "nowrap",
                              marginBottom: 2,
                            }}
                          >
                            {selectedFile.file_name}
                          </div>
                          <div
                            style={{
                              fontSize: 9,
                              color: "#94a3b8",
                              fontFamily: "monospace",
                              overflow: "hidden",
                              textOverflow: "ellipsis",
                              whiteSpace: "nowrap",
                            }}
                          >
                            {selectedFile.file_path}
                          </div>
                        </div>
                        <div style={{ textAlign: "right", flexShrink: 0 }}>
                          <div
                            style={{
                              fontSize: 16,
                              fontWeight: 800,
                              color: AI.accentLight,
                            }}
                          >
                            {((selectedFile.confidence ?? 0) * 100).toFixed(0)}%
                          </div>
                          <div style={{ fontSize: 9, color: "#94a3b8" }}>
                            신뢰도
                          </div>
                        </div>
                      </div>

                      {["video", "audio", "movie", "music"].includes(
                        selectedFile.file_type,
                      ) && (
                        <div style={{ marginBottom: 13 }}>
                          <AVDetailContent result={selectedFile} />
                        </div>
                      )}

                      {selectedFile.file_type === "image" &&
                        selectedFile.preview_url && (
                          <div
                            style={{
                              marginBottom: 13,
                              borderRadius: 10,
                              background: "#06030f",
                              padding: 10,
                              display: "flex",
                              alignItems: "center",
                              justifyContent: "center",
                            }}
                          >
                            <img
                              src={`${API_BASE}${selectedFile.preview_url}`}
                              alt={selectedFile.file_name}
                              style={{
                                maxWidth: "100%",
                                maxHeight: 220,
                                objectFit: "contain",
                                borderRadius: 7,
                                cursor: "zoom-in",
                              }}
                              onClick={() => setZoomImage({
                                src: `${API_BASE}${selectedFile.preview_url}`,
                                title: selectedFile.file_name,
                              })}
                            />
                          </div>
                        )}

                      {/* [v3.1] doc 페이지 이미지 (references chip 클릭 시 표시).
                          trichef_id 가 page_images/<stem>/p<N>.jpg 형태이거나 단순 stem 일 수 있음. */}
                      {selectedFile.file_type === "doc" &&
                        (selectedFile.selected_page != null || selectedFile.page_num != null) &&
                        selectedFile.trichef_id && (() => {
                          const stem = selectedFile.trichef_id.replace(/^page_images\//, "").split("/")[0];
                          const pageNum = (selectedFile.selected_page ?? selectedFile.page_num) - 1; // UI 는 1-indexed, 파일은 0-indexed
                          const pad = String(Math.max(0, pageNum)).padStart(4, "0");
                          const path = `page_images/${stem}/p${pad}.jpg`;
                          const url = `${API_BASE}/api/trichef/file?domain=doc_page&path=${encodeURIComponent(path)}`;
                          const displayPage = selectedFile.selected_page ?? selectedFile.page_num;
                          return (
                            <div
                              style={{
                                marginBottom: 13,
                                borderRadius: 10,
                                background: "#06030f",
                                padding: 10,
                                display: "flex",
                                flexDirection: "column",
                                alignItems: "center",
                                gap: 8,
                              }}
                            >
                              <div
                                style={{
                                  alignSelf: "stretch",
                                  display: "flex",
                                  alignItems: "center",
                                  justifyContent: "space-between",
                                  fontSize: 11,
                                  fontWeight: 700,
                                  color: "#86efac",
                                  letterSpacing: "0.08em",
                                  textTransform: "uppercase",
                                }}
                              >
                                <span>📄 {displayPage}페이지 미리보기</span>
                                <span style={{ fontSize: 10, color: "#94a3b8", textTransform: "none" }}>
                                  클릭하여 확대
                                </span>
                              </div>
                              <img
                                src={url}
                                alt={`${selectedFile.file_name} ${displayPage}p`}
                                style={{
                                  maxWidth: "100%",
                                  maxHeight: 380,
                                  objectFit: "contain",
                                  borderRadius: 7,
                                  cursor: "zoom-in",
                                  border: "1px solid rgba(139,92,246,0.18)",
                                }}
                                onClick={() => setZoomImage({ src: url, title: `${selectedFile.file_name} - ${displayPage}페이지` })}
                                onError={(e) => {
                                  e.currentTarget.style.display = "none";
                                  const sibling = e.currentTarget.nextElementSibling;
                                  if (sibling) sibling.style.display = "block";
                                }}
                              />
                              <div
                                style={{
                                  display: "none",
                                  fontSize: 11,
                                  color: "#fbbf24",
                                  padding: "8px 12px",
                                }}
                              >
                                ⚠️ 페이지 이미지 로드 실패 (캐시에 없음)
                              </div>
                              {/* [v3.1] 인용 부분 (chip 클릭 시 전달된 snippet) */}
                              {selectedFile.snippet && (
                                <div
                                  style={{
                                    alignSelf: "stretch",
                                    marginTop: 4,
                                    padding: "10px 12px",
                                    borderRadius: 8,
                                    background: "rgba(16,185,129,0.08)",
                                    border: "1px solid rgba(16,185,129,0.22)",
                                  }}
                                >
                                  <div
                                    style={{
                                      fontSize: 10,
                                      fontWeight: 700,
                                      color: "#6ee7b7",
                                      letterSpacing: "0.12em",
                                      textTransform: "uppercase",
                                      marginBottom: 6,
                                      display: "flex",
                                      alignItems: "center",
                                      gap: 4,
                                    }}
                                  >
                                    <span
                                      className="material-symbols-outlined"
                                      style={{ fontSize: 13, fontVariationSettings: '"FILL" 1' }}
                                    >
                                      format_quote
                                    </span>
                                    인용한 부분
                                  </div>
                                  <div
                                    style={{
                                      fontSize: 12,
                                      lineHeight: 1.6,
                                      color: "#dcfce7",
                                      whiteSpace: "pre-wrap",
                                      maxHeight: 200,
                                      overflowY: "auto",
                                    }}
                                  >
                                    {selectedFile.snippet}
                                  </div>
                                </div>
                              )}
                            </div>
                          );
                        })()}

                      {(() => {
                        const fid =
                          selectedFile.trichef_id || selectedFile.file_name;
                        const cks = selectedScanChunks[fid];
                        if (!cks?.length) return null;
                        return (
                          <div
                            style={{
                              marginBottom: 13,
                              borderRadius: 9,
                              overflow: "hidden",
                              border: "1px solid rgba(16,185,129,0.2)",
                            }}
                          >
                            <div
                              style={{
                                padding: "7px 11px",
                                background: "rgba(16,185,129,0.08)",
                                borderBottom: "1px solid rgba(16,185,129,0.15)",
                                display: "flex",
                                alignItems: "center",
                                gap: 5,
                                fontSize: 10,
                                fontWeight: 700,
                                color: "#10b981",
                              }}
                            >
                              <span
                                className="material-symbols-outlined"
                                style={{ fontSize: 11 }}
                              >
                                find_in_page
                              </span>
                              매칭 내용 ({cks.length}개)
                            </div>
                            <div
                              style={{
                                padding: "9px 11px",
                                display: "flex",
                                flexDirection: "column",
                                gap: 6,
                              }}
                            >
                              {cks.map((chunk, i) => (
                                <div
                                  key={i}
                                  style={{
                                    padding: "7px 9px",
                                    borderRadius: 7,
                                    fontSize: 11,
                                    color: "#94a3b8",
                                    lineHeight: 1.5,
                                    background: "rgba(16,185,129,0.04)",
                                    border: "1px solid rgba(16,185,129,0.1)",
                                  }}
                                >
                                  ...{chunk.slice(0, 280)}...
                                </div>
                              ))}
                            </div>
                          </div>
                        );
                      })()}

                      {selectedFile.file_type === "doc" && (
                        <div style={{ marginBottom: 13 }}>
                          {detailLoading ? (
                            <div
                              style={{
                                display: "flex",
                                alignItems: "center",
                                gap: 6,
                                fontSize: 11,
                                color: "#334155",
                              }}
                            >
                              <span
                                className="material-symbols-outlined ai-spin"
                                style={{ fontSize: 12 }}
                              >
                                progress_activity
                              </span>
                              로드 중...
                            </div>
                          ) : fileDetail ? (
                            <div
                              style={{
                                display: "flex",
                                flexDirection: "column",
                                gap: 4,
                              }}
                            >
                              {Object.entries(fileDetail)
                                .slice(0, 8)
                                .map(([k, v]) => (
                                  <div
                                    key={k}
                                    style={{
                                      display: "flex",
                                      gap: 8,
                                      fontSize: 11,
                                    }}
                                  >
                                    <span
                                      style={{
                                        color: "#94a3b8",
                                        flexShrink: 0,
                                        width: 70,
                                      }}
                                    >
                                      {k}
                                    </span>
                                    <span
                                      style={{
                                        color: "#e2e8f0",
                                        overflow: "hidden",
                                        textOverflow: "ellipsis",
                                        whiteSpace: "nowrap",
                                      }}
                                    >
                                      {String(v)}
                                    </span>
                                  </div>
                                ))}
                            </div>
                          ) : null}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      <style>{`
        @keyframes ai-spin  { from{transform:rotate(0deg)} to{transform:rotate(360deg)} }
        @keyframes ai-blink { 0%,100%{opacity:1} 50%{opacity:0} }
        @keyframes ai-scan-line { 0%{transform:translateY(-100%);opacity:0.8} 100%{transform:translateY(100%);opacity:0.3} }
        @keyframes ai-avatar-pulse { 0%,100%{transform:scale(1);opacity:0.55} 50%{transform:scale(1.08);opacity:0.18} }
        .ai-spin { animation: ai-spin 1s linear infinite; }
        .ai-scan-line {
          position:absolute;top:0;left:0;right:0;height:40%;
          background:linear-gradient(to bottom,transparent,rgba(139,92,246,0.35),transparent);
          animation:ai-scan-line 1.2s ease-in-out infinite;
        }
      `}</style>

      {/* [v3.1] 페이지 이미지 확대 modal — chip 또는 미리보기 클릭 시 표시 */}
      {zoomImage && (
        <div
          onClick={() => setZoomImage(null)}
          style={{
            position: "fixed",
            inset: 0,
            zIndex: 9999,
            background: "rgba(0,0,0,0.88)",
            backdropFilter: "blur(8px)",
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            cursor: "zoom-out",
            padding: 40,
          }}
        >
          <div
            style={{
              maxWidth: "90vw",
              maxHeight: "85vh",
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              gap: 12,
            }}
          >
            {zoomImage.title && (
              <div
                style={{
                  fontSize: 13,
                  fontWeight: 700,
                  color: "#e2e8f0",
                  letterSpacing: "-0.01em",
                  padding: "8px 14px",
                  background: "rgba(139,92,246,0.15)",
                  border: "1px solid rgba(139,92,246,0.3)",
                  borderRadius: 8,
                }}
              >
                {zoomImage.title}
              </div>
            )}
            <img
              src={zoomImage.src}
              alt={zoomImage.title || "preview"}
              onClick={(e) => e.stopPropagation()}
              style={{
                maxWidth: "90vw",
                maxHeight: "78vh",
                objectFit: "contain",
                borderRadius: 8,
                boxShadow: "0 20px 60px rgba(0,0,0,0.5)",
                cursor: "default",
              }}
            />
            <div
              style={{
                fontSize: 11,
                color: "#94a3b8",
                opacity: 0.7,
              }}
            >
              어두운 영역 클릭 또는 ESC 로 닫기
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
