// ============================================================
// src/core/EventBus.ts —— 核心事件总线
// 负责在 WebSocketClient 接收框架层事件后，将事件跨组件分发给 UI
// (支持文档中定义的所有 15 种下行广播事件的无缝路由)
// ============================================================

type Listener = (...args: any[]) => void;

export class EventBus {
  private listeners: Map<string, Set<Listener>> = new Map();

  /** 订阅事件 (UI组件中使用) */
  on(event: string, fn: Listener): () => void {
    if (!this.listeners.has(event)) {
      this.listeners.set(event, new Set());
    }
    this.listeners.get(event)!.add(fn);

    // 返回取消订阅函数，供 useEffect cleanup 使用
    return () => {
      this.listeners.get(event)?.delete(fn);
    };
  }

  /** 取消订阅 */
  off(event: string, fn: Listener): void {
    this.listeners.get(event)?.delete(fn);
  }

  /** 触发事件 (WebSocketClient 中使用) */
  emit(event: string, ...args: any[]): void {
    this.listeners.get(event)?.forEach((fn) => fn(...args));
  }

  /** 清空所有订阅 (切换剧本或销毁时使用) */
  clear(): void {
    this.listeners.clear();
  }
}

/** 全局唯一总线实例 */
export const globalEventBus = new EventBus();