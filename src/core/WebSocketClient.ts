// ============================================================
// src/core/WebSocketClient.ts —— 实时因果长连接信道管理
// 100% 对齐框架层终极版接口文档 (涵盖下行广播与上行指令)
// ============================================================
import { globalEventBus } from "./EventBus";
import { gameState } from "./GameState";
import { WSMessage } from "../types/api";

export class WebSocketClient {
  private ws: WebSocket | null = null;
  private url: string;
  private reconnectTimer: number | null = null;
  private heartbeatTimer: number | null = null;
  private lastTick: number = 0;

  constructor(baseUrl: string = "ws://localhost:8000/ws", worldId: string = "default_world") {
    this.url = `${baseUrl}?world_id=${worldId}`;
  }

  public connect() {
    console.log("[WebSocket] 建立纯文本长连接...", this.url);
    this.ws = new WebSocket(this.url);

    this.ws.onopen = () => {
      console.log("[WebSocket] 通道连接成功！");
      if (this.reconnectTimer) { clearInterval(this.reconnectTimer); this.reconnectTimer = null; }
      this.startHeartbeat();
      
      // [✨控制流·同步重连] 断线重连时，前端上报本地最后 Tick 请求补偿
      if (this.lastTick > 0) {
        this.send("sync_request", { lastTick: this.lastTick });
      }
    };

    this.ws.onmessage = (event) => {
      try {
        // 根据协议，长连接不再包裹 code/message
        const msg = JSON.parse(event.data) as WSMessage;
        this.handleMessage(msg);
      } catch (e) {
        console.error("[WebSocket] 数据解析异常", e);
      }
    };

    this.ws.onclose = () => {
      this.stopHeartbeat();
      this.scheduleReconnect();
    };
  }

  /**
   * 100% 对齐文档 3.1: 框架层下行广播 (Server -> Client)
   */
  private handleMessage(msg: WSMessage) {
    if (msg.type === "world_state" && msg.data.tick) {
      this.lastTick = msg.data.tick;
    }

    const msgType = msg.type as string;

    switch (msgType) {
      // ✅ 基础流：大纲直发与宇宙就绪
      case "setup:outline":
        gameState.initializeOutline(msg.data.background, msg.data.summary, msg.data.initial_quest);
        break;
      case "story:initialized":
        console.log("[System] 故事宇宙加载就绪与引擎时钟唤醒:", msg.data.message);
        break;

      // ✅ 基础流：世界属性与NPC差量更新
      case "world_state":
        gameState.applyWorldUpdate(msg.data as any);
        break;
      case "agent_state":
        gameState.updateAgentState(msg.data as any);
        break;

      // ✅ 基础流：流式说话与全量对话
      case "dialogue:token_stream":
        // 由底部泛发 emit，此处不做重复
        break;
      case "dialogue":
        gameState.addDialogue(msg.data as any);
        // 由底部泛发 emit，此处不做重复
        break;
      case "director:prompt":
        if (msg.data?.content) {
          gameState.setDirectorPrompt(msg.data.content);
          // 如果旁白还未出现在对话日志中，追加一条导演旁白条目
          const existingIds = new Set(gameState.getDialogueLog().map((d: any) => d.id));
          const narrationId = `narration_ws_${msg.data.tick || 0}`;
          if (!existingIds.has(narrationId) && msg.data.content) {
            gameState.addDialogue({
              id: narrationId,
              speakerId: "director",
              speakerName: "旁白",
              content: msg.data.content,
              tick: msg.data.tick || 0,
              emotion: "neutral",
              actionType: "narration",
              thought: "",
            });
          }
        }
        break;

      // ✅ 叙事流：大纲事件与章节结算
      case "narrative_event":
        gameState.addNarrativeEvent(msg.data as any);
        break;
      case "story:settlement":
        console.log("[Story] 章节冲突已收束，时钟挂起", msg.data);
        break;

      // ✅ 沉浸流：视听氛围调度与暗骰检定
      case "director:atmosphere":
        console.log("[Director] 氛围调度:", msg.data);
        break;
      case "system:skill_check":
        break;

      // ✅ 玩家干预反馈
      case "intervention_result":
        gameState.setInterventionFeedback(msg.data as any);
        break;

      // ✅ 控制流：时钟控制反向广播与时空回溯响应
      case "story:rollback_result":
        console.log("[System] 时空已成功重塑至:", msg.data.current_tick);
        break;

      // ✅ 时间线跳转：按模式触发历史回看或分支重写
      case "timeline:jump_result":
        if (msg.data.success) {
          const mode = (msg.data as any).mode || "rewrite";
          const targetTick = (msg.data as any).target_tick ?? (msg.data as any).current_tick;
          console.log("[Timeline] 跳转成功:", mode, targetTick);
          gameState.clearDialogueLog();
          gameState.clearNarrativeEvents();
          if (mode === "view") {
            gameState.startHistoryView(targetTick);
            globalEventBus.emit("timeline:view_feed", msg.data);
          } else {
            gameState.exitHistoryView();
            globalEventBus.emit("timeline:rewrite_feed", msg.data);
          }
        }
        break;
      case "game:control":
        gameState.setPaused(Boolean((msg.data as any).paused));
        console.log("[System] 时钟引擎收到状态反向广播:", msg.data);
        break;
        
      case "pong":
        // 心跳回包，无需特殊处理
        break;
    }

    // 无论如何，均通过总线往外抛一份，供特定 React 组件自行订阅
    globalEventBus.emit(msgType, msg.data);
  }

  /**
   * 底层发送包装器
   */
  private send(type: string, data: any) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      console.warn(`[WebSocket] 无法发送 "${type}" — 连接未就绪 (readyState=${this.ws ? this.ws.readyState : 'null'})`);
      return;
    }
    this.ws.send(JSON.stringify({ type, data }));
  }

  // ============================================================
  // 100% 对齐文档 3.2: 前端上行指令 (Client -> Server)
  // ============================================================

  // 1. [一键启动] 玩家确认大纲无误，全面挂载引擎时钟
  public startGameGeneration() {
    this.send("setup:start_generation", { text: "开始生成" });
  }

  // 2. [干预投递] 底部控制台自由文本干预指令
  public sendIntervention(target: string, type: string, content: string) {
    this.send("player:intervention", {
      content: content,
      type: type,
      target_agent_id: target,
      player_id: "player_01",
    });
  }

  // 3. [时钟控制] 玩家要求锁定/恢复物理与逻辑时针
  public setGameControl(action: "pause" | "resume") {
    this.send("game:control", { action });
  }

  // 4. [分歧回溯] 时空分歧点倒流重塑（保留兼容，内部走 timeline:jump）
  public rollbackStory(targetTick: number, _chapterId: string) {
    this.jumpToTick(targetTick);
  }

  // 5. [时间线跳转] 跳转到指定 tick
  public jumpToTick(tick: number, mode: "view" | "rewrite" = "rewrite") {
    this.send("timeline:jump", { tick, mode });
  }

  // --- 心跳保活逻辑 ---
  private startHeartbeat() {
    this.heartbeatTimer = window.setInterval(() => {
      // 5. [心跳保活] 定期投递维持长连接
      this.send("ping", {});
    }, 30000);
  }
  
  private stopHeartbeat() { 
    if (this.heartbeatTimer) clearInterval(this.heartbeatTimer); 
  }
  
  private scheduleReconnect() {
    if (!this.reconnectTimer) this.reconnectTimer = window.setInterval(() => this.connect(), 5000);
  }
}

// 暴露出全局单例
export const wsClient = new WebSocketClient("ws://localhost:8000/ws", "default_world");