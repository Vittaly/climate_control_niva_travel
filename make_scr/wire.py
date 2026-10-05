# wire.py
"""Провод: сегменты, отростки, точки T-соединений.

Провод хранит:
    - путь (клетки основного маршрута, строго ортогонального);
    - отростки start_stub / end_stub (ссылки на stub.Stub);
    - признак T-врезки для проводов, присоединяющих пин к сети.

Отростки физически живут в stub.py; здесь — только ссылки на них.

Кэширование геометрии:
    segments(), WireSegment.cells() и orientations_at() вычисляются
    лениво и запоминаются. Геометрия провода неизменна после
    создания, поэтому повторные вызовы из горячего цикла роутера
    (can_enter/can_leave) сводятся к O(1) lookup.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

from cell import Cell
from constants import (
    WIRE_ANGLE_TO_ORIENTATION,
    WireAngle,
    WireOrientation,
)
from primitive import Primitive

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

    def cells(self) -> Tuple[Cell, ...]:
        """Клетки сегмента, включая start и end.

        Для ортогональных сегментов — все промежуточные клетки.
        Для диагональных — только концы (промежуточные не определены
        в целочисленной сетке).

        Результат кэшируется в объекте сегмента: повторные вызовы
        возвращают готовый кортеж. Сегмент неизменяем (frozen),
        поэтому кэш кладётся через object.__setattr__.
        """
        cached = getattr(self, "_cells_cache", None)
        if cached is not None:
            return cached

        if self.angle is None:
            result: Tuple[Cell, ...] = (self.start, self.end)
        elif self.angle in (WireAngle.EAST, WireAngle.WEST):
            lo, hi = sorted((self.start.col, self.end.col))
            row = self.start.row
            result = tuple(Cell(c, row) for c in range(lo, hi + 1))
        else:  # NORTH / SOUTH
            lo, hi = sorted((self.start.row, self.end.row))
            col = self.start.col
            result = tuple(Cell(col, r) for r in range(lo, hi + 1))

        object.__setattr__(self, "_cells_cache", result)
        return result

    def contains_cell(self, c: int, r: int) -> bool:
        if self.angle is None:
            return ((c, r) == (self.start.col, self.start.row) or
                    (c, r) == (self.end.col, self.end.row))
        if self.angle in (WireAngle.EAST, WireAngle.WEST):
            if r != self.start.row:
                return False
            lo, hi = sorted((self.start.col, self.end.col))
            return lo <= c <= hi
        if c != self.start.col:
            return False
        lo, hi = sorted((self.start.row, self.end.row))
        return lo <= r <= hi


@dataclass(eq=False)
class Wire(Primitive):
    """Провод сети: путь + отростки + точки врезок.

    Attributes:
        net_name:   имя сети.
        start:      пин-начало.
        end:        пин-конец (None для T-врезки).
        path:       клетки основного пути между концами отростков.
        start_stub: отросток от start-пина.
        end_stub:   отросток от end-пина (None для T-врезки).
        t_junction: True, если провод присоединяет пин к существующей сети.

    Внутренние кэши (приватные, не влияют на сравнение):
        _segments_cache:     tuple[WireSegment, ...] — результат segments().
        _orientations_cache: dict[(col, row)] → tuple[WireOrientation, ...]
                             — карта ориентаций, для orientations_at().
    """
    net_name: str
    start: "Pin"
    end: Optional["Pin"] = None
    path: List[Cell] = field(default_factory=list, repr=False, compare=False)
    start_stub: Optional["Stub"] = None
    end_stub: Optional["Stub"] = None
    t_junction: bool = False

    _segments_cache: Optional[Tuple[WireSegment, ...]] = field(
        default=None, repr=False, compare=False,
    )
    _orientations_cache: Optional[Dict[Tuple[int, int],
                                       Tuple[WireOrientation, ...]]] = field(
        default=None, repr=False, compare=False,
    )

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

    def segments(self) -> Tuple[WireSegment, ...]:
        """Разбивает основной путь на прямолинейные сегменты (без отростков).

        Результат кэшируется: путь провода неизменен после создания.
        """
        if self._segments_cache is not None:
            return self._segments_cache

        if len(self.path) < 2:
            self._segments_cache = ()
            return self._segments_cache

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
        self._segments_cache = tuple(segments)
        return self._segments_cache

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

    # ---------- ориентации по клеткам (для can_enter/can_leave) ----------

    def orientations_at(self, cell: Cell) -> Tuple[WireOrientation, ...]:
        """Ориентации сегментов провода, проходящих через клетку.

        Возвращает пустой кортеж, если клетка не принадлежит проводу.
        В угловых клетках (стык двух сегментов) возвращает обе
        ориентации — это соответствует семантике «провод здесь
        проходит и горизонтально, и вертикально».

        Первый вызов строит карту по всем сегментам провода; далее
        lookup — O(1). Это устраняет повторный пересчёт segments() и
        cells() в горячем цикле can_enter/can_leave.
        """
        if self._orientations_cache is None:
            self._build_orientations_cache()
        return self._orientations_cache.get((cell.col, cell.row), ())

    def _build_orientations_cache(self) -> None:
        """Строит карту (col,row) → tuple[WireOrientation, ...].

        В угловой клетке две ориентации (H и V). Если сегмент
        диагональный — DIAGONAL.
        """
        acc: Dict[Tuple[int, int], List[WireOrientation]] = {}
        for seg in self.segments():
            orient = seg.orientation
            for c in seg.cells():
                key = (c.col, c.row)
                bucket = acc.get(key)
                if bucket is None:
                    acc[key] = [orient]
                else:
                    bucket.append(orient)

        self._orientations_cache = {
            key: tuple(bucket) for key, bucket in acc.items()
        }

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
