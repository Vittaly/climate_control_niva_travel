# router_impl/rules.py
"""Правила входа/выхода в клетку. Чистые функции без self.

Модель: клетка может быть занята до ДВУМЯ проводами разных сетей,
если оба проходят через неё ТРАНЗИТОМ и перпендикулярно друг другу.
Один endpoint (пин, T-врезка, конец пути, угол) — блокирует клетку
для чужой сети монопольно.

Правила:
    - ComponentBody — стена;
    - PinCell — endpoint, чужая сеть не входит;
    - WireCell:
        * своя сеть — всегда ок;
        * чужая с is_endpoint — запрещено;
        * чужая транзитная перпендикулярно к входу — разрешено;
        * чужая транзитная параллельно — запрещено;
    - пустая клетка — ок.

has_parallel_foreign_wire больше не нужен: прямой чек по всем
usage в клетке (включая corner как две ориентации) закрывает
все случаи, ради которых он был введён.
"""
from typing import List, Optional, Tuple

from cell import Cell
from constants import WireAngle, WireOrientation
from occupant import ComponentBody, PinCell, WireCell


# =========================================================
# Определение ориентации и endpoint провода в клетке
# =========================================================



def _orientations_at(wire, cell: Cell) -> List[WireOrientation]:
    """Ориентации сегментов провода, проходящих через клетку.

    Возвращает:
        []              — провод не проходит через клетку;
        [HORIZONTAL]    — прямолинейный проход по горизонтали;
        [VERTICAL]      — прямолинейный проход по вертикали;
        [DIAGONAL]      — диагональный сегмент;
        [H, V]          — угол (провод поворачивает в этой клетке).
    """
    c, r = cell.col, cell.row
    result: List[WireOrientation] = []
    for seg in wire.segments():
        if seg.contains_cell(c, r):
            result.append(seg.orientation)
    return result


def _is_endpoint_at(wire, cell: Cell) -> bool:
    """Является ли клетка endpoint провода.

    Endpoint — пин, T-врезка, концы path. Угол провода — не
    endpoint, но он «блокирует» клетку через наличие двух
    ориентаций (см. _orientations_at).
    """
    # Пин start
    if wire.start is not None and wire.start.component is not None:
        if wire.start.component.abs_pin_cell(wire.start) == cell:
            return True
    # Пин end (не T)
    if (wire.end is not None
            and not getattr(wire, "t_junction", False)
            and wire.end.component is not None):
        if wire.end.component.abs_pin_cell(wire.end) == cell:
            return True
    # T-точка
    if getattr(wire, "t_junction", False) and wire.path:
        if wire.path[-1] == cell:
            return True
    # Концы path
    if wire.path:
        if wire.path[0] == cell or wire.path[-1] == cell:
            return True
    return False


def _check_entry(orients: List[WireOrientation],
                 is_endpoint: bool,
                 entry_angle: WireAngle,
                 entry_is_endpoint: bool,
                 foreign_net: str) -> Optional[str]:
    """Проверяет совместимость чужого usage с нашим входом.

    Возвращает причину конфликта или None.
    """
    if is_endpoint:
        return f"foreign endpoint {foreign_net}"
    if entry_is_endpoint:
        return f"our endpoint into {foreign_net}"
    if WireOrientation.DIAGONAL in orients:
        return f"foreign diagonal {foreign_net}"

    # наш вход — горизонтальный/вертикальный
    entry_h = entry_angle in (WireAngle.EAST, WireAngle.WEST)

    for o in orients:
        o_h = (o == WireOrientation.HORIZONTAL)
        if o_h == entry_h:
            # параллельно — конфликт
            return f"wire {foreign_net} parallel entry"
    return None


# =========================================================
# Публичные проверки
# =========================================================

def in_bounds(bounds, cell: Cell) -> bool:
    """Лежит ли клетка внутри поля."""
    min_c, max_c, min_r, max_r = bounds
    return min_c <= cell.col <= max_c and min_r <= cell.row <= max_r


def can_enter(map_, bounds, cell: Cell, net: str,
              entry_angle: WireAngle,
              entry_is_endpoint: bool = False
              ) -> Tuple[bool, Optional[str]]:
    """Можно ли войти в клетку.

    Args:
        map_: карта занятости.
        bounds: границы поля.
        cell: клетка входа.
        net: имя нашей сети.
        entry_angle: направление входа (EAST/WEST/NORTH/SOUTH).
        entry_is_endpoint: True, если наша клетка — endpoint
            (пин, T-врезка, конец path). Тогда любая чужая usage
            в клетке блокирует вход.
    """
    if not in_bounds(bounds, cell):
        return False, f"out of bounds {cell}"

    occ = map_.get((cell.col, cell.row))
    if occ is None:
        return True, None

    if isinstance(occ, ComponentBody):
        return False, f"box {occ.component.designator}"

    if isinstance(occ, PinCell):
        if occ.pin.net_ref == net:
            return True, None
        return False, f"pin {occ.component.designator}.{occ.pin.number}"

    if isinstance(occ, WireCell):
        for w in occ.wires:
            if w.net_name == net:
                continue
            orients = _orientations_at(w, cell)
            is_endpoint = _is_endpoint_at(w, cell)
            reason = _check_entry(orients, is_endpoint,
                                  entry_angle, entry_is_endpoint,
                                  w.net_name)
            if reason is not None:
                return False, reason
        return True, None

    return True, None


def can_leave(map_, cell: Cell, net: str,
              entry_angle: Optional[WireAngle],
              exit_angle: WireAngle,
              exit_is_endpoint: bool = False
              ) -> Tuple[bool, Optional[str]]:
    """Можно ли выйти из клетки в направлении exit_angle.

    Симметрично can_enter: если клетка содержит чужой транзитный
    провод, выход должен быть перпендикулярен ему.
    """
    occ = map_.get((cell.col, cell.row))
    if not isinstance(occ, WireCell):
        return True, None

    for w in occ.wires:
        if w.net_name == net:
            continue
        orients = _orientations_at(w, cell)
        is_endpoint = _is_endpoint_at(w, cell)
        reason = _check_entry(orients, is_endpoint,
                              exit_angle, exit_is_endpoint,
                              w.net_name)
        if reason is not None:
            return False, f"exit: {reason}"
    return True, None


# =========================================================
# Совместимость со старым API
# =========================================================

def is_perpendicular(wire, cell: Cell, angle: WireAngle) -> bool:
    """Перпендикулярен ли angle ориентации провода в клетке.

    True, если хотя бы одна ориентация провода в клетке
    перпендикулярна angle. Для угла (H+V) — да, для любой angle
    одна из ориентаций окажется параллельной, а другая
    перпендикулярной.
    """
    orients = _orientations_at(wire, cell)
    if not orients or WireOrientation.DIAGONAL in orients:
        return False
    ang_h = angle in (WireAngle.EAST, WireAngle.WEST)
    for o in orients:
        o_h = (o == WireOrientation.HORIZONTAL)
        if o_h != ang_h:
            return True
    return False


def is_parallel(wire, cell: Cell, angle: WireAngle) -> bool:
    """Параллелен ли angle ориентации провода в клетке."""
    orients = _orientations_at(wire, cell)
    if not orients or WireOrientation.DIAGONAL in orients:
        return False
    ang_h = angle in (WireAngle.EAST, WireAngle.WEST)
    for o in orients:
        o_h = (o == WireOrientation.HORIZONTAL)
        if o_h == ang_h:
            return True
    return False