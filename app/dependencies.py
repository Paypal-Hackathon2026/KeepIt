"""
Auth dependency — backward-compatible alias.

The canonical implementation lives in app.deps.current_user.
This module re-exports it as get_current_user so that existing
route imports (from app.dependencies import get_current_user) keep working.
"""

from app.deps import current_user as get_current_user

__all__ = ["get_current_user"]
