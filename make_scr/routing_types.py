# routing_types.py
"""Типы данных, которые роутер складывает в страницу.

Отдельный модуль — чтобы не было цикла sheet ↔ router.
"""
from __future__ import annotations

from dataclasses import dataclass

from cell import Cell


@dataclass
class FallbackLabel:
    """Метка на пине, который не удалось подключить.

    Attributes:
        net_name:  имя сети — что писать в текст метки.
        local_key: локальный ключ пина ("U2:5") — для отчёта.
        cell:      координата метки в клетках.
        reason:    почему метка появилась.
        kind:      "label" или "hierarchical_label".
    """
    net_name: str
    local_key: str
    cell: Cell
    reason: str
    kind: str = "label"


@dataclass
class TJunction:
    """T-врезка: новый отросток примыкает к существующей сети.

    Attributes:
        net_name:  имя сети.
        target:    клетка на существующем сегменте (точка врезки).
        source:    tip отростка нового пина.
        wire_key:  ключ провода-хозяина (для отчёта).
    """
    net_name: str
    target: Cell
    source: Cell
    wire_key: str = ""
