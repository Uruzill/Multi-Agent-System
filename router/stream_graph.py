"""
流式 LangGraph 节点与工作流定义
"""

import logging
import re
import operator
import sys
import os
from typing import TypedDict, Annotated
from langgraph.graph import StateGraph, END

_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_DIR not in sys.path:
    sys.path.insert(0, _PROJECT_DIR)

from agents import create_llm, SYSTEM_PROMPTS
from tools import search_knowledge
from executor import CodeExecutor
from router.stream_state import SessionState, push

logger = logging.getLogger(__name__)

# ── LangGraph 状态定义 ──
class StreamWorkflowState(TypedDict):
    session: SessionState
    user_input: str
    lane_mode: str
    task_type: str
    complexity: str
    need_report: bool
    plan: str
    knowledge: str
    code_or_draft: str
    execution_result: str
    test_result: str
    fix_count: int
    thinking: Annotated[list, operator.add]
    final_output: str


_MAX_FIX_CYCLES = 2


# ── LangGraph 节点与路由 ──
def _route_lane(state: StreamWorkflowState) -> str:
    return "bot" if state.get("complexity") == "轻" else "planner"


def _route_task(state: StreamWorkflowState) -> str:
    task_type = state.get("task_type", "编程")
    return "writer" if task_type == "写作" else "coder"


def _route_after_executor(state: StreamWorkflowState) -> str:
    exec_result = state.get("execution_result", "")
    if "无代码" in exec_result or "无有效代码块" in exec_result:
        return "summarizer" if state.get("need_report", True) else END
    return "tester"


def _route_test(state: StreamWorkflowState) -> str:
    test_result = state.get("test_result", "")
    fix_count = state.get("fix_count", 0)
    task_type = state.get("task_type", "编程")
    need_report = state.get("need_report", True)

    if "✅" in test_result or fix_count >= _MAX_FIX_CYCLES:
        return "summarizer" if need_report else END

    return "coder" if task_type in ("编程", "分析") else "writer"


def _stream_llm(role: str, prompt: str, session: SessionState, temperature: float = 0.3) -> str:
    """辅助函数：通用 LLM 流式调用并推送到队列"""
    push(session, {"type": "agent_start", "name": role})
    llm = create_llm(role, temperature=temperature)
    content = ""
    for chunk in llm.stream(prompt):
        if session.cancel.is_set():
            push(session, {"type": "cancelled"})
            break
        text = chunk.content if hasattr(chunk, "content") else str(chunk)
        content += text
        push(session, {"type": "token", "name": role, "content": text})
    push(session, {"type": "agent_end", "name": role, "content": content})
    logger.info("stream | agent_end=%s | chars=%d", role, len(content))
    return content


def bot_node(state: StreamWorkflowState) -> dict:
    session = state["session"]
    prompt = f"{SYSTEM_PROMPTS['Bot']}\n\n用户输入: {state['user_input']}"
    content = _stream_llm("Bot", prompt, session, temperature=0.5)
    return {"final_output": content, "thinking": [{"name": "Bot", "content": content}]}


def planner_node(state: StreamWorkflowState) -> dict:
    session = state["session"]
    task_type = state.get("task_type", "编程")
    extra = ""
    if task_type == "分析":
        extra = "\n注意：这是数据分析任务。规划步骤应包含：数据加载 → 清洗 → 统计/分组 → 可视化。"
    elif task_type == "编程":
        extra = "\n注意：执行环境仅支持 Python。如用户要求 C/Java/Rust 等语言，只规划到「编写代码片段」这一步。"

    prompt = f"{SYSTEM_PROMPTS['Planner']}\n{extra}\n\n用户需求: {state['user_input']}"
    content = _stream_llm("Planner", prompt, session)
    return {"plan": content, "thinking": [{"name": "Planner", "content": content}]}


def retriever_node(state: StreamWorkflowState) -> dict:
    session = state["session"]
    push(session, {"type": "agent_start", "name": "Retriever"})
    kb_result = search_knowledge.invoke(state["user_input"])
    
    prompt = (
        f"任务：{state['user_input']}\n任务类型：{state.get('task_type', '')}\n计划：{state.get('plan', '')}\n"
        f"知识库检索结果：{kb_result}\n\n请总结与任务最相关的信息。"
    )
    llm = create_llm("Retriever")
    content = ""
    for chunk in llm.stream(prompt):
        if session.cancel.is_set():
            push(session, {"type": "cancelled"})
            break
        text = chunk.content if hasattr(chunk, "content") else str(chunk)
        content += text
        push(session, {"type": "token", "name": "Retriever", "content": text})
    push(session, {"type": "agent_end", "name": "Retriever", "content": content})
    logger.info("stream | agent_end=Retriever | chars=%d", len(content))
    return {"knowledge": content, "thinking": [{"name": "Retriever", "content": content}]}


def coder_node(state: StreamWorkflowState) -> dict:
    session = state["session"]
    task_type = state.get("task_type", "编程")
    sys_prompt = SYSTEM_PROMPTS["Coder"]
    if task_type == "分析":
        sys_prompt = (
            "你是 Python 数据分析师。你的核心职责是：**编写数据分析代码并执行**。\n"
            "1. 用 ```python ... ``` 代码块编写可直接执行的 Python 代码。\n"
            "2. 使用 pandas 读取数据、分组聚合、统计分析。\n"
            "3. 使用 matplotlib 生成图表。\n"
            "4. 代码必须包含 print() 输出关键分析结果。\n"
            "5. 不要在代码块里写「建议」「如果」「可以」——给出确定的可执行代码。"
        )

    prompt = (
        f"用户需求：{state['user_input']}\n\n任务类型：{task_type}\n\n"
        f"执行计划：{state.get('plan', '')}\n\n知识库参考：{state.get('knowledge', '')}\n\n"
    )
    if state.get("test_result") and "❌" in state.get("test_result", ""):
        prompt += f"上一次评审反馈（请据此修改代码）：\n{state.get('test_result')}\n\n"
    if state.get("execution_result") and "exitcode:" in state.get("execution_result", ""):
        prompt += f"上一次执行结果（请据此修复代码）：\n{state.get('execution_result')}\n\n"
    prompt += "请编写代码实现上述需求。"

    session_prompt = f"{sys_prompt}\n\n{prompt}"
    content = _stream_llm("Coder", session_prompt, session, temperature=0.2)
    return {"code_or_draft": content, "thinking": [{"name": "Coder", "content": content}]}


def writer_node(state: StreamWorkflowState) -> dict:
    session = state["session"]
    prompt = (
        f"用户需求：{state['user_input']}\n\n执行计划：{state.get('plan', '')}\n\n"
        f"参考资料：{state.get('knowledge', '')}\n\n"
    )
    if state.get("test_result") and "❌" in state.get("test_result", ""):
        prompt += f"上一次评审反馈（请据此修改文档）：\n{state.get('test_result')}\n\n"
    prompt += "请撰写满足需求的文档/报告。"

    session_prompt = f"{SYSTEM_PROMPTS['Writer']}\n\n{prompt}"
    content = _stream_llm("Writer", session_prompt, session, temperature=0.4)
    return {"code_or_draft": content, "thinking": [{"name": "Writer", "content": content}]}


def executor_node(state: StreamWorkflowState) -> dict:
    session = state["session"]
    code_or_draft = state.get("code_or_draft", "")
    code_blocks = re.findall(r"```(?:python)?\s*\n(.*?)```", code_or_draft, re.DOTALL)
    
    if not code_blocks:
        return {"execution_result": "（无有效代码块执行）"}
        
    push(session, {"type": "agent_start", "name": "Executor"})
    executor = CodeExecutor()
    all_results = []
    
    for i, code in enumerate(code_blocks):
        code = code.strip()
        if len(code) < 10:
            continue
        result = executor.execute(code)
        text = (
            f"--- 代码块 {i + 1} ---\n"
            f"exitcode: {result['exitcode']}\n"
            f"stdout:\n{result['stdout']}\n"
            f"stderr:\n{result['stderr']}"
        )
        all_results.append(text)
        push(session, {"type": "token", "name": "Executor", "content": text + "\n\n"})
        
    execution_result = "\n\n".join(all_results) if all_results else "（无有效代码块执行）"
    push(session, {"type": "agent_end", "name": "Executor", "content": execution_result})
    return {"execution_result": execution_result, "thinking": [{"name": "Executor", "content": execution_result}]}


def tester_node(state: StreamWorkflowState) -> dict:
    session = state["session"]
    task_type = state.get("task_type", "编程")
    code_or_draft = state.get("code_or_draft", "")
    execution_result = state.get("execution_result", "")
    
    prompt = (
        f"用户原始需求：{state['user_input']}\n\n任务类型：{task_type}\n"
        f"产出内容：\n{code_or_draft[:3000]}\n"
    )
    if "无代码" not in execution_result:
        prompt += f"执行结果：\n{execution_result}\n\n"
    prompt += "请评审上述产出是否满足用户原始需求。"
    
    session_prompt = f"{SYSTEM_PROMPTS['Tester']}\n\n{prompt}"
    content = _stream_llm("Tester", session_prompt, session, temperature=0.2)
    
    new_fix_count = state.get("fix_count", 0)
    if "❌" in content:
        new_fix_count += 1
        
    return {"test_result": content, "fix_count": new_fix_count, "thinking": [{"name": "Tester", "content": content}]}


def summarizer_node(state: StreamWorkflowState) -> dict:
    session = state["session"]
    prompt = (
        f"{SYSTEM_PROMPTS['Summarizer']}\n\n"
        "以下是一个多智能体协作过程的记录。请你据此生成一份结构化的执行报告。\n\n"
        f"## 用户需求\n{state['user_input']}\n## 任务类型\n{state.get('task_type', '')}\n"
        f"## 执行计划\n{state.get('plan', '')}\n## 产出\n{state.get('code_or_draft', '')[:3000]}\n"
        f"## 评审结果\n{state.get('test_result', '')}"
    )
    content = _stream_llm("Summarizer", prompt, session)
    return {"final_output": content, "thinking": [{"name": "Summarizer", "content": content}]}


# ── 构建 LangGraph ──
def build_stream_workflow() -> StateGraph:
    wf = StateGraph(StreamWorkflowState)

    wf.add_node("bot", bot_node)
    wf.add_node("planner", planner_node)
    wf.add_node("retriever", retriever_node)
    wf.add_node("coder", coder_node)
    wf.add_node("writer", writer_node)
    wf.add_node("executor", executor_node)
    wf.add_node("tester", tester_node)
    wf.add_node("summarizer", summarizer_node)

    wf.set_conditional_entry_point(_route_lane)

    wf.add_edge("bot", END)

    wf.add_edge("planner", "retriever")
    wf.add_conditional_edges("retriever", _route_task)
    
    wf.add_edge("coder", "executor")
    wf.add_conditional_edges("executor", _route_after_executor)
    
    wf.add_edge("writer", "tester")
    wf.add_conditional_edges("tester", _route_test)
    
    wf.add_edge("summarizer", END)

    return wf.compile()
