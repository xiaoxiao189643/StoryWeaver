// ============================================================
// useGameState.ts —— 将无房间文本叙事状态及高级控制流安全切入 React
// ============================================================
import { useEffect, useState } from "react";
import { gameState, GameStateSnapshot } from "../../core/GameState";
import { globalEventBus } from "../../core/EventBus";
import { WSMessageType } from "../../types/api";
import type { AgentStateData, NarrativeEventData } from "../../types/api";

export function useGameState(): GameStateSnapshot {
  const [snap, setSnap] = useState<GameStateSnapshot>(() => gameState.getSnapshot());

  useEffect(() => {
    const refresh = () => setSnap(gameState.getSnapshot());

    const unsubs = [
      globalEventBus.on(WSMessageType.WORLD_STATE, refresh),
      globalEventBus.on(WSMessageType.AGENT_STATE, refresh),
      globalEventBus.on(WSMessageType.DIRECTOR_ATMOSPHERE, refresh),
      globalEventBus.on(WSMessageType.STORY_SETTLEMENT, refresh),
      globalEventBus.on(WSMessageType.STORY_INITIALIZED, refresh),
      globalEventBus.on(WSMessageType.GAME_CONTROL, refresh),
      globalEventBus.on(WSMessageType.SETUP_OUTLINE, refresh),
      globalEventBus.on("timeline:view_feed", refresh),
      globalEventBus.on("timeline:rewrite_feed", refresh)
    ];

    return () => unsubs.forEach((fn) => fn());
  }, []);

  return snap;
}

export function useNPCs(): AgentStateData[] {
  const [npcs, setNpcs] = useState<AgentStateData[]>(() => gameState.getSnapshot().npcs);

  useEffect(() => {
    const refresh = () => setNpcs(gameState.getSnapshot().npcs);
    const unsubs = [
      globalEventBus.on(WSMessageType.AGENT_STATE, refresh),
      globalEventBus.on(WSMessageType.WORLD_STATE, refresh)
    ];
    return () => unsubs.forEach((fn) => fn());
  }, []);

  return npcs;
}

export function useDialogueLog(): any[] {
  const [log, setLog] = useState<any[]>(() => gameState.getDialogueLog());

  useEffect(() => {
    const refresh = () => setLog([...gameState.getDialogueLog()]);
    const unsubs = [
      globalEventBus.on(WSMessageType.DIALOGUE, refresh),
      globalEventBus.on(WSMessageType.DIALOGUE_TOKEN_STREAM, refresh),
      globalEventBus.on(WSMessageType.DIRECTOR_PROMPT, refresh)
    ];
    return () => unsubs.forEach((fn) => fn());
  }, []);

  return log;
}

export function useNarrativeEvents(): NarrativeEventData[] {
  const [events, setEvents] = useState<NarrativeEventData[]>(() => gameState.getNarrativeEvents());

  useEffect(() => {
    const refresh = () => setEvents([...gameState.getNarrativeEvents()]);
    const unsubs = [
      globalEventBus.on(WSMessageType.NARRATIVE_EVENT, refresh),
      globalEventBus.on(WSMessageType.STORY_SETTLEMENT, refresh),
      globalEventBus.on(WSMessageType.STORY_ROLLBACK_RESULT, refresh)
    ];
    return () => unsubs.forEach((fn) => fn());
  }, []);

  return events;
}