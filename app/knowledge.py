"""知识库管理 API 路由。"""
import os
from fastapi import APIRouter, UploadFile, File, Depends
from fastapi.responses import JSONResponse

from user.helpers import require_auth

router = APIRouter()

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ALLOWED_EXTENSIONS = {"pdf", "txt", "png", "jpg", "jpeg"}


def _get_user_kb_dirs(user_id: str):
    """返回 (documents_dir, chroma_db_dir)，按 user_id 物理隔离。
    目录不存在时自动创建。"""
    docs = os.path.join(_BASE, "rag", "documents", user_id)
    chroma = os.path.join(_BASE, "rag", "chroma_db", user_id)
    os.makedirs(docs, exist_ok=True)
    os.makedirs(chroma, exist_ok=True)
    return docs, chroma


@router.get("/files")
async def kb_files(user: dict = Depends(require_auth)):
    """列出用户知识库中的文件"""
    docs_dir, _ = _get_user_kb_dirs(user["user_id"])
    files = []
    for fname in os.listdir(docs_dir):
        fpath = os.path.join(docs_dir, fname)
        if os.path.isfile(fpath) and fname.rsplit(".", 1)[-1].lower() in ALLOWED_EXTENSIONS:
            files.append({"name": fname, "size": os.path.getsize(fpath)})
    return JSONResponse(files)


@router.get("/stats")
async def kb_stats(user: dict = Depends(require_auth)):
    from rag.knowledge_base import get_stats
    return JSONResponse(get_stats(user["user_id"]))


@router.post("/rebuild")
async def kb_rebuild(user: dict = Depends(require_auth)):
    from rag.knowledge_base import build_index
    n = build_index(user["user_id"])
    return JSONResponse({"success": True, "added": n})


@router.post("/upload")
async def kb_upload(file: UploadFile = File(...), user: dict = Depends(require_auth)):
    docs_dir, _ = _get_user_kb_dirs(user["user_id"])

    # Sanitize filename to prevent path traversal
    safe_name = os.path.basename(file.filename)
    ext = safe_name.rsplit(".", 1)[-1].lower() if "." in safe_name else ""

    if ext not in ALLOWED_EXTENSIONS:
        return JSONResponse(
            {"success": False, "error": f"不支持的文件类型: .{ext}"},
            status_code=400,
        )

    if ext in ("png", "jpg", "jpeg"):
        try:
            from PIL import Image
            import pytesseract
            import io

            contents = await file.read()
            img = Image.open(io.BytesIO(contents))
            text = pytesseract.image_to_string(img, lang="chi_sim+eng")

            if not text.strip():
                return JSONResponse({"success": False, "error": "图片中未识别到文字"}, status_code=400)

            txt_name = safe_name.rsplit(".", 1)[0] + "_ocr.txt"
            txt_path = os.path.join(docs_dir, os.path.basename(txt_name))
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(text)
            return JSONResponse({"success": True, "filename": txt_name, "ocr": True})
        except ImportError as e:
            return JSONResponse({"success": False, "error": f"依赖未安装: {e}"}, status_code=500)
        except Exception as e:
            return JSONResponse({"success": False, "error": f"OCR 失败: {e}"}, status_code=500)
    else:
        doc_path = os.path.join(docs_dir, safe_name)
        contents = await file.read()
        with open(doc_path, "wb") as f:
            f.write(contents)
        return JSONResponse({"success": True, "filename": safe_name})


@router.delete("/{filename}")
async def kb_delete(filename: str, user: dict = Depends(require_auth)):
    safe_name = os.path.basename(filename)
    docs_dir, _ = _get_user_kb_dirs(user["user_id"])
    path = os.path.join(docs_dir, safe_name)
    if not os.path.exists(path):
        return JSONResponse({"success": False, "error": "文件不存在"}, status_code=404)
    try:
        os.remove(path)
    except OSError as e:
        return JSONResponse({"success": False, "error": f"删除失败: {e}"}, status_code=500)
    return JSONResponse({"success": True})
