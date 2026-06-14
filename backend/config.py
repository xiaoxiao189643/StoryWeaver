# ============================================================
# config.py —— 全局配置
# 通过环境变量 + .env 文件加载
# ============================================================
# 本文件集中管理所有运行时配置项，包括：
#   - LLM 提供商密钥
#   - 数据库连接串
#   - ChromaDB 路径
#   - 游戏运行参数（帧率、Agent 数量上限等）
# ============================================================

from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # ── LLM（角色 Agent） ──
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "gpt-4o-mini"
    LLM_BASE_URL: Optional[str] = None
    LLM_TEMPERATURE: float = 0.7

    # ── 导演 LLM ──
    DIRECTOR_API_KEY: str = ""
    DIRECTOR_MODEL: str = "deepseek-chat"
    DIRECTOR_TEMPERATURE: float = 0.9

    # ── JSON 文件存储 ──
    STORAGE_DIR: str = "./data"

    # ── Game ──
    MAX_AGENTS: int = 8
    TICK_INTERVAL_MS: int = 1000  # 1 tick = 1 秒游戏内时间
    TIME_SCALE: float = 1.0  # 现实时间 : 游戏时间 比例

    # ── WebSocket ──
    WS_HEARTBEAT_INTERVAL: int = 30

    class Config:
        env_file = "../.env"
        env_file_encoding = "utf-8"


settings = Settings()
