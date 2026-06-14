// ============================================================
// src/core/ApiClient.ts —— 封装所有 REST API 请求 (框架层网关版)
// 100% 对标全小写中划线名词路径，以及 {code, data, message} 统一结构
// ============================================================
import { DirectorOutlineResponse, AgentBeliefResponse, StorySessionResponse } from "../types/api";

export const API_BASE_URL = "http://localhost:8000";

/**
 * 统一请求拦截与外壳脱除包装器
 * 自动处理后端的 { code, data, message } 结构
 */
async function fetchWrap<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(url, options);
  if (!res.ok) {
    throw new Error(`网络请求失败 [Status: ${res.status}]`);
  }
  
  const json = await res.json();
  
  // 按照接口文档约定：code 为 0 代表成功
  if (json.code !== 0) {
    throw new Error(json.message || "后端业务处理异常");
  }
  
  // 剥离外壳，直接向业务层返回干净的 data
  return json.data as T;
}

export class ApiClient {
  // ── 1. 故事会话与归档管理 (Story Sessions) ──

  static async getStorySessions(userId: string) {
    return fetchWrap<any[]>(`${API_BASE_URL}/users/${userId}/story-sessions`);
  }

  static async createSession(userPrompt: string) {
    return fetchWrap<any>(`${API_BASE_URL}/story-sessions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_prompt: userPrompt }),
    });
  }

  static async getSession(sessionId: string) {
    return fetchWrap<StorySessionResponse>(`${API_BASE_URL}/story-sessions/${sessionId}`);
  }

  static async getSessionChapters(sessionId: string) {
    return fetchWrap<any[]>(`${API_BASE_URL}/story-sessions/${sessionId}/chapters`);
  }

  static async getSessionEvents(sessionId: string, limit: number = 50) {
    return fetchWrap<any[]>(`${API_BASE_URL}/story-sessions/${sessionId}/events?limit=${limit}`);
  }

  // ── 2. 世界沙盒与推演交互 (Worlds & Interventions) ──

  static async initWorldSnapshot(worldId: string) {
    return fetchWrap<any>(`${API_BASE_URL}/worlds/${worldId}/snapshot`);
  }

  static async getWorldState(worldId: string) {
    return fetchWrap<any>(`${API_BASE_URL}/worlds/${worldId}/state`);
  }

  static async intervene(worldId: string, target: string, action: string, content: string) {
    return fetchWrap<any>(`${API_BASE_URL}/worlds/${worldId}/interventions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ target, action, content }),
    });
  }

  static async getDialogueHistory(worldId: string, limit: number = 50, from: string = "") {
    let url = `${API_BASE_URL}/worlds/${worldId}/dialogues?limit=${limit}`;
    if (from) url += `&from=${from}`;
    return fetchWrap<any>(url);
  }

  // ── 3. 智能体深度探测 (Agents) ──

  static async getAgentList(worldId: string) {
    return fetchWrap<any[]>(`${API_BASE_URL}/worlds/${worldId}/agents`);
  }

  static async getAgentDetail(worldId: string, agentId: string) {
    return fetchWrap<any>(`${API_BASE_URL}/worlds/${worldId}/agents/${agentId}`);
  }

  static async getAgentRelationships(worldId: string, agentId: string) {
    return fetchWrap<any>(`${API_BASE_URL}/worlds/${worldId}/agents/${agentId}/relationships`);
  }

  static async getAgentBelief(worldId: string, agentId: string) {
    return fetchWrap<AgentBeliefResponse>(`${API_BASE_URL}/worlds/${worldId}/agents/${agentId}/beliefs`);
  }

  // ── 4. 导演引擎监控 (Director) ──

  static async getDirectorOutline(worldId: string) {
    return fetchWrap<DirectorOutlineResponse>(`${API_BASE_URL}/worlds/${worldId}/director/outline`);
  }

  static async getDirectorStatus(worldId: string) {
    return fetchWrap<any>(`${API_BASE_URL}/worlds/${worldId}/director/status`);
  }

  static async getUpcomingEvents(worldId: string) {
    return fetchWrap<any[]>(`${API_BASE_URL}/worlds/${worldId}/director/upcoming-events`);
  }
}