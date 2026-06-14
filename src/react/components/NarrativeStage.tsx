// ============================================================
// src/react/components/NarrativeStage.tsx —— 真实数据驱动的主叙事舞台
// ============================================================
import { useEffect, useRef, useState } from "react";
import { useDialogueLog, useGameState } from "../hooks/useGameState";
import { gameState } from "../../core/GameState";
import { globalEventBus } from "../../core/EventBus";
import { getAgentAvatar } from "../utils/agentPresentation";

function TypewriterText({ text, speed = 40, paused = false, onComplete }: { text: string; speed?: number; paused?: boolean; onComplete?: () => void }) {
  const [displayedText, setDisplayedText] = useState("");
  const indexRef = useRef(0);
  const doneRef = useRef(false);
  const onCompleteRef = useRef(onComplete);

  useEffect(() => { onCompleteRef.current = onComplete; }, [onComplete]);
  useEffect(() => { indexRef.current = 0; doneRef.current = false; setDisplayedText(""); }, [text]);

  useEffect(() => {
    if (paused || doneRef.current) return;
    const timer = window.setInterval(() => {
      if (indexRef.current >= text.length) {
        window.clearInterval(timer);
        if (!doneRef.current) { doneRef.current = true; onCompleteRef.current?.(); }
        return;
      }
      indexRef.current++;
      setDisplayedText(text.slice(0, indexRef.current));
    }, speed);
    return () => window.clearInterval(timer);
  }, [text, speed, paused]);

  return (<span>{displayedText}{!doneRef.current && <span className="typing-cursor"></span>}</span>);
}

interface DialogueProps {
  name: string; avatar: string; thought?: string; action: string;
  isPlayer?: boolean; emotion?: string; paused?: boolean;
  useTypewriter?: boolean; onComplete?: () => void;
}

function DialogueItem({ name, avatar, thought, action, isPlayer = false, emotion, paused = false, useTypewriter = false, onComplete }: DialogueProps) {
  const needsShake = emotion === "anxious" || emotion === "angry" || emotion === "nervous";

  if (name === "旁白" || name.includes("导演")) {
    return (
      <div className="dialogue-wrapper narration-wrapper">
        <div className="narration-text">
          {useTypewriter ? <TypewriterText text={action} speed={35} paused={paused} onComplete={onComplete} /> : action}
        </div>
      </div>
    );
  }

  if (isPlayer) {
    return (
      <div className="dialogue-wrapper player-wrapper">
        <div className="dialogue-content player-content">
          <div className="dialogue-name" style={{ textAlign: "right" }}>{name}</div>
          <div className="dialogue-bubble player-bubble">
            <div className="dialogue-text">
              {useTypewriter ? <TypewriterText text={action} speed={80} paused={paused} onComplete={onComplete} /> : action}
            </div>
          </div>
        </div>
        <div className="dialogue-avatar player-avatar" aria-label={name} title={name}><span className="avatar-symbol">{avatar}</span></div>
      </div>
    );
  }

  return (
    <div className="dialogue-wrapper">
      <div className={`dialogue-avatar ${needsShake ? "avatar-shake" : ""}`} aria-label={name} title={name}><span className="avatar-symbol">{avatar}</span></div>
      <div className="dialogue-content">
        <div className="dialogue-name">{name}</div>
        <div className="dialogue-bubble">
          {thought && <div className="dialogue-thought">(内心) {thought}</div>}
          <div className="dialogue-text">
            {useTypewriter ? <TypewriterText text={action} speed={80} paused={paused} onComplete={onComplete} /> : action}
          </div>
        </div>
      </div>
    </div>
  );
}

export function NarrativeStage() {
  const dialogueLog = useDialogueLog();
  const { tension, summary, background, initialQuest, directorPrompt, isPaused, isViewingHistory, viewingTick } = useGameState();
  const stageRef = useRef<HTMLDivElement>(null);
  const [visibleCount, setVisibleCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const [interventionToast, setInterventionToast] = useState<{ success: boolean; message: string; effectiveness: number } | null>(null);
  const jumpScrollRef = useRef<{ tick: number; retries: number } | null>(null);
  const isAtBottomRef = useRef(true);            // 用户是否在底部（控制自动下滑）
  const userScrolledRef = useRef(false);         // 用户是否手动上滑过了
  const isTypingRef = useRef(false);             // 当前是否正在打字中（防止新对话切断打字）

  // 启动故事
  const startStory = () => {
    setLoading(true);
    fetch("http://localhost:8000/story/resume", { method: "POST" }).catch(() => { });
  };


  // 干预结果反馈 toast（6 秒后自动消失，置顶吸顶）
  useEffect(() => {
    const handler = (data: any) => {
      setInterventionToast({
        success: data.success,
        message: data.narrative_response || (data.success ? "干预已生效" : "干预未能执行"),
        effectiveness: data.effectiveness ?? 1.0,
      });
      setTimeout(() => setInterventionToast(null), 6000);
    };
    const unsub = globalEventBus.on("intervention_result", handler);
    return unsub;
  }, []);

  // 时间线跳转后重新从 /feed 拉取对话
  useEffect(() => {
    const reload = async (data: any) => {
      try {
        const mode = data?.mode || "rewrite";
        const targetTick = data?.target_tick ?? data?.current_tick ?? gameState.getPendingJumpTick() ?? 0;
        if (mode === "view") {
          gameState.startHistoryView(targetTick);
        } else {
          gameState.exitHistoryView();
        }

        // view 模式加载全部对话（用户回看历史）；rewrite 模式只加载到目标 tick
        const feedUrl = mode === "rewrite" && targetTick > 0
          ? `http://localhost:8000/feed/all?to_tick=${targetTick}`
          : "http://localhost:8000/feed/all";
        const res = await fetch(feedUrl);
        const items = await res.json();
        if (!items.length) return;

        gameState.clearDialogueLog();
        for (const item of items) {
          let text = item.content || "";
          const m = text.match(/：「(.+?)」/);
          const content = m ? m[1] : text.replace(/^我/, "");
          const id = `feed_${item.tick}_${item.agent_id}_${content.slice(0, 20)}`;
          gameState.addDialogue({
            id,
            speakerId: item.agent_id, speakerName: item.agent_name || item.agent_id,
            content, tick: item.tick,
            fromHistory: true,
            emotion: item.emotion || "neutral", actionType: item.actionType || "", thought: "",
          });
        }

        // 标记跳转滚动目标，等 React 渲染完成后滚动
        jumpScrollRef.current = { tick: targetTick, retries: 0 };
        setVisibleCount(gameState.getDialogueLog().length);
        globalEventBus.emit("dialogue", {});
        gameState.setPendingJumpTick(0);
      } catch (e) { }
    };
    const unsub = globalEventBus.on("timeline:view_feed", reload);
    const unsub2 = globalEventBus.on("timeline:rewrite_feed", reload);
    return () => { unsub(); unsub2(); };
  }, []);

  // 跳转后滚动到目标 tick 第一条对话（等 React 渲染 DOM 后执行）
  useEffect(() => {
    if (!jumpScrollRef.current) return;
    const target = jumpScrollRef.current;
    // 最多重试 10 次，每次间隔 100ms
    if (target.retries >= 10) { jumpScrollRef.current = null; return; }

    const timer = setTimeout(() => {
      const container = scrollContainer();
      if (!container) { jumpScrollRef.current = null; return; }

      // 找第一条 >= 目标 tick 的对话
      const allItems = container.querySelectorAll('[id^="msg-feed_"]');
      let found: HTMLElement | null = null;
      for (const el of allItems) {
        const id = (el as HTMLElement).id;
        const tickMatch = id.match(/^msg-feed_(\d+)_/);
        if (tickMatch && parseInt(tickMatch[1]) >= target.tick) {
          found = el as HTMLElement;
          break;
        }
      }
      if (found) {
        found.scrollIntoView({ behavior: "smooth", block: "start" });
        jumpScrollRef.current = null;
      } else {
        target.retries++;
        jumpScrollRef.current = { ...target };
      }
    }, 150);

    return () => clearTimeout(timer);
  }, [dialogueLog, visibleCount]);

  // ── 游标推进：只有最后一条打字，一条播完才出下一条 ──
  const advanceDialogue = () => {
    isTypingRef.current = false;                       // 当前条目打完
    setTimeout(() => {
      setVisibleCount((c) => {
        const next = Math.min(c + 1, dialogueLog.length);
        if (next > c) isTypingRef.current = true;      // 新条目开始打字
        return next;
      });
    }, 600);
  };

  useEffect(() => {
    setVisibleCount((c) => {
      if (dialogueLog.length === 0) return 0;
      if (c === 0) {
        // 初始加载（刷新/历史）：全部展示，不触发打字机（由 fromHistory 标记控制）
        return dialogueLog.length;
      }
      // 实时对话：打字中不抢，打完才推进
      if (!isTypingRef.current && c < dialogueLog.length) {
        isTypingRef.current = true;
        return c + 1;
      }
      return Math.min(c, dialogueLog.length);
    });
  }, [dialogueLog.length]);

  const scrollContainer = () => stageRef.current?.closest(".sw-stage") as HTMLElement | null;

  // ── 监听用户滚动行为：到底时恢复自动下滑，上滑时解除 ──
  useEffect(() => {
    const container = scrollContainer();
    if (!container) return;

    const onScroll = () => {
      const distToBottom = container.scrollHeight - container.scrollTop - container.clientHeight;
      const atBottom = distToBottom < 60;
      isAtBottomRef.current = atBottom;
      if (!atBottom && distToBottom >= 60) {
        userScrolledRef.current = true;   // 用户主动上滑，暂停自动下滑
      }
      if (atBottom) {
        userScrolledRef.current = false;  // 回到最底，恢复自动下滑
      }
    };

    container.addEventListener("scroll", onScroll, { passive: true });
    return () => container.removeEventListener("scroll", onScroll);
  }, []);

  // ── 新对话弹出时：如果用户在最底部（或未上滑），自动滚到最底 ──
  useEffect(() => {
    const container = scrollContainer();
    if (!container) return;
    const shouldAutoScroll = isAtBottomRef.current || !userScrolledRef.current || dialogueLog.length <= 1;
    if (shouldAutoScroll) {
      // requestAnimationFrame 确保 DOM 已渲染再滚动
      requestAnimationFrame(() => {
        container.scrollTo({ top: container.scrollHeight, behavior: "instant" });
      });
    }
  }, [dialogueLog, visibleCount, summary, background]);

  // ── 页面刷新后，历史对话渲染完成后延迟滚到底部（兜底） ──
  useEffect(() => {
    if (dialogueLog.length === 0) return;
    const timer = setTimeout(() => {
      const container = scrollContainer();
      if (container) {
        container.scrollTo({ top: container.scrollHeight, behavior: "instant" });
      }
    }, 300);
    return () => clearTimeout(timer);
  }, []); // 仅在组件挂载时执行一次

  const isHighTension = typeof tension === "number" && tension >= 85;
  const visibleDialogues = dialogueLog.slice(0, visibleCount);

  return (
    <div className="stage-scroll-inner" ref={stageRef}
      style={{ maxWidth: "850px", margin: "0 auto", paddingBottom: "40px", position: "relative", minHeight: "100%" }}>
      <div className={`tension-vignette ${isHighTension ? "active" : ""}`}></div>

      <div className="log-system">
        <div style={{ fontWeight: "bold" ,fontFamily: "STKaiti",fontSize:"20px",color: "#ffbe76",textShadow: "0 0 10px rgba(255, 190, 118, 0.5)"}}>【真实推演已接入】</div>
        <div style={{fontFamily:"SimSun",fontWeight: "bold",fontSize:"18px"}}>{summary || "等待后端下发当前世界大纲……"}</div>
        {background && <div style={{ marginTop: "8px", color: "#a5d8ff" ,opacity: 0.8,fontFamily:"SimSun",fontWeight: "bold",fontSize:"18px"}}>{background}</div>}
        {initialQuest && <div style={{ marginTop: "8px", color: "#ff7675",fontFamily:"SimSun",fontWeight: "bold",fontSize:"18px" }}>阶段目标：{initialQuest}</div>}
      </div>

      {isPaused && (
        <div className="log-system" >
          【时钟暂停】智能体对话流已冻结。点击底部暂停按钮继续。
        </div>
      )}

      {isViewingHistory && (
        <div className="log-system" >
          正在只读回看 TICK {viewingTick} 之前的历史。
          <button
            onClick={() => {
              const currentTick = gameState.getSnapshot().tick;
              gameState.exitHistoryView();
              gameState.clearDialogueLog();
              globalEventBus.emit("timeline:rewrite_feed", { mode: "rewrite", target_tick: currentTick });
            }}
            style={{ marginLeft: 12, padding: "4px 10px", borderRadius: 6, border: "1px solid #93c5fd", background: "#fff", color: "#1d4ed8", cursor: "pointer" }}
          >
            返回当前时间线
          </button>
        </div>
      )}

      {interventionToast && (
        <div className="log-system" style={{
          borderColor: interventionToast.success ? "#bbf7d0" : "#fecaca",
          background: interventionToast.success ? "#f0fdf4" : "#fff1f2",
          color: interventionToast.success ? "#166534" : "#991b1b",
          animation: "fadeIn 0.3s ease-out",
          transition: "opacity 0.5s",
          position: "sticky",
          top: 8,
          zIndex: 10,
          boxShadow: "0 2px 8px rgba(0,0,0,0.08)",
        }}>
          {interventionToast.success ? "✅" : "❌"} {interventionToast.message}
          {interventionToast.effectiveness < 1.0 && (
            <span style={{ marginLeft: "8px", fontSize: "12px", opacity: 0.7 }}>
              (有效性: {(interventionToast.effectiveness * 100).toFixed(0)}%)
            </span>
          )}
        </div>
      )}

      {/* 序幕：优先使用后端导演动态开场旁白；当对话为空且无导演提示时才展示备用静态序幕 */}
      {directorPrompt ? (
        <div className="narration-wrapper" style={{ marginTop: "20px" }}>
          <div className="narration-text" style={{ fontSize: "15px", lineHeight: "2", maxWidth: "95%" }}>
            <p>{directorPrompt}</p>
          </div>
        </div>
      ) : dialogueLog.length === 0 ? (
        <div className="narration-wrapper" style={{ marginTop: "20px" }}>
          <div className="narration-text" style={{ fontSize: "15px", lineHeight: "2", maxWidth: "95%" }}>
            <p>暴风雪夜，雪山别墅「雪隐」。晚餐刚结束，四个人还坐在餐桌旁，没有人说话。</p>
            <p>突然——整栋别墅的灯闪了一下，灭了，又亮起来。</p>
            <p>紧接着，三楼传来一声沉闷的巨响。</p>
            <p>像什么重物砸在地板上。</p>
          </div>
        </div>
      ) : null}

      {dialogueLog.length === 0 ? (
        <div style={{ textAlign: "center", padding: "80px 20px" }}>
          {loading ? (
            <div style={{ fontSize: "15px", color: "#94a3b8" }}>正在生成故事...</div>
          ) : (
            <button onClick={startStory} className="frosty-text start-btn">start</button>
          )}
        </div>
      ) : (
        visibleDialogues.map((msg: any, index: number) => {
          const isLastVisible = index === visibleDialogues.length - 1;
          const speakerName = msg.speakerName || msg.name || "未知角色";
          // 历史对话直接展示，不打字机；仅实时新对话使用打字机
          const shouldTypewrite = isLastVisible && !msg.fromHistory;
          return (
            <div key={msg.id || `dialogue-${index}`} id={`msg-${msg.id}`}>
              <DialogueItem
                name={speakerName}
                avatar={getAgentAvatar(speakerName, msg.speakerId)}
                thought={msg.thought}
                action={msg.content || msg.action || ""}
                emotion={msg.emotion}
                isPlayer={msg.speakerId === "player_01" || speakerName.includes("玩家")}
                useTypewriter={shouldTypewrite}
                paused={isPaused}
                onComplete={shouldTypewrite ? advanceDialogue : undefined}
              />
            </div>
          );
        })
      )}
    </div>
  );
}
