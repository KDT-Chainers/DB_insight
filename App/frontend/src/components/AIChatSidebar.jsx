// [v3] AIMODE 전용 좌측 사이드바 — 채팅방 목록 + "새 채팅" 버튼.
// GPT/Claude 스타일: 새 채팅 시작 → 같은 thread 안에서 turn 누적 → 사이드바 항목 클릭으로 복원.
import { useEffect, useState, useCallback } from "react";
import { API_BASE } from "../api";
import WindowControls from "./WindowControls";
import TeamLogoMark from "./TeamLogoMark";

export default function AIChatSidebar({
  currentThreadId,
  onNewChat,
  onSelectThread,
  refreshTrigger,    // 새 turn 저장 후 부모가 ++ 하면 목록 새로고침
}) {
  const [threads, setThreads] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [editingTid, setEditingTid] = useState(null);
  const [editValue, setEditValue] = useState("");

  const fetchThreads = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const r = await fetch(`${API_BASE}/api/aimode/threads?limit=100`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      setThreads(d.threads || []);
    } catch (e) {
      console.warn("[AIChatSidebar] fetch threads 실패", e);
      setError(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchThreads();
  }, [fetchThreads, refreshTrigger]);

  const handleDelete = async (tid, e) => {
    e.stopPropagation();
    if (!window.confirm("이 채팅방을 삭제하시겠습니까?")) return;
    try {
      await fetch(`${API_BASE}/api/aimode/chat/${tid}`, { method: "DELETE" });
      // 현재 채팅방 삭제 시 새 채팅으로
      if (tid === currentThreadId) onNewChat?.();
      fetchThreads();
    } catch (err) {
      console.warn("[AIChatSidebar] delete 실패", err);
    }
  };

  const handleEditStart = (tid, title, e) => {
    e.stopPropagation();
    setEditingTid(tid);
    setEditValue(title);
  };

  const handleEditSave = async (tid, e) => {
    e?.stopPropagation();
    const newTitle = editValue.trim();
    if (!newTitle) {
      setEditingTid(null);
      return;
    }
    try {
      await fetch(`${API_BASE}/api/aimode/threads/${tid}/title`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: newTitle }),
      });
      setEditingTid(null);
      fetchThreads();
    } catch (err) {
      console.warn("[AIChatSidebar] title patch 실패", err);
      setEditingTid(null);
    }
  };

  const fmtRelative = (iso) => {
    if (!iso) return "";
    try {
      const t = Date.parse(iso);
      if (!t) return "";
      const diff = Date.now() - t;
      const min = Math.floor(diff / 60000);
      if (min < 1) return "방금";
      if (min < 60) return `${min}분 전`;
      const hr = Math.floor(min / 60);
      if (hr < 24) return `${hr}시간 전`;
      const day = Math.floor(hr / 24);
      if (day < 7) return `${day}일 전`;
      return new Date(t).toLocaleDateString("ko-KR", { month: "2-digit", day: "2-digit" });
    } catch { return ""; }
  };

  return (
    <aside
      className="ai-chat-sidebar"
      style={{
        position: "fixed",
        left: 0,
        top: 0,
        width: 260,
        height: "100vh",
        background: "linear-gradient(180deg, rgba(5,5,7,0.96) 0%, rgba(12,8,22,0.96) 100%)",
        borderRight: "1px solid rgba(139,92,246,0.18)",
        display: "flex",
        flexDirection: "column",
        flexShrink: 0,
        zIndex: 20,
      }}
    >
      {/* ── 타이틀바 (윈도우 컨트롤 + 로고) ── */}
      <div
        style={{
          height: 32,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "0 8px 0 10px",
          borderBottom: "1px solid rgba(139,92,246,0.12)",
          WebkitAppRegion: "drag",   // Electron 윈도우 드래그
        }}
      >
        <div style={{ WebkitAppRegion: "no-drag" }}>
          <TeamLogoMark />
        </div>
        <div style={{ WebkitAppRegion: "no-drag" }}>
          <WindowControls />
        </div>
      </div>

      {/* ── 헤더 (새 채팅 버튼) ── */}
      <div
        style={{
          padding: "16px 14px 10px",
          borderBottom: "1px solid rgba(139,92,246,0.15)",
        }}
      >
        <button
          type="button"
          onClick={() => onNewChat?.()}
          style={{
            width: "100%",
            padding: "10px 12px",
            borderRadius: 10,
            border: "1px solid rgba(167,139,250,0.4)",
            background:
              "linear-gradient(135deg, rgba(139,92,246,0.25) 0%, rgba(217,70,239,0.20) 100%)",
            color: "#f5f3ff",
            fontWeight: 700,
            fontSize: 13,
            cursor: "pointer",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: 6,
            transition: "transform 0.15s, background 0.15s",
          }}
          onMouseEnter={(e) =>
            (e.currentTarget.style.background =
              "linear-gradient(135deg, rgba(139,92,246,0.4) 0%, rgba(217,70,239,0.32) 100%)")
          }
          onMouseLeave={(e) =>
            (e.currentTarget.style.background =
              "linear-gradient(135deg, rgba(139,92,246,0.25) 0%, rgba(217,70,239,0.20) 100%)")
          }
        >
          <span className="material-symbols-outlined" style={{ fontSize: 16 }}>
            add
          </span>
          새 채팅
        </button>
      </div>

      {/* ── 목록 헤더 ── */}
      <div
        style={{
          padding: "12px 14px 6px",
          fontSize: 10,
          fontWeight: 700,
          letterSpacing: "0.14em",
          textTransform: "uppercase",
          color: "rgba(196,181,253,0.7)",
        }}
      >
        대화 기록 {threads.length > 0 && `(${threads.length})`}
      </div>

      {/* ── 채팅방 목록 ── */}
      <div
        style={{
          flex: 1,
          overflowY: "auto",
          padding: "0 8px 14px",
        }}
      >
        {loading && (
          <div style={{ padding: 14, fontSize: 11, color: "rgba(196,181,253,0.6)" }}>
            불러오는 중…
          </div>
        )}
        {error && (
          <div style={{ padding: 14, fontSize: 11, color: "#fca5a5" }}>
            목록 로드 실패: {error}
          </div>
        )}
        {!loading && !error && threads.length === 0 && (
          <div style={{ padding: 14, fontSize: 11, color: "rgba(196,181,253,0.6)" }}>
            아직 대화 기록이 없습니다.<br />위 "새 채팅" 으로 시작하세요.
          </div>
        )}
        {threads.map((t) => {
          const isActive = t.thread_id === currentThreadId;
          const isEditing = editingTid === t.thread_id;
          return (
            <div
              key={t.thread_id}
              onClick={() => !isEditing && onSelectThread?.(t.thread_id)}
              style={{
                padding: "9px 10px",
                marginBottom: 3,
                borderRadius: 9,
                cursor: isEditing ? "default" : "pointer",
                background: isActive
                  ? "rgba(167,139,250,0.18)"
                  : "transparent",
                border: isActive
                  ? "1px solid rgba(167,139,250,0.35)"
                  : "1px solid transparent",
                transition: "background 0.12s, border-color 0.12s",
                position: "relative",
                display: "flex",
                flexDirection: "column",
                gap: 3,
              }}
              onMouseEnter={(e) => {
                if (!isActive && !isEditing)
                  e.currentTarget.style.background = "rgba(139,92,246,0.08)";
              }}
              onMouseLeave={(e) => {
                if (!isActive && !isEditing)
                  e.currentTarget.style.background = "transparent";
              }}
            >
              {isEditing ? (
                <input
                  type="text"
                  value={editValue}
                  onChange={(e) => setEditValue(e.target.value)}
                  onBlur={(e) => handleEditSave(t.thread_id, e)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") handleEditSave(t.thread_id, e);
                    if (e.key === "Escape") setEditingTid(null);
                  }}
                  autoFocus
                  style={{
                    width: "100%",
                    padding: "2px 4px",
                    fontSize: 12,
                    fontWeight: 600,
                    color: "#f5f3ff",
                    background: "rgba(0,0,0,0.4)",
                    border: "1px solid rgba(167,139,250,0.5)",
                    borderRadius: 4,
                    outline: "none",
                  }}
                  onClick={(e) => e.stopPropagation()}
                />
              ) : (
                <div
                  style={{
                    fontSize: 12.5,
                    fontWeight: 600,
                    color: isActive ? "#f5f3ff" : "rgba(229,231,235,0.95)",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                  title={t.title}
                >
                  {t.title || "(제목 없음)"}
                </div>
              )}
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  fontSize: 10,
                  color: "rgba(196,181,253,0.55)",
                }}
              >
                <span>{fmtRelative(t.updated_at)}</span>
                <span>{Math.floor((t.msg_count || 0) / 2)}회</span>
              </div>
              {/* 호버 액션 (편집·삭제) */}
              {!isEditing && (
                <div
                  style={{
                    position: "absolute",
                    right: 6,
                    top: 6,
                    display: "flex",
                    gap: 2,
                    opacity: 0,
                    transition: "opacity 0.15s",
                  }}
                  className="ai-chat-sidebar-actions"
                  onClick={(e) => e.stopPropagation()}
                >
                  <button
                    type="button"
                    onClick={(e) => handleEditStart(t.thread_id, t.title, e)}
                    title="제목 변경"
                    style={{
                      width: 22,
                      height: 22,
                      borderRadius: 5,
                      border: "none",
                      background: "rgba(0,0,0,0.5)",
                      color: "#c4b5fd",
                      cursor: "pointer",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                    }}
                  >
                    <span
                      className="material-symbols-outlined"
                      style={{ fontSize: 13 }}
                    >
                      edit
                    </span>
                  </button>
                  <button
                    type="button"
                    onClick={(e) => handleDelete(t.thread_id, e)}
                    title="삭제"
                    style={{
                      width: 22,
                      height: 22,
                      borderRadius: 5,
                      border: "none",
                      background: "rgba(0,0,0,0.5)",
                      color: "#fca5a5",
                      cursor: "pointer",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                    }}
                  >
                    <span
                      className="material-symbols-outlined"
                      style={{ fontSize: 13 }}
                    >
                      delete
                    </span>
                  </button>
                </div>
              )}
            </div>
          );
        })}
      </div>

      <style>{`
        .ai-chat-sidebar > div:nth-child(3) > div:hover > .ai-chat-sidebar-actions {
          opacity: 1 !important;
        }
      `}</style>
    </aside>
  );
}
