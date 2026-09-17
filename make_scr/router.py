# router.py
"""Публичный фасад роутера.

Импорт: from router import Router, RouteAttempt
Реализация: router_impl/.
"""
from router_impl.router_impl import Router
from router_impl.router_types import RouteAttempt

__all__ = ["Router", "RouteAttempt"]