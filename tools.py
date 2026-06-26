"""
工具系统 —— 基于 LangChain @tool 装饰器。
所有工具返回字符串，供 Agent 调用。
"""

import os
os.environ["HF_ENDPOINT"] = os.getenv("HF_ENDPOINT", "https://hf-mirror.com")

from langchain.tools import tool

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
WORK_DIR = os.path.join(PROJECT_DIR, "coding")


def _resolve_path(path: str) -> str:
    if path.startswith("coding/"):
        return os.path.join(PROJECT_DIR, path)
    return os.path.join(WORK_DIR, path)


# ===== 文件读写 =====

@tool
def read_file(path: str) -> str:
    """读取 coding/ 目录下的文件内容。参数 path: 文件路径（如 'output.py' 或 'coding/output.py'）"""
    full_path = _resolve_path(path)
    if not os.path.exists(full_path):
        return f"[错误] 文件 {path} 不存在"
    with open(full_path, "r", encoding="utf-8") as f:
        return f.read()


@tool
def write_file(path: str, content: str) -> str:
    """将内容写入 coding/ 目录的文件。参数 path: 文件路径, content: 要写入的内容"""
    full_path = _resolve_path(path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path, "w", encoding="utf-8") as f:
        f.write(content)
    return f"[成功] 已写入 {path}"


# ===== 知识库检索 =====

@tool
def search_knowledge(query: str) -> str:
    """在知识库中搜索相关文档。输入查询字符串，返回相关文本片段（最多3条）。"""
    try:
        from rag.knowledge_base import search
        results = search(query, user_id="shared")
        if not results:
            return "知识库中未找到相关信息，请使用自身知识完成任务。"
        filtered = [r for r in results if len(r.strip()) > 50]
        if not filtered:
            return "知识库中未找到相关信息，请使用自身知识完成任务。"
        return "\n\n---\n\n".join(filtered[:3])
    except Exception as e:
        return f"[检索失败] {e}"


# ===== 计算器 =====

@tool
def calculate(expression: str) -> str:
    """安全计算数学表达式。支持 +, -, *, /, **, %, 以及 abs/round/min/max/pow/int/float。参数 expression: 数学表达式字符串，如 '2+3*4'"""
    import ast
    import operator as _op

    _SAFE_BUILTINS = {"abs": abs, "round": round, "min": min, "max": max,
                      "pow": pow, "int": int, "float": float, "len": len}
    _SAFE_OPS = {
        ast.Add: _op.add, ast.Sub: _op.sub, ast.Mult: _op.mul,
        ast.Div: _op.truediv, ast.FloorDiv: _op.floordiv,
        ast.Mod: _op.mod, ast.Pow: _op.pow, ast.USub: _op.neg,
    }

    def _eval(node):
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.BinOp):
            op = _SAFE_OPS.get(type(node.op))
            if op is None:
                raise ValueError(f"不支持的操作符: {type(node.op).__name__}")
            return op(_eval(node.left), _eval(node.right))
        if isinstance(node, ast.UnaryOp):
            op = _SAFE_OPS.get(type(node.op))
            if op is None:
                raise ValueError(f"不支持的操作符: {type(node.op).__name__}")
            return op(_eval(node.operand))
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in _SAFE_BUILTINS:
                args = [_eval(a) for a in node.args]
                return _SAFE_BUILTINS[node.func.id](*args)
            raise ValueError("仅支持内置函数: abs, round, min, max, pow, int, float, len")
        raise ValueError(f"不支持的表达式类型: {type(node).__name__}")

    try:
        tree = ast.parse(expression.strip(), mode="eval")
        result = _eval(tree)
        return str(result)
    except Exception as e:
        return f"[计算错误] {e}"


# ===== 数据分析 =====

@tool
def analyze_data(path: str, group_by: str = "", agg_col: str = "") -> str:
    """分析 CSV/Excel 文件：按指定列分组求和，返回降序结果。
    参数 path: 文件路径, group_by: 分组列名（留空自动选）, agg_col: 汇总列名（留空自动选）"""
    full_path = _resolve_path(path)
    if not os.path.exists(full_path):
        return f"[错误] 文件 {path} 不存在"
    try:
        import pandas as pd
    except ImportError:
        return "[错误] pandas 未安装，请执行 pip install pandas"
    try:
        if path.endswith(".csv"):
            df = pd.read_csv(full_path)
        elif path.endswith((".xlsx", ".xls")):
            df = pd.read_excel(full_path)
        else:
            return "[错误] 仅支持 .csv / .xlsx / .xls 文件"

        col_info = f"列名: {list(df.columns)}（共 {len(df)} 行）\n"
        num_cols = df.select_dtypes(include=["number"]).columns.tolist()
        obj_cols = df.select_dtypes(exclude=["number"]).columns.tolist()
        gb = group_by if group_by in df.columns else (obj_cols[0] if obj_cols else "")
        ac = agg_col if agg_col in df.columns else (num_cols[0] if num_cols else "")

        if not gb or not ac:
            return col_info + "[提示] 未能自动识别分组列和数值列，请指定 group_by 和 agg_col 参数"

        result = df.groupby(gb)[ac].sum().sort_values(ascending=False)
        lines = [f"{k}: {v}" for k, v in result.items()]
        return col_info + "\n".join(lines[:50])
    except Exception as e:
        return f"[分析错误] {e}"


# ===== 数据可视化 (Pillow) =====

@tool
def visualize_data(path: str, chart_type: str = "bar", save_as: str = "chart.png",
                   group_by: str = "", agg_col: str = "") -> str:
    """读取 CSV 用 Pillow 绘制统计图表（柱状图/折线图）并保存。
    参数 path: CSV 文件路径, chart_type: 'bar'或'line', save_as: 输出文件名,
    group_by: 分组列名（留空自动选）, agg_col: 汇总列名（留空自动选）"""
    full_path = _resolve_path(path)
    if not os.path.exists(full_path):
        return f"[错误] 文件 {path} 不存在"

    try:
        import pandas as pd
    except ImportError:
        return "[错误] pandas 未安装"
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return "[错误] Pillow 未安装，请执行 pip install Pillow"

    _FONT_PATHS = os.environ.get("FONT_PATH", "").split(os.pathsep) if os.environ.get("FONT_PATH") else [
        # Windows
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "C:/Windows/Fonts/simsun.ttc",
        # macOS
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
        # Linux
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ]
    _cjk_font = None
    _title_font = None
    for fp in _FONT_PATHS:
        if os.path.exists(fp):
            try:
                _cjk_font = ImageFont.truetype(fp, 14)
                _title_font = ImageFont.truetype(fp, 22)
                break
            except Exception:
                continue

    try:
        df = pd.read_csv(full_path)
    except Exception as e:
        return f"[错误] 无法读取 CSV: {e}"

    if group_by and group_by in df.columns and agg_col and agg_col in df.columns:
        df = df.groupby(group_by, as_index=False)[agg_col].sum().sort_values(agg_col, ascending=False)

    num_cols = df.select_dtypes(include=["number"]).columns
    obj_cols = df.select_dtypes(exclude=["number"]).columns
    if len(obj_cols) == 0 or len(num_cols) == 0:
        return "[错误] CSV 需至少包含一列文本和一列数值"

    label_col = obj_cols[0]
    val_col = num_cols[0]
    labels = df[label_col].astype(str).tolist()
    values = df[val_col].tolist()
    max_val = max(values) if values else 1
    n = len(labels)

    W, H = 800, 500
    ML, MR, MT, MB = 80, 40, 60, 80
    CW, CH = W - ML - MR, H - MT - MB

    img = Image.new("RGB", (W, H), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    title = f"{label_col} × {val_col}" if group_by else f"{label_col} 汇总"
    if _title_font:
        draw.text((ML, 10), title, fill=(30, 30, 30), font=_title_font)

    if chart_type == "line":
        draw.line([ML, MT, ML, H - MB], fill="black", width=2)
        draw.line([ML, H - MB, W - MR, H - MB], fill="black", width=2)
        for i in range(6):
            y_val = max_val * i / 5
            y = H - MB - int(CH * i / 5)
            draw.line([ML - 5, y, ML, y], fill="black")
            if _cjk_font:
                draw.text((5, y - 8), f"{y_val:.0f}", fill="black", font=_cjk_font)
        pts = []
        for i, (label, val) in enumerate(zip(labels, values)):
            x = ML + i * CW // (n - 1) if n > 1 else ML + CW // 2
            y = H - MB - int((val / max_val) * CH)
            pts.append((x, y))
            draw.ellipse([x - 4, y - 4, x + 4, y + 4], fill=(66, 133, 244))
            if _cjk_font:
                draw.text((x - 12, H - MB + 5), label[:6], fill="black", font=_cjk_font)
        for i in range(1, len(pts)):
            draw.line([pts[i - 1], pts[i]], fill=(66, 133, 244), width=3)
    else:
        step = CW // n if n > 0 else CW
        bar_w = min(step // 3, 36)
        draw.line([ML, MT, ML, H - MB], fill="black", width=2)
        draw.line([ML, H - MB, W - MR, H - MB], fill="black", width=2)
        for i in range(6):
            y_val = max_val * i / 5
            y = H - MB - int(CH * i / 5)
            draw.line([ML - 5, y, ML, y], fill="black")
            if _cjk_font:
                draw.text((5, y - 8), f"{y_val:.0f}", fill="black", font=_cjk_font)
        for i, (label, val) in enumerate(zip(labels, values)):
            x_c = ML + i * step + step // 2
            bh = int((val / max_val) * CH)
            x0, y0 = x_c - bar_w // 2, H - MB - bh
            x1, y1 = x_c + bar_w // 2, H - MB
            draw.rectangle([x0, y0, x1, y1], fill=(66, 133, 244), outline=(40, 100, 200))
            if _cjk_font:
                draw.text((x_c - 10, H - MB + 5), label[:6], fill="black", font=_cjk_font)

    full_save = os.path.join(WORK_DIR, save_as)
    img.save(full_save)
    return f"[成功] 图表已保存至 {save_as}（{len(labels)} 条{chart_type}图）"


# ===== OCR (Tesseract) =====

@tool
def ocr_image(image_path: str, language: str = "chi_sim+eng") -> str:
    """从图片中提取文字（OCR）。支持中英文混合识别。
    参数 image_path: 图片文件路径（PNG/JPG等）, language: OCR语言代码（默认 chi_sim+eng）"""
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return "[错误] pytesseract 或 Pillow 未安装"

    full_path = _resolve_path(image_path)
    if not os.path.exists(full_path):
        return f"[错误] 图片 {image_path} 不存在"

    try:
        img = Image.open(full_path)
        text = pytesseract.image_to_string(img, lang=language)
        return text.strip() or "[提示] 图片中未识别到文字"
    except Exception as e:
        return f"[OCR错误] {e}"


# ===== 工具字典 =====

ALL_TOOLS = {
    "read_file": read_file,
    "write_file": write_file,
    "search_knowledge": search_knowledge,
    "calculate": calculate,
    "analyze_data": analyze_data,
    "visualize_data": visualize_data,
    "ocr_image": ocr_image,
}
