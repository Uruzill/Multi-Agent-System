"""
多智能体协作系统 — 模型与角色配置。

添加新模型：在 MODEL_POOL 里加一个 entry，key 随意（建议 "字母-名称"）。
切换角色所用模型：改 ROLE_MODEL 中对应角色的 value 为 MODEL_POOL 的 key。
"""

import os
from typing import Any

# ═══════════════════════════════════════════════════════════════
# 角色集合
# ═══════════════════════════════════════════════════════════════

ROLES: tuple[str, ...] = (
    "Planner", "Retriever", "Coder", "Writer",
    "Tester", "Summarizer", "Bot",
)

# ═══════════════════════════════════════════════════════════════
# 模型池  {key → {model, api_key, base_url}}
# ═══════════════════════════════════════════════════════════════

MODEL_POOL: dict[str, dict[str, Any]] = {
    "a-deepseek": {
        "model": "deepseek-v4-flash",
        "api_key": os.getenv("DEEPSEEK_API_KEY", ""),
        "base_url": "https://api.deepseek.com/v1",
    },
}

# ═══════════════════════════════════════════════════════════════
# 角色 ↦ 模型 key 映射
# ═══════════════════════════════════════════════════════════════

_ROLE_MODEL: dict[str, str] = {
    "Planner":    "a-deepseek",
    "Retriever":  "a-deepseek",
    "Coder":      "a-deepseek",
    "Tester":     "a-deepseek",
    "Writer":     "a-deepseek",
    "Summarizer": "a-deepseek",
    "Bot":        "a-deepseek",
}

# 公开别名（向后兼容）
ROLE_MODEL: dict[str, str] = _ROLE_MODEL


# ═══════════════════════════════════════════════════════════════
# 公共 API
# ═══════════════════════════════════════════════════════════════

def _resolve_model(role: str) -> dict[str, Any]:
    """根据角色名查找模型池中的配置。找不到返回占位配置。"""
    key = _ROLE_MODEL.get(role, "")
    if key and key in MODEL_POOL:
        cfg = dict(MODEL_POOL[key])
        cfg.setdefault("api_key", "ollama")
        cfg.setdefault("base_url", "http://localhost:11434/v1")
        return cfg
    return {"model": "?", "api_key": "ollama", "base_url": "http://localhost:11434/v1"}


def get_config(role: str) -> dict[str, list[dict[str, Any]]]:
    """返回 AutoGen / AG2 兼容格式的 llm_config"""
    return {"config_list": [_resolve_model(role)]}


def get_model_config(role: str) -> dict[str, Any]:
    """返回角色对应的模型原始配置 {model, api_key, base_url}（推荐使用）"""
    return _resolve_model(role)


def get_model_display(role: str) -> str:
    """返回角色对应的模型名（前端展示用）"""
    return _resolve_model(role)["model"]
