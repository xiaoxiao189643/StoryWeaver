// ============================================================
// src/core/GameState.ts —— 前端本地核心运行时状态管理
// 100% 对齐框架层终极版接口文档
// ============================================================
import { AgentStateData, NarrativeEventData } from "../types/api";

export interface GameStateSnapshot {
  tick: number;
  time: any | null;   // 兼容后端的字典结构，例如 { hour: 18, minute: 30 }
  tension: number;
  background: string; // 对应 setup:outline 的 background
  summary: string;    // 对应 setup:outline 的 summary
  initialQuest: string; // ✨ 新增：对应 setup:outline 的 initial_quest
  directorPrompt: string; // 导演当前的场景旁白
  npcs: AgentStateData[];
  isPaused: boolean;
  isViewingHistory: boolean;
  viewingTick: number;
}

class GameState {
  private tick: number = 0;
  private time: any | null = null;
  private tension: number = 0;
  private background: string = "";
  private summary: string = "";
  private initialQuest: string = ""; // ✨ 新增
  private isPaused: boolean = false;
  private directorPrompt: string = ""; // 导演当前场景旁白

  private npcs: Map<string, AgentStateData> = new Map();
  private dialogueLog: any[] = [];
  private narrativeEvents: NarrativeEventData[] = [];
  private interventionFeedback: { success: boolean; effectiveness: number; message: string; tick?: number } | null = null;
  private pendingJumpTick: number = 0;
  private isViewingHistory: boolean = false;
  private viewingTick: number = 0;

  // 1. 初始化世界大纲设定（完全对齐 setup:outline 事件负载）
  public initializeOutline(background: string, summary: string, initialQuest?: string) {
    this.background = background || this.background;
    this.summary = summary || this.summary;
    if (initialQuest) {
      this.initialQuest = initialQuest;
    }
  }

  public initializeSnapshot(data: any) {
    if (!data) return;
    if (data.world_state) this.applyWorldUpdate(data.world_state);
    if (Array.isArray(data.agents)) {
      data.agents.forEach((agent: AgentStateData) => this.updateAgentState(agent));
    }
    this.initializeOutline(data.background, data.summary, data.initial_quest);
  }

  // 2. 接收下行时钟广播同步 (完全对齐 world_state 事件负载)
  public applyWorldUpdate(data: { tick: number; time: any; tension: number }) {
    if (data.tick !== undefined) this.tick = data.tick;
    if (data.time !== undefined) this.time = data.time;
    if (data.tension !== undefined) this.tension = data.tension;
  }

  // 3. 接收下行 NPC 属性差量校准 (完全对齐 agent_state 事件负载)
  public updateAgentState(data: any) {
    if (!data.agentId) return;
    // 使用差量合并：只更新后端下发变更了的字段（如只更新 emotion），保留其他字段不变
    const existing = this.npcs.get(data.agentId) || {} as AgentStateData;
    this.npcs.set(data.agentId, { ...existing, ...data });
  }

  // 4. 追加文本对话气泡记录 (对应 dialogue 事件)，按 id 去重
  public addDialogue(dialogue: any) {
    if (this.isViewingHistory && !dialogue?.fromHistory) return;
    const id = dialogue?.id;
    if (id && this.dialogueLog.some((d: any) => d.id === id)) return;
    this.dialogueLog.push(dialogue);
  }

  // 5. 追加叙事大纲事件 (对应 narrative_event 事件)
  public addNarrativeEvent(event: NarrativeEventData) {
    this.narrativeEvents.push(event);
  }

  public setPaused(paused: boolean) {
    this.isPaused = paused;
  }

  public setDirectorPrompt(prompt: string) {
    if (prompt) this.directorPrompt = prompt;
  }

  public setInterventionFeedback(feedback: { success: boolean; effectiveness: number; narrative_response: string; tick?: number }) {
    this.interventionFeedback = {
      success: feedback.success,
      effectiveness: feedback.effectiveness,
      message: feedback.narrative_response,
      tick: feedback.tick,
    };
  }
  public getInterventionFeedback() { return this.interventionFeedback; }
  public clearInterventionFeedback() { this.interventionFeedback = null; }

  public setPendingJumpTick(tick: number) { this.pendingJumpTick = tick; }
  public getPendingJumpTick(): number { return this.pendingJumpTick; }
  public startHistoryView(tick: number) { this.isViewingHistory = true; this.viewingTick = tick; }
  public exitHistoryView() { this.isViewingHistory = false; this.viewingTick = 0; }
  public isInHistoryView(): boolean { return this.isViewingHistory; }
  public getViewingTick(): number { return this.viewingTick; }

  // ── 提供给组件层消费的只读探针 ──
  public getSnapshot(): GameStateSnapshot {
    return {
      tick: this.tick,
      time: this.time,
      tension: this.tension,
      background: this.background,
      summary: this.summary,
      initialQuest: this.initialQuest, // ✨ 对齐输出
      directorPrompt: this.directorPrompt,
      npcs: Array.from(this.npcs.values()),
      isPaused: this.isPaused,
      isViewingHistory: this.isViewingHistory,
      viewingTick: this.viewingTick,
    };
  }

  public getDialogueLog() { return this.dialogueLog; }
  public getNarrativeEvents() { return this.narrativeEvents; }

  // ── 时间线跳转：清空对话记录 ──
  public clearDialogueLog() {
    this.dialogueLog = [];
  }
  public clearNarrativeEvents() {
    this.narrativeEvents = [];
  }
}

export const gameState = new GameState();