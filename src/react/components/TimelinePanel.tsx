// ============================================================
// TimelinePanel —— 左侧：可点击跳转的时间线面板
// ============================================================
// 替代 StoryHistory。点击任意章节节点即可跳转到该时刻。
// 跳转走 WebSocket（timeline:jump），由后端广播新状态，前端自动清理对话并重载。
// ============================================================
import { useState, useEffect, useRef } from "react";
import type { TimelineNodeData } from "../../types/api";
import { wsClient } from "../../core/WebSocketClient";
import { gameState } from "../../core/GameState";
import { globalEventBus } from "../../core/EventBus";

const API_URL = "http://localhost:8000/api/v1/timeline/tree";

export function TimelinePanel() {
  const [nodes, setNodes] = useState<TimelineNodeData[]>([]);
  const [currentTick, setCurrentTick] = useState(0);
  const [jumping, setJumping] = useState(false);
  const [error, setError] = useState("");
  const activeRef = useRef<HTMLDivElement>(null);

  // ── 5 秒轮询拉取节点列表 ──
  useEffect(() => {
    const fetchTree = async () => {
      try {
        const res = await fetch(`${API_URL}?world_id=default_world`);
        if (res.ok) {
          const data = await res.json();
          if (data.nodes?.length > 0) {
            setNodes(data.nodes);
          }
          // 以 GameState 的真实 tick 为准
          const realTick = gameState.getSnapshot().tick;
          setCurrentTick(data.current_tick ?? realTick ?? 0);
        }
      } catch (_) {}
    };
    fetchTree();
    const timer = setInterval(fetchTree, 5000);
    return () => clearInterval(timer);
  }, []);

  // ── 订阅 world_state 同步真实 tick ──
  useEffect(() => {
    const handler = () => setCurrentTick(gameState.getSnapshot().tick);
    const unsub = globalEventBus.on("world_state", handler);
    return unsub;
  }, []);

  // ── 跳转结果：结束跳转状态并显示失败信息 ──
  useEffect(() => {
    const handler = (data: any) => {
      setJumping(false);
      if (!data?.success) setError(data?.message || "跳转失败");
    };
    const unsub = globalEventBus.on("timeline:jump_result", handler);
    return unsub;
  }, []);

  // ── 当前活跃章节滚动到可见 ──
  useEffect(() => {
    if (activeRef.current) {
      activeRef.current.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [nodes, currentTick]);

  // ── 跳转到指定 tick（点击默认只读回看；重写需要明确确认） ──
  const handleJump = (tick: number, mode: "view" | "rewrite" = "view") => {
    if (jumping) return;
    if (mode === "rewrite" && !window.confirm(`确定从 TICK ${tick} 重新改写故事吗？\n该节点之后的对话、记忆和章节节点会被裁剪。`)) return;
    setJumping(true);
    setError("");
    gameState.setPendingJumpTick(tick);
    gameState.clearDialogueLog();
    gameState.clearNarrativeEvents();
    wsClient.jumpToTick(tick, mode);
  };

  const tensionColor = (t: string): string => {
    switch (t) {
      case "平静": return "#22c55e";
      case "紧张": return "#eab308";
      case "危机": return "#ef4444";
      case "收束": return "#a855f7";
      default: return "#94a3b8";
    }
  };

  if (nodes.length === 0) {
    return (
      <div className="timeline-list">
        <div className="timeline-empty">等待导演生成章节...</div>
      </div>
    );
  }

  return (
    <div className="timeline-list">
      <div className="timeline-branch active">
        {nodes.map((node, i) => {
          const isCurrent = node.tick <= currentTick
            && (i === nodes.length - 1 || (nodes[i + 1]?.tick ?? Infinity) > currentTick);
          const isPast = node.tick <= currentTick && !isCurrent;

          return (
            <div key={node.node_id} style={{ position: "relative", marginBottom: 4 }}
              ref={isCurrent ? activeRef : undefined}
            >
              <div
                className={`timeline-node ${isCurrent ? "current" : ""} ${isPast ? "past" : ""}`}
                onClick={() => handleJump(node.tick, "view")}
                title={isCurrent ? "当前所在，点击回看本章" : `点击只读回看 TICK ${node.tick}`}
              >
                <div className="timeline-dot" style={{
                  background: isCurrent ? "#3b82f6" : tensionColor(node.tension),
                  boxShadow: isCurrent ? "0 0 0 3px rgba(59,130,246,0.3), 0 0 8px rgba(59,130,246,0.4)" : "none",
                }} />

                <div className="timeline-node-content">
                  <div className="timeline-node-title">
                    {isCurrent && <span className="timeline-current-marker" title="当前章节">📍 </span>}
                    {node.title}
                  </div>
                  {node.summary && (
                    <div className="timeline-node-summary">{node.summary}</div>
                  )}
                  <div className="timeline-node-tick">
                    TICK {node.tick}
                    {node.tension && <span className={`timeline-tension tag-${node.tension}`}> · {node.tension}</span>}
                  </div>

                  {node.key_events && node.key_events.length > 0 && (
                    <div className="timeline-key-events">
                      {node.key_events.map((ev, j) => (
                        <div key={j} className="timeline-key-event">• {ev}</div>
                      ))}
                    </div>
                  )}
                  <button
                    type="button"
                    className="timeline-rewrite-btn"
                    onClick={(e) => { e.stopPropagation(); handleJump(node.tick, "rewrite"); }}
                  >
                    从此重写
                  </button>
                </div>
              </div>

              {i < nodes.length - 1 && (
                <div className="timeline-connector" />
              )}
            </div>
          );
        })}
      </div>

      {jumping && (
        <div className="timeline-jumping">跳转中...</div>
      )}
      {error && (
        <div className="timeline-jumping" style={{ color: "#991b1b" }}>{error}</div>
      )}
    </div>
  );
}
