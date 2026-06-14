# ============================================================
# framework/router.py —— 前端请求 → 模块路由
# ============================================================
# HTTP 路径 → (目标模块, 消息类型)
# 前端请求统一走这里分发
# ============================================================

# HTTP method + path → (to_module, message_type)
# 格式: ("METHOD", "/path") → ("module", "message_type")

ROUTES = {
    # ── 角色模块 ──
    ("GET",    "/agent/list"):              ("character", "get_agent_list"),
    ("GET",    "/agent/{agent_id}"):        ("character", "get_agent_detail"),
    ("GET",    "/agent/{agent_id}/relationships"): ("character", "get_agent_relationships"),
    ("GET",    "/agent/{agent_id}/belief"): ("character", "get_agent_belief"),
    ("POST",   "/agent/{agent_id}/belief"): ("character", "write_agent_belief"),
    ("GET",    "/dialogue/history"):        ("character", "get_dialogue_history"),
    ("POST",   "/memory/event/from-agent"): ("character", "report_agent_event"),
    ("POST",   "/agent/tick"):              ("character", "debug_tick"),

    # ── 导演模块 ──
    ("GET",    "/world/state"):               ("director", "get_world_state"),
    ("GET",    "/director/outline"):          ("director", "get_director_outline"),
    ("GET",    "/director/status"):           ("director", "get_director_status"),
    ("GET",    "/director/upcoming_events"):  ("director", "get_upcoming_events"),
    ("GET",    "/world/map"):                 ("director", "get_world_map"),
    ("GET",    "/world/timeline"):            ("director", "get_world_timeline"),
    ("POST",   "/world/tick"):                ("director", "world_tick"),
    ("GET",    "/story/chapters"):            ("director", "get_story_chapters"),

    # ── 记忆模块 ──
    ("POST",   "/memory/add"):               ("memory",  "memory_add"),
    ("GET",    "/memory/recent"):             ("memory",  "memory_get_recent"),
    ("GET",    "/memory/search"):             ("memory",  "memory_search"),
    ("POST",   "/memory/dialogue/add"):       ("memory",  "memory_dialogue_add"),
    ("GET",    "/memory/dialogue/list"):      ("memory",  "memory_dialogue_list"),
    ("PATCH",  "/memory/relationship/update"): ("memory", "memory_relationship_update"),
    ("POST",   "/memory/rollback"):           ("memory",  "memory_rollback"),
    ("GET",    "/memory/stats"):              ("memory",  "memory_stats"),
    ("GET",    "/memory/context"):            ("memory",  "memory_context"),
    ("POST",   "/memory/consolidate"):        ("memory",  "memory_consolidate"),
    ("POST",   "/memory/forget"):             ("memory",  "memory_forget"),
    ("POST",   "/memory/merge"):              ("memory",  "memory_merge"),

    # ── 导演 → Agent 相关 ──
    ("GET",    "/director/agent/{agent_id}"):   ("director", "get_director_agent"),
    ("GET",    "/director/agent/{agent_id}/scene"): ("director", "get_director_agent_scene"),

    # ── 初始化 ──
    ("GET",    "/api/init"):                ("director", "init_world"),

    # ── 时间线模块 ──
    ("GET",    "/timeline/tree"):           ("timeline", "get_timeline_tree"),
    ("GET",    "/timeline/snapshots"):      ("timeline", "get_snapshots"),
    ("POST",   "/timeline/jump"):           ("timeline", "jump_to_tick"),
}

# 动态路径匹配
import re

DYNAMIC_ROUTES = [
    # (pattern, method) → (to_module, message_type, extract_params)
    (re.compile(r"^/agent/(?P<agent_id>[^/]+)/belief$"),         "GET",  "character", "get_agent_belief"),
    (re.compile(r"^/agent/(?P<agent_id>[^/]+)/belief$"),         "POST", "character", "write_agent_belief"),
    (re.compile(r"^/agent/(?P<agent_id>[^/]+)/relationships$"),  "GET",  "character", "get_agent_relationships"),
    (re.compile(r"^/agent/(?P<agent_id>[^/]+)$"),                "GET",  "character", "get_agent_detail"),

    # 导演模块动态路由
    (re.compile(r"^/director/agent/(?P<agent_id>[^/]+)/scene$"), "GET", "director", "get_director_agent_scene"),
    (re.compile(r"^/director/agent/(?P<agent_id>[^/]+)$"),       "GET", "director", "get_director_agent"),

    # 记忆模块动态路由
    (re.compile(r"^/memory/dialogue/list$"),                     "GET", "memory", "memory_dialogue_list"),
]


def resolve(method: str, path: str):
    """
    解析 HTTP 请求 → (module, message_type, path_params)
    先查静态路由，再查动态路由。
    """
    key = (method.upper(), path)
    if key in ROUTES:
        return (*ROUTES[key], {})

    for pattern, pm, mod, mtype in DYNAMIC_ROUTES:
        if method.upper() == pm:
            m = pattern.match(path)
            if m:
                return (mod, mtype, m.groupdict())

    return (None, None, {})
