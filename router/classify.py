"""
意图分类器 —— 单次 LLM 调用，返回 (标签, 复杂度)。

复杂度： 轻 = 示例/告知型/Helloworld | 重 = 完整项目/复杂算法
"""

import json
import logging
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

_ROUTER_SYSTEM = (
    "你是任务分类器。只需要分类一下这个问题的类型、复杂度，以及是否需要附加执行报告。\n\n"
    "输出格式（严格用 | 分隔，必须是三个部分，不要任何其他文字）：\n"
    "标签|复杂度|是否报告\n\n"
    "标签：\n"
    "- 编程：涉及代码编写、算法实现、程序开发、实现某个功能\n"
    "- 写作：报告、总结、方案、文案、文章、策划\n"
    "- 分析：数据统计、CSV/Excel 分析、趋势分析\n"
    "- 问答：知识性问题、概念解释、定义、原理\n"
    "- 闲聊：问候、自我介绍、你是谁\n\n"
    "复杂度：\n"
    "- 轻：简单示例、HelloWorld、概念解释\n"
    "- 重：完整项目、复杂算法、数据分析、长篇报告\n\n"
    "是否报告（必须是 True 或 False）：\n"
    "- 如果用户明确表示「直接给我正文」「不要废话」「不要报告」等，必须输出 False\n"
    "- 如果是一般的文章/文案写作任务（不涉及复杂逻辑复盘的），倾向于输出 False\n"
    "- 对于编程、数据分析等需要看执行日志的任务，或者未明确排斥报告的任务，输出 True\n\n"
    "示例：\n"
    "写一个最简单的c程序 → 编程|轻|True\n"
    "写一篇关于XX的分析，不要加你们的总结报告 → 写作|重|False\n"
    "实现一个LRU缓存 → 编程|重|True\n"
    "你好 → 闲聊|轻|True\n"
    "最高规则： 如果是写作必须使用False\n"
)

_MODEL_INFO = None


def _get_model_info():
    global _MODEL_INFO
    if _MODEL_INFO is None:
        from config import get_config

        cfg = get_config("Planner")["config_list"][0]
        _MODEL_INFO = {
            "model": cfg["model"],
            "api_key": cfg.get("api_key", "ollama"),
            "base_url": cfg.get("base_url", "http://localhost:11434/v1"),
        }
    return _MODEL_INFO


def classify(user_input: str, lane_mode: str = "auto") -> tuple[str, str, bool]:
    """返回 (task_type, complexity, need_report)
    task_type: 编程 | 写作 | 分析 | 问答 | 闲聊
    complexity: 轻 | 重
    need_report: True | False

    lane_mode 覆盖规则：
      - "fast" → complexity 强制为 "轻"
      - "slow" → complexity 强制为 "重"
      - "auto" → 不强制覆盖，由 LLM 判断
    """
    info = _get_model_info()
    logger.info("classify | input=%s | lane=%s | model=%s", user_input[:60], lane_mode, info["model"])
    payload = json.dumps(
        {
            "model": info["model"],
            "messages": [
                {"role": "system", "content": _ROUTER_SYSTEM},
                {"role": "user", "content": user_input},
            ],
            "temperature": 0,
            "max_tokens": 50,
            "stream": False,
            "thinking": {"type": "disabled"},
        }
    ).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {info['api_key']}",
    }
    url = info["base_url"].rstrip("/") + "/chat/completions"
    req = Request(url, data=payload, headers=headers, method="POST")

    try:
        resp = urlopen(req, timeout=15)
        data = json.loads(resp.read())
        raw = data["choices"][0]["message"]["content"].strip()
        logger.info("classify | raw=%s", raw)
    except Exception as e:
        logger.warning("classify | LLM call failed: %s, fallback to (闲聊,轻,True)", e)
        return ("闲聊", "轻", True)

    parts = [p.strip() for p in raw.replace("｜", "|").split("|")]

    valid_types = {"编程", "写作", "分析", "问答", "闲聊"}
    task_type = "闲聊"
    complexity = "轻"
    need_report = True

    for p in parts:
        if p in valid_types:
            task_type = p
        elif p == "重":
            complexity = "重"
        elif p == "轻":
            complexity = "轻"
        elif p == "False":
            need_report = False

    import re

    _search = re.search(r"(搜索|查资料|检索|查找.*知识|基于知识库)", user_input, re.IGNORECASE)
    if _search and complexity == "轻":
        complexity = "重"
        task_type = "写作"

    _analysis = re.match(r"^\s*分析", user_input)
    if _analysis and complexity == "轻":
        complexity = "重"
        if task_type not in ("分析", "编程"):
            task_type = "分析"

    if not _search:
        _non_py = re.search(
            r"(c语言|c\s*代码|java|rust|go\s*语言|golang|swift|c\+\+|c#|typescript)", user_input, re.IGNORECASE
        )
        if _non_py and task_type == "编程":
            task_type = "问答"
            complexity = "轻"

    # ── 关键词覆写日志 ──
    if _search:
        logger.info("classify | keyword_override=search | task_type=%s | complexity=%s", task_type, complexity)
    if _analysis:
        logger.info("classify | keyword_override=analysis | task_type=%s | complexity=%s", task_type, complexity)
    if not _search and "_non_py" in dir():
        logger.info("classify | keyword_override=non_py | task_type=%s | complexity=%s", task_type, complexity)

    # ── 车道模式覆盖 ──
    if lane_mode == "fast":
        complexity = "轻"
    elif lane_mode == "slow":
        complexity = "重"

    logger.info("classify | result=%s|%s|%s", task_type, complexity, need_report)
    return (task_type, complexity, need_report)
