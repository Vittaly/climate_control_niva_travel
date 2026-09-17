# router_impl/types.py
"""Типы роутера. RouteAttempt — результат поиска пути."""
from dataclasses import dataclass, field
from typing import List, Set

from cell import Cell
from wire import WireSegment


@dataclass
class RouteAttempt:
    """Результат Dijkstra между двумя точками.

    Attributes:
        success:  удалось ли найти путь.
        path:     клетки пути (без отростков).
        segments: разбивка пути на сегменты.
        visited:  сколько клеток посетил Dijkstra.
        frontier: описания блокеров, помешавших пройти.
    """
    success: bool
    path: List[Cell] = field(default_factory=list)
    segments: List[WireSegment] = field(default_factory=list)
    visited: int = 0
    frontier: Set[str] = field(default_factory=set)