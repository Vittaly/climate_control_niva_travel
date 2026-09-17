# make_scr/stub.py
"""Отросток от пина до первой свободной клетки за bbox.

Модель поиска tip:

    1. Реальная точка пина берётся в мм из Component:
       pin_mm = comp.abs_pin_mm(pin)
       Component сам знает anchor_page_mm и pin.offset_mm.

    2. Клетка пина — из Component:
       pin_cell = comp.abs_pin_cell(pin)
       Component сам округляет.

    3. bbox компонента — из Component:
       bbox = comp.bbox_page_cell()
       Component сам считает из anchor_page_mm + anchor_offset_mm.

    4. tip-кандидат = первая клетка ВНЕ bbox по направлению:
       NORTH: (pin_cell.col, min(pin_cell.row - 1, by0 - 1))
       SOUTH: (pin_cell.col, max(pin_cell.row + 1, by1))
       WEST:  (min(pin_cell.col - 1, bx0 - 1), pin_cell.row)
       EAST:  (max(pin_cell.col + 1, bx1), pin_cell.row)

    5. Удлинение при занятости:
       шагаем дальше по direction, пока клетка занята WireCell
       или СВОИМ пином.
       ComponentBody / чужой PinCell / превышение _MAX_STUB_EXTRA — ошибка.

    6. Провод строится от pin_mm (мм) до tip_mm (= tip * grid_mm).
       Оба конца — в мм. Пин может быть не на сетке — это нормально.

Направление (direction):
    pin.direction (KiCad «в тело») → opposite → outward (система символа)
    → apply_orientation(comp.rotation, comp.mirror) → outward на странице.
    TODO: при rotation != 0 / mirror != None Component сам пересчитает
    pin.offset_mm и bbox — stub.py не должен это делать.

============================================================
TODO (комплексная переработка, отдельной задачей)
============================================================
TODO-1. Ошибки stub → исключение StubError с контекстом.
TODO-2. Router ловит StubError и обрабатывает.
TODO-3. Поле failed в StubResult.
TODO-4. Стратегия _route_net для сетей с >2 пинами.
TODO-5. MAX_EXTRA как параметр / конфиг.
TODO-6. cells в Stub — проверить использование в Wire.
TODO-7. Единая система координат во всех логах.
TODO-8. Убрать из Router разбор «first free cell».
============================================================
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple, TYPE_CHECKING

from cell import Cell
from constants import (
    Axis,
    Direction,
    GRID_EPSILON_MM,
    WireAngle,
    direction_to_wire_angle,
    opposite_direction,
)
from logging_setup import get_logger, ctx

if TYPE_CHECKING:
    from component import Component
    from pin import Pin
    from placer import Placer
    from router_map import RouterMap

log = get_logger(__name__)


# ---------- направления и сдвиги ----------
# ANGLE_DELTA — в ЭКРАННОЙ системе (Y вниз):
#   NORTH = вверх (row - 1)
#   SOUTH = вниз  (row + 1)
#   EAST  = вправо (col + 1)
#   WEST  = влево (col - 1)

ANGLE_DELTA: Dict[WireAngle, Tuple[int, int]] = {
    WireAngle.EAST:  (+1, 0),
    WireAngle.WEST:  (-1, 0),
    WireAngle.NORTH: (0, -1),
    WireAngle.SOUTH: (0, +1),
}

ANGLE_NAME: Dict[WireAngle, str] = {
    WireAngle.EAST:  "right",
    WireAngle.WEST:  "left",
    WireAngle.NORTH: "up",
    WireAngle.SOUTH: "down",
}


_MAX_STUB_EXTRA = 20


# ---------- поворот и зеркало ----------

_ORDER: list[WireAngle] = [
    WireAngle.NORTH, WireAngle.EAST, WireAngle.SOUTH, WireAngle.WEST,
]


def rotate_angle(angle: WireAngle, rotation_deg: int) -> WireAngle:
    """Поворот по часовой стрелке на rotation_deg (0/90/180/270)."""
    idx = _ORDER.index(angle)
    steps = (rotation_deg // 90) % 4
    return _ORDER[(idx + steps) % 4]


def mirror_angle(angle: WireAngle, mirror: Optional[str]) -> WireAngle:
    """Отражение направления."""
    if mirror == "x":
        if angle == WireAngle.NORTH: return WireAngle.SOUTH
        if angle == WireAngle.SOUTH: return WireAngle.NORTH
    elif mirror == "y":
        if angle == WireAngle.EAST:  return WireAngle.WEST
        if angle == WireAngle.WEST:  return WireAngle.EAST
    return angle


def apply_orientation(angle: WireAngle, rotation: int,
                      mirror: Optional[str]) -> WireAngle:
    """Ориентация экземпляра: сначала mirror, потом rotation."""
    return rotate_angle(mirror_angle(angle, mirror), rotation)


# ---------- структуры ----------

@dataclass
class Stub:
    """Отросток от пина до первой свободной клетки за bbox."""
    pin: "Pin"
    cells: list[Cell] = field(default_factory=list)
    tip: Optional[Cell] = None
    direction: WireAngle = WireAngle.EAST
    pin_mm: Tuple[float, float] = (0.0, 0.0)
    tip_mm: Tuple[float, float] = (0.0, 0.0)
    on_grid: bool = False
    diagonal: bool = False

    @property
    def length(self) -> int:
        return len(self.cells)

    @property
    def delta_mm(self) -> Tuple[float, float]:
        return (self.tip_mm[Axis.X] - self.pin_mm[Axis.X],
                self.tip_mm[Axis.Y] - self.pin_mm[Axis.Y])


@dataclass
class StubResult:
    """Результат планирования отростка."""
    pin: "Pin"
    stub: Stub
    tip: Cell
    tip_mm: Tuple[float, float]
    on_grid: bool
    diagonal: bool
    direction: WireAngle


# ---------- внутренние хелперы ----------

def _first_cell_outside_bbox(
    pin_cell: Cell,
    direction: WireAngle,
    bbox: Tuple[int, int, int, int],
) -> Cell:
    """Первая клетка, удовлетворяющая ВСЕМ условиям:

        1) вне bbox (не входит в тело компонента);
        2) не на границе bbox (не в клетке тела);
        3) не совпадает с самим пином.

    bbox = (bx0, by0, bx1, by1) — [bx0, bx1) x [by0, by1).
    Границы тела: bx0, bx1-1, by0, by1-1. Клетка by1 (и bx1) —
    ПЕРВАЯ ЗА телом.
    """
    bx0, by0, bx1, by1 = bbox
    col, row = pin_cell.col, pin_cell.row
    dc, dr = ANGLE_DELTA[direction]

    if direction == WireAngle.NORTH:
        tip = Cell(col, min(row - 1, by0 - 1))
    elif direction == WireAngle.SOUTH:
        tip = Cell(col, max(row + 1, by1))
    elif direction == WireAngle.WEST:
        tip = Cell(min(col - 1, bx0 - 1), row)
    elif direction == WireAngle.EAST:
        tip = Cell(max(col + 1, bx1), row)
    else:
        return pin_cell

    # условие (3): tip не совпадает с пином
    guard = 0
    while (tip.col, tip.row) == (pin_cell.col, pin_cell.row):
        tip = Cell(tip.col + dc, tip.row + dr)
        guard += 1
        if guard > _MAX_STUB_EXTRA:
            break
    return tip


# ---------- планирование ----------

def plan_stub(pin: "Pin", placer: "Placer",
              router_map: "RouterMap") -> StubResult:
    """Строит отросток от пина до первой свободной клетки за bbox.

    pin_mm и pin_cell берутся из Component:
        pin_mm   = comp.abs_pin_mm(pin)     — мм, система страницы, Y↓
        pin_cell = comp.abs_pin_cell(pin)   — клетки (округление)
        bbox     = comp.bbox_page_cell()    — (col0, row0, col1, row1)

    Component сам знает anchor_page_mm, anchor_offset_mm,
    pin.offset_mm и grid_mm. stub.py их только использует.

    Направление:
        pin.direction (KiCad «в тело»)
        → opposite (outward в системе символа)
        → apply_orientation(comp.rotation, comp.mirror)
        → WireAngle в системе СТРАНИЦЫ.

    При неудаче (не удалось выйти за bbox / всё занято / чужой bbox):
        - пишется log.error;
        - возвращается вырожденный StubResult (tip = pin_cell, on_grid=True).
    """
    from occupant import ComponentBody, WireCell

    comp = pin.component
    if comp is None:
        raise ValueError(f"Пин {pin.local_key} не привязан к компоненту")

    grid_mm = comp.grid_mm

    # 1. Реальная точка пина в мм — из Component.
    pin_mm = comp.abs_pin_mm(pin)

    # 2. Клетка пина — из Component.
    pin_cell = comp.abs_pin_cell(pin)

    # 3. outward в системе символа = opposite(pin.direction)
    outward_symbol = direction_to_wire_angle(
        opposite_direction(pin.direction)
    )
    rotation = comp.rotation
    mirror = comp.mirror
    direction = apply_orientation(outward_symbol, rotation, mirror)
    dc, dr = ANGLE_DELTA[direction]

    page = comp.sheet_path or "root"

    log.debug("%s plan_stub %s direction=%s outward_symbol=%s "
              "rotation=%d mirror=%s pin_mm=(%.2f,%.2f) pin_cell=%s",
              ctx(page=page, comp=comp.designator, pin=pin.local_key),
              pin.local_key, ANGLE_NAME[direction],
              ANGLE_NAME[outward_symbol],
              rotation, mirror,
              pin_mm[Axis.X], pin_mm[Axis.Y], pin_cell)

    # 4. bbox — из Component.
    bbox = comp.bbox_page_cell()   # (bx0, by0, bx1, by1)

    # 5. tip-кандидат = первая клетка вне bbox по direction.
    tip = _first_cell_outside_bbox(pin_cell, direction, bbox)

    # 6. Удлинение при занятости.
    stub_cells: list[Cell] = []

    occupied_extra = 0
    while occupied_extra <= _MAX_STUB_EXTRA:
        occ = router_map.get((tip.col, tip.row))

        if occ is None:
            break

        if isinstance(occ, WireCell):
            stub_cells.append(tip)
            tip = Cell(tip.col + dc, tip.row + dr)
            occupied_extra += 1
            continue

        # if isinstance(occ, PinCell):
        #     # Свой пин — пропускаем.
        #     if occ.pin is pin or occ.pin.local_key == pin.local_key:
        #         stub_cells.append(tip)
        #         tip = Cell(tip.col + dc, tip.row + dr)
        #         occupied_extra += 1
        #         continue
        #     # Чужой пин — блокировка.
        #     log.error("%s stub_blocked_by_pin comp=%s.%s pin=%s tip=%s",
        #               ctx(page=page, comp=comp.designator, pin=pin.local_key),
        #               occ.component.designator, occ.pin.number,
        #               pin.local_key, tip)
        #     return _degenerate_result(
        #         pin, pin_mm, pin_cell, direction, comp, page,
        #         reason="foreign_pin",
        #     )

        if isinstance(occ, ComponentBody):
            log.error("%s stub_blocked_by_bbox comp=%s pin=%s tip=%s",
                      ctx(page=page, comp=comp.designator, pin=pin.local_key),
                      occ.component.designator, pin.local_key, tip)
            return _degenerate_result(
                pin, pin_mm, pin_cell, direction, comp, page,
                reason="foreign_bbox",
            )

        log.error("%s stub_unknown_occupant type=%s pin=%s tip=%s",
                  ctx(page=page, comp=comp.designator, pin=pin.local_key),
                  type(occ).__name__, pin.local_key, tip)
        return _degenerate_result(
            pin, pin_mm, pin_cell, direction, comp, page,
            reason="unknown_occupant",
        )
    else:
        log.error("%s stub_max_extra_exceeded limit=%d pin=%s tip=%s",
                  ctx(page=page, comp=comp.designator, pin=pin.local_key),
                  _MAX_STUB_EXTRA, pin.local_key, tip)
        return _degenerate_result(
            pin, pin_mm, pin_cell, direction, comp, page,
            reason="max_extra_exceeded",
        )

    # tip найден.
    stub_cells.append(tip)

    tip_mm = (tip.col * grid_mm, tip.row * grid_mm)

    diagonal = (
        abs(pin_mm[Axis.X] - tip_mm[Axis.X]) > GRID_EPSILON_MM or
        abs(pin_mm[Axis.Y] - tip_mm[Axis.Y]) > GRID_EPSILON_MM
    )

    log.debug("%s stub_found pin=%s tip=%s tip_mm=(%.2f,%.2f) "
              "extra=%d cells=%d",
              ctx(page=page, comp=comp.designator, pin=pin.local_key),
              pin.local_key, tip, tip_mm[Axis.X], tip_mm[Axis.Y],
              occupied_extra, len(stub_cells))

    stub = Stub(
        pin=pin,
        cells=stub_cells,
        tip=tip,
        direction=direction,
        pin_mm=pin_mm,
        tip_mm=tip_mm,
        on_grid=False,
        diagonal=diagonal,
    )
    return StubResult(
        pin=pin,
        stub=stub,
        tip=tip,
        tip_mm=tip_mm,
        on_grid=False,
        diagonal=diagonal,
        direction=direction,
    )


def _degenerate_result(
    pin: "Pin",
    pin_mm: Tuple[float, float],
    pin_cell: Cell,
    direction: WireAngle,
    comp: "Component",
    page: str,
    reason: str,
) -> StubResult:
    """Вырожденный StubResult (tip = pin_cell, on_grid=True)."""
    log.error("%s stub_failed reason=%s pin=%s pin_mm=(%.2f,%.2f) cell=%s",
              ctx(page=page, comp=comp.designator, pin=pin.local_key),
              reason, pin.local_key,
              pin_mm[Axis.X], pin_mm[Axis.Y], pin_cell)

    stub = Stub(
        pin=pin, cells=[], tip=pin_cell,
        direction=direction,
        pin_mm=pin_mm, tip_mm=pin_mm,
        on_grid=True, diagonal=False,
    )
    return StubResult(
        pin=pin, stub=stub, tip=pin_cell, tip_mm=pin_mm,
        on_grid=True, diagonal=False, direction=direction,
    )