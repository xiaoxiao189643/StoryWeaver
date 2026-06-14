// ============================================================
// src/main.tsx —— 纯文本框架前端入口点
// ============================================================
import ReactDOM from "react-dom/client";
import { App } from "./App";
import { wsClient } from "./core/WebSocketClient";
import { gameState } from "./core/GameState";
import { globalEventBus } from "./core/EventBus";
import { ApiClient } from "./core/ApiClient";

// 先挂载 React，再异步拉取后端数据，避免白屏阻塞
const rootElement = document.getElementById("react-root");
if (rootElement) {
  ReactDOM.createRoot(rootElement).render(<App />);
}

// 异步初始化：拉取快照 + 历史对话 + 建立 WebSocket
async function init() {
  try {
    const data = await ApiClient.initWorldSnapshot("default_world");
    if (data) {
      gameState.initializeSnapshot(data);
      // 通知 React hooks：角色数据、世界状态已就绪
      globalEventBus.emit("world_state", data.world_state || {});
      if (Array.isArray(data.agents)) {
        data.agents.forEach((a: any) => globalEventBus.emit("agent_state", a));
      }
    }
  } catch (error) {
    console.warn("[系统提示] 冷启动拉取世界快照失败，等待 WebSocket 推送...", error);
  }

  // 加载历史对话，保证刷新后故事不丢失（一次性加载全部，后端按 tick 升序返回）
  try {
    const res = await fetch("http://localhost:8000/feed/all");
    const items = await res.json();
    if (Array.isArray(items) && items.length > 0) {
      const existing = new Set<string>();
      for (const item of items) {
        const contentKey = (item.content || "").slice(0, 50).replace(/[^a-zA-Z0-9一-鿿]/g, "");
        const id = `hist_${item.tick}_${item.agent_id}_${contentKey}`;
        if (existing.has(id)) continue;
        existing.add(id);
        let text = item.content || "";
        const m = text.match(/：「(.+?)」/);
        gameState.addDialogue({
          id,
          speakerId: item.agent_id,
          speakerName: item.agent_name || item.agent_id,
          content: m ? m[1] : text.replace(/^我/, ""),
          tick: item.tick,
          fromHistory: true,
          emotion: item.emotion || "neutral",
          actionType: item.actionType || "",
          thought: item.thought || "",
        });
      }
    }
    // 通知 hooks 数据已更新
    globalEventBus.emit("dialogue", {});
  } catch (e) {
    console.warn("[系统提示] 加载历史对话失败", e);
  }

  // 历史对话加载完成后自动恢复 tick 循环
  try {
    await fetch("http://localhost:8000/story/resume", { method: "POST" });
  } catch (e) {
    console.warn("[系统提示] 自动恢复故事失败", e);
  }

  wsClient.connect();
}

init();