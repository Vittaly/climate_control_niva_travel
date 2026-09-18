# sheet_ref.py
"""Ссылка на вложенный лист (X_*) как компонент.

SheetRefComponent — обычный Component для Sheet, Placer, Router:
    - Sheet кладёт его в sheet.components;
    - Placer раскладывает как обычный компонент;
    - Router видит его пины как endpoints сетей;
    - Writer рисует add_sheet вместо components.add.

Отличия от PortComponent:
    - не один фиктивный пин, а столько, сколько портов в дочернем YAML;
    - lib_id="" — тот же сигнал «нет symbol в KiCad»;
    - is_sheet_ref=True — отдельный маркер для Writer.

Пины листа соответствуют портам дочерней страницы. Например, если в
sheets/power_supply.yaml есть порты VCC_3V3, GND, MOTOR_1_A, то у
X_PWR будет три пина с этими именами. Роутер сможет тянуть провод
к X_PWR:VCC_3V3 — как к обычному пину.

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
from typing import List, Optional, Tuple

import yaml

from constants import Axis, DEFAULT_GRID_MM, Direction
from logging_setup import get_logger
from pin import Pin

from component import Component

log = get_logger(__name__)


@dataclass(eq=False)
class SheetRefComponent(Component):
    """Ссылка на вложенный лист как компонент.

    Attributes:
        sheet_file:   имя файла листа (sheets/power_supply.yaml).
        sheet_name:   имя листа в KiCad (X_PWR).
        ports:        список портов дочернего YAML (сырые dict'ы).
    """
    sheet_file: str = ""
    sheet_name: str = ""
    ports: List[dict] = field(default_factory=list)

    # Габарит листа считается по числу портов — как в Writer
    CHAR_WIDTH_CELLS = 1
    ROW_HEIGHT_CELLS = 2       # высота одной строки порта, в клетках
    PADDING_ROWS = 4           # отступы сверху/снизу
    MIN_WIDTH_CELLS = 16       # минимум 16 клеток в ширину
    MIN_HEIGHT_CELLS = 8       # минимум 8 клеток в высоту

    # Зазор между встречными текстами левых и правых портов.
    GAP_CELLS = 2
    # Отступы от краёв bbox до текстов (пиктограмма + поля).
    SIDE_PADDING_CELLS = 1

    # -------- классификация портов --------
    @staticmethod
    def _is_output(port: dict) -> bool:
        """True, если порт выходной (стоит справа)."""
        return str(port.get("type", "INPUT")).upper() == "OUTPUT"

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
        """Ширина bbox: левый текст + зазор + правый текст + отступы.

        Левые порты стоят у левого края bbox и растут вправо.
        Правые порты стоят у правого края bbox и растут влево.
        Их тексты встречаются в середине — нужно, чтобы они
        не накладывались.
        """
        left_cells = cls._label_cells(left)
        right_cells = cls._label_cells(right)

        # если одна сторона пуста — зазор не нужен
        gap = cls.GAP_CELLS if (left and right) else 0
        padding = 2 * cls.SIDE_PADDING_CELLS

        return max(
            cls.MIN_WIDTH_CELLS,
            left_cells + gap + right_cells + padding,
        )

    @classmethod
    def _compute_bbox_rows(cls, n_ports: int, ports_per_side_max: int) -> int:
        """Высота bbox: отступы сверху/снизу + строки портов.

        Левые и правые порты нумеруются независимо (index в своей
        группе), но физически они делят одну колонку строк. Поэтому
        высота определяется МАКСИМУМОМ из числа левых и правых портов,
        а не их суммой.
        """
        return max(
            cls.MIN_HEIGHT_CELLS,
            cls.PADDING_ROWS + ports_per_side_max * cls.ROW_HEIGHT_CELLS,
        )

    def __post_init__(self):
        """Создаёт пины по портам дочернего YAML и считает габарит."""
        if not self.ports:
            self.ports = []

        left, right = self._split_ports(self.ports)

        # ---- габарит ----
        bbox_cols = self._compute_bbox_cols(left, right)
        bbox_rows = self._compute_bbox_rows(
            len(self.ports),
            max(len(left), len(right)),
        )
        self.bbox_size = (bbox_cols, bbox_rows)

        # anchor_offset_mm = (0, 0): anchor совпадает с левым-верхним
        # углом bbox. Пины задаются offset_mm от anchor.
        self.anchor_offset_mm = (0.0, 0.0)

        # ---- пины ----
        self.pins = []
        for i, port in enumerate(left):
            self._add_pin(port, side="left", index=i)
        for i, port in enumerate(right):
            self._add_pin(port, side="right", index=i)

        for pin in self.pins:
            pin.component = self

    def _add_pin(self, port: dict, side: str, index: int) -> None:
        """Создаёт Pin на границе листа по данным порта.

        Пин задаётся offset_mm от anchor (anchor = левый-верхний угол).
        Позиция пина в клетках от anchor:
            left  → col = 0
            right → col = bbox_cols - 1
            row = PADDING_ROWS // 2 + index * ROW_HEIGHT_CELLS

        pin.direction — «в тело» компонента (как в PortComponent):
            left  → RIGHT (внутрь bbox, вправо)
            right → LEFT  (внутрь bbox, влево)
        stub.py инвертирует его и получает отводку НАРУЖУ bbox.
        """
        net_label = str(port.get("net_label", ""))
        if not net_label:
            return

        # строка пина в клетках от anchor
        row_cell = self.PADDING_ROWS // 2 + index * self.ROW_HEIGHT_CELLS

        if side == "left":
            col_cell = 0
            # «в тело»: пин на левом краю смотрит вправо (внутрь bbox)
            direction = Direction.RIGHT
        else:
            col_cell = self.bbox_cols
            # «в тело»: пин на правом краю смотрит влево (внутрь bbox)
            direction = Direction.LEFT

        # смещение от anchor в мм
        offset_x = col_cell * self.grid_mm
        offset_y = row_cell * self.grid_mm

        self.pins.append(Pin(
            owner=self.designator,
            number=net_label,          # номер пина = имя порта
            name=net_label,
            offset_mm=(offset_x, offset_y),
            direction=direction,
        ))

    # ---------- удобный конструктор ----------

    @classmethod
    def create(cls, designator: str, sheet_file: str,
               parent_yaml_path: Path) -> "SheetRefComponent":
        """Создаёт ссылку на лист, читая его порты из YAML.

        Args:
            designator:      локальное имя листа ("X_PWR").
            sheet_file:      относительный путь к YAML
                             ("sheets/power_supply.yaml").
            parent_yaml_path: путь к main.yaml (для разрешения
                             относительного пути).
        """
        yaml_path = Path(parent_yaml_path).parent / sheet_file
        ports = []
        try:
            data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
            ports = data.get("ports", []) or []
        except Exception as e:
            log.warning("SheetRef %s: не прочитал %s: %s",
                        designator, yaml_path, e)

        return cls(
            designator=designator,
            name=designator,
            lib_id="",                 # нет symbol в KiCad
            bbox_size=(0, 0),          # пересчитается в __post_init__
            pins=[],
            fields={},
            sheet=None,
            sheet_file=sheet_file,
            sheet_name=designator,
            ports=ports,
        )

    # ---------- маркеры ----------

    @property
    def is_sheet_ref(self) -> bool:
        """True — отличает ссылку на лист от обычного компонента."""
        return True