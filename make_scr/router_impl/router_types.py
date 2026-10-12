# router_impl/router_types.py
"""Типы результатов поиска пути в роутере.

RouteAttempt — то, что возвращает find_path. Помимо success и
path хранит признаки, полезные для диагностики и для вызывающего
кода:

  * visited, frontier — для логов и для накопления «забора»
    клеток, которые роутер не смог пройти (используется в
    fallback-логике);
  * segments — предвычисленные сегменты пути (кеш, чтобы не
    строить их повторно в _route_pair и _route_t_junction);
  * goal_reached_by — как именно сработала остановка:
        "target" — дошли до заранее выбранной клетки-ориентира;
        "goal"   — раньше target попали в клетку host-провода
                   с перпендикулярным входом («везение»);
        None     — успех не достигнут (success=False).

    Для _route_pair всегда "target" (host_cells не передаётся).
    Для _route_t_junction — "goal" или "target", в зависимости
    от того, что сработало первым.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Set

from cell import Cell
from wire import WireSegment


@dataclass
class RouteAttempt:
    """Результат одной попытки поиска пути.

    Attributes:
        success:         True, если путь найден.
        path:            клетки найденного пути, включая start и goal.
                         Пустой список при success=False.
        segments:        предвычисленные ортогональные сегменты пути.
                         Пустой список при success=False или при
                         длине path < 2.
        visited:         число клеток, вытащенных из очереди (для
                         диагностики и для ограничения MAX_VISITS).
        frontier:        множество «блокеров» — описаний клеток, в
                         которые роутер не смог войти. Используется
                         для анализа в _log_frontier.
        goal_reached_by: "target" | "goal" | None. См. описание выше.
    """
    success: bool
    path: List[Cell] = field(default_factory=list)
    segments: List[WireSegment] = field(default_factory=list)
    visited: int = 0
    frontier: Set[str] = field(default_factory=set)
    goal_reached_by: Optional[str] = None