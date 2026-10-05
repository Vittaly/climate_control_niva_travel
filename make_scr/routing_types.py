# routing_types.py
"""Типы данных, которые роутер складывает в страницу.

Отдельный модуль — чтобы не было цикла sheet ↔ router.
"""
from __future__ import annotations

from dataclasses import dataclass

from cell import Cell

from typing import Tuple
from constants import Direction






