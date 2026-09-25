# wire.py
"""Провод: сегменты, отростки, точки T-соединений.

Провод хранит:
    - путь (клетки основного маршрута, строго ортогонального);
    - отростки start_stub / end_stub (ссылки на stub.Stub);
    - признак T-врезки для проводов, присоединяющих пин к сети.

Отростки физически живут в stub.py; здесь — только ссылки на них.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, TYPE_CHECKING

from cell import Cell
from constants import (
    WIRE_ANGLE_TO_ORIENTATION,
    WireAngle,
    WireOrientation,
)

if TYPE_CHECKING:
    from pin import Pin
    from stub import Stub


def segment_angle(a: Cell, b: Cell) -> Optional[WireAngle]:
    """Угол сегмента между двумя соседними клетками.

    Returns:
        WireAngle для ортогонального перехода,
        None для диагонали или совпадающих клеток.
    """
    dc = b.col - a.col
    dr = b.row - a.row
    if dc == 0 and dr == 0:
        return None
    if dr == 0:
        return WireAngle.EAST if dc > 0 else WireAngle.WEST
    if dc == 0:
        return WireAngle.SOUTH if dr > 0 else WireAngle.NORTH
    return None


@dataclass(frozen=True)
class WireSegment:
    """Один прямолинейный сегмент провода.

    Основной маршрут — только ортогональные сегменты (angle не None).
    Отростки могут быть диагональными (angle is None), если пин
    компонента не попадает на сетку.
    """
    start: Cell
    end: Cell
    angle: Optional[WireAngle]

    @property
    def orientation(self) -> WireOrientation:
        """Ориентация сегмента: HORIZONTAL / VERTICAL / DIAGONAL."""
        if self.angle is None:
            return WireOrientation.DIAGONAL
        return WIRE_ANGLE_TO_ORIENTATION[self.angle]

    @property
    def is_diagonal(self) -> bool:
        """Диагональный ли сегмент."""
        return self.angle is None

    @property
    def length(self) -> int:
        """Длина сегмента в шагах сетки."""
        return abs(self.start.col - self.end.col) + \
               abs(self.start.row - self.end.row)

    def cells(self) -> List[Cell]:
        """Клетки сегмента, включая start и end.

        Для ортогональных сегментов — все промежуточные клетки.
        Для диагональных — только концы (промежуточные не определены
        в целочисленной сетке).
        """
        if self.angle is None:
            return [self.start, self.end]

        result: List[Cell] = []
        if self.angle in (WireAngle.EAST, WireAngle.WEST):
            lo, hi = sorted((self.start.col, self.end.col))
            for c in range(lo, hi + 1):
                result.append(Cell(c, self.start.row))
        else:  # NORTH / SOUTH
            lo, hi = sorted((self.start.row, self.end.row))
            for r in range(lo, hi + 1):
                result.append(Cell(self.start.col, r))
        return result


@dataclass(eq=False)
class Wire:
    """Провод сети: путь + отростки + точки врезок.

    Attributes:
        net_name:   имя сети.
        start:      пин-начало.
        end:        пин-конец (None для T-врезки).
        path:       клетки основного пути между концами отростков.
        start_stub: отросток от start-пина.
        end_stub:   отросток от end-пина (None для T-врезки).
        t_junction: True, если провод присоединяет пин к существующей сети.
    """
    net_name: str
    start: "Pin"
    end: Optional["Pin"] = None
    path: List[Cell] = field(default_factory=list, repr=False, compare=False)
    start_stub: Optional["Stub"] = None
    end_stub: Optional["Stub"] = None
    t_junction: bool = False

    # ---------- хэш / идентичность ----------

    def __hash__(self) -> int:
        end_key = self.end.local_key if self.end else "T"
        return hash((self.start.local_key, end_key, self.net_name))

    @property
    def key(self) -> str:
        """Человекочитаемый ключ провода."""
        end_key = self.end.local_key if self.end else "T"
        return f"{self.start.local_key} -> {end_key}"

    # ---------- геометрия ----------

    def segments(self) -> List[WireSegment]:
        """Разбивает основной путь на прямолинейные сегменты (без отростков)."""
        if len(self.path) < 2:
            return []

        segments: List[WireSegment] = []
        seg_start = self.path[0]
        current_angle = segment_angle(self.path[0], self.path[1])

        for i in range(1, len(self.path) - 1):
            a, b = self.path[i], self.path[i + 1]
            ang = segment_angle(a, b)
            if ang != current_angle:
                segments.append(WireSegment(seg_start, a, current_angle))
                seg_start = a
                current_angle = ang

        segments.append(WireSegment(seg_start, self.path[-1], current_angle))
        return segments

    def all_cells(self) -> List[Cell]:
        """Все клетки провода: отростки + основной путь."""
        cells: List[Cell] = []
        if self.start_stub and not self.start_stub.on_grid:
            cells.extend(self.start_stub.cells)
        cells.extend(self.path)
        if self.end_stub and not self.end_stub.on_grid:
            cells.extend(self.end_stub.cells)
        return cells

    def contains(self, cell: Cell) -> bool:
        """Лежит ли клетка на основном пути."""
        return cell in self.path

    @property
    def length(self) -> int:
        """Суммарная длина основного пути в шагах сетки."""
        return sum(s.length for s in self.segments())

    @property
    def orientation(self) -> Optional[WireOrientation]:
        """Ориентация провода, если он прямой (один сегмент)."""
        segs = self.segments()
        return segs[0].orientation if len(segs) == 1 else None

    @property
    def angle(self) -> Optional[WireAngle]:
        """Угол провода, если он прямой (один сегмент)."""
        segs = self.segments()
        return segs[0].angle if len(segs) == 1 else None

    def summary(self) -> str:
        """Краткое описание движений (для лога): "right ×5, up ×4, left ×2"."""
        names = {
            WireAngle.EAST:  "right",
            WireAngle.WEST:  "left",
            WireAngle.NORTH: "up",
            WireAngle.SOUTH: "down",
        }
        return ", ".join(f"{names[s.angle]} ×{s.length}"
                         for s in self.segments())