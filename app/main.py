"""Public ASGI entry point for the stable application."""
from app.api.stable import app, create_app

__all__ = ["app", "create_app"]
