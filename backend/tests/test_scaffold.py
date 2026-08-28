from fastapi import FastAPI

from app.main import app


def test_application_scaffold_is_importable() -> None:
    assert isinstance(app, FastAPI)
    assert app.title == "CodeAgent"
