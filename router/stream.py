"""
流式工作流引擎 —— 管理 SSE 会话并在后台线程运行 LangGraph。
"""

import threading
import logging
import time
import os
import sys

logger = logging.getLogger(__name__)

_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_DIR not in sys.path:
    sys.path.insert(0, _PROJECT_DIR)

# 重新导出供外部路由使用
from router.stream_state import SessionState, push, push_done, _DONE
from router.stream_graph import build_stream_workflow, StreamWorkflowState
from router.classify import classify

sessions: dict[str, "SessionState"] = {}


# ── 后台 session 清理 ──
def _cleanup_loop():
    while True:
        time.sleep(120)
        now = time.time()
        expired = [sid for sid, s in list(sessions.items()) if now - s.created_at > 1800]
        for sid in expired:
            sessions.pop(sid, None)
            logger.info("stream | cleanup expired session=%s", sid)


threading.Thread(target=_cleanup_loop, daemon=True).start()


# 初始化唯一的图实例
_stream_graph = build_stream_workflow()


# ── 暴露给 router 的入口 ──
def run_workflow_streaming(data: dict, state: SessionState):
    """在后台线程运行 LangGraph 流式工作流，通过 queue 推送到 SSE。"""
    try:
        user_input = data.get("message", "")
        lane_mode = data.get("lane_mode", "auto")
        
        logger.info("stream | start langgraph pipeline | input=%s", user_input[:60])
        
        task_type, complexity, need_report = classify(user_input, lane_mode)
        
        initial_state = StreamWorkflowState(
            session=state,
            user_input=user_input,
            lane_mode=lane_mode,
            task_type=task_type,
            complexity=complexity,
            need_report=need_report,
            plan="",
            knowledge="",
            code_or_draft="",
            execution_result="",
            test_result="",
            fix_count=0,
            thinking=[],
            final_output=""
        )
        
        result_state = _stream_graph.invoke(initial_state)
        
        # 提取最终回复
        final_reply = result_state.get("final_output") or result_state.get("code_or_draft", "")
        thinking = result_state.get("thinking", [])
        
        push(state, {
            "type": "done",
            "reply": final_reply,
            "thinking": thinking,
            "task_type": result_state.get("task_type", "未知")
        })
        logger.info("stream | pipeline finished | reply_chars=%d", len(final_reply))
        
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        logger.error("stream | pipeline exception: %s\n%s", e, tb)
        push(state, {"type": "error", "content": f"{type(e).__name__}: {e}\n{tb}"})
    finally:
        push_done(state)


