"""Authenticated local development API. Creation performs no feed reads."""
from .app import create_app

__all__ = ["create_app"]
