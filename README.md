# StoryWeaver

多 Agent 驱动的非线性叙事模拟系统。让多个具有自主性的角色在统一世界规则下，通过互动、冲突、记忆与玩家干预，动态演化出故事。

## 核心理念

系统建立在 **"语言层"与"状态层"分离** 的核心理念上：

- **语言层**：由 LLM 驱动的对话、情绪表达、人格、策略和推理
- **状态层**：由系统维护的时间、位置、关系、物品、知识和事件

所有实体（玩家、角色 Agent、导演 Agent）只能提出 **Intent（意图）**，由 **World Simulator** 验证并修改世界状态。

```
Intent → Resolution → State Update
```

## 三层世界状态

| 状态 | 说明 |
|------|------|
| **World Truth** | 客观真相，唯一真实世界 |
| **Agent Belief** | 角色主观认知，可能错误或被误导 |
| **Player Influence** | 玩家对角色的影响（信任、情感等） |

## 系统架构

```
┌─────────────────────────┐
│   Frontend (React + Vite) │
└──────────┬────────────────┘
           │ WebSocket + HTTP
┌──────────▼────────────────┐
│   FastAPI Server          │
├──────────┼────────────────┤
│ Director │ World State    │
│ Service  │ + Rule Engine   │
│          │ + Intent Resolver│
├──────────┼────────────────┤
│ Agent Runtime + Memory   │
├──────────────────────────┤
│ LLM Provider (DeepSeek)  │
└──────────────────────────┘
```

### Tick 循环

每个 Tick 执行：导演生成场景目标 → NPC 并发 LLM 决策 → 发言去重/限制 → LogicValidator 校验 → 意图解析 → 状态更新 → 时间推进 → 前端广播

## 技术栈

| 层 | 技术 |
|----|------|
| **前端** | React 18 + TypeScript + Vite + PixiJS 8 |
| **后端** | Python 3.10+ + FastAPI + WebSocket |
| **数据** | Pydantic + JSON 文件存储 |
| **AI** | DeepSeek API（角色决策 + 导演叙事） |

## 环境依赖

- **Python** ≥ 3.10
- **Node.js** ≥ 18
- **DeepSeek API Key**（或其他兼容 OpenAI 接口的 LLM）

## 项目配置

在项目根目录创建 `.env` 文件：

```env
# LLM（角色 Agent）
LLM_API_KEY=your_api_key_here
LLM_MODEL=deepseek-chat
LLM_BASE_URL=https://api.deepseek.com/chat/completions
LLM_TEMPERATURE=0.7

# 导演 LLM
DIRECTOR_API_KEY=your_api_key_here
DIRECTOR_MODEL=deepseek-chat
DIRECTOR_TEMPERATURE=0.9

# 数据存储
STORAGE_DIR=./data

# 游戏参数
MAX_AGENTS=8
TICK_INTERVAL_MS=1000
TIME_SCALE=1.0
```

> **注意**：LLM 调用代码当前直接读取 `DEEPSEEK_API_KEY` 环境变量（非 `LLM_API_KEY`），并硬编码 DeepSeek API URL。未设置 API key 时回退到 idle 兜底决策。

## 本地部署

### 1. 克隆项目

```bash
git clone https://github.com/YOUR_USERNAME/StoryWeaver.git
cd StoryWeaver
```

### 2. 后端

```bash
# 创建虚拟环境
python -m venv .venv
source .venv/Scripts/activate   # Windows
# source .venv/bin/activate      # macOS/Linux

# 安装依赖
pip install -r backend/requirements.txt

# 启动后端（端口 8000）
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

### 3. 前端

```bash
# 安装依赖
npm install

# 启动开发服务器（端口 5173）
npm run dev
```

### 4. 访问

- 前端页面：`http://localhost:5173`
- 后端测试页：`http://localhost:8000/play`
- API 文档：`http://localhost:8000/docs`

## API 端点

| 端点 | 说明 |
|------|------|
| `GET /health` | 健康检查 |
| `GET /api/v1/world/state?world_id=default_world` | 世界状态 |
| `GET /api/v1/director/status` | 导演状态 |
| `GET /api/v1/agent/list?world_id=default_world` | Agent 列表 |
| `POST /api/v1/world/tick` | 手动推进 Tick |
| `GET /feed?limit=30` | 最近对话 |
| `GET /feed/all` | 全部历史对话 |
| `GET /story/status` | 故事暂停状态 |
| `POST /story/resume` | 恢复故事时钟 |
| `WS /ws?world_id=default_world` | WebSocket 实时通信 |

完整 API 接口文档见 `大模型项目接口.md`。

## 演示场景

默认场景为**雪山别墅谜案**：4 个 NPC（苏晚晴、江策、顾言、钟叔）被困在封闭别墅中，围绕一桩谋杀案展开互动。

角色 ID：`hostess_su`、`detective_jiang`、`artist_gu`、`butler_zhong`

## 项目结构

```
StoryWeaver/
├── backend/
│   ├── main.py                 # FastAPI 入口 + 场景初始化
│   ├── config.py               # 全局配置
│   ├── engine/                  # 世界模拟器核心
│   │   ├── world_simulator.py  # Tick 循环 + 命令执行
│   │   ├── ground_truth.py     # 客观世界真相
│   │   ├── intent_resolver.py  # 意图解析
│   │   └── rule_engine.py      # 规则校验
│   ├── modules/                 # 功能模块
│   │   ├── director/           # 叙事导演
│   │   ├── character/          # 角色运行时
│   │   ├── memory/             # 记忆系统
│   │   ├── llm/                # LLM 调用
│   │   └── narrative/          # 叙事逻辑校验
│   ├── framework/              # WebSocket、Gateway、Bus
│   ├── timeline/               # 时间线 + 快照恢复
│   ├── prompt/                 # Prompt 模板
│   └── model/                  # Pydantic 数据模型
├── src/
│   ├── main.tsx                # 前端入口
│   ├── App.tsx                 # 根 UI
│   ├── core/                   # WebSocket、GameState、EventBus
│   ├── react/                  # React hooks + 组件
│   ├── pixi/                   # PixiJS 视觉层
│   └── types/                  # 共享协议类型
└── public/                     # 静态资源
```
