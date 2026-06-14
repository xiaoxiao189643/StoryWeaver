多 Agent 非线性叙事游戏项目总设计
一、项目定位

该项目本质上不是传统：

分支剧情游戏
AI 聊天游戏
固定脚本 AVG

而是：

“多 Agent 驱动的非线性叙事模拟系统”

核心目标：

让多个具有自主性的角色
在统一世界规则下
通过互动、冲突、记忆与玩家干预
动态演化出故事

项目核心关键词：

Multi-Agent
Emergent Narrative
World Simulation
Interactive Drama
Narrative Director
二、核心思想

整个系统建立在：

“语言层”与“状态层”分离

这一核心理念上。

1. Language Layer（语言层）1. 语言层

由 LLM 驱动。

负责：

对话
情绪表达
策略
人格
推理

特点：

自由
动态
富有表现力
2. State Layer（状态层）

由系统维护。

负责：

时间
位置
关系
物品
知识
事件

特点：

严格
一致
可验证
三、系统核心哲学

系统中：

没有任何实体能直接修改现实。

包括：

玩家
角色 Agent
导演 Agent

所有实体只能：

提出 Intent（意图）

例如：

“尝试说服”
“尝试攻击”
“尝试触发事件”

然后：

World Simulator 决定是否成立。
四、三层世界状态

系统维护三种状态：

1. World Truth（客观真相）

唯一真实世界。

例如：

{
  "killer": "alice"
}
2. Agent Belief（角色认知）

角色主观看法。

例如：

{
  "bob_suspects": "eva"
}

角色可能：

错误
被误导
被欺骗
3. Player Influence（玩家影响）

玩家对角色造成的影响。

例如：

{
  "alice_trust_player": 0.8
}
五、系统运行机制

整个系统围绕：

Intent → Resolution → State Update

运行。

Step 1：Intent（意图）

来源：

玩家
角色 Agent
导演 Agent

例如：

玩家：
“Bob 在撒谎”

角色：
“尝试进入实验室”

导演：
“增加冲突”
Step 2：Resolution（解析）

由：

World Simulator

负责：

规则验证
行为解析
冲突处理
概率计算

例如：

角色是否在场？
是否知道该信息？
门是否锁住？
Step 3：State Update（状态更新）

系统更新：

关系
知识
位置
情绪
事件
六、导演 Agent（Narrative Director）

Director 不是：导演不是：

“写剧情”

而是：

“控制叙事结构”
Director 的职责
1. 节奏控制

例如：

提高紧张感
减缓节奏
2. 信息控制

例如：

限制真相曝光
3. 事件调度

例如：

停电
广播
警报
谋杀
4. 叙事收束

防止：

剧情无限发散
Director 输出的不是具体台词

而是：

{
  "scene_goal":
  "Increase distrust between Alice and Bob"
}

真正的行为由角色 Agent 自主完成。

七、角色 Agent

每个角色拥有：

人格
目标
记忆
关系
情绪
知识

运行方式：

ReAct Loop
Observe
→ Think
→ Act
Agent 不直接修改世界

只能：

提出行动意图

例如：

“尝试打开门”

然后由：

World Simulator

验证。

八、玩家干预系统

玩家不是：

“控制角色”

而是：

“影响角色”
干预类型
1. Observation（观察）1. 观察结果

例如：

偷听
调查
跟踪
2. Suggestion（建议）2. 建议

例如：

“别相信 Bob”
3. Persuasion（说服）3. 说服/劝说

系统计算：

信任
情绪
人格
关系

决定是否接受。

4. Override（强制干预）

极少使用。

否则会破坏 Agent 自主性。

九、World Simulator（世界模拟器）

整个系统最核心模块。

负责：

1. Ground Truth（唯一真相）

例如：

谁在哪
谁拿着什么
谁知道什么
2. Rule Validation（规则验证）

例如：

门锁着无法进入
3. Time Progression（时间推进）

例如：

夜晚角色会睡觉
4. Information Isolation（信息隔离）4. 我的信息

例如：

不知道的信息不能说
十、技术路线
前端
React

负责：

UI
状态展示
交互
PixiJS

负责：

2D 场景
角色显示
动画
后端
FastAPI

负责：

Simulation Backend
API
WebSocket
LangGraph

负责：

多 Agent 工作流
状态编排
PostgreSQL

负责：

世界状态
角色状态
事件
关系
ChromaDB / FAISS

负责：

向量记忆检索
十一、完整系统架构
┌────────────────────────────┐
│         Frontend           │
│ React + PixiJS             │
└────────────┬───────────────┘
             │
         WebSocket
             │
┌────────────▼───────────────┐
│        FastAPI Server      │
└────────────┬───────────────┘
             │
 ┌───────────┼──────────────────────────────┐
 ↓           ↓                              ↓
Director   World State                Intervention
Service    Service                    Service
             ↓                              ↓
        Rule Engine                 Influence Engine
             ↓                              ↓
         PostgreSQL                 Relationship System
             ↓                              ↓
          ChromaDB                  Belief System
                    └────────────┬────────────┘
                                 ↓
                          Agent Runtime
                                 ↓
                            LangGraph
                                 ↓
                            LLM Provider
十二、系统核心循环
玩家输入
↓
Intent Parser
↓
World Simulator
↓
Director Update
↓
Agent Observe
↓
Agent Planning
↓
Action Validation
↓
State Update
↓
Dialogue Generation
↓
Frontend Render
十三、推荐 MVP（第一版）
场景

推荐：

空间站
研究所
雪山别墅
列车

原因：

封闭空间
关系密度高
易于控制复杂度
Agent 数量
3~5 个
内容规模
一个核心秘密
一个主要冲突
动态关系系统
有限地图
十四、开发优先级

真正重要的开发顺序：

1. World State
2. Rule Engine
3. Agent Memory
4. Utility Decision
5. Director Control
6. Intervention System
7. Dialogue Polish
十五、项目最终目标

该项目最终目标不是：

“让 AI 自动写故事”

而是：

“让多个自治角色在规则约束下自然演化出可信故事”。