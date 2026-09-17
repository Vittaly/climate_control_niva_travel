# component.py
"""Компонент: собирается из YAML-описания типа.

Компонент знает свою страницу (двусторонняя связь Sheet ↔ Component).
Автоматический __eq__ отключён (eq=False) — сравнение по идентичности.
__hash__ строится по designator: он неизменяем после создания.

Alias-пины:
    Схлопывание пинов, сидящих на одном паде, выполняет Netlist
    (см. netlist.assign_pin_to_net). Компонент только:
      - владеет пинами и их геометрией,
      - умеет считать abs_pin_mm,
      - логирует дефекты библиотеки, но НЕ схлопывает их.

Системы координат:
    Символ (KiCad lib):     Y↑, 0 в anchor (точке привязки).
    Страница:               Y↓, 0 в верхнем-левом углу сетки.

    При загрузке из библиотеки координаты пинов немедленно
    конвертируются в систему СТРАНИЦЫ (Y↓) и сохраняются как
    СМЕЩЕНИЕ ОТ ЯКОРЯ:
        pin.offset_mm.x = x_lib - anchor_sym.x
        pin.offset_mm.y = anchor_sym.y - y_lib   (Y↓)

    где anchor_sym = (0, 0) в системе символа.

    После конвертации pin.offset_mm — всегда в системе страницы (Y↓),
    отсчитывается ОТ ЯКОРЯ.

    bbox_size (cols, rows) рассчитывается по координатам пинов.
    Если ширина/высота bbox меньше одной клетки, bbox СИММЕТРИЧНО
    расширяется на одну клетку С КАЖДОЙ СТОРОНЫ. bbox.min в системе
    компонента = (0, 0) — не сдвигается. При расширении сдвигается
    только якорь (anchor_offset_mm увеличивается на grid_mm с каждой
    стороны). Смещения пинов от якоря НЕ меняются.

    Точка якоря на странице (anchor_page_mm) вычисляется из
    bbox_origin (переданного placer'ом) и anchor_offset_mm:
        anchor_page_mm = bbox_origin_mm + anchor_offset_mm
    и сохраняется в компоненте через set_position().
    Сам bbox_origin НЕ хранится.

Направление пина (direction):
    Считается в from_yaml из ГЕОМЕТРИИ, но на СЫРЫХ координатах
    символа (Y↑, до конвертации). Библиотечный orientation
    используется только для сравнения.

Ориентация экземпляра (rotation, mirror):
    По умолчанию rotation=0, mirror=None. Задаются Placer'ом при
    расстановке (или из YAML). Пересчёт bbox, координат пинов и
    клеток при не-дефолтных значениях — TODO (см. _apply_orientation).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional, Tuple, TYPE_CHECKING

from cell import Cell
from constants import (
    Axis,
    DEFAULT_DIRECTION,
    DEFAULT_GRID_MM,
    GRID_EPSILON_MM,
    Direction,
    WireAngle,
    orientation_to_direction,
    opposite_direction,
    wire_angle_to_direction,
)
from logging_setup import get_logger
from pin import Pin

if TYPE_CHECKING:
    from kicad_source import KiCadSource
    from sheet import Sheet

log = get_logger(__name__)


# =========================================================
# Геометрия пина: направление «наружу от bbox» в системе СИМВОЛА
# =========================================================

def _compute_outward_angle(
    x_mm: float, y_mm: float,
    min_x: float, min_y: float,
    max_x: float, max_y: float,
) -> WireAngle:
    """Направление наружу от bbox в системе СИМВОЛА (Y вверх).

    Возвращает WireAngle:
        NORTH = вверх (y+), SOUTH = вниз (y−),
        WEST  = влево (x−), EAST  = вправо (x+).

    Логика:
        - расстояния от пина до каждой грани bbox;
        - минимум — единственный кандидат, если пин на одной грани;
        - при ничье (пин в углу bbox) — идём вдоль длинной оси.

    Args:
        x_mm, y_mm:  координаты пина в системе символа (Y вверх).
        min_x, min_y, max_x, max_y:  bbox символа (Y вверх).

    Returns:
        WireAngle — направление «наружу» в системе символа.
    """
    dist_left   = x_mm - min_x
    dist_right  = max_x - x_mm
    dist_top    = max_y - y_mm
    dist_bottom = y_mm - min_y

    candidates = [
        (dist_left,   WireAngle.WEST,  "h"),
        (dist_right,  WireAngle.EAST,  "h"),
        (dist_top,    WireAngle.NORTH, "v"),
        (dist_bottom, WireAngle.SOUTH, "v"),
    ]
    min_dist = min(c[0] for c in candidates)
    closest = [c for c in candidates if abs(c[0] - min_dist) < 1e-6]

    if len(closest) == 1:
        return closest[0][1]

    width  = max_x - min_x
    height = max_y - min_y
    priority = {"v": 0, "h": 1} if height >= width else {"h": 0, "v": 1}
    closest.sort(key=lambda c: priority[c[2]])
    return closest[0][1]


# =========================================================
# Компонент
# =========================================================

@dataclass(eq=False)
class Component:
    """Экземпляр компонента на странице.

    Attributes:
        designator:        локальное обозначение ("U1", "R3").
        name:              человекочитаемое value ("10k", "STM32F103").
        lib_id:            KiCad lib_id символа ("Device:R").
        bbox_size:         (cols, rows) — размер габарита в клетках.
        pins:              список Pin со смещением от якоря (мм, Y↓).
        fields:            дополнительные поля из YAML.
        sheet:             страница-владелец.
        rotation:          угол поворота экземпляра (0/90/180/270).
        mirror:            отражение экземпляра: None / "x" / "y".
        anchor_offset_mm:  (x_mm, y_mm) — смещение якоря от левого-верхнего
                           угла bbox (система страницы, Y↓).
        anchor_page_mm:    (x_mm, y_mm) — координаты якоря на странице (мм),
                           заполняются Placer'ом через set_position().
        grid_mm:           шаг сетки в мм.
    """
    designator: str
    name: str
    lib_id: str
    bbox_size: Tuple[int, int]              # (cols, rows) в клетках
    pins: List[Pin] = field(default_factory=list)
    fields: Dict[str, str] = field(default_factory=dict)
    sheet: Optional["Sheet"] = field(default=None, repr=False)
    rotation: int = 0
    mirror: Optional[str] = None
    anchor_offset_mm: Tuple[float, float] = (0.0, 0.0)
    anchor_page_mm: Optional[Tuple[float, float]] = None
    grid_mm: float = DEFAULT_GRID_MM

    # ---------- удобные свойства ----------

    @property
    def bbox_cols(self) -> int:
        """Ширина bbox в клетках."""
        return self.bbox_size[Axis.X]

    @property
    def bbox_rows(self) -> int:
        """Высота bbox в клетках."""
        return self.bbox_size[Axis.Y]

    # ---------- хэш / идентичность ----------

    def __hash__(self) -> int:
        """Хэш по designator'у. Уникален в пределах страницы."""
        return hash(self.designator)

    @property
    def sheet_path(self) -> str:
        """Путь страницы-владельца ("" для корня, если sheet не задан)."""
        return self.sheet.sheet_path if self.sheet else ""

    @property
    def fqn(self) -> str:
        """Полное имя с префиксом страницы."""
        sp = self.sheet_path
        return f"{sp}/{self.designator}" if sp else self.designator

    def fqn_pin(self, pin: Pin) -> str:
        """FQN пина этого компонента: "X_ACT/U2:5"."""
        return f"{self.fqn}:{pin.number}"

    # ---------- поиск пинов ----------

    def pin_by_number(self, number: str) -> Optional[Pin]:
        """Возвращает пин по номеру ("1", "A", ...) или None."""
        for p in self.pins:
            if p.number == number:
                return p
        return None

    def pin_by_local_key(self, local_key: str) -> Optional[Pin]:
        """Возвращает пин по локальному ключу "U1:42" или None."""
        for p in self.pins:
            if p.local_key == local_key:
                return p
        return None

    # ---------- построение из YAML ----------

    @classmethod
    def from_yaml(
        cls,
        designator: str,
        cdef: dict,
        types: dict,
        source: "KiCadSource",
        grid_mm: float = DEFAULT_GRID_MM,
    ) -> Optional["Component"]:
        """Собирает компонент из описания типа в component_types.

        Что РАССЧИТЫВАЕТСЯ:
            - bbox_sym (min/max по пинам, система символа, Y↑);
            - bbox СИММЕТРИЧНО расширяется на grid_mm с КАЖДОЙ стороны,
              если ширина/высота < grid_mm. bbox.min в системе
              компонента = (0, 0) — не сдвигается. Сдвигается только
              якорь (anchor_offset_mm += grid_mm с каждой стороны).
            - bbox_size (cols, rows) в клетках;
            - anchor_offset_mm (смещение якоря от bbox.min, мм, Y↓);
            - pin.offset_mm (смещение пина от якоря, мм, Y↓);
            - pin.direction (из геометрии, на сырых координатах).

        Args:
            designator: локальное обозначение ("U1").
            cdef:       словарь вида {"type": "TYPE_R_10K", ...}.
            types:      таблица component_types из YAML.
            source:     KiCadSource для доступа к библиотеке символов.
            grid_mm:    шаг сетки в мм.

        Returns:
            Component либо None, если тип неизвестен или символ не найден.
        """
        tname = cdef.get("type")
        if not tname or tname not in types:
            log.warning("Компонент %s: тип '%s' не описан, пропускаю",
                        designator, tname)
            return None

        tinfo = types[tname]
        lib_id = tinfo["symbol"]
        value = tinfo.get("value", tname)
        fields = dict(tinfo.get("fields", {}))

        try:
            pins_raw = source.get_pins(lib_id)
        except KeyError:
            log.error("Компонент %s: нет символа %s в библиотеке",
                      designator, lib_id)
            return None

        # --- 1. bbox по пинам (система СИМВОЛА, Y↑) ---
        pin_coords = [(float(p.get("x_mm", 0.0)), float(p.get("y_mm", 0.0)))
                      for p in pins_raw]
        if pin_coords:
            min_x = min(x for x, y in pin_coords)
            max_x = max(x for x, y in pin_coords)
            min_y = min(y for x, y in pin_coords)
            max_y = max(y for x, y in pin_coords)
        else:
            min_x = max_x = min_y = max_y = 0.0

        # --- 2. СИММЕТРИЧНОЕ расширение bbox на grid_mm с КАЖДОЙ стороны ---
        # bbox.min в системе компонента = (0, 0) — не сдвигается.
        # Сдвигается только якорь: anchor_offset_mm увеличивается
        # на grid_mm с каждой стороны (влево/вправо/вверх/вниз).
        # Смещения пинов от якоря НЕ меняются.
        if max_x - min_x < grid_mm:
            min_x -= grid_mm
            max_x += grid_mm
        if max_y - min_y < grid_mm:
            min_y -= grid_mm
            max_y += grid_mm

        # --- 3. размер в клетках ---
        bbox_cols = max(1, int(round((max_x - min_x) / grid_mm)))
        bbox_rows = max(1, int(round((max_y - min_y) / grid_mm)))
        bbox_size = (bbox_cols, bbox_rows)

        # --- 4. anchor в системе символа ---
        anchor_x_sym = 0.0
        anchor_y_sym = 0.0

        # --- 5. anchor_offset_mm (от левого-верхнего угла bbox, Y↓) ---
        # В системе символа: anchor_offset_sym = anchor - bbox.min
        # В системе страницы: X не инвертируется, Y инвертируется
        anchor_offset_x = anchor_x_sym - min_x
        anchor_offset_y = max_y - anchor_y_sym   # Y↓
        anchor_offset_mm = (anchor_offset_x, anchor_offset_y)

        # --- 6. пины (система СТРАНИЦЫ, Y↓, смещение от якоря) ---
        pins: List[Pin] = []
        for p in pins_raw:
            x_lib = float(p.get("x_mm", 0.0))
            y_lib = float(p.get("y_mm", 0.0))

            log.debug(
                "  %s.%-3s %-8s sym_mm=(%7.2f,%7.2f) orient=%s",
                designator, p["number"], p["name"],
                x_lib, y_lib, p.get("orientation", 0),
            )

            # смещение пина от якоря (система страницы, Y↓)
            pin_offset_x = x_lib - anchor_x_sym
            pin_offset_y = anchor_y_sym - y_lib

            # outward — на сырых координатах (система символа, Y↑)
            outward = _compute_outward_angle(
                x_mm=x_lib, y_mm=y_lib,
                min_x=min_x, min_y=min_y, max_x=max_x, max_y=max_y,
            )
            expected_direction = opposite_direction(
                wire_angle_to_direction(outward)
            )

            # что дала библиотека
            lib_orientation = p.get("orientation", 0)
            try:
                lib_orientation_int = int(lib_orientation)
            except (TypeError, ValueError):
                lib_orientation_int = 0
            lib_direction = orientation_to_direction(lib_orientation_int)

            if lib_direction != expected_direction:
                log.warning(
                    "%s: пин %s — библиотечный orientation=%s "
                    "(direction=%s), по геометрии ожидается "
                    "direction=%s (outward=%s). Используем геометрию.",
                    designator, p["number"],
                    lib_orientation, lib_direction,
                    expected_direction, outward,
                )
            elif lib_direction == DEFAULT_DIRECTION and lib_orientation_int != 0:
                log.warning(
                    "%s: неизвестная ориентация %s, принято %s",
                    designator, lib_orientation, DEFAULT_DIRECTION,
                )

            pins.append(Pin(
                owner=designator,
                number=p["number"],
                name=p["name"],
                offset_mm=(pin_offset_x, pin_offset_y),
                direction=expected_direction,
            ))

            log.debug(
                "  %s.%-3s %-8s offset_mm=(%7.2f,%7.2f) dir=%s",
                designator, p["number"], p["name"],
                pin_offset_x, pin_offset_y,
                expected_direction,
            )

        comp = cls(
            designator=designator,
            name=value,
            lib_id=lib_id,
            bbox_size=bbox_size,
            pins=pins,
            fields=fields,
            rotation=int(cdef.get("rotation", 0)) % 360,
            mirror=cdef.get("mirror"),
            anchor_offset_mm=anchor_offset_mm,
            grid_mm=grid_mm,
        )
        # двусторонняя связь: пин знает своего компонента
        for pin in pins:
            pin.component = comp

        # диагностика дефектов библиотеки: пины на одном паде
        comp._warn_duplicate_pin_positions()

        return comp

    # ---------- диагностика дубликатов пинов ----------

    def _warn_duplicate_pin_positions(self) -> None:
        """Логирует группы пинов с одинаковыми координатами внутри компонента."""
        for i, pi in enumerate(self.pins):
            for j in range(i + 1, len(self.pins)):
                pj = self.pins[j]
                if not self._same_pin_position(pi, pj):
                    continue
                if pi.name == pj.name:
                    log.info(
                        "%s: пины %s и %s на одной позиции, имя '%s' "
                        "(кандидаты на alias — схлопнёт Netlist)",
                        self.designator, pi.local_key, pj.local_key, pi.name,
                    )
                else:
                    log.error(
                        "%s: пины %s и %s на одной позиции, "
                        "но разные имена ('%s' vs '%s') — дефект библиотеки",
                        self.designator, pi.local_key, pj.local_key,
                        pi.name, pj.name,
                    )

    def _same_pin_position(self, a: Pin, b: Pin) -> bool:
        """Совпадают ли смещения пинов от якоря."""
        return (abs(a.offset_mm[Axis.X] - b.offset_mm[Axis.X]) <= GRID_EPSILON_MM
                and abs(a.offset_mm[Axis.Y] - b.offset_mm[Axis.Y]) <= GRID_EPSILON_MM)

    # ---------- позиционирование ----------

    def set_position(
        self,
        bbox_origin: Cell,
        rotation: int = 0,
        mirror: Optional[str] = None,
    ) -> None:
        """Устанавливает позицию компонента на странице.

        Вызывается Placer'ом. Принимает bbox_origin (левый-верхний угол
        bbox в клетках), вычисляет anchor_page_mm и сохраняет только его.
        bbox_origin НЕ хранится — он нужен только для вычисления.

        Args:
            bbox_origin: левый-верхний угол bbox (клетки).
            rotation:    угол поворота (0/90/180/270).
            mirror:      отражение (None / "x" / "y").
        """
        self.rotation = rotation
        self.mirror = mirror
        self._apply_orientation()
        self.anchor_page_mm = self.anchor_page_mm_at(bbox_origin, self.grid_mm)

    def anchor_page_mm_at(
        self,
        bbox_origin: Cell,
        grid_mm: float = DEFAULT_GRID_MM,
    ) -> Tuple[float, float]:
        """Точка якоря на странице для данного bbox_origin.

        anchor_page_mm = bbox_origin_mm + anchor_offset_mm.

        Args:
            bbox_origin: левый-верхний угол bbox (клетки).
            grid_mm:     шаг сетки в мм.

        Returns:
            (x_mm, y_mm) — точка якоря на странице, Y↓.
        """
        bx = bbox_origin.col * grid_mm
        by = bbox_origin.row * grid_mm
        return (bx + self.anchor_offset_mm[Axis.X],
                by + self.anchor_offset_mm[Axis.Y])

    def _apply_orientation(self) -> None:
        """Пересчитывает bbox, pin_offset и anchor_offset с учётом rotation/mirror.

        Пока rotation=0, mirror=None — ничего не делает.
        TODO: реализовать при появлении реальных поворотов.
        """
        if self.rotation == 0 and self.mirror is None:
            return
        log.warning(
            "%s: rotation=%d mirror=%s — пересчёт геометрии не реализован",
            self.designator, self.rotation, self.mirror,
        )

    # ---------- геометрия ----------

    def bbox_origin_cell(self) -> Cell:
        """Левый-верхний угол bbox на странице (клетки).

        Вычисляется из anchor_page_mm и anchor_offset_mm:
            bbox_origin_mm = anchor_page_mm - anchor_offset_mm
            bbox_origin_cell = round(bbox_origin_mm / grid_mm)

        Raises:
            RuntimeError: если anchor_page_mm не установлен.
        """
        if self.anchor_page_mm is None:
            raise RuntimeError(
                f"Компонент {self.designator}: anchor_page_mm не установлен. "
                "Вызовите set_position() перед bbox_origin_cell()."
            )
        ax, ay = self.anchor_page_mm
        ox = ax - self.anchor_offset_mm[Axis.X]
        oy = ay - self.anchor_offset_mm[Axis.Y]
        return Cell(round(ox / self.grid_mm), round(oy / self.grid_mm))

    def bbox_page_cell(self) -> Tuple[int, int, int, int]:
        """(col0, row0, col1, row1) — прямоугольник на странице (клетки).

        Raises:
            RuntimeError: если anchor_page_mm не установлен.
        """
        origin = self.bbox_origin_cell()
        return (origin.col, origin.row,
                origin.col + self.bbox_cols,
                origin.row + self.bbox_rows)

    def abs_pin_mm(self, pin: Pin) -> Tuple[float, float]:
        """Реальная точка пина на странице (мм).

        abs_pin_mm = anchor_page_mm + pin.offset_mm.

        Raises:
            RuntimeError: если anchor_page_mm не установлен.
        """
        if self.anchor_page_mm is None:
            raise RuntimeError(
                f"Компонент {self.designator}: anchor_page_mm не установлен. "
                "Вызовите set_position() перед abs_pin_mm()."
            )
        ax, ay = self.anchor_page_mm
        return (ax + pin.offset_mm[Axis.X],
                ay + pin.offset_mm[Axis.Y])

    def abs_pin_cell(self, pin: Pin) -> Cell:
        """Клетка пина на странице (округление от abs_pin_mm).

        Raises:
            RuntimeError: если anchor_page_mm не установлен.
        """
        x, y = self.abs_pin_mm(pin)
        return Cell(round(x / self.grid_mm), round(y / self.grid_mm))

    def iter_occupied_cells(self) -> Iterator[Tuple[int, int]]:
        """Генерирует клетки, занятые габаритом компонента.

        Raises:
            RuntimeError: если anchor_page_mm не установлен.
        """
        origin = self.bbox_origin_cell()
        for c in range(origin.col, origin.col + self.bbox_cols):
            for r in range(origin.row, origin.row + self.bbox_rows):
                yield (c, r)

    def iter_pin_cells(self) -> Iterator[Tuple[int, int]]:
        """Генерирует абсолютные клетки пинов компонента.

        Raises:
            RuntimeError: если anchor_page_mm не установлен.
        """
        for pin in self.pins:
            cell = self.abs_pin_cell(pin)
            yield (cell.col, cell.row)

    # ---------- признаки ----------

    @property
    def is_port(self) -> bool:
        """Обычный компонент — не порт."""
        return False

    @property
    def is_sheet_ref(self) -> bool:
        """Обычный компонент — не ссылка на лист."""
        return False