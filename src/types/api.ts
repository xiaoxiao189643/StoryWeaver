// ============================================================
// types/api.ts —— 前后端 API 通信类型 (纯文本无空间终极版)
// ============================================================

// ── WebSocket 消息类型 (type) ──
export enum WSMessageType {
  // --- 基础流 (PVE核心) ---
  SETUP_OUTLINE = "setup:outline",             // 后端推送：下发世界背景与定制梗概
  STORY_INITIALIZED = "story:initialized",     // 后端推送：故事宇宙就绪，进入剧本
  DIALOGUE = "dialogue",                       // 后端推送：常规全量对话（备用）
  DIALOGUE_TOKEN_STREAM = "dialogue:token_stream", // 后端推送：LLM 流式逐字高频推送
  DIRECTOR_PROMPT = "director:prompt",         // 后端推送：导演场景旁白
  WORLD_STATE = "world_state",                 // 后端推送：世界 Tick 与时钟更新
  AGENT_STATE = "agent_state",                 // 后端推送：NPC 状态/好感度属性变更
  NARRATIVE_EVENT = "narrative_event",         // 后端推送：核心大纲黑天鹅事件爆发

  // --- 控制流 (时空操控) ---
  GAME_CONTROL = "game:control",               // 上行/下行：引擎时钟锁定/恢复控制
  STORY_ROLLBACK_RESULT = "story:rollback_result", // 后端推送：时光回溯重置完毕响应

  // --- 沉浸流 (跨媒体调度) ---
  SYSTEM_SKILL_CHECK = "system:skill_check",   // 后端推送：跑团暗骰因果律检定
  DIRECTOR_ATMOSPHERE = "director:atmosphere", // 后端推送：视听氛围环境多媒体调度
  STORY_SETTLEMENT = "story:settlement",       // 后端推送：章节大纲收束结算
  INTERVENTION_RESULT = "intervention_result", // 后端推送：玩家文本干预即时算法反馈

  // --- 客户端主动发送的上行指令 ───
  SETUP_START_GENERATION = "setup:start_generation", // 前端发送：玩家确认梗概，一键启动
  PLAYER_INTERVENTION = "player:intervention",       // 前端发送：神谕纯文本指令干预
  STORY_ROLLBACK = "story:rollback",                 // 前端发送：时光分歧点倒流回溯
  TIMELINE_JUMP = "timeline:jump",                   // 前端发送：时间线跳转到指定 tick
  TIMELINE_JUMP_RESULT = "timeline:jump_result",     // 后端推送：跳转完成
  PING = "ping",                                     // 前端发送：通道长连接保活心跳
  PONG = "pong",                                     // 后端回复：心跳响应
}

// ── WebSocket 通用包裹格式 ──
export interface WSMessage<T = Record<string, any>> {
  type: WSMessageType;
  data: T;
}

// ── 下行核心数据状态负载结构 ──
export interface WorldStateData {
  tick: number;
  time: {
    day: number;
    hour: number;
    minute: number;
  };
  tension: number; // 紧张度等级
}

export interface AgentStateData {
  id: string;
  agentId: string;
  name: string;
  state: string;       // 文学级剧情动作状态描述
  emotion: string;     // 主导情绪状态机标签
  trustPlayer: number; // 对玩家的信任度进度条 (-1.0 ~ 1.0)
  x?: number;
  y?: number;
  location?: string;
  locationName?: string;
}

export interface DialogueTokenStreamData {
  msg_id: string;
  speakerId: string;
  token: string;
  is_thought: boolean; // 标识是否为角色内心独白戏
  is_end: boolean;     // 流式吐字落闸哨兵
}

export interface DialogueData {
  id: string;
  speakerId: string;
  speakerName: string;
  thought: string;     // 心理描述文本
  content: string;     // 台词口白文本
  emotion: string;
}

export interface NarrativeEventData {
  tick: number;
  event_type: string;
  description: string;
  timestamp: number;
}

// ── REST API 响应模型结构 ──
export interface StorySessionResponse {
  id: string;
  title: string;
  userPrompt: string;
  status: string;
  background: string; // 创世生成的专属精炼世界观背景文本
  summary: string;    // 当前会话的全局核心戏剧冲突与剧情大纲
}

export interface DirectorOutlineResponse {
  theme: string;
  background: string;
  main_conflict: string;
  world_parameters: Record<string, string>; // 名词别名映射字典（江湖结交度/杀气值）
}

export interface AgentBeliefResponse {
  agentId: string;
  knownFacts: string[];
  suspicions: string[]; // 揣测同伴产生的真实怀疑权重列表
  secrets: string[];    // 深度隐藏背景卷宗
  misconceptions: string[];
}

// ── 时间线 ──
export interface TimelineNodeData {
  node_id: string;
  tick: number;
  title: string;
  summary: string;
  tension: string;
  key_events: string[];
}

export interface TimelineTreeData {
  nodes: TimelineNodeData[];
  current_tick: number;
  snapshot_ticks: number[];
  total_nodes: number;
}

export interface TimelineJumpResult {
  success: boolean;
  mode?: "view" | "rewrite";
  current_tick?: number;
  target_tick?: number;
  available_tick?: number;
  message?: string;
}
