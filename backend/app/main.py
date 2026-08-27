"""Uvicorn 应用入口；建议仅监听 127.0.0.1。"""

from app.api import create_app

app = create_app()
