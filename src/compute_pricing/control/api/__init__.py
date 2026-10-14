"""Authenticated local development API. Construction performs no feed reads.

An explicitly configured application lifecycle may run approved public reads.
"""
from .app import create_app

__all__ = ["create_app"]
