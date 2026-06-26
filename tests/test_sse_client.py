"""
模拟后台调用，在终端中直接展示流式 SSE 输出效果（免依赖 httpx）
"""

import asyncio
import threading
import time
import json
import sys
import os

# 把项目根目录加到 sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from router.stream_state import SessionState, _DONE
from router.stream import run_workflow_streaming


async def run_test():
    print("====== 1. 模拟 /chat/start 启动工作流 ======")
    user_input = "以毛泽东词句风雷动，旌旗奋，是人寰为核心立意，撰写一篇 200 字议论文，"
    print(f"用户输入: {user_input}\n")

    # 构造并初始化 session
    state = SessionState(
        queue=asyncio.Queue(),
        cancel=threading.Event(),
        loop=asyncio.get_running_loop(),
        created_at=time.time(),
    )

    # 模拟 HTTP 参数
    data = {"message": user_input, "lane_mode": "slow", "history": []}

    # 在后台线程运行
    thread = threading.Thread(
        target=run_workflow_streaming,
        args=(data, state),
        daemon=True,
    )
    thread.start()

    print("====== 2. 模拟 SSE 连接，开始接收推送 ======")
    while True:
        event = await state.queue.get()
        if event is _DONE:
            break

        type_ = event.get("type")

        if type_ == "agent_start":
            print(f"\n\n[🚀 {event.get('name')} 开始执行]")
        elif type_ == "agent_end":
            print(f"\n[✅ {event.get('name')} 执行完毕]")
        elif type_ == "token":
            # 流式打印 token
            print(event.get("content", ""), end="", flush=True)
        elif type_ == "error":
            print(f"\n\n[❌ 错误] {event.get('content')}")
        elif type_ == "done":
            print("\n\n[🎉 工作流全部完成]")

    print("\n流式传输已结束。")


if __name__ == "__main__":
    asyncio.run(run_test())
