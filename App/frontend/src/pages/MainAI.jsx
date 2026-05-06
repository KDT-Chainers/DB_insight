import { useState, useRef, useEffect, useCallback } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import SearchSidebar from "../components/SearchSidebar";
import AnimatedOrb from "../components/AnimatedOrb";
import { useSidebar } from "../context/SidebarContext";
import { useSpeechRecognition } from "../hooks/useSpeechRecognition";
import { useMicLevelRef } from "../hooks/useMicLevelRef";
import { API_BASE } from "../api";

const AI_ORB_ASSEMBLE_SECONDS = 8;

const AI = {
  accent: "#8b5cf6",
  accentLight: "#a78bfa",
  accentDark: "#6d28d9",
  bg: "#080514",
  leftBg: "#0b0718",
  rightBg: "#070310",
  card: "#120d22",
  border: "rgba(139,92,246,0.18)",
};

const TYPE_META = {
  doc: { icon: "description", color: "#85adff", label: "문서" },
  video: { icon: "movie", color: "#ac8aff", label: "동영상" },
  image: { icon: "image", color: "#34d399", label: "이미지" },
  audio: { icon: "volume_up", color: "#fbbf24", label: "음성" },
  movie: { icon: "movie", color: "#ac8aff", label: "동영상" },
  music: { icon: "volume_up", color: "#fbbf24", label: "음성" },
};
const getTypeMeta = (t) =>
  TYPE_META[t] ?? {
    icon: "insert_drive_file",
    color: "#94a3b8",
    label: t ?? "파일",
  };

function fmtTime(sec) {
  if (!sec && sec !== 0) return "0:00";
  const s = Math.floor(sec);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}
function avStreamUrl(r) {
  const domain =
    r.trichef_domain ?? (r.file_type === "video" ? "movie" : "music");
  return `${API_BASE}/api/admin/file?domain=${domain}&id=${encodeURIComponent(r.file_path)}`;
}
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
});

// ── AI 아바타 ─────────────────────────────────────────────────────
// isLatest=true 이면 실제 AnimatedOrb, 아니면 CSS 버전
function AIAvatar({ isLatest, size = 30 }) {
  if (isLatest) {
    return (
      <div
        style={{
          width: size,
          height: size,
          borderRadius: "50%",
          overflow: "hidden",
          flexShrink: 0,
          marginTop: 2,
        }}
      >
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
        marginTop: 2,
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
  } = turn;
  const isChatMode = route === "chat";
  const isQaMode = route === "qa_gen";

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
            background: "linear-gradient(135deg,#3b1d7a,#4c1d95,#5b21b6)",
            borderRadius: "18px 18px 4px 18px",
            fontSize: 15,
            color: "#ede9fe",
            lineHeight: 1.6,
            boxShadow:
              "0 4px 20px rgba(109,40,217,0.3), inset 0 1px 0 rgba(255,255,255,0.08)",
            letterSpacing: "-0.01em",
          }}
        >
          {query}
        </div>
      </div>

      {/* AI 응답 블록 */}
      {(intentMessage || candidates.length > 0 || answer || error) && (
        <div style={{ display: "flex", gap: 10 }}>
          {/* 아바타 (실제 오브 또는 CSS 오브) */}
          <AIAvatar isLatest={isLatest} size={30} />

          <div style={{ flex: 1, minWidth: 0 }}>
            {/* route 뱃지 */}
            {route === "rag" && (
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
                  background: "rgba(139,92,246,0.12)",
                  color: AI.accentLight,
                  border: `1px solid rgba(139,92,246,0.22)`,
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
                RAG · 파일 검색
              </div>
            )}
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
                  padding: "11px 15px",
                  marginBottom: 8,
                  background: "rgba(109,40,217,0.08)",
                  border: "1px solid rgba(139,92,246,0.18)",
                  borderRadius: "4px 16px 16px 16px",
                  fontSize: 14.5,
                  color: "#c4b5fd",
                  lineHeight: 1.65,
                  fontWeight: 500,
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

            {/* 답변 (qa_gen이 아닌 경우만 표시) */}
            {answer && !isQaMode && (
              <div
                style={{
                  padding: "13px 16px",
                  marginBottom: 6,
                  background: isChatMode
                    ? "rgba(6,3,15,0.5)"
                    : "rgba(109,40,217,0.07)",
                  border: `1px solid ${isChatMode ? "rgba(139,92,246,0.1)" : AI.border}`,
                  borderRadius: 10,
                  fontSize: 15,
                  color: "#e2e8f0",
                  lineHeight: 1.9,
                  whiteSpace: "pre-wrap",
                  letterSpacing: "-0.01em",
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

// ── FileCard (right panel) ─────────────────────────────────────────
function FileCard({ source, index, scanState, selected, onClick }) {
  const [imgError, setImgError] = useState(false);
  const fname = source.file_name || "?",
    ftype = source.file_type || "";
  const conf = source.confidence ?? 0,
    meta = getTypeMeta(ftype);
  const hasThumb = (ftype === "image" || ftype === "doc") && source.preview_url;
  const isFound = scanState === "found",
    isNF = scanState === "not_found",
    isScan = scanState === "scanning";
  const borderColor = selected
    ? AI.accent
    : isFound
      ? "#10b981"
      : isScan
        ? AI.accent
        : isNF
          ? "rgba(71,85,105,0.3)"
          : AI.border;
  return (
    <button
      onClick={() => onClick?.(source)}
      style={{
        textAlign: "left",
        width: "100%",
        padding: 0,
        background: selected ? "rgba(139,92,246,0.1)" : AI.card,
        border: `1px solid ${borderColor}`,
        borderRadius: 12,
        overflow: "hidden",
        cursor: "pointer",
        opacity: isNF ? 0.4 : 1,
        filter: isNF ? "grayscale(60%)" : "none",
        boxShadow: isFound
          ? "0 0 16px rgba(16,185,129,0.2)"
          : selected
            ? "0 0 16px rgba(139,92,246,0.25)"
            : "none",
        transition: "all 0.3s",
      }}
    >
      <div
        style={{
          height: 88,
          background: "#06030f",
          position: "relative",
          overflow: "hidden",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        {hasThumb && !imgError ? (
          <img
            src={`${API_BASE}${source.preview_url}`}
            alt={fname}
            style={{
              maxWidth: "100%",
              maxHeight: "100%",
              objectFit: "contain",
            }}
            onError={() => setImgError(true)}
          />
        ) : (
          <span
            className="material-symbols-outlined"
            style={{
              fontSize: 30,
              color: meta.color,
              fontVariationSettings: '"FILL" 0, "wght" 200',
            }}
          >
            {meta.icon}
          </span>
        )}
        {isScan && (
          <div
            style={{
              position: "absolute",
              inset: 0,
              background: "rgba(109,40,217,0.08)",
              overflow: "hidden",
            }}
          >
            <div className="ai-scan-line" />
          </div>
        )}
        <div
          style={{
            position: "absolute",
            top: 5,
            left: 5,
            background: "linear-gradient(135deg,#6d28d9,#7c3aed)",
            color: "#fff",
            fontSize: 9,
            fontWeight: 700,
            padding: "1px 6px",
            borderRadius: 999,
          }}
        >
          #{index + 1}
        </div>
        {scanState !== "idle" && (
          <div
            style={{
              position: "absolute",
              top: 5,
              right: 5,
              background: isFound
                ? "rgba(16,185,129,0.9)"
                : isScan
                  ? "rgba(109,40,217,0.9)"
                  : "rgba(71,85,105,0.85)",
              color: "#fff",
              fontSize: 9,
              fontWeight: 700,
              padding: "1px 6px",
              borderRadius: 999,
              display: "flex",
              alignItems: "center",
              gap: 2,
            }}
          >
            {isScan && (
              <span
                className="material-symbols-outlined ai-spin"
                style={{ fontSize: 9 }}
              >
                progress_activity
              </span>
            )}
            {isFound && (
              <span
                className="material-symbols-outlined"
                style={{ fontSize: 9 }}
              >
                check_circle
              </span>
            )}
            {isNF && (
              <span
                className="material-symbols-outlined"
                style={{ fontSize: 9 }}
              >
                cancel
              </span>
            )}
            {isScan ? "스캔" : isFound ? "발견" : "없음"}
          </div>
        )}
      </div>
      <div style={{ padding: "8px 10px" }}>
        <div
          style={{
            fontSize: 11,
            fontWeight: 600,
            color: "#e2e8f0",
            lineHeight: 1.3,
            marginBottom: 5,
            display: "-webkit-box",
            WebkitLineClamp: 2,
            WebkitBoxOrient: "vertical",
            overflow: "hidden",
          }}
        >
          {fname}
        </div>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
          }}
        >
          <span style={{ fontSize: 9, color: meta.color, fontWeight: 600 }}>
            {meta.label}
          </span>
          <span
            style={{
              fontSize: 9,
              fontFamily: "monospace",
              fontWeight: 700,
              color: AI.accentLight,
            }}
          >
            {(conf * 100).toFixed(0)}%
          </span>
        </div>
      </div>
    </button>
  );
}

// ── AVDetailContent ────────────────────────────────────────────────
function AVDetailContent({ result }) {
  const isVideo = result.file_type === "video" || result.file_type === "movie";
  const playerRef = useRef(null),
    streamUrl = avStreamUrl(result),
    segments = result.segments ?? [];
  const seekTo = (t) => {
    const p = playerRef.current;
    if (!p) return;
    p.currentTime = t;
    p.play().catch(() => {});
  };
  return (
    <div>
      <div
        style={{
          borderRadius: 10,
          overflow: "hidden",
          background: "#000",
          marginBottom: 12,
        }}
      >
        {isVideo ? (
          <video
            ref={playerRef}
            src={streamUrl}
            controls
            preload="metadata"
            style={{ width: "100%", maxHeight: 200, display: "block" }}
          />
        ) : (
          <div
            style={{
              padding: 16,
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              gap: 8,
            }}
          >
            <span
              className="material-symbols-outlined"
              style={{
                fontSize: 30,
                color: "#fbbf24",
                fontVariationSettings: '"FILL" 1',
              }}
            >
              volume_up
            </span>
            <audio
              ref={playerRef}
              src={streamUrl}
              controls
              preload="metadata"
              style={{ width: "100%" }}
            />
          </div>
        )}
      </div>
      {segments.length > 0 && (
        <div>
          <p
            style={{
              fontSize: 11,
              fontWeight: 700,
              color: AI.accentLight,
              marginBottom: 8,
              textTransform: "uppercase",
              letterSpacing: 1,
            }}
          >
            매칭 구간 ({segments.length}개)
          </p>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {segments.slice(0, 5).map((seg, i) => (
              <button
                key={i}
                onClick={() => seekTo(seg.start ?? 0)}
                style={{
                  background: AI.card,
                  border: `1px solid ${AI.border}`,
                  borderRadius: 8,
                  padding: "8px 10px",
                  textAlign: "left",
                  cursor: "pointer",
                  width: "100%",
                }}
              >
                <div
                  style={{
                    display: "flex",
                    gap: 6,
                    alignItems: "center",
                    marginBottom: 3,
                  }}
                >
                  <span
                    className="material-symbols-outlined"
                    style={{ fontSize: 13, color: AI.accent }}
                  >
                    play_circle
                  </span>
                  <span
                    style={{
                      fontSize: 13,
                      fontFamily: "monospace",
                      fontWeight: 700,
                      color: AI.accentLight,
                    }}
                  >
                    {fmtTime(seg.start ?? 0)} → {fmtTime(seg.end ?? 0)}
                  </span>
                </div>
                {(seg.text || seg.caption) && (
                  <p
                    style={{
                      fontSize: 11,
                      color: "#94a3b8",
                      lineHeight: 1.4,
                      display: "-webkit-box",
                      WebkitLineClamp: 2,
                      WebkitBoxOrient: "vertical",
                      overflow: "hidden",
                    }}
                  >
                    {seg.text || seg.caption}
                  </p>
                )}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════
export default function MainAI() {
  const navigate = useNavigate();
  const location = useLocation();
  const { open } = useSidebar();

  const [view, setView] = useState("home");
  const [inputValue, setInputValue] = useState("");

  // 대화 기록 (턴 배열)
  const [turns, setTurns] = useState([]);
  const activeTurnId = useRef(null);

  // right panel
  const [rightMode, setRightMode] = useState("cards");
  const [selectedFile, setSelectedFile] = useState(null);
  const [fileDetail, setFileDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [selectedScanChunks, setSelectedScanChunks] = useState({});

  const [topK, setTopK] = useState(5);
  const abortRef = useRef(null);

  // home animation
  const [homeExiting, setHomeExiting] = useState(false);
  const [aiHomeEntranceOn, setAiHomeEntranceOn] = useState(false);
  const [searchTransitioning, setSearchTransitioning] = useState(false);
  const [ripplePos, setRipplePos] = useState({ x: "50%", y: "50%" });

  const btnRef = useRef(null);
  const inputRef = useRef(null);
  const orbSinkRef = useRef(null);
  const orbVoiceRef = useRef(0);
  const conversationEndRef = useRef(null);
  const doSearchRef = useRef(null);

  const ml = open ? "ml-64" : "ml-0";

  // 최신 턴
  const latestTurn = turns[turns.length - 1] ?? null;
  const isAnyStreaming = latestTurn?.streaming ?? false;

  // 턴 업데이트 헬퍼
  const patchTurn = useCallback((id, patch) => {
    setTurns((prev) => prev.map((t) => (t.id === id ? { ...t, ...patch } : t)));
  }, []);
  const patchTurnFn = useCallback((id, fn) => {
    setTurns((prev) => prev.map((t) => (t.id === id ? { ...t, ...fn(t) } : t)));
  }, []);

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

  // 새 메시지 오면 스크롤
  useEffect(() => {
    conversationEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns.length, latestTurn?.answer, latestTurn?.scannedCount]);

  useEffect(() => {
    if (view !== "home") {
      const t = setTimeout(() => inputRef.current?.focus(), 150);
      return () => clearTimeout(t);
    }
  }, [view]);

  const {
    listening,
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
    const handle = () => {
      if (view === "chat") {
        setView("home");
        setTurns([]);
        setInputValue("");
      }
    };
    window.addEventListener("popstate", handle);
    return () => window.removeEventListener("popstate", handle);
  }, [view]);

  useEffect(() => {
    const q = location.state?.query;
    if (q) {
      window.history.replaceState({}, "");
      doSearchRef.current?.(q);
    }
  }, [location.state]);

  // ── thread_id 관리 ──────────────────────────────────────────────
  const getOrCreateThreadId = () => {
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
          JSON.stringify({ id: tid, expires: Date.now() + 86400000 }),
        );
      } catch {}
    }
    window.__aimodeThreadId = tid;
    return tid;
  };

  // ── runRAG ──────────────────────────────────────────────────────
  const runRAG = useCallback(
    async (q) => {
      if (abortRef.current) abortRef.current.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      const turnId = `turn_${Date.now()}`;
      activeTurnId.current = turnId;
      setTurns((prev) => [...prev, makeTurn(turnId, q)]);
      setRightMode("cards");
      setSelectedFile(null);

      const tid = getOrCreateThreadId();

      try {
        const resp = await fetch(`${API_BASE}/api/aimode/chat`, {
          method: "POST",
          signal: controller.signal,
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ query: q, topk: topK, thread_id: tid }),
        });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buf = "";

        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          buf += decoder.decode(value, { stream: true });
          const lines = buf.split("\n");
          buf = lines.pop() ?? "";
          for (const line of lines) {
            if (!line.startsWith("data: ")) continue;
            const raw = line.slice(6).trim();
            if (!raw) continue;
            let ev;
            try {
              ev = JSON.parse(raw);
            } catch {
              continue;
            }
            switch (ev.type) {
              case "route":
                patchTurn(turnId, { route: ev.mode || "rag" });
                break;
              case "intent":
                patchTurn(turnId, {
                  intentMessage: ev.message || "",
                  fileKeywords: ev.file_keywords || [],
                  detailKeywords: ev.detail_keywords || [],
                });
                break;
              case "candidates": {
                const items = ev.items || [];
                const init = {};
                items.forEach((s) => {
                  init[s.trichef_id || s.file_name] = "idle";
                });
                patchTurn(turnId, {
                  candidates: items,
                  scanStates: init,
                  scanChunks: {},
                });
                fetch(`${API_BASE}/api/history`, {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({
                    query: q,
                    method: "aimode",
                    result_count: items.length,
                  }),
                })
                  .then(() =>
                    window.dispatchEvent(new Event("history-updated")),
                  )
                  .catch(() => {});
                break;
              }
              case "scanning":
                patchTurnFn(turnId, (t) => ({
                  scanStates: { ...t.scanStates, [ev.file_id]: "scanning" },
                }));
                break;
              case "scan_result":
                patchTurnFn(turnId, (t) => ({
                  scanStates: {
                    ...t.scanStates,
                    [ev.file_id]: ev.found ? "found" : "not_found",
                  },
                  scanChunks:
                    ev.found && ev.chunks?.length
                      ? { ...t.scanChunks, [ev.file_id]: ev.chunks }
                      : t.scanChunks,
                  scannedCount: t.scannedCount + 1,
                  foundCount: t.foundCount + (ev.found ? 1 : 0),
                }));
                break;
              case "selected":
                patchTurn(turnId, { sources: ev.sources || [] });
                break;
              case "key_facts":
                patchTurn(turnId, { keyFacts: ev.facts || [] });
                break;
              case "generating":
                patchTurn(turnId, { generating: true });
                break;
              case "token":
                patchTurnFn(turnId, (t) => ({
                  answer: t.answer + (ev.text || ""),
                  generating: false,
                }));
                break;
              case "qa_generating":
                patchTurn(turnId, {
                  qaGenerating: true,
                  qaAttempt: ev.attempt || 1,
                  qaMax: ev.max || 3,
                });
                break;
              case "qa_result":
                patchTurn(turnId, {
                  qaGenerating: false,
                  qaQuestion: ev.question || "",
                  qaAnswer: ev.answer || "",
                  qaAttempt: ev.attempts || 1,
                  qaValid: ev.valid ?? false,
                  qaIssues: ev.issues || [],
                  qaSources: ev.sources || [],
                });
                break;
              case "done":
                patchTurnFn(turnId, (t) => ({
                  answer: ev.answer || t.answer,
                  done: true,
                  streaming: false,
                }));
                break;
              case "error":
                patchTurn(turnId, {
                  error: ev.message || "오류 발생",
                  streaming: false,
                });
                break;
            }
          }
        }
      } catch (e) {
        if (e.name !== "AbortError")
          patchTurn(turnId, {
            error: e.message || "연결 오류",
            streaming: false,
          });
        else patchTurn(turnId, { streaming: false });
      }
    },
    [topK, patchTurn, patchTurnFn],
  );

  // ── doSearch ────────────────────────────────────────────────────
  const doSearch = useCallback(
    (q) => {
      if (!q.trim() || searchTransitioning) return;
      setInputValue("");
      if (view === "home") {
        setHomeExiting(true);
        setTimeout(() => {
          setHomeExiting(false);
          setView("chat");
          window.history.pushState({ view: "chat" }, "");
          runRAG(q);
        }, 420);
      } else {
        runRAG(q);
      }
    },
    [view, searchTransitioning, runRAG],
  );

  doSearchRef.current = doSearch;
  useEffect(() => {
    doSearchRef.current = doSearch;
  });

  const handleSearch = (e) => {
    e?.preventDefault();
    doSearch(inputValue);
  };

  const handleSelectFile = (file) => {
    setSelectedFile(file);
    setRightMode("detail");
    // scanChunks는 최신 턴에서 가져오기
    setSelectedScanChunks(latestTurn?.scanChunks ?? {});
    const isAV = ["video", "audio", "movie", "music"].includes(file.file_type);
    if (!isAV && file.file_path) {
      setDetailLoading(true);
      setFileDetail(null);
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
    setTurns([]);
    setView("home");
    setInputValue("");
    setSelectedFile(null);
    setFileDetail(null);
    setRightMode("cards");
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

  // 우측 패널: 최신 턴의 candidates
  const rightCandidates = latestTurn?.candidates ?? [];
  const rightScanStates = latestTurn?.scanStates ?? {};

  // ── Render ──────────────────────────────────────────────────────
  return (
    <div
      style={{
        display: "flex",
        height: "100vh",
        background: AI.bg,
        overflow: "hidden",
      }}
    >
      {searchTransitioning && (
        <div className="fixed inset-0 z-[9999] pointer-events-none overflow-hidden">
          <div
            className="portal-overlay absolute rounded-full"
            style={{
              width: 80,
              height: 80,
              left: ripplePos.x,
              top: ripplePos.y,
              transform: "translate(-50%,-50%)",
              background:
                "radial-gradient(circle,#1c253e 0%,#0c1326 60%,#070d1f 100%)",
              boxShadow: "0 0 30px 10px rgba(133,173,255,0.15)",
            }}
          />
          {[0, 200].map((delay, i) => (
            <div
              key={i}
              className="portal-ring absolute rounded-full border border-[#85adff]/25"
              style={{
                width: 160,
                height: 160,
                left: ripplePos.x,
                top: ripplePos.y,
                transform: "translate(-50%,-50%)",
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

      <SearchSidebar
        entranceOn={view === "home" ? aiHomeEntranceOn : undefined}
      />

      <div
        className={`${ml} flex-1 flex flex-col overflow-hidden transition-[margin] duration-300`}
      >
        {/* ══ HOME ══ */}
        {view === "home" && (
          <main className="relative flex h-full flex-col overflow-hidden bg-transparent pt-8">
            <div
              className="ai-home-orbit-bg pointer-events-none absolute inset-0 z-0"
              style={{ "--ai-orbit-assemble": `${AI_ORB_ASSEMBLE_SECONDS}s` }}
              aria-hidden
            />
            <div ref={orbSinkRef} className="absolute inset-0 z-0" aria-hidden>
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
              className={`pointer-events-none relative z-10 flex h-full flex-col ${aiHomeEntranceOn ? "main-search-entrance-on" : "main-search-entrance-off"}`}
            >
              <div className="relative z-10 flex min-h-0 flex-1 flex-col items-center justify-center px-6 py-8">
                <div className="relative flex w-full max-w-lg flex-col items-center gap-9 text-center">
                  <div
                    className={`mse-hero-down pointer-events-auto transition-all duration-300 ${homeExiting ? "opacity-0 -translate-y-6" : ""}`}
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
                    className="mse-search-up group pointer-events-auto relative z-10 w-full max-w-[min(90vw,22rem)] shrink-0 md:max-w-[24rem]"
                    style={homeExiting ? { visibility: "hidden" } : {}}
                  >
                    <div className="pointer-events-none absolute -inset-[2px] rounded-full bg-gradient-to-r from-fuchsia-500/0 via-violet-400/25 to-fuchsia-500/0 opacity-0 blur-md transition-opacity duration-500 group-focus-within:opacity-100" />
                    <div className="relative flex items-center gap-2 rounded-full border border-violet-200/[0.14] bg-gradient-to-b from-violet-100/[0.09] to-violet-950/[0.28] px-1.5 py-1.5 shadow-[inset_0_1px_0_rgba(255,255,255,0.16),inset_0_-1px_0_rgba(0,0,0,0.22),0_10px_44px_rgba(32,12,58,0.5)] backdrop-blur-2xl transition-all duration-300 group-focus-within:border-violet-200/25">
                      <button
                        type="button"
                        className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-violet-900 to-purple-600 text-violet-50 shadow-[0_0_20px_rgba(124,58,237,0.32),inset_0_1px_0_rgba(255,255,255,0.18)] transition-transform hover:from-violet-800 hover:to-purple-500 active:scale-90"
                      >
                        <span className="material-symbols-outlined text-[20px] font-bold">
                          add
                        </span>
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
                        className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full border backdrop-blur-md transition-colors ${listening ? "border-rose-400/35 bg-rose-950/40 text-rose-200" : "border-violet-300/18 bg-violet-950/35 text-violet-200/80"}`}
                      >
                        <span className="material-symbols-outlined text-[20px]">
                          mic
                        </span>
                      </button>
                    </div>
                  </form>
                </div>
              </div>
              <div className="mse-search-up mse-search-up-delay-1 pointer-events-auto flex shrink-0 flex-col items-center pb-10 pt-2">
                <button
                  ref={btnRef}
                  onClick={handleGoToSearch}
                  disabled={searchTransitioning}
                  className="group flex items-center gap-3 rounded-full border border-white/10 bg-white/[0.06] px-8 py-3 text-sm font-bold uppercase tracking-widest text-neutral-400 transition-all duration-300 hover:border-white/20 hover:text-neutral-200 disabled:pointer-events-none"
                >
                  <span
                    className="h-2 w-2 animate-pulse rounded-full bg-violet-500"
                    style={{ boxShadow: "0 0 6px rgba(139,92,246,0.9)" }}
                  />
                  검색 모드로 전환
                  <span className="material-symbols-outlined text-lg transition-transform group-hover:translate-x-1">
                    arrow_forward
                  </span>
                </button>
              </div>
            </div>
          </main>
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
                background: "rgba(6,3,15,0.94)",
                backdropFilter: "blur(20px)",
                borderBottom: "1px solid rgba(139,92,246,0.09)",
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
                Obsidian AI
              </button>

              {/* 현재 route 뱃지 */}
              {latestTurn?.route === "rag" && (
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 4,
                    fontSize: 10,
                    fontWeight: 700,
                    letterSpacing: "0.08em",
                    textTransform: "uppercase",
                    color: AI.accentLight,
                    background: "rgba(139,92,246,0.12)",
                    border: `1px solid rgba(139,92,246,0.25)`,
                    padding: "3px 10px",
                    borderRadius: 999,
                    flexShrink: 0,
                  }}
                >
                  🔍 RAG
                </div>
              )}
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
                    className="material-symbols-outlined ai-spin"
                    style={{ fontSize: 11 }}
                  >
                    sync
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
                  width: "55%",
                  display: "flex",
                  flexDirection: "column",
                  borderRight: "1px solid rgba(139,92,246,0.07)",
                  background: AI.leftBg,
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

                {/* 입력창 */}
                <div
                  style={{
                    padding: "10px 14px",
                    flexShrink: 0,
                    borderTop: "1px solid rgba(139,92,246,0.07)",
                    background: "rgba(6,3,15,0.92)",
                    backdropFilter: "blur(12px)",
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
                          fontSize: 13,
                          color: "#e2e8f0",
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
                          ? "linear-gradient(135deg,#6d28d9,#7c3aed)"
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
                  width: "45%",
                  display: "flex",
                  flexDirection: "column",
                  background: AI.rightBg,
                  overflow: "hidden",
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
                            color: "rgba(139,92,246,0.08)",
                          }}
                        >
                          folder_open
                        </span>
                        <p
                          style={{
                            fontSize: 11,
                            color: "#0e0924",
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
                            color: "#1e1535",
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
                        {/* 파일 헤더 */}
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
                                color: "#2d2050",
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
                            <div style={{ fontSize: 9, color: "#2d2050" }}>
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

                        {/* 매칭 청크 */}
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
                                          color: "#2d2050",
                                          flexShrink: 0,
                                          width: 70,
                                        }}
                                      >
                                        {k}
                                      </span>
                                      <span
                                        style={{
                                          color: "#4b3f6b",
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
      </div>

      <style>{`
        @keyframes ai-spin  { from{transform:rotate(0deg)} to{transform:rotate(360deg)} }
        @keyframes ai-blink { 0%,100%{opacity:1} 50%{opacity:0} }
        @keyframes ai-scan-line { 0%{transform:translateY(-100%);opacity:0.8} 100%{transform:translateY(100%);opacity:0.3} }
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
