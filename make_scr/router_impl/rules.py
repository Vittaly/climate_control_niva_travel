# router_impl/rules.py
"""Правила входа/выхода в клетку. Чистые функции без self.

Правила маршрутизации (один слой):
    - вход в чужой WireCell ПЕРПЕНДИКУЛЯРНО разрешён (пересечение);
    - вход в чужой WireCell ПАРАЛЛЕЛЬНО запрещён (наложение);
    - после перпендикулярного входа в чужой WireCell следующий
      шаг ПАРАЛЛЕЛЬНО чужому проводу запрещён — нельзя «въехать»
      в чужой провод и поехать вдоль него;
    - выход ПЕРПЕНДИКУЛЯРНО из чужого WireCell разрешён
      (завершение пересечения).
"""
from typing import Optional, Tuple

from cell import Cell
from constants import WireAngle
from occupant import ComponentBody, PinCell, WireCell


def in_bounds(bounds, cell: Cell) -> bool:
    """Лежит ли клетка внутри поля."""
    min_c, max_c, min_r, max_r = bounds
    return min_c <= cell.col <= max_c and min_r <= cell.row <= max_r


def can_enter(map_, bounds, cell: Cell, net: str,
              entry_angle: WireAngle) -> Tuple[bool, Optional[str]]:
    """Можно ли войти в клетку.

    Returns:
        (True, None) — можно;
        (False, описание блокера) — нельзя.
    """
    if not in_bounds(bounds, cell):
        return False, f"out of bounds {cell}"

    occ = map_.get((cell.col, cell.row))

    if occ is None:
        if has_parallel_foreign_wire(map_, cell, net, entry_angle):
            return False, f"parallel wire near {cell}"
        return True, None

    if isinstance(occ, ComponentBody):
        return False, f"box {occ.component.designator}"

    if isinstance(occ, PinCell):
        if occ.pin.net_ref == net:
            return True, None
        return False, f"pin {occ.component.designator}.{occ.pin.number}"

    if isinstance(occ, WireCell):
        if occ.wire.net_name == net:
            return True, None
        # чужой провод: вход только перпендикулярно
        if is_perpendicular(occ.wire, cell, entry_angle):
            return True, None
        return False, f"wire {occ.wire.net_name} parallel entry"

    return True, None


def can_leave(map_, cell: Cell, net: str,
              entry_angle: Optional[WireAngle],
              exit_angle: WireAngle) -> Tuple[bool, Optional[str]]:
    """Можно ли выйти из клетки в направлении exit_angle.

    Если клетка — чужой WireCell, и мы вошли в неё
    перпендикулярно чужому проводу, то выход параллельно
    чужому проводу запрещён: нельзя «въехать» в чужой провод
    и поехать вдоль него.

    Если клетка свободна или принадлежит своему проводу —
    выход всегда разрешён.

    Если entry_angle is None (стартовая клетка) — проверка
    выхода не делается.
    """
    occ = map_.get((cell.col, cell.row))
    if not isinstance(occ, WireCell):
        return True, None
    if occ.wire.net_name == net:
        return True, None

    # вошли перпендикулярно? тогда выход параллельно запрещён
    if entry_angle is not None and is_perpendicular(
            occ.wire, cell, entry_angle):
        if is_parallel(occ.wire, cell, exit_angle):
            return False, f"wire {occ.wire.net_name} parallel exit"
    return True, None


def is_perpendicular(wire, cell: Cell, angle: WireAngle) -> bool:
    """Перпендикулярно ли направление angle проводу wire в клетке.

    Провод может проходить через клетку несколькими сегментами
    (в клетке поворота). Возвращает True, если хотя бы один
    сегмент перпендикулярен заданному направлению.
    """
    for seg in wire.segments():
        if cell not in seg.cells():
            continue
        seg_h = seg.angle in (WireAngle.EAST, WireAngle.WEST)
        ang_h = angle in (WireAngle.EAST, WireAngle.WEST)
        if seg_h != ang_h:
            return True
    return False


def is_parallel(wire, cell: Cell, angle: WireAngle) -> bool:
    """Параллельно ли направление angle проводу wire в клетке.

    Провод может проходить через клетку несколькими сегментами
    (в клетке поворота). Возвращает True, если хотя бы один
    сегмент параллелен заданному направлению.
    """
    for seg in wire.segments():
        if cell not in seg.cells():
            continue
        seg_h = seg.angle in (WireAngle.EAST, WireAngle.WEST)
        ang_h = angle in (WireAngle.EAST, WireAngle.WEST)
        if seg_h == ang_h:
            return True
    return False


def has_parallel_foreign_wire(map_, cell: Cell, net: str,
                              entry_angle: WireAngle) -> bool:
    """Есть ли рядом параллельный провод чужой сети."""
    if entry_angle in (WireAngle.EAST, WireAngle.WEST):
        perp = [Cell(cell.col, cell.row - 1),
                Cell(cell.col, cell.row + 1)]
    else:
        perp = [Cell(cell.col - 1, cell.row),
                Cell(cell.col + 1, cell.row)]

    for c in perp:
        occ = map_.get((c.col, c.row))
        if isinstance(occ, WireCell) and occ.wire.net_name != net:
            return True
    return False