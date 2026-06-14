# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概览

StoryWeaver 是一个多 Agent 的非线性叙事模拟系统。`backend/readme.txt` 和 `导演.md` 描述的核心思路不是"分支剧情"或"聊天机器人"，而是一个由多个自治角色共同演化故事的模拟器。

完整的 API 接口文档在 `大模型项目接口.md`，涵盖框架层、导演后端、角色后端、记忆后端的全部端点及请求/响应格式。

核心不变量：玩家、角色 Agent、导演都只产出 **Intent**；只有模拟器负责解析意图并修改客观世界状态。任何修改都应遵循 `Intent -> Resolution -> State Update` 的流向，不要让 UI、角色模块或导演模块直接改写世界真相。

系统分成两层：

- **语言层**：由 LLM 驱动的对话、情绪表达、人格、策略和推理。
- **状态层**：由系统维护的时间、位置、关系、物品、知识、事件和玩家影响。

三层世界状态：World Truth（客观真相）、Agent Belief（角色主观认知）、Player Influence（玩家对角色的影响）。

## 常用开发命令

### 前端

```bash
npm install
npm run dev
npm run build
npm run preview
```

- `npm run dev` 启动 Vite，默认地址 `http://localhost:5173`。
- `npm run build` 执行 `tsc && vite build`，这是前端主要的类型检查/构建命令。
- 当前 `package.json` 没有配置 `lint` 或测试脚本。

### 后端

```bash
python -m venv .venv
source .venv/Scripts/activate
pip install -r backend/requirements.txt
python -m backend.main
```

等价启动命令：

```bash
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

后端 smoke checks：

```bash
curl http://localhost:8000/health
curl http://localhost:8000/
curl "http://localhost:8000/api/init?world_id=default_world"
curl "http://localhost:8000/api/v1/world/state?world_id=default_world"
curl "http://localhost:8000/api/v1/director/status"
curl "http://localhost:8000/api/v1/agent/list?world_id=default_world"
curl -X POST "http://localhost:8000/api/v1/world/tick" -H "Content-Type: application/json" -d "{}"
```

- 后端还自带一个 HTML 测试页 `http://localhost:8000/play`（`/test` 会重定向到此），可在线触发 4 个 NPC 的 DeepSeek 决策并展示结果。测试页通过 `/feed` 端点轮询对话，每 5 秒一次。
- 故事控制端点：`GET /story/status`（查看暂停状态和 tick 数）、`POST /story/resume`（恢复故事时钟并启动 tick 循环）。
- 对话数据端点：`GET /feed?limit=30`（最近对话增量）、`GET /feed/all`（全部历史对话，供时间线跳转后重载）。
- 当前仓库没有统一的 Python 测试运行器，也没有已提交的后端测试。以后如果补上测试，请同时记录完整测试命令和单个测试的运行方式。

## 运行时配置

- 后端配置集中在 `backend/config.py`，通过 `pydantic-settings` 从 `../.env` 读取。
- 主要配置项：`LLM_API_KEY`、`LLM_MODEL`、`LLM_BASE_URL`、`LLM_TEMPERATURE`、`DIRECTOR_API_KEY`、`DIRECTOR_MODEL`、`DIRECTOR_TEMPERATURE`、`STORAGE_DIR`、`MAX_AGENTS`、`TICK_INTERVAL_MS`、`TIME_SCALE`、`WS_HEARTBEAT_INTERVAL`。
- LLM 调用代码在 `backend/engine/agent_runtime.py` 和 `backend/modules/llm/handler.py`，它们直接读取环境变量 `DEEPSEEK_API_KEY`（注意不是 `LLM_API_KEY`），并硬编码 DeepSeek API URL，**不使用** `config.py` 的 `LLM_MODEL`/`LLM_BASE_URL`。未设置 API key 时回退到 idle 兜底决策。
- 运行时 JSON 存储落在 `STORAGE_DIR` 指向的目录，`backend/framework/json_store.py` 会在需要时自动创建 backing file。
- `backend/requirements.txt` 当前仅包含 `fastapi`、`uvicorn`、`websockets`、`httpx`、`pydantic`/`pydantic-settings`、`python-dotenv`。旧版重依赖（SQLAlchemy、asyncpg、Alembic、ChromaDB、LangGraph、LangChain）已移至 `backend/requirements_old.txt`，当前代码**未**使用它们。注意 `backend/engine/agent_runtime.py` import 了 `aiohttp` 但 `requirements.txt` 未声明（不过该文件在活跃 tick 流中未被使用，见下文）。

## 高层架构

### 前端

- 入口 `src/main.tsx`：先通过 `ApiClient.initWorldSnapshot("default_world")` 拉取初始世界快照，然后从 `/feed/all` 加载历史对话，调用 `/story/resume` 恢复故事时钟，最后连接 WebSocket 单例，再渲染 React。
- 根 UI `src/App.tsx` 只渲染 `UIOverlay`，由历史记录、叙事阶段、观察面板、NPC 状态面板和玩家输入区组成。
- **没有客户端路由**：整个应用是单页应用，未使用 React Router 或任何路由库。`tsconfig.json` 启用了 `strict: true`、`noUnusedLocals`、`noUnusedParameters`，构建命令 `npm run build` 会执行完整的 `tsc` 类型检查。
- 状态流向：
  - `src/core/WebSocketClient.ts` 连接 `ws://localhost:8000/ws?world_id=default_world`，解析 JSON 消息，更新 `GameState`，并向前端事件总线发事件。
  - `src/core/GameState.ts` 是前端本地可变运行时状态，保存 tick/time/tension、世界大纲、NPC 状态、对话日志和叙事事件。
  - `src/core/EventBus.ts` 把事件分发给 React hooks 和 Pixi。
  - `src/react/hooks/useGameState.ts` 把 `GameState` 和 `EventBus` 接到 React 订阅层。
- Pixi 集成在 `src/pixi/Game.ts`，目前主要是透明的视觉/效果层，真正的 UI 还是以 React 文本面板为主。
- 前后端共享的协议类型放在 `src/types/api.ts`。

### 后端框架层

- 入口 `backend/main.py`：创建 FastAPI 应用、配置 CORS、在 lifespan 启动阶段初始化单例、注入默认别墅谜案场景（`_init_demo_scene()`）、注册 handler、启动 `WorldSimulator`，并暴露 `/ws`、统一网关和几个直接路由端点。
- `main.py` 中的直接路由（不走 gateway/router 分发）：
  - `GET /story/status` — 查看暂停状态和当前 tick 数
  - `GET|POST /story/resume` — 恢复故事时钟并启动 tick 循环
  - `GET /feed?limit=N` — 最近对话增量（前端每 5 秒轮询）
  - `GET /feed/all?to_tick=N` — 全部历史对话（时间线跳转后重载）
  - `GET /play` — HTML 测试页（`/test` 重定向到此）
  - `WS /ws` — WebSocket 连接点
- HTTP 请求有两条路径：
  1. **前端兼容路径** `/worlds/...`、`/story-sessions/...`、`/users/...`：在 `backend/framework/gateway.py` 中直接注册，返回 `{code, data, message}` 包装格式，与 `src/core/ApiClient.ts` 对齐。
  2. **统一网关** `/api/v1/{path}`：经 `backend/framework/router.py` 解析 `(method, path)` → `(module, message_type)`，再通过 `backend/framework/bus.py` 发到对应模块，返回原始 JSON（不包装）。
- 已注册的模块 handler：
  - `backend/modules/director/handler.py`：世界状态、导演状态、地图、时间线、tick 等接口。
  - `backend/modules/character/handler.py`：Agent 列表、详情、认知、关系、对话和调试 tick。
  - `backend/modules/memory/handler.py`：短期记忆、关系、对话历史和搜索类操作。
  - `backend/modules/llm/handler.py`：DeepSeek 驱动的角色决策调用。
- 内部异步事件使用 `backend/framework/event_bus.py`。

### 仿真与世界状态

- `backend/engine/world_simulator.py` 是中心写入路径。每个 tick：导演生成 `SceneGoal` → `CharacterRuntime`（模块层）生成 NPC 意图 → 合并玩家意图 → `IntentResolver` 解析 → 转为 `WorldCommand` → 执行命令 → 推进时间 → 发布内部事件。
- **有两个 NPC 运行时**：`backend/modules/character/runtime.py`（CharacterRuntime，通过 bus→LLM 模块调用 DeepSeek）是 tick 循环中**实际活跃的**运行时；`backend/engine/agent_runtime.py`（直接通过 aiohttp 调用 DeepSeek）存在但当前 tick 流中未使用。
- `backend/engine/ground_truth.py` 负责客观世界真相，对应 `backend/model/world.py` 中的 `WorldTruth`。提供 `move_agent`、`move_item`、`advance_time` 等读写辅助方法；原则上只有模拟器应当写它。
- `backend/engine/intent_resolver.py` 的文档注释描述了一套基于概率分发的旧解析逻辑，但实际实现只有一个简化版的 `resolve()`，冲突处理等特性并未实现（概率执行已实现）。
- `backend/engine/rule_engine.py` 提供意图校验辅助逻辑，配合上面的旧 resolver 路径使用。
- `backend/engine/agent_runtime.py` 是模拟器拥有的按 tick Agent 运行时。根据世界真相、附近角色/物品、目标、情绪、最近事件和导演的 `SceneGoal` 构造上下文，再调用 DeepSeek 为每个活跃 Agent 生成 JSON 意图。

### 导演、角色与记忆模块

- `backend/modules/director/director_service.py` 负责叙事节奏、事件调度、信息释放、叙事收束和 `SceneGoal` 生成。它的职责是给结构，不是写对白，也不是直接改世界状态。
- 导演子模块位于 `backend/modules/director/` 下，分别处理节奏、事件、信息控制和收束。
- `backend/modules/character/runtime.py` 是 tick 循环中 NPCC 决策的实际执行者。它通过 bus 与导演、记忆、LLM 模块通信，实现导演调度（优先级排序、被点名优先、轮转防垄断）、并发 LLM 决策、发言去重和发言人数限制。**不要**和模拟器拥有的 `backend/engine/agent_runtime.py` 当成同一条路径（后者已注册但当前 tick 流未使用）。
- 角色的主观状态在 `backend/modules/character/` 里，特别是 `belief_system.py` 和 `player_influence.py`；客观真相仍在 `backend/engine/ground_truth.py`。
- 记忆和关系持久化在 `backend/modules/memory/`。短期记忆为 JSON 存储；向量记忆（`vector_memory.py`）是自定义 Python 实现（关键词匹配 + 语义相关性启发式评分 + 情绪标签匹配 + 衰减），**不使用** ChromaDB。记忆整合（短期→长期）每 5 tick 触发一次。
- **叙事逻辑层** `backend/modules/narrative/`：`StoryState` 跟踪角色秘密、已知事实和矛盾检测；`LogicValidator` 校验对话场景的连贯性；`PlotManager` 跟踪发言者轮换。这三个在 `main.py` lifespan 中初始化并注入 WorldSimulator。
- **Prompt 模板** `backend/prompt/`：存放 `agent_prompts.py`、`dialogue_prompts.py`、`director_prompts.py`，被 LLM handler 用于构造不同角色的 System Prompt。
- **时间线模块** `backend/timeline/`：`TimelineStore` 持久化 timeline nodes（章节节点）和世界快照到 JSON 文件；`build_snapshot()` / `restore_from_snapshot()` 支持在任意 tick 保存/恢复完整世界状态；通过 `timeline:jump` WebSocket 消息实现时间线跳转（前端 `jumpToTick()` → 后端加载最近快照 → 恢复 GroundTruth/Agent/Memory/Director → 广播新状态）。

### Tick 详细流程

`WorldSimulator._do_tick()` 的实际执行顺序：

1. **Director.update()** → 生成 SceneGoal + narration
2. **唤醒 NPC**：将导演事件和 SceneGoal 注入 CharacterRuntime 的 wake_events
3. **注入 tick 上下文**：phase（6 阶段系统）、character_goals（博弈目标）、character_knowledge（两层知识：surface + deep secrets 渐进揭示）、incident（首 tick 巨响事件）、stagnation（停滞检测）、fix_hints（逻辑校验反馈）、max_speakers（早期限制发言人数）、opening_narration
4. **CharacterRuntime.tick()** → 导演调度（优先级排序、去重）→ 并发 LLM 决策 → 发言人数限制 → 写入记忆
5. **LogicValidator 校验**：对话文本一致性检查，不通过则生成 fix_hints 供下一 tick 修正
6. **StoryState 记录**：记录对话事件、发言者事实、更新角色认知
7. **生成导演旁白**（非首 tick 时通过 LLM 生成）
8. **合并玩家意图** → IntentResolver.resolve() → WorldCommand → _apply_command()
9. **GroundTruth.advance_time()** → 发布 world:time_changed 事件
10. **extract_frontend_events()** → 提取对话/旁白 → 持久化到 feed_cache.json
11. 每 5 tick 触发记忆整合

Tick 有并发保护（`_tick_in_progress` 锁 + 60s 超时强制释放）和 `asyncio.wait_for(45s)` 总超时。

### WebSocket 与自动 Tick 循环

- `backend/framework/websocket.py` 的 `ConnectionManager` 管理所有 WS 连接。消息类型（`WSMessageType`）与前端 `src/types/api.ts` 中的 `WSMessageType` 枚举**已对齐**（`world_state`、`agent_state`、`dialogue`、`narrative_event` 等）。
- 当有 WebSocket 连接时，`_tick_loop_removed`（命名有误导性，实际是活跃的 tick 循环）会以硬编码的 **8 秒**间隔自动推进世界 tick 并广播结果（**注意**：不使用配置中的 `TICK_INTERVAL_MS`，该值当前为 1000ms 但未被 websocket 层引用）。`start_tick_loop()` 被前端"开始"按钮触发后会**立即执行首个 tick**（不等 8 秒），然后启动后台循环。tick 循环会检查 `story_paused`（暂停时 sleep 1s 等待）和 `player_intervention_pending`（玩家干预进行中时 sleep 1s 等待）标志。
- 玩家干预走 WebSocket 的 `PLAYER_INTERVENTION` 消息，会设置 `player_intervention_pending` 锁防止自动 tick 竞态，即时触发一次 tick 并广播结果。干预后会有 3 秒缓冲期让前端轮询到 NPC 回应。
- 事件桥（`_ensure_event_bridge`）将内部事件总线的 `narrative_event`、`directive`、`world:time_changed`、`director:goal_updated`、`director:atmosphere`、`system:skill_check`、`story:settlement`、`dialogue:token_stream` 事件转发到 WebSocket 广播。
- **对话交付走双通道**：WebSocket 实时推送 `dialogue` 和 `dialogue:token_stream` 消息（`WebSocketClient.ts` 中已处理），同时前端 `NarrativeStage.tsx` 也会轮询 `/feed` 端点作为补充（每 5 秒），对话缓存在 `feed_cache.json`。两个通道互为备份。

## API 和协议注意事项

- 前端 `src/core/ApiClient.ts` 访问 `/worlds/...` 路径并期望 `{code, data, message}` 包装响应。后端 `gateway.py` 中已为这些路径注册了兼容路由。
- 注意 `gateway.py` 中存在三组重叠的 URL 空间：`/worlds/{world_id}/...`（前端兼容，包装响应）、`/api/v1/{path}`（统一网关，原始 JSON）、以及 `/agent/...`、`/memory/...`、`/director/...`（遗留直接端点）。修改路由时注意不要新增重复。
- `/api/v1/...` 网关走 router → bus 分发，返回原始 JSON（无 `{code, data, message}` 包装）。如果前端要切到这个路径，需同步修改 ApiClient。
- `导演.md` 里提到的 `/api/v1/ping` 和 `/director/world_basic_info` 等路由，在 `backend/framework/router.py` 里不存在。`/api/v1/ping` 在 gateway.py 中有直接注册，但不经过 router 分发。
- 后端 Pydantic 模型放在 `backend/model/`；前端协议接口放在 `src/types/`。改消息载荷时，两边要一起改。

## 代码组织提示

- 默认演示场景写在 `backend/main.py` 的 `_init_demo_scene()` 里（雪山别墅谜案：4 个 NPC、5 个地点、4 个物品、3 个定时事件）；如果要替换剧情，先从这里开始。
  - 角色 ID 映射：`hostess_su`（苏晚晴·女主人）、`detective_jiang`（江策·侦探）、`artist_gu`（顾言·画家）、`butler_zhong`（钟叔·管家），调试 API 时用这些 ID。
- 搜索或编辑代码时，忽略 `.venv`、`node_modules`、`__pycache__` 和 `dist` 这些产物目录。
- 注意区分数据目录：**运行时数据**在项目根目录 `data/`（由后端 STORAGE_DIR 配置写入的 JSON 持久化文件）。`src/data/` 目录已不存在，不要被旧文档中提到的该路径误导。
- Python 导入使用 `from backend.xxx import yyy` 风格，项目根目录必须在 Python path 中（uvicorn 启动时自动处理）。
- i18n 在 `backend/utils/i18n.py`：后端模型用英文字段名，前端展示中文翻译值。修改字段时两边要一致。

## 已知技术债务

- **死代码**：
  - `backend/engine/time_system.py` — `TimeSystem` 类已定义但未被任何模块导入或使用，是完全的死代码。时间推进直接走 `GroundTruthManager.advance_time()`。
  - `backend/engine/rule_engine.py` — 大部分校验方法直接返回通过（`can_agent_perform`、`can_interact_with`、`validate_intent`、`can_know_information` 等），仅 `can_access_location` 有实际逻辑（检查地点是否存在、是否上锁）。`intent_resolver.py` 的 `resolve()` 也直接 trust `validate_intent()`。
  - `backend/engine/intent_resolver.py` — 注释中描述的冲突处理逻辑未实现，当前是简化的直接映射版本（概率执行已实现但冲突解决缺失）。
- **未使用的依赖 / 旧依赖**：`backend/requirements_old.txt` 保留了 SQLAlchemy、asyncpg、Alembic、ChromaDB、LangGraph、LangChain 等旧版依赖声明，但活跃的 `requirements.txt` 已移除它们，代码中也无任何 import 使用。`backend/engine/agent_runtime.py` import 了 `aiohttp` 但 `requirements.txt` 未声明（该文件在活跃 tick 流中未被使用，影响有限）。
- **重复模型**：`DialogueRecord` 同时在 `backend/model/dialogue.py` 和 `backend/modules/memory/schema.py` 中定义，字段略有差异。
- **硬编码**：`backend/engine/agent_runtime.py` 和 `backend/modules/llm/handler.py` 都直接读取 `DEEPSEEK_API_KEY` 环境变量并硬编码 `https://api.deepseek.com/chat/completions` URL，没有使用 `config.py` 中的 `LLM_API_KEY`/`LLM_BASE_URL` 设置。
- **三组重叠路由**：`gateway.py` 中 `/worlds/...`、`/api/v1/...`、`/agent/...` `/memory/...` `/director/...` 三组 URL 空间重叠，存在大量路由重复逻辑。
- **废弃备份目录**：`backend/temp/` 目录包含 `director/` 和 `memory/` 子模块的旧版副本，与活跃的 `backend/modules/` 下对应文件存在差异（缺少部分新文件）。这些是历史迭代遗留，修改代码时以 `backend/modules/` 下的活跃版本为准，不要被 `temp/` 中的旧代码误导。
- **`_tick_loop_removed` 命名误导**：函数名暗示 tick 循环已被移除，但实际是活跃的后台 tick 循环（每 8 秒推进一次）。现已正确检查 `story_paused` 和 `player_intervention_pending` 标志。
