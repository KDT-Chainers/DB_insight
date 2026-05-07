import { useState, useRef, useEffect, useCallback } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import SearchSidebar from "../components/SearchSidebar";
import AnimatedOrb from "../components/AnimatedOrb";
import { useSidebar } from "../context/SidebarContext";
import { useSpeechRecognition } from "../hooks/useSpeechRecognition";
import { useMicLevelRef } from "../hooks/useMicLevelRef";
import { API_BASE } from "../api";

/** Orb `assembleIntro` 길이와 헤일로 PNG `ai-orbit-halo-emerge` 동기 (초) */
const AI_ORB_ASSEMBLE_SECONDS = 8;

const AI = {
  accent: "#8b5cf6",
  accentLight: "#a78bfa",
  accentDark: "#6d28d9",
  bg: "#060410",
  leftBg: "rgba(12,8,24,0.86)",
  rightBg: "rgba(8,5,18,0.82)",
  card: "rgba(24,17,42,0.62)",
  border: "rgba(167,139,250,0.24)",
};

const TYPE_META = {
  doc:   { icon: 'description', color: 'text-[#8cf2ff]', label: '문서',   grad: 'from-[#1e3a6e] to-[#5c9dff]' },
  video: { icon: 'movie',       color: 'text-[#ff59e0]', label: '동영상', grad: 'from-[#581c87] to-[#be185d]' },
  image: { icon: 'image',       color: 'text-[#52fac7]', label: '이미지', grad: 'from-[#0f766e] to-[#14b8a6]' },
  audio: { icon: 'volume_up',   color: 'text-[#ff7a5c]', label: '음성',   grad: 'from-[#7c2d12] to-[#ea580c]' },
  movie: { icon: 'movie',       color: 'text-[#ff59e0]', label: '동영상', grad: 'from-[#581c87] to-[#be185d]' },
  music: { icon: 'volume_up',   color: 'text-[#ff7a5c]', label: '음성',   grad: 'from-[#7c2d12] to-[#ea580c]' },
}
const getTypeMeta = (t) =>
  TYPE_META[t] ?? { icon: 'insert_drive_file', color: 'text-on-surface-variant', label: t ?? '파일', grad: 'from-[#1c253e] to-[#263354]' }

function fmtTime(sec) {
  if (!sec && sec !== 0) return '0:00'
  const s = Math.floor(sec)
  const m = Math.floor(s / 60)
  return `${m}:${String(s % 60).padStart(2, '0')}`
}

// AI 답변 안전장치 — 시스템 프롬프트로 마크다운 금지했지만,
// LLM 이 이를 어길 경우를 대비한 프론트엔드 폴리필.
// 별표/헤딩/백틱/인용/하이픈 불릿 → 평문 변환
function stripMarkdown(text) {
  if (!text) return text
  return text
    .replace(/\*\*(.+?)\*\*/g, "$1")
    .replace(/(?<![*\w])\*(.+?)\*(?!\*)/g, "$1")
    .replace(/^#{1,6}\s+/gm, "")
    .replace(/`([^`\n]+)`/g, "$1")
    .replace(/^>\s+/gm, "")
    .replace(/^[-*_]{3,}\s*$/gm, "")
    .replace(/^(\s*)[-*]\s+/gm, "$1• ");
}
function renderAnswer(text) {
  if (!text) return null;
  return text.split(/(\[출처\d+\])/g).map((part, i) =>
    /^\[출처\d+\]$/.test(part) ? (
      <span
        key={i}
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
        {part}
      </span>
    ) : (
      <span key={i}>{part}</span>
    ),
  );
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
  blocked: null,    // { stage: 'stream'|'final', reason, pii_types }
  security: null,   // { masked: bool, pii_types, reason }
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
          boxShadow: "0 0 0 1px rgba(167,139,250,0.34), 0 0 16px rgba(139,92,246,0.3)",
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
  const {
    query,
    route,
    intentMessage,
    fileKeywords,
    detailKeywords,
    candidates,
    scanStates,
    scanChunks,
    scannedCount,
    foundCount,
    sources,
    answer,
    streaming,
    done,
    error,
    keyFacts,
    generating,
    qaGenerating,
    qaAttempt,
    qaMax,
    qaQuestion,
    qaAnswer,
    qaValid,
    qaIssues,
    qaSources,
    blocked,
    security,
  } = turn;
  const isChatMode = route === "chat";
  const isQaMode = route === "qa_gen";
  const showCenterNotice = done && !streaming && isNoInfoCenterAlert(answer);
  const shouldRenderInlineAnswer = answer && !isQaMode && !blocked && !showCenterNotice;
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
                <span className="material-symbols-outlined" style={{ fontSize: 18, color: "#f87171", marginTop: 1, fontVariationSettings: '"FILL" 1' }}>shield</span>
                <div>
                  <div style={{ fontWeight: 600, marginBottom: 2 }}>
                    보안 모드: 응답이 차단되었습니다
                  </div>
                  <div style={{ opacity: 0.9 }}>{blocked.reason}</div>
                  {blocked.pii_types && blocked.pii_types.length > 0 && (
                    <div style={{ marginTop: 4, fontSize: 11, opacity: 0.7 }}>
                      탐지: {blocked.pii_types.join(", ")} · 단계: {blocked.stage}
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
                <span className="material-symbols-outlined" style={{ fontSize: 16, color: "#fbbf24", fontVariationSettings: '"FILL" 1' }}>shield</span>
                <span>보안 모드: 개인정보({(security.pii_types || []).join(", ")})가 마스킹되었습니다.</span>
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
                  whiteSpace: "pre-wrap",
                  letterSpacing: "-0.01em",
                  backdropFilter: "blur(8px) saturate(1.05)",
                  boxShadow: "inset 0 1px 0 rgba(255,255,255,0.08)",
                }}
              >
                {renderAnswer(stripMarkdown(answer))}
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

            {/* 출처 */}
            {done && sources.length > 0 && (
              <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
                {sources.map((src, i) => (
                  <button
                    key={i}
                    onClick={() => onClickSource?.(src)}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 6,
                      padding: "3px 6px",
                      borderRadius: 6,
                      fontSize: 11,
                      background: "transparent",
                      border: "none",
                      cursor: "pointer",
                      color: "#4b5563",
                      textAlign: "left",
                    }}
                  >
                    <span
                      style={{
                        fontSize: 11,
                        fontWeight: 700,
                        flexShrink: 0,
                        background: "rgba(139,92,246,0.15)",
                        color: AI.accentLight,
                        padding: "2px 7px",
                        borderRadius: 4,
                      }}
                    >
                      출처{i + 1}
                    </span>
                    <span
                      style={{
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                        fontSize: 12.5,
                      }}
                    >
                      {src.file_name || "?"}
                    </span>
                  </button>
                ))}
              </div>
            )}

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
function AIIterationPanel({ iterationData, domainSelection, streaming, hasLLM }) {
  const [collapsed, setCollapsed] = useState(false)

  if (!iterationData.length && !streaming) return null

  const focusedCount = iterationData.filter(it => it.iteration > 0).length

  return (
    <div className="mb-6 rounded-xl overflow-hidden" style={{ border: `1px solid ${AI.border}`, background: AI.card }}>
      {/* 패널 헤더 */}
      <button
        onClick={() => setCollapsed(c => !c)}
        className="w-full flex items-center justify-between px-5 py-3 hover:brightness-110 transition-all"
        style={{ background: 'rgba(109,40,217,0.15)' }}
      >
        <div className="flex items-center gap-2.5">
          <span className="material-symbols-outlined text-lg" style={{ color: AI.accentLight, fontVariationSettings: '"FILL" 1' }}>
            {streaming ? 'psychology' : 'auto_awesome'}
          </span>
          <span className="text-sm font-bold" style={{ color: AI.accentLight }}>AI 탐색 과정</span>
          <span className="text-[10px] px-2 py-0.5 rounded-full font-bold"
            style={{ background: 'rgba(139,92,246,0.15)', color: AI.accentLight, border: `1px solid ${AI.border}` }}>
            {iterationData.length}단계
          </span>
          {hasLLM !== undefined && (
            <span className="text-[10px] px-2 py-0.5 rounded-full font-bold"
              style={{ background: hasLLM ? 'rgba(139,92,246,0.1)' : 'rgba(100,116,139,0.1)',
                       color: hasLLM ? AI.accentLight : '#94a3b8',
                       border: `1px solid ${hasLLM ? AI.border : 'rgba(100,116,139,0.15)'}` }}>
              {hasLLM ? '🤖 LLM' : '⚙️ 휴리스틱'}
            </span>
          )}
          {streaming && <span className="material-symbols-outlined text-base animate-spin" style={{ color: AI.accent }}>progress_activity</span>}
        </div>
        <span className="material-symbols-outlined text-sm text-on-surface-variant/50">
          {collapsed ? 'expand_more' : 'expand_less'}
        </span>
      </button>

      {!collapsed && (
        <div className="p-4 space-y-3">
          {iterationData.map((step, idx) => {
            const isGlobal = step.iteration === 0
            const dc = DOMAIN_META[step.domain] ?? DOMAIN_META.all

            return (
              <div key={idx}>
                {/* 도메인 선택 안내 배너 (전체→집중 전환 시) */}
                {!isGlobal && idx > 0 && iterationData[idx - 1]?.iteration === 0 && domainSelection && (
                  <div className="flex items-start gap-2 mb-2 px-3 py-2 rounded-lg"
                    style={{ background: 'rgba(109,40,217,0.08)', border: `1px dashed ${AI.border}` }}>
                    <span className="material-symbols-outlined text-sm shrink-0 mt-0.5" style={{ color: AI.accent }}>arrow_forward</span>
                    <div>
                      <span className="text-[11px] font-bold" style={{ color: AI.accentLight }}>
                        {dc.label} 도메인으로 집중합니다
                      </span>
                      <span className="text-[11px] text-on-surface-variant/50 ml-2">{domainSelection.reason}</span>
                    </div>
                  </div>
                )}

                {/* 단계 카드 */}
                <div className="rounded-xl overflow-hidden"
                  style={{ 
                    border: `1.5px solid ${dc.border}28`, 
                    background: 'rgba(13, 7, 24, 0.5)',
                    backdropFilter: 'blur(12px)',
                    boxShadow: `0 4px 16px rgba(0, 0, 0, 0.2), inset 0 1px 2px rgba(255, 255, 255, 0.08), inset 0 -1px 2px rgba(0, 0, 0, 0.3)`
                  }}>

                  {/* 단계 헤더 */}
                  <div className="flex items-center gap-2 px-3 py-2"
                    style={{ 
                      background: `rgba(13, 7, 24, 0.6)`,
                      backdropFilter: 'blur(12px)',
                      borderBottom: `1.5px solid ${dc.border}28`
                    }}>
                    <div className="w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold text-white shrink-0"
                      style={{ background: step.done ? `linear-gradient(135deg,${ORB.mint},#0d9488)` : isGlobal ? 'rgba(140,242,255,0.35)' : AI.rankBg }}>
                      {isGlobal ? '①' : step.iteration}
                    </div>
                    <span className="text-[11px] font-mono font-bold text-on-surface/80 flex-1 truncate">
                      "{step.query}"
                    </span>
                    <span className="text-[9px] px-1.5 py-0.5 rounded-full font-bold border shrink-0"
                      style={{ background: dc.bg, color: dc.text, borderColor: dc.border }}>
                      {dc.label}
                    </span>
                    <span className="text-[10px] text-on-surface-variant/40 shrink-0">{step.count ?? step.items?.length ?? 0}건</span>
                  </div>

                  {/* 결과 미리보기 카드 (top 3) */}
                  {step.items?.length > 0 && (
                    <div className="px-3 py-2.5 flex gap-2 overflow-x-auto"
                      style={{ scrollbarWidth: 'thin', scrollbarColor: `${AI.border} transparent` }}>
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
                    <div className="px-3 py-2 flex items-start gap-2"
                      style={{ borderTop: '1px solid rgba(109,40,217,0.08)' }}>
                      <span className="material-symbols-outlined text-sm shrink-0 mt-0.5"
                        style={{ color: step.done ? ORB.mint : AI.accent, fontVariationSettings: '"FILL" 1' }}>
                        {step.done ? 'check_circle' : 'psychology'}
                      </span>
                      <p className="text-[11px] text-on-surface-variant/65 leading-relaxed">{step.thought}</p>
                    </div>
                  )}
                </div>
              </div>
            )
          })}

          {/* 스트리밍 대기 표시 */}
          {streaming && (
            <div className="flex items-center gap-2 px-3 py-2 rounded-lg"
              style={{ border: `1px dashed ${AI.border}`, background: 'rgba(109,40,217,0.05)' }}>
              <span className="material-symbols-outlined text-sm animate-spin" style={{ color: AI.accentLight }}>progress_activity</span>
              <span className="text-[11px] text-on-surface-variant/40 animate-pulse">AI가 결과를 분석하는 중...</span>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── 메인 컴포넌트 ─────────────────────────────────────────────
export default function MainAI() {
  const navigate  = useNavigate()
  const location  = useLocation()
  const { open }  = useSidebar()

  const [view,         setView]         = useState('home')
  const [query,        setQuery]        = useState('')
  const [inputValue,   setInputValue]   = useState('')
  const [selectedFile, setSelectedFile] = useState(null)
  const [fileDetail,   setFileDetail]   = useState(null)
  const [detailLoading,setDetailLoading]= useState(false)

  // AI 에이전트 상태
  const [streaming,      setStreaming]      = useState(false)
  const [results,        setResults]        = useState([])
  const [iterationData,  setIterationData]  = useState([])
  const [domainSelection,setDomainSelection]= useState(null)
  const [aiError,        setAiError]        = useState('')
  const [finalQuery,     setFinalQuery]     = useState('')
  const [hasLLM,         setHasLLM]         = useState(undefined)

  // ── AIMODE 시각화 4-step 상태 ─────────────────────────────
  const [aimodeSteps,       setAimodeSteps]       = useState([])
  const [aimodeQuery,       setAimodeQuery]       = useState('')
  const [aimodeContentKws,  setAimodeContentKws]  = useState([])
  const [aimodeDetailKws,   setAimodeDetailKws]   = useState([])
  const [aimodeSources,     setAimodeSources]     = useState([])
  const [aimodeSelected,    setAimodeSelected]    = useState(null)
  const [aimodeAnswer,      setAimodeAnswer]      = useState('')
  const [aimodeDone,        setAimodeDone]        = useState(false)
  const [useAimode,         setUseAimode]         = useState(true)
  const [topK,              setTopK]              = useState(20)
  const [maxIter,           setMaxIter]           = useState(5)
  const abortRef = useRef(null)
  const activeQueryRef = useRef('')

  const dispatchAiSidebarView = useCallback((viewName) => {
    try {
      window.dispatchEvent(
        new CustomEvent('ai-sidebar-view-changed', { detail: { view: viewName } }),
      )
    } catch {}
  }, [])

  // 애니메이션
  const [homeExiting,  setHomeExiting]  = useState(false)
  const [resultsReady, setResultsReady] = useState(false)
  const [detailVisible,setDetailVisible]= useState(false)

  const [aiHomeEntranceOn, setAiHomeEntranceOn] = useState(
    () => typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches
  )

  // 포털 전환
  const [searchTransitioning, setSearchTransitioning] = useState(false)
  const [ripplePos, setRipplePos] = useState({ x: '50%', y: '50%' })
  const [aiDockExpanded, setAiDockExpanded] = useState(false)
  const btnRef      = useRef(null)
  const formRef     = useRef(null)
  const inputRef    = useRef(null)
  const orbSinkRef  = useRef(null)
  const orbVoiceRef = useRef(0)

  // aiHomeEntranceOn 제어
  useEffect(() => {
    if (view !== 'home') { setAiHomeEntranceOn(false); return }
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) { setAiHomeEntranceOn(true); return }
    setAiHomeEntranceOn(false)
    const t = window.setTimeout(() => setAiHomeEntranceOn(true), 180)
    return () => clearTimeout(t)
  }, [view])

  // 뷰 변경 시 검색창 자동 포커스 (detail 제외 모든 뷰)
  useEffect(() => {
    if (view !== 'detail') {
      const t = setTimeout(() => inputRef.current?.focus(), 150)
      return () => clearTimeout(t)
    }
  }, [view])

  const ml       = open ? 'ml-64' : 'ml-0'
  const leftEdge = open ? 'left-64' : 'left-0'
  const sidebarPx= open ? 256 : 0

  // STT
  const doSearchRef = useRef(null)
  const { listening, interim, toggle: toggleMic, stop: stopMic } = useSpeechRecognition({
    onFinal: useCallback((text) => {
      setInputValue(text)
      setTimeout(() => doSearchRef.current?.(text), 80)
    }, []),
  })

  useMicLevelRef(view === 'home' && listening, orbVoiceRef, { startDelayMs: 420 })

  useEffect(() => {
    if (view !== 'home') stopMic()
  }, [view, stopMic])

  useEffect(() => {
    if (view !== 'results' && aiDockExpanded) setAiDockExpanded(false)
  }, [view, aiDockExpanded])

  // 로컬 전용: AIMODE 결과·상세 레이아웃 프리뷰 (백엔드 없이)
  useEffect(() => {
    if (!_LOCAL_AI_DUMMY_HOST || location.pathname !== '/ai') return
    const sp = new URLSearchParams(location.search || '')
    if (sp.get('devDummy') !== '1') return

    const userQ = '김라민 생년월일이 적힌 보고서를 찾아줘 (더미)'
    const extracted = '김라민 보고서'
    const rawItems = [
      {
        file_path: '/tmp/dev-dummy/report_kim.pdf',
        file_name: 'report_kim.pdf',
        file_type: 'doc',
        confidence: 0.91,
        similarity: 0.91,
        snippet: '김라민 — 생년월일: 1995-03-12 (더미 텍스트)',
        preview_url: null,
        segments: [],
        trichef_id: 'doc_dummy_1',
        trichef_domain: 'doc_page',
        dense: 0.82,
        lexical: 0.44,
      },
      {
        file_path: '/tmp/dev-dummy/meeting_photo.jpg',
        file_name: 'meeting_photo.jpg',
        file_type: 'image',
        confidence: 0.76,
        similarity: 0.76,
        snippet: '회의 장면 스냅 — 배경에 이름표 (더미)',
        preview_url: null,
        segments: [],
        trichef_id: 'img_dummy_1',
        trichef_domain: 'image',
        dense: 0.71,
        lexical: null,
      },
      {
        file_path: '/tmp/dev-dummy/interview_clip.mp4',
        file_name: 'interview_clip.mp4',
        file_type: 'video',
        confidence: 0.68,
        similarity: 0.68,
        snippet: '인터뷰 구간 — 자막에 김라민 언급 (더미)',
        preview_url: null,
        segments: [],
        trichef_id: 'mov_dummy_1',
        trichef_domain: 'movie',
        dense: 0.65,
        rerank_score: 0.2,
      },
    ]
    const mappedItems = rawItems.map(mapItem)

    activeQueryRef.current = userQ
    setStreaming(false)
    setAiError('')
    setQuery(userQ)
    setInputValue(userQ)
    setFinalQuery(extracted)
    setAimodeQuery(extracted)
    setAimodeContentKws(['생년월일', '보고서'])
    setAimodeDetailKws(['김라민', '생년월일'])
    setAimodeSources(mappedItems)
    setAimodeSelected(0)
    setAimodeAnswer(
      '[더미] 첫 번째 PDF 보고서에서 김라민의 생년월일을 확인했습니다. (실제 데이터 아님)',
    )
    setAimodeDone(true)
    setAimodeSteps([
      { step: 1, label: '✓ 검색어 추출', done: true, query: extracted },
      { step: 2, label: `✓ ${rawItems.length}건 발견`, done: true },
      { step: 3, label: '✓ #1 자동 선택', done: true, selected_idx: 0 },
      { step: 4, label: '✓ 답변', done: true },
    ])
    setResults(mappedItems)
    setResultsReady(false)
    setView('results')
    window.history.replaceState({ view: 'results' }, '')
    requestAnimationFrame(() => setResultsReady(true))
  }, [location.pathname, location.search])

  // 뒤로가기
  useEffect(() => {
    const handle = () => {
      setDetailVisible(false)
      if (view === 'detail')        setTimeout(() => setView('results'), 320)
      else if (view === 'results')  { setResultsReady(false); setView('home') }
    }
    window.addEventListener('popstate', handle)
    return () => window.removeEventListener('popstate', handle)
  }, [view])

  // 사이드바 검색 기록 클릭
  useEffect(() => {
    const q = location.state?.query
    if (q) { window.history.replaceState({}, ''); doSearchRef.current?.(q) }
  }, [location.state])

  // ── SSE 실행 (AIMODE 시각화 또는 기존 에이전트) ─────────────
  const runAISearch = useCallback(async (q) => {
    if (abortRef.current) abortRef.current.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setStreaming(true)
    setResults([])
    setIterationData([])
    setDomainSelection(null)
    setAiError('')
    setFinalQuery(q)
    activeQueryRef.current = q
    setHasLLM(undefined)

    // AIMODE 시각화 상태 초기화
    setAimodeSteps([])
    setAimodeQuery('')
    setAimodeContentKws([])
    setAimodeDetailKws([])
    setAimodeSources([])
    setAimodeSelected(null)
    setAimodeAnswer('')
    setAimodeDone(false)

    const endpoint = useAimode
      ? `${API_BASE}/api/aimode/chat`
      : `${API_BASE}/api/ai/search`
    // LangGraph thread_id — localStorage 영속 (24h TTL)
    let tid = null
    try {
      const raw = localStorage.getItem('aimode_thread_id')
      if (raw) {
        const obj = JSON.parse(raw)
        if (obj?.id && obj?.expires > Date.now()) tid = obj.id
      }
    } catch {}
    if (!tid) {
      tid = `t_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
      try {
        localStorage.setItem('aimode_thread_id', JSON.stringify({
          id: tid, expires: Date.now() + 24 * 3600 * 1000,
        }))
      } catch {}
    }
    window.__aimodeThreadId = tid
    const body = useAimode
      ? { query: q, topk: topK, thread_id: tid }
      : { query: q, topk: topK, max_iterations: maxIter }

    try {
      const res = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        signal: controller.signal,
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)

      const reader  = res.body.getReader()
      const decoder = new TextDecoder()
      let   buffer  = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop()

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          try {
            const ev = JSON.parse(line.slice(6))
            handleSSEEvent(ev)
          } catch {}
        }
      }
    } catch (e) {
      if (e.name !== 'AbortError') setAiError(e.message)
    } finally {
      setStreaming(false)
    }
  }, [topK, maxIter, useAimode])

  const mapItem = (item) => {
    const dom =
      item.domain ??
      item.trichef_domain ??
      (item.file_type === 'doc'
        ? 'doc_page'
        : item.file_type === 'video'
          ? 'movie'
          : item.file_type === 'audio'
            ? 'music'
            : item.file_type === 'image'
              ? 'image'
              : null)
    const isDocPage = dom === 'doc_page'
    const pathKey =
      item.file_path || item.source_path || item.id || item.trichef_id || ''
    const idKey = item.trichef_id ?? item.id ?? pathKey
    let ft = item.file_type
    if (!ft && dom === 'image') ft = 'image'
    else if (!ft && isDocPage) ft = 'doc'
    else if (!ft && dom === 'movie') ft = 'video'
    else if (!ft && dom === 'music') ft = 'audio'
    else if (!ft) ft = 'doc'
    const conf =
      item.confidence ?? item.similarity ?? 0
    return {
      file_path:      pathKey,
      trichef_id:     idKey,
      file_name:      item.file_name || String(pathKey).split(/[/\\]/).pop() || '?',
      page_num:       item.page_num ?? null,
      file_type:      ft,
      confidence:     conf,
      similarity:     item.similarity ?? conf,
      dense:          item.dense ?? 0,
      lexical:        item.lexical ?? null,
      asf:            item.asf ?? null,
      snippet:        item.snippet ?? '',
      preview_url:    item.preview_url ?? null,
      segments:       item.segments ?? [],
      low_confidence: item.low_confidence ?? false,
      trichef_domain: dom ?? undefined,
      rerank_score:   item.rerank_score ?? item.rerank ?? null,
      z_score:        item.z_score ?? null,
    }
  }

  const handleSSEEvent = (ev) => {
    switch (ev.type) {
      // ── AIMODE 시각화 이벤트 (/api/aimode/chat) ─────────────
      case 'step':
        setAimodeSteps(prev => {
          const idx = prev.findIndex(s => s.step === ev.step)
          const entry = {
            step: ev.step,
            label: ev.label,
            done: ev.done === true,
            query: ev.query,
            selected_idx: ev.selected_idx,
          }
          if (idx >= 0) {
            const next = [...prev]
            next[idx] = { ...next[idx], ...entry }
            return next
          }
          return [...prev, entry]
        })
        if (ev.step === 1 && ev.done) {
          if (ev.query) setAimodeQuery(ev.query)
          if (ev.content_keywords) setAimodeContentKws(ev.content_keywords)
          if (ev.detail_keywords)  setAimodeDetailKws(ev.detail_keywords)
        }
        if (ev.step === 3 && typeof ev.selected_idx === 'number') {
          setAimodeSelected(ev.selected_idx)
          // Step 3 완료 — LangGraph 가 선택한 카드 자동 클릭 (1.4s 딜레이 후)
          setAimodeSources(prev => {
            const file = prev[ev.selected_idx]
            if (file) {
              setTimeout(() => handleSelectFile(file), 1400)
            }
            return prev
          })
        }
        break

      case 'sources': {
        // AIMODE 검색 결과 — 작은 단계 패널용 + MainSearch 와 동일한 큰 카드 그리드용
        const items = ev.items || []
        const mapped = items.map(mapItem)
        setAimodeSources(mapped)
        // ★ 동일 데이터를 큰 카드 그리드로도 렌더 (MainSearch 와 동일한 UX)
        setResults(mapped)
        const histQ =
          activeQueryRef.current ||
          ev.query ||
          finalQuery ||
          ''
        // 검색 기록 저장
        fetch(`${API_BASE}/api/history`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            query: histQ,
            method: 'aimode',
            result_count: mapped.length,
          }),
        }).then(() => {
          window.dispatchEvent(new Event('history-updated'))
        }).catch(() => {})
        break
      }

      case 'token':
        setAimodeAnswer(prev => prev + (ev.text || ''))
        break

      case 'done':
        setAimodeDone(true)
        if (ev.answer) setAimodeAnswer(ev.answer)
        if (typeof ev.selected_idx === 'number') setAimodeSelected(ev.selected_idx)
        break

      case 'error':
        setAiError(ev.message || '오류')
        break

      // ── 기존 ai_search 이벤트 (fallback) ─────────────────────
      case 'info':
        setHasLLM(ev.has_llm)
        break

      case 'iteration_results':
        // 각 단계 결과 카드 저장/업데이트
        setIterationData(prev => {
          const idx = prev.findIndex(it => it.iteration === ev.iteration)
          const entry = {
            iteration: ev.iteration,
            query:     ev.query,
            domain:    ev.domain,
            items:     ev.items ?? [],
            count:     ev.items?.length ?? 0,
            thought:   '',
            done:      false,
          }
          if (idx >= 0) {
            const next = [...prev]
            next[idx] = { ...next[idx], ...entry }
            return next
          }
          return [...prev, entry]
        })
        break

      case 'domain_selected':
        setDomainSelection({ domain: ev.domain, reason: ev.reason })
        break

      case 'thought':
        // 마지막 focused 단계(iteration>0)의 thought 업데이트
        setIterationData(prev => {
          if (!prev.length) return prev
          const updated = [...prev]
          // 뒤에서부터 iteration>0인 항목 찾기
          for (let i = updated.length - 1; i >= 0; i--) {
            if (updated[i].iteration > 0) {
              updated[i] = { ...updated[i], thought: ev.text, done: ev.done }
              return updated
            }
          }
          return prev
        })
        break

      case 'results': {
        const mapped = (ev.items ?? []).map(mapItem)
        setResults(mapped)
        setFinalQuery(ev.final_query || ev.query)
        // 최종 history로 iterationData thought/done 동기화
        if (ev.history?.length) {
          setIterationData(prev => {
            const updated = [...prev]
            ev.history.forEach((h, hi) => {
              const idx = updated.findIndex(it => it.iteration === hi + 1)
              if (idx >= 0) {
                updated[idx] = { ...updated[idx], thought: h.thought, done: h.done, count: h.count }
              }
            })
            return updated
          })
        }
        break
      }
      // case 'error' 는 위쪽에 이미 정의 (AIMODE/legacy 공용)
    }
  }

  const doSearch = (q) => {
    if (!q.trim() || searchTransitioning) return
    setQuery(q)
    setInputValue(q)

    if (view === 'home') {
      setHomeExiting(true)
      setTimeout(() => {
        setHomeExiting(false)
        setResultsReady(false)
        setView('results')
        window.history.pushState({ view: 'results' }, '')
        dispatchAiSidebarView('results')
        requestAnimationFrame(() => setResultsReady(true))
        runAISearch(q)
      }, 420)
    } else {
      setView('results')
      window.history.pushState({ view: 'results' }, '')
      dispatchAiSidebarView('results')
      runAISearch(q)
    }
  }

  doSearchRef.current = doSearch;

  useEffect(() => { doSearchRef.current = doSearch })

  const handleSearch  = (e) => { e?.preventDefault(); doSearch(inputValue) }

  const handleSelectFile = (file) => {
    setSelectedFile(file)
    setRightMode("detail")
    setSelectedScanChunks(latestTurn?.scanChunks ?? {})
    setFileDetail(null)
    setDetailVisible(false)
    setView('detail')
    window.history.pushState({ view: 'detail' }, '')
    dispatchAiSidebarView('detail')
    requestAnimationFrame(() => requestAnimationFrame(() => setDetailVisible(true)))
    const isAV = file.file_type === 'video' || file.file_type === 'audio'
    if (!isAV) {
      setDetailLoading(true)
      fetch(`${API_BASE}/api/files/detail?path=${encodeURIComponent(file.file_path)}`)
        .then(r => r.json()).then(d => { setFileDetail(d); setDetailLoading(false) })
        .catch(() => setDetailLoading(false))
    }
  }

  const handleBackToResults = () => {
    setRightMode("cards")
    setDetailVisible(false)
    window.history.pushState({ view: 'results' }, '')
    dispatchAiSidebarView('results')
    setTimeout(() => setView('results'), 320)
  }

  // 새 대화 — 서버 history + localStorage thread_id 모두 비움
  const handleNewConversation = useCallback(async () => {
    if (abortRef.current) abortRef.current.abort()
    const tid = window.__aimodeThreadId
    if (tid) {
      try { await fetch(`${API_BASE}/api/aimode/chat/${encodeURIComponent(tid)}`, { method: 'DELETE' }) } catch {}
    }
    try { localStorage.removeItem('aimode_thread_id') } catch {}
    window.__aimodeThreadId = null
    setAimodeSteps([])
    setAimodeQuery('')
    setAimodeContentKws([])
    setAimodeDetailKws([])
    setAimodeSources([])
    setAimodeSelected(null)
    setAimodeAnswer('')
    setAimodeDone(false)
    setResults([])
    setIterationData([])
    setSelectedFile(null)
    setFileDetail(null)
    setAiError('')
    setView('home')
    setInputValue('')
  }, [])

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

  // 우측 패널: 최신 턴의 candidates
  const rightCandidates = latestTurn?.candidates ?? [];
  const rightScanStates = latestTurn?.scanStates ?? {};
  const shouldShowCenterNoInfoAlert =
    latestTurn?.done &&
    !latestTurn?.streaming &&
    isNoInfoCenterAlert(latestTurn?.answer);

  // ── Render ──────────────────────────────────────────────────────
  return (
    <div className={view === 'home' ? 'overflow-hidden h-screen relative' : 'min-h-screen relative text-on-surface'}
      style={{
        display: "flex",
        height: "100vh",
        background: AI.bg,
        backgroundImage:
          "radial-gradient(120% 90% at 0% 100%, rgba(109,40,217,0.1) 0%, transparent 60%), radial-gradient(100% 80% at 100% 0%, rgba(59,130,246,0.08) 0%, transparent 58%)",
        overflow: "hidden",
      }}
    >
      {searchTransitioning && (
        <div className="fixed inset-0 z-[9999] pointer-events-none overflow-hidden">
          <div className="portal-overlay absolute rounded-full"
            style={{ width: '80px', height: '80px', left: ripplePos.x, top: ripplePos.y,
              transform: 'translate(-50%, -50%)',
              background: 'radial-gradient(circle, #1c253e 0%, #0c1326 60%, #070d1f 100%)',
              boxShadow: '0 0 30px 10px rgba(133,173,255,0.15)' }} />
          {[0, 200].map((delay, i) => (
            <div key={i} className="portal-ring absolute rounded-full border border-[#8cf2ff]/28"
              style={{ width: '160px', height: '160px', left: ripplePos.x, top: ripplePos.y,
                transform: 'translate(-50%, -50%)', animationDelay: `${delay}ms` }} />
          ))}
          <div className="portal-text absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 flex flex-col items-center gap-2">
            <span className="material-symbols-outlined text-[#a5aac2] text-4xl" style={{ fontVariationSettings: '"FILL" 1' }}>database</span>
            <span className="font-manrope uppercase tracking-[0.25em] text-base text-[#a5aac2]">검색 모드</span>
          </div>
        </div>
      )}

      {/* 사이드바 */}
      <SearchSidebar entranceOn={view === 'home' ? aiHomeEntranceOn : undefined} />

      {/* ════ HOME VIEW ════ */}
      {view === 'home' && (
        <>
          <main className={`${ml} relative flex h-full min-h-0 flex-col overflow-x-hidden overflow-y-auto bg-transparent transition-[margin] duration-300 pt-8`}>
            <div
              className="ai-home-orbit-bg pointer-events-none absolute inset-0 z-0 min-h-0"
              style={{ '--ai-orbit-assemble': `${AI_ORB_ASSEMBLE_SECONDS}s` }}
              aria-hidden
            />
            {/* Orb */}
            <div ref={orbSinkRef} className="absolute inset-0 z-0 min-h-0" aria-hidden>
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

            <div className={`pointer-events-none relative z-10 flex h-full min-h-0 w-full flex-col ${aiHomeEntranceOn ? 'main-search-entrance-on' : 'main-search-entrance-off'}`}>
              <div className="relative z-10 flex min-h-0 flex-1 flex-col items-center justify-center overflow-y-auto px-6 py-8 md:px-8">
                <div className="relative flex w-full max-w-lg flex-col items-center justify-center">
                  <div className="relative z-10 flex w-full flex-col items-center gap-9 text-center md:gap-10">
                    <div className={`mse-hero-down pointer-events-auto max-w-lg shrink-0 transition-all duration-300 ${homeExiting ? 'opacity-0 -translate-y-6' : ''}`}>
                      <h2 className="font-headline inline-flex flex-wrap items-baseline justify-center gap-0 text-4xl font-semibold tracking-tight md:text-5xl lg:text-6xl">
                        <span className="font-headline inline-block bg-gradient-to-r from-[#5e5a52] from-[6%] via-[#b8b0a2] to-[#d4cec2] bg-clip-text text-transparent">B</span>
                        <span className="font-headline text-[#cbc4b6] drop-shadow-[0_1px_5px_rgba(18,16,14,0.18)]">eyond Smarte</span>
                        <span className="font-headline inline-block bg-gradient-to-r from-[#d4cec2] via-[#9e978a] to-[#45423c] to-[90%] bg-clip-text text-transparent">r</span>
                      </h2>
                    </div>
                    <form
                      onSubmit={handleSearch}
                      className="mse-search-up group pointer-events-auto relative z-10 w-full max-w-[min(90vw,22rem)] shrink-0 md:max-w-[24rem]"
                      style={homeExiting ? { visibility: 'hidden' } : {}}
                    >
                      <div className="pointer-events-none absolute -inset-[2px] rounded-full bg-gradient-to-r from-fuchsia-500/0 via-violet-400/25 to-fuchsia-500/0 opacity-0 blur-md transition-opacity duration-500 group-focus-within:opacity-100" />
                      <div className="relative flex items-center gap-2 rounded-full border border-violet-200/[0.14] bg-gradient-to-b from-violet-100/[0.09] to-violet-950/[0.28] px-1.5 py-1.5 shadow-[inset_0_1px_0_rgba(255,255,255,0.16),inset_0_-1px_0_rgba(0,0,0,0.22),0_10px_44px_rgba(32,12,58,0.5)] backdrop-blur-2xl transition-all duration-300 group-focus-within:border-violet-200/25 group-focus-within:from-violet-100/[0.12] group-focus-within:to-violet-950/[0.34]">
                        <button
                          type="button"
                          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-violet-900 to-purple-600 text-violet-50 shadow-[0_0_20px_rgba(124,58,237,0.32),inset_0_1px_0_rgba(255,255,255,0.18)] transition-transform hover:from-violet-800 hover:to-purple-500 active:scale-90"
                        >
                          <span className="material-symbols-outlined text-[20px] font-bold">add</span>
                        </button>
                        <input
                          type="text"
                          value={inputValue}
                          onChange={(e) => setInputValue(e.target.value)}
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
                  className="group flex items-center gap-3 rounded-full border border-white/20 px-8 py-3 text-sm font-bold uppercase tracking-widest text-neutral-300 transition-all duration-300 hover:border-white/40 hover:text-white hover:shadow-lg disabled:pointer-events-none"
                  style={{
                    background: 'rgba(255, 255, 255, 0.1)',
                    backdropFilter: 'blur(10px)',
                    boxShadow: '0 8px 32px rgba(139, 92, 246, 0.1), inset 0 1px 1px rgba(255, 255, 255, 0.2)',
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.background = 'rgba(255, 255, 255, 0.15)';
                    e.currentTarget.style.boxShadow =
                      "0 8px 32px rgba(139, 92, 246, 0.3), inset 0 1px 1px rgba(255, 255, 255, 0.3), 0 0 30px rgba(139, 92, 246, 0.25)";
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.background = 'rgba(255, 255, 255, 0.1)';
                    e.currentTarget.style.boxShadow = '0 8px 32px rgba(139, 92, 246, 0.1), inset 0 1px 1px rgba(255, 255, 255, 0.2)';
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

        {/* ══ CHAT ══ */}
        {view === "chat" && (
          <div
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
                background: "rgba(9,6,22,0.74)",
                backdropFilter: "blur(10px) saturate(1.06)",
                borderBottom: "1px solid rgba(167,139,250,0.16)",
                boxShadow: "inset 0 1px 0 rgba(255,255,255,0.08)",
                position: "relative",
                zIndex: 10,
              }}
            >
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
                    color: "#10b981",
                    background: "rgba(16,185,129,0.1)",
                    border: "1px solid rgba(16,185,129,0.22)",
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
                    color: "#06b6d4",
                    background: "rgba(6,182,212,0.1)",
                    border: "1px solid rgba(6,182,212,0.22)",
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
                    color: "#eab308",
                    background: "rgba(234,179,8,0.1)",
                    border: "1px solid rgba(234,179,8,0.25)",
                    padding: "3px 10px",
                    borderRadius: 999,
                    flexShrink: 0,
                  }}
                >
                  📝 QA Gen
                </div>
              )}

              {isAnyStreaming && (
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 5,
                    fontSize: 10,
                    fontWeight: 700,
                    color: AI.accentLight,
                    background: "rgba(139,92,246,0.1)",
                    border: `1px solid ${AI.border}`,
                    padding: "3px 10px",
                    borderRadius: 999,
                    flexShrink: 0,
                  }}
                >
                  <span
                    className="inline-flex rounded-md border border-violet-400/25 bg-violet-500/10 px-2 py-0.5 text-[10px] font-bold uppercase tracking-widest mt-3"
                    style={{ color: AI.accentLight }}
                  >
                    AI 쿼리
                  </span>
                  처리 중
                </div>
              )}
              {!isAnyStreaming && latestTurn?.done && (
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 5,
                    fontSize: 10,
                    fontWeight: 700,
                    color: "#10b981",
                    background: "rgba(16,185,129,0.1)",
                    border: "1px solid rgba(16,185,129,0.2)",
                    padding: "3px 10px",
                    borderRadius: 999,
                    flexShrink: 0,
                  }}
                >
                  <span
                    className="material-symbols-outlined"
                    style={{ fontSize: 11 }}
                  >
                    check_circle
                  </span>
                  완료
                </div>
              )}

              <div style={{ flex: 1 }} />

              <button
                onClick={handleNewConversation}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 5,
                  padding: "5px 12px",
                  background: AI.card,
                  border: `1px solid ${AI.border}`,
                  borderRadius: 999,
                  fontSize: 11,
                  fontWeight: 700,
                  color: "#64748b",
                  cursor: "pointer",
                  flexShrink: 0,
                  transition: "color 0.2s, border-color 0.2s",
                }}
              >
                <span
                  className="material-symbols-outlined"
                  style={{ fontSize: 14 }}
                >
                  restart_alt
                </span>
                새 대화
              </button>
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
                        ref={inputRef}
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
                        title={securityMode ? "보안 모드 켜짐: LLM 응답이 SecurityCritic 통과 후 송출됨" : "보안 모드 꺼짐"}
                        style={{
                          background: "none",
                          border: "none",
                          cursor: "pointer",
                          padding: 0,
                          flexShrink: 0,
                          color: securityMode ? "#f87171" : "rgba(139,92,246,0.3)",
                          transition: "color 0.2s",
                        }}
                      >
                        <span
                          className="material-symbols-outlined"
                          style={{
                            fontSize: 16,
                            fontVariationSettings: securityMode ? '"FILL" 1' : '"FILL" 0',
                            filter: securityMode ? "drop-shadow(0 0 6px rgba(248,113,113,0.6))" : "none",
                          }}
                        >
                          shield
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
                          gap: 10,
                          padding: 40,
                        }}
                      >
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
                      </div>
                    ) : (
                      <>
                        <p
                          style={{
                            fontSize: 10,
                            fontWeight: 700,
                            color: "#a78bfa",
                            letterSpacing: "0.12em",
                            textTransform: "uppercase",
                            marginBottom: 9,
                          }}
                        >
                          후보 파일 {rightCandidates.length}개
                        </p>
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

                    {streaming && results.length === 0 && (
                      <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] px-4 py-3 text-center text-xs text-on-surface-variant">
                        AIMODE 파이프라인이 실행 중입니다. 잠시만 기다려 주세요.
                      </div>
                    )}

                    {useAimode && aimodeAnswer && !streaming && (
                      <div className="relative overflow-hidden rounded-xl border border-white/[0.08] bg-white/[0.03]">
                        <div className="pointer-events-none absolute inset-0 bg-gradient-to-br from-fuchsia-500/[0.07] via-transparent to-violet-500/[0.08]" />
                        <div className="relative flex items-center gap-3 border-b border-white/[0.08] px-4 py-2.5">
                          <span className="material-symbols-outlined text-lg" style={{ color: AI.accentLight }}>
                            stylus
                          </span>
                          <span className="text-[11px] font-bold uppercase tracking-widest" style={{ color: AI.accentLight }}>
                            초안 답변
                          </span>
                          {aimodeDone ? (
                            <span className="ml-auto flex items-center gap-1 text-[11px] text-[#7af5d9]">
                              <span className="material-symbols-outlined text-base">check_circle</span> 완료
                            </span>
                          ) : (
                            <span className="ml-auto flex items-center gap-1 text-[11px]" style={{ color: AI.accentLight }}>
                              <span className="material-symbols-outlined animate-spin text-base">progress_activity</span>
                              작성 중
                            </span>
                          )}
                        </div>
                        <div className="relative px-4 py-3 text-xs leading-relaxed text-on-surface/95 whitespace-pre-wrap">
                          {stripMarkdown(aimodeAnswer)}
                          {!aimodeDone && (
                            <span className="inline-block w-2 h-4 bg-violet-400 ml-1 animate-pulse align-middle" />
                          )}
                        </div>
                        {selectedFile &&
                          ["video", "audio", "movie", "music"].includes(
                            selectedFile.file_type,
                          ) && (
                            <div style={{ marginBottom: 13 }}>
                              <AVDetailContent result={selectedFile} />
                            </div>
                          )}
                      </div>
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
                              {((selectedFile.confidence ?? 0) * 100).toFixed(
                                0,
                              )}
                              %
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
                                }}
                              />
                            </div>
                          )}

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
                                  borderBottom:
                                    "1px solid rgba(16,185,129,0.15)",
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
    </div>
  );
}
