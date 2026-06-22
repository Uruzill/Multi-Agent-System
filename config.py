"""
LLM 配置。

【第一次使用？】
  1. 设置 DEEPSEEK_API_KEY 环境变量（PyCharm: Run → Edit Config → Env）
  2. 在下方 MODEL_POOL 添加你的模型：
     - 格式： "编号-标签": {"model": "模型名", "api_key": ..., "base_url": ...}
     - api_key 值：
       * 云端 API (DeepSeek / OpenAI 等) → os.getenv("你的环境变量名")
       * 本地 Ollama → "ollama"
       * 直写字符串（仅测试用，不要提交代码库）
  3. 在 ROLE_MODEL 里给每个角色指定要用的模型（填 MODEL_POOL 的 key）
  4. pip install -r requirements.txt
  5. streamlit run main.py

【示例：添加 GPT-4o】
  MODEL_POOL = {
      "a-deepseek": {...},
      "b-qwen": {...},
      "c-gpt4o": {"model": "gpt-4o-mini",
                  "api_key": os.getenv("OPENAI_API_KEY"),
                  "base_url": "https://api.openai.com/v1"},
  }
  ROLE_MODEL = {"Planner": "c-gpt4o", ...}  # 引号内填 MODEL_POOL 的 key
"""

import os
from dotenv import load_dotenv
load_dotenv()

# ===== 模型池 =====
# 在这里添加你的所有模型，格式：
#   "编号-标签": {"model": "...", "api_key": ..., "base_url": "..."}
# api_key 支持三种写法：
#   os.getenv("VAR")  — 环境变量（推荐）
#   "ollama"          — 本地 Ollama
#   "sk-xxx"          — 直写 Key（不安全，仅测试）
MODEL_POOL = {
    "a-deepseek": {
        "model": "deepseek-v4-flash",
        "api_key": os.getenv("DEEPSEEK_API_KEY"),
        "base_url": "https://api.deepseek.com/v1",
        "price": [0.001, 0.001],
    },
    "b-qwen": {
        "model": "qwen2.5:7b",
        "api_key": "ollama",
        "base_url": "http://localhost:11434/v1",
    },
}

# ===== 角色-模型对应表 =====
# 把 role-model 的值改成上面 MODEL_POOL 的 key 即可
ROLE_MODEL = {
    "Planner":    "a-deepseek",
    "Retriever":  "a-deepseek",
    "Coder":      "a-deepseek",
    "Tester":     "a-deepseek",
    "Writer":     "a-deepseek",
    "Summarizer": "a-deepseek",
    "Bot":        "a-deepseek",
}


def get_config(role: str) -> dict:
    """返回 AG2 兼容的 llm_config"""
    key = ROLE_MODEL[role]
    cfg = dict(MODEL_POOL[key])
    return {"config_list": [cfg]}


def get_model_display(role: str) -> str:
    """返回前端显示的模型名"""
    key = ROLE_MODEL[role]
    return MODEL_POOL[key]["model"]
