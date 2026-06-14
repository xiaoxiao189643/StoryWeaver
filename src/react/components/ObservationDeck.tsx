import { useState, useEffect, useMemo } from "react";
import { ApiClient } from "../../core/ApiClient";
import { globalEventBus } from "../../core/EventBus";
import { useGameState, useNPCs } from "../hooks/useGameState";
import { getAgentAvatar } from "../utils/agentPresentation";

const TRAIT_NAMES: Record<string, string> = {
  openness: "开放",
  conscientiousness: "尽责",
  extraversion: "外向",
  agreeableness: "宜人",
  neuroticism: "情绪",
};

const EMOTION_CN: Record<string, string> = {
  calm: "平静",
  neutral: "平静",
  anxious: "焦虑",
  nervous: "紧张",
  suspicious: "怀疑",
  angry: "愤怒",
  sad: "悲伤",
  excited: "兴奋",
  scared: "恐惧",
};

export function ObservationDeck() {
  const { tension, summary, background } = useGameState();
  const npcs = useNPCs();
  const [agentDetails, setAgentDetails] = useState<Record<string, any>>({});
  const [agentRelations, setAgentRelations] = useState<Record<string, any[]>>({});
  const [isExpanded, setIsExpanded] = useState<Record<string, boolean>>({});

  // 合并 gameState NPC 数据和 API 数据
  const [apiAgents, setApiAgents] = useState<any[]>([]);
  useEffect(() => {
    ApiClient.getAgentList("default_world").then(res => {
      if (Array.isArray(res)) setApiAgents(res);
    }).catch(() => {});
    const unsub = globalEventBus.on("agent_state", (data: any) => {
      if (!data?.agentId) return;
      setApiAgents(prev => prev.map(a => a.id === data.agentId || a.agentId === data.agentId ? { ...a, ...data } : a));
    });
    return () => unsub();
  }, []);

  // 优先用 API 数据，降级用快照 NPC 数据
  const agents = useMemo(() => {
    if (apiAgents.length > 0) return apiAgents;
    return npcs.map(n => ({ id: n.id || n.agentId, agentId: n.agentId || n.id, name: n.name, emotion: n.emotion || "neutral", state: n.state || "待机", trustPlayer: n.trustPlayer || 50, location: n.location, locationName: n.locationName }));
  }, [apiAgents, npcs]);

  // ID → 名字映射（用于关系显示）
  const idToName = useMemo(() => {
    const map: Record<string, string> = {};
    for (const a of agents) {
      map[a.id] = a.name;
      if (a.agentId) map[a.agentId] = a.name;
    }
    return map;
  }, [agents]);

  // 初始化展开状态
  useEffect(() => {
    if (agents.length > 0) {
      setIsExpanded(prev => {
        const next = { ...prev };
        agents.forEach(a => { if (!(a.id in next)) next[a.id] = false; });
        return next;
      });
    }
  }, [agents.length]);

  const toggleExpand = (id: string) => {
    setIsExpanded(prev => {
      const next = !prev[id];
      if (next && !agentDetails[id]) {
        const worldId = "default_world";
        ApiClient.getAgentDetail(worldId, id)
          .then(d => setAgentDetails(prev => ({ ...prev, [id]: d || {} })))
          .catch(() => {});
        ApiClient.getAgentRelationships(worldId, id)
          .then(r => {
            if (r?.relationships) setAgentRelations(prev => ({ ...prev, [id]: r.relationships }));
          }).catch(() => {});
      }
      return { ...prev, [id]: next };
    });
  };

  return (
    <div className="sidebar-inner">
      <div className="sidebar-main-title frosty">故事详情</div>

      {/* 世界状态 */}
      <div className="section-divider world-section-title frosty">世界状态</div>
      <div className="story-bg-card world-state-card profile-container world-profile-card" style={{ padding: '14px' }}>
        <div className="entity-row world-state-header">
          <span className="entity-label world-metric-label">紧张度</span>
          <span className="world-metric-value" style={{ fontWeight: 800, color: tension >= 75 ? '#ef4444' : '#3b82f6', marginLeft: 'auto' }}>
            {tension || 0}%
          </span>
        </div>
        {summary && (
          <div className="world-summary-block" style={{ marginTop: '10px' }}>
            <div className="world-summary-title" style={{ fontSize: '12px', color: '#64748b', marginBottom: '4px' }}>主线</div>
            <div className="world-summary-text" style={{ fontSize: '13px', color: '#475569', lineHeight: 1.5 }}>{summary}</div>
          </div>
        )}
        {background && (
          <div className="world-background-text" style={{ marginTop: '8px', fontSize: '11px', color: '#94a3b8', fontStyle: 'italic' }}>
            {background}
          </div>
        )}
      </div>

      {/* NPC 列表 */}
      <div className="section-divider frosty">角色</div>

      {agents.length === 0 ? (
        <div style={{ color: 'white', fontSize: '13px', textAlign: 'center', padding: '24px' }}>
          等待角色登场...
        </div>
      ) : (
        agents.map(agent => {
          const detail = agentDetails[agent.id] || {};
          const relations = agentRelations[agent.id] || [];
          const trust = Math.round(agent.trustPlayer || 50);
          const personality = detail.personality ? Object.entries(detail.personality) : [];

          return (
            <div key={agent.id} className={`entity-card profile-container ${isExpanded[agent.id] ? 'expanded-card' : ''}`}>

              {/* 卡片头 */}
              <div className="entity-header clickable-header profile-left" onClick={() => toggleExpand(agent.id)}
                   style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '14px', cursor: 'pointer' }}>
                <div className="profile-left-head" style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                  <div className="profile-avatar-box avatar-small" style={{ background: '#fff', border: '1.5px solid #d1d5db' }}>
                    <span className="profile-avatar-symbol" style={{ fontSize: '18px', fontWeight: 700, color: '#1f2937' }}>{getAgentAvatar(agent.name, agent.id)}</span>
                  </div>
                  <div className="profile-identity">
                    <div className="char-name" style={{ fontWeight: 800, fontSize: '15px' }}>{agent.name}</div>
                    <div className="char-status" style={{ fontSize: '12px', color: '#94a3b8' }}>
                      {EMOTION_CN[agent.emotion] || agent.emotion || '平静'}
                    </div>
                  </div>
                </div>
                <span className="expand-icon" style={{ color: '#94a3b8', fontSize: '10px', transition: 'transform 0.2s', transform: isExpanded[agent.id] ? 'rotate(180deg)' : 'none' }}>
                  ▼
                </span>
              </div>

              {/* 展开详情 */}
              {isExpanded[agent.id] && (
                <div className="profile-right" style={{ padding: '0 14px 14px', animation: 'fadeIn 0.2s ease-out' }}>

                  {/* 角色介绍 */}
                  {detail.motivation && (
                    <div className="char-biography" style={{ fontSize: '13px', color: '#475569', lineHeight: 1.6, marginBottom: '12px', padding: '10px', background: '#f8fafc', borderRadius: '8px', borderLeft: '3px solid #3b82f6' }}>
                      {detail.motivation}
                    </div>
                  )}

                  {/* 信任度 */}
                  <div className="trust-wrapper" style={{ marginBottom: '12px' }}>
                    <div className="trust-header" style={{ display: 'flex', justifyContent: 'space-between', fontSize: '13px', marginBottom: '4px' }}>
                      <span className="trust-label" style={{ color: '#64748b' }}>信任度</span>
                      <span className="trust-value" style={{ fontWeight: 800, color: trust >= 70 ? '#10b981' : trust >= 40 ? '#f59e0b' : '#ef4444' }}>{trust}%</span>
                    </div>
                    <div className="trust-bar-bg" style={{ height: '6px', background: '#e5e7eb', borderRadius: '3px', overflow: 'hidden' }}>
                      <div className="trust-bar-fill" style={{ height: '100%', width: `${trust}%`, background: trust >= 70 ? '#10b981' : trust >= 40 ? '#f59e0b' : '#ef4444', borderRadius: '3px', transition: 'width 0.3s' }} />
                    </div>
                  </div>

                  {/* 目标与动机 */}
                  <div className="data-section-title bio-title" style={{ margin: '10px 0 4px' }}>目标</div>
                  <div className="goal-box bio-text">
                    <div className="goal-text">{detail.goal || '暂无'}</div>
                  </div>

                  <div className="data-section-title bio-title" style={{ margin: '10px 0 4px' }}>性格</div>
                  <div className="personality-matrix" style={{ marginBottom: '8px' }}>
                    {personality.length > 0 ? (
                      personality.map(([trait, value]) => {
                        const pct = Number(value);
                        return (
                          <div key={trait} className="trait-row" style={{ marginBottom: '6px' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px', marginBottom: '2px' }}>
                              <span className="trait-name" style={{ color: '#64748b' }}>{TRAIT_NAMES[trait] || trait}</span>
                              <span className="trait-val" style={{ fontWeight: 700, color: '#475569' }}>{pct}</span>
                            </div>
                            <div className="trait-bar-bg" style={{ height: '4px', background: '#e5e7eb', borderRadius: '2px', overflow: 'hidden' }}>
                              <div className="trait-bar-fill" style={{ height: '100%', width: `${pct}%`, background: '#3b82f6', borderRadius: '2px' }} />
                            </div>
                          </div>
                        );
                      })
                    ) : (
                      <div className="bio-text">暂无</div>
                    )}
                  </div>

                  {/* 对其他角色的看法（补全所有角色对，未互动过默认中立） */}
                  <div className="bio-title" style={{ margin: '10px 0 4px' }}>对他人的看法</div>
                  {(() => {
                    const otherAgents = agents.filter(a => a.id !== agent.id && (a.agentId || a.id) !== agent.id);
                    const relMap: Record<string, any> = {};
                    for (const r of relations) relMap[r.targetId] = r;

                    return otherAgents.map((other) => {
                      const rel = relMap[other.id] || relMap[other.agentId];
                      const v = rel ? (rel.value || 0) : 0;
                      const { label, color } =
                        v >= 30  ? { label: '信任', color: '#10b981' } :
                        v >= -30 ? { label: '一般', color: '#94a3b8' } :
                                   { label: '不信任', color: '#ef4444' };
                      const pct = Math.round((v + 100) / 2);
                      const targetName = other.name || idToName[other.id] || other.id;
                      return (
                        <div key={other.id || other.agentId} style={{ fontSize: '12px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', margin: '4px 0', color: '#475569' }}>
                          <span>{targetName}</span>
                          <span style={{ fontWeight: 700, color, fontSize: '11px' }}>
                            {label} {pct}%
                          </span>
                        </div>
                      );
                    });
                  })()}
                </div>
              )}
            </div>
          );
        })
      )}
    </div>
  );
}
