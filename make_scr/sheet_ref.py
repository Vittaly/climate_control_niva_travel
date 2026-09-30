# sheet_ref.py
"""Ссылка на вложенный лист (X_*) как компонент.

SheetRefComponent — обычный Component для Sheet, Placer, Router:
    - Sheet кладёт его в sheet.components;
    - Placer раскладывает как обычный компонент;
    - Router видит его пины как endpoints сетей;
    - Writer рисует add_sheet вместо components.add.

Источник истины о портах — дочерний YAML, секция nets:
    Порт — это сеть с флагом is_hierarchical_port: true.
    Имя порта = имя сети. Направление (для размещения пина на
    левом/правом краю) читается из port_direction у той же сети,
    по умолчанию INPUT.

    Устаревший верхний блок ports: не читается. Миграция
    завершена: все листы хранят порты в nets.*.is_hierarchical_port.

    Верхний блок port_map в родительском YAML не читается здесь:
    он обслуживает связь pin↔root_net на уровне родительской
    страницы, и его обработка — задача расширителя нетлиста,
    а не SheetRefComponent.

Отличия от PortComponent:
    - не один фиктивный пин, а столько, сколько портов в дочернем YAML;
    - lib_id="" — тот же сигнал «нет symbol в KiCad»;
    - is_sheet_ref=True — отдельный маркер для Writer.

Пины листа соответствуют портам дочерней страницы. Например, если в
sheets/power_supply.yaml есть сети VCC_3V3, GND с флагом
is_hierarchical_port, то у X_PWR будет два пина с этими именами.
Роутер сможет тянуть провод к X_PWR:VCC_3V3 — как к обычному пину.

    Для sheet-ref-пина number == name == имя порта. Числовых
    номеров у пина листа нет по определению. Резолв таких пинов
    идёт через pin_by_name, никогда через pin_by_number с числом.

Геометрия:
    bbox_size — размер листа в клетках.
    anchor_offset_mm = (0, 0) — anchor совпадает с левым-верхним
        углом bbox. Пины задаются offset_mm от anchor (мм, Y↓).

Семантика pin.direction:
    Как в PortComponent и в символах KiCad, pin.direction смотрит
    «в тело» компонента:
        side="left"  → пин на ЛЕВОМ краю bbox,  direction=RIGHT (внутрь)
        side="right" → пин на ПРАВОМ краю bbox, direction=LEFT  (внутрь)
    stub.py инвертирует pin.direction (opposite) и получает
    направление отводки НАРУЖУ bbox.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

from constants import Axis, DEFAULT_GRID_MM, Direction
from logging_setup import get_logger
from pin import Pin

from component import Component

log = get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────
# Кэш разобранных YAML-файлов листов
#
# Один и тот же лист инстанцируется многократно (actuator_channel ×4).
# Парсить YAML каждый раз — лишний I/O. Ключ — разрешённый путь,
# значение — загруженный словарь верхнего уровня.
# ─────────────────────────────────────────────────────────────────────

_YAML_CACHE: Dict[Path, dict] = {}


def _load_yaml_cached(path: Path) -> dict:
    """Загружает YAML с кэшем. Ошибки чтения → пустой dict."""
    key = path.resolve()
    if key in _YAML_CACHE:
        return _YAML_CACHE[key]
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as e:
        log.warning("SheetRef: не прочитал %s: %s", path, e)
        data = {}
    _YAML_CACHE[key] = data
    return data


def clear_yaml_cache() -> None:
    """Сброс кэша (для тестов и hot-reload)."""
    _YAML_CACHE.clear()


# ─────────────────────────────────────────────────────────────────────
# Ошибка сборки SheetRef
# ─────────────────────────────────────────────────────────────────────

class SheetRefError(Exception):
    """SheetRefComponent не смог собрать порты дочернего листа.

    Причины:
        - дочерний YAML вообще не читается;
        - в дочернем YAML нет ни одной сети с is_hierarchical_port,
          а родитель ожидает у листа пины.
    """

    def __init__(self, designator: str, reason: str, *,
                 hint: Optional[str] = None):
        self.designator = designator
        self.reason = reason
        self.hint = hint
        parts = [f"SheetRef {designator!r}: {reason}"]
        if hint:
            parts.append(f"({hint})")
        super().__init__(" ".join(parts))


@dataclass(eq=False)
class SheetRefComponent(Component):
    """Ссылка на вложенный лист как компонент.

    Attributes:
        sheet_file:   имя файла листа (sheets/power_supply.yaml).
        sheet_name:   имя листа в KiCad (X_PWR).
        ports:        список портов дочернего YAML (нормализованные
                      dict'ы с ключами net_label, direction, description).
    """
    sheet_file: str = ""
    sheet_name: str = ""
    ports: List[dict] = field(default_factory=list)

    # Габарит листа считается по числу портов — как в Writer
    CHAR_WIDTH_CELLS = 1
    ROW_HEIGHT_CELLS = 2
    PADDING_ROWS = 4
    MIN_WIDTH_CELLS = 16
    MIN_HEIGHT_CELLS = 8

    # Зазор между встречными текстами левых и правых портов.
    GAP_CELLS = 2
    # Отступы от краёв bbox до текстов (пиктограмма + поля).
    SIDE_PADDING_CELLS = 1

    # ─────────────── классификация портов ───────────────

    @staticmethod
    def _is_output(port: dict) -> bool:
        """True, если порт выходной (стоит справа)."""
        return str(port.get("direction", "INPUT")).upper() == "OUTPUT"

    @classmethod
    def _split_ports(cls, ports: List[dict]) -> Tuple[List[dict], List[dict]]:
        """Делит порты на левые (входные) и правые (выходные)."""
        left = [p for p in ports if not cls._is_output(p)]
        right = [p for p in ports if cls._is_output(p)]
        return left, right

    @classmethod
    def _label_cells(cls, ports: List[dict]) -> int:
        """Ширина самого длинного net_label среди портов, в клетках."""
        max_len = max(
            (len(str(p.get("net_label", ""))) for p in ports),
            default=0,
        )
        return int(round(max_len * cls.CHAR_WIDTH_CELLS))

    @classmethod
    def _compute_bbox_cols(cls, left: List[dict], right: List[dict]) -> int:
        """Ширина bbox: левый текст + зазор + правый текст + отступы."""
        left_cells = cls._label_cells(left)
        right_cells = cls._label_cells(right)
        gap = cls.GAP_CELLS if (left and right) else 0
        padding = 2 * cls.SIDE_PADDING_CELLS
        return max(
            cls.MIN_WIDTH_CELLS,
            left_cells + gap + right_cells + padding,
        )

    @classmethod
    def _compute_bbox_rows(cls, n_ports: int, ports_per_side_max: int) -> int:
        """Высота bbox: отступы сверху/снизу + строки портов."""
        return max(
            cls.MIN_HEIGHT_CELLS,
            cls.PADDING_ROWS + ports_per_side_max * cls.ROW_HEIGHT_CELLS,
        )

    def __post_init__(self):
        """Создаёт пины по нормализованным портам и считает габарит.

        На входе self.ports — уже нормализованный список dict'ов с
        ключами net_label, direction, description (см. _extract_ports).
        """
        if not self.ports:
            self.ports = []

        left, right = self._split_ports(self.ports)

        bbox_cols = self._compute_bbox_cols(left, right)
        bbox_rows = self._compute_bbox_rows(
            len(self.ports),
            max(len(left), len(right)),
        )
        self.bbox_size = (bbox_cols, bbox_rows)

        self.anchor_offset_mm = (0.0, 0.0)

        self.pins = []
        for i, port in enumerate(left):
            self._add_pin(port, side="left", index=i)
        for i, port in enumerate(right):
            self._add_pin(port, side="right", index=i)

        for pin in self.pins:
            pin.component = self

    def _add_pin(self, port: dict, side: str, index: int) -> None:
        """Создаёт Pin на кромке frame.

        Координаты пина считаем в системе frame:
            left  → col_in_frame = 0
            right → col_in_frame = frame_cols - 1

        Затем переводим в координаты anchor (= ЛВ bbox):
            col_cell = frame_offset_cols + col_in_frame
        где frame_offset_cols = 1 (bbox = frame + 1 клетка маржи с каждой
        стороны).

        Аналогично по строкам: row_in_frame → row_cell = 1 + row_in_frame.
        """
        net_label = str(port.get("net_label", ""))
        if not net_label:
            return

        fc, _fr = self.frame_size          # frame_cols из рамки, не из bbox
        row_in_frame = self.PADDING_ROWS // 2 + index * self.ROW_HEIGHT_CELLS

        if side == "left":
            col_in_frame = 0
            direction = Direction.RIGHT
        else:
            col_in_frame = fc - 1
            direction = Direction.LEFT

        # frame_offset_mm = (grid, grid) — ЛВ frame на 1 клетку внутрь bbox.
        col_cell = col_in_frame + 1
        row_cell = row_in_frame + 1

        offset_x = col_cell * self.grid_mm
        offset_y = row_cell * self.grid_mm

        self.pins.append(Pin(
            owner=self.designator,
            number=None,
            name=net_label,
            offset_mm=(offset_x, offset_y),
            direction=direction,
        ))
    # ─────────────── удобный конструктор ───────────────

    @classmethod
    def create(cls, designator: str, sheet_file: str,
               parent_yaml_path: Path) -> "SheetRefComponent":
        """Создаёт ссылку на лист, читая порты из nets дочернего YAML.

        Порт — это сеть с флагом is_hierarchical_port: true. Имя
        порта = имя сети. Направление для размещения (для выбора
        левого/правого края) берётся из port_direction у той же
        сети; по умолчанию INPUT.

        Args:
            designator:       локальное имя листа ("X_PWR").
            sheet_file:       относительный путь к YAML
                              ("sheets/power_supply.yaml").
            parent_yaml_path: путь к main.yaml (для разрешения
                              относительного пути).
        """
        yaml_path = Path(parent_yaml_path).parent / sheet_file
        data = _load_yaml_cached(yaml_path)
        ports = cls._extract_ports(data, yaml_path, designator)

        return cls(
            designator=designator,
            name=designator,
            lib_id="",
            bbox_size=(0, 0),
            pins=[],
            fields={},
            sheet=None,
            sheet_file=sheet_file,
            sheet_name=designator,
            ports=ports,
        )

    @staticmethod
    def _extract_ports(data: dict, yaml_path: Path,
                       designator: str) -> List[dict]:
        """Извлекает порты дочернего листа из nets.*.is_hierarchical_port.

        Возвращает список нормализованных dict'ов:
            {"net_label": <имя сети-порта>,
             "direction": <"INPUT"|"OUTPUT"|"BIDIR">,
             "description": <строка из YAML или "">}

        Порт — это сеть с флагом is_hierarchical_port: true. Устаревший
        блок ports: не читается: миграция завершена, все листы хранят
        порты в nets. Лист с нулём таких сетей валиден (лист без
        портов) — тогда возвращается пустой список с INFO-сообщением.
        """
        nets = data.get("nets", {}) or {}
        ports: List[dict] = []

        for name, net in nets.items():
            if not isinstance(net, dict):
                continue
            if not net.get("is_hierarchical_port"):
                continue

            direction = str(net.get("port_direction", "INPUT")).upper()
            if direction not in ("INPUT", "OUTPUT", "BIDIR"):
                log.warning(
                    "SheetRef %s: %s: сеть %r имеет "
                    "port_direction=%r — неизвестное значение, "
                    "принято INPUT.",
                    designator, yaml_path, name, direction,
                )
                direction = "INPUT"

            ports.append({
                "net_label":   name,
                "direction":   direction,
                "description": net.get("description", "") or "",
            })

        if not ports:
            log.info(
                "SheetRef %s: %s не содержит сетей с "
                "is_hierarchical_port: true — у листа не будет пинов.",
                designator, yaml_path,
            )

        return ports

    # ─────────────── маркеры ───────────────

    @property
    def is_sheet_ref(self) -> bool:
        """True — отличает ссылку на лист от обычного компонента."""
        return True

    
    @property
    def frame_size(self) -> Tuple[int, int]:
        fc, fr = self.bbox_size
        return (fc - 2, fr - 2)


    @property
    def frame_offset_mm(self) -> Tuple[float, float]:
        return (self.grid_mm, self.grid_mm)