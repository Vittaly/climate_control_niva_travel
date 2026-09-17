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
    CHAR_WIDTH_CELLS = 0.75
    ROW_HEIGHT_CELLS = 2       # высота одной строки порта, в клетках
    PADDING_ROWS = 4           # отступы сверху/снизу
    MIN_WIDTH_CELLS = 16       # минимум 16 клеток в ширину
    MIN_HEIGHT_CELLS = 8       # минимум 8 клеток в высоту

    def __post_init__(self):
        """Создаёт пины по портам дочернего YAML и считает габарит."""
        if not self.ports:
            # если портов нет — оставляем пустой список
            self.ports = []

        # габарит по числу портов
        n = len(self.ports)
        label_max = max(
            (len(str(p.get("net_label", ""))) for p in self.ports),
            default=8,
        )

        bbox_cols = max(
            self.MIN_WIDTH_CELLS,
            int(round(label_max * self.CHAR_WIDTH_CELLS)) + 4,
        )
        bbox_rows = max(
            self.MIN_HEIGHT_CELLS,
            self.PADDING_ROWS + n * self.ROW_HEIGHT_CELLS,
        )
        self.bbox_size = (bbox_cols, bbox_rows)

        # anchor_offset_mm = (0, 0): anchor совпадает с левым-верхним
        # углом bbox. Пины задаются offset_mm от anchor.
        self.anchor_offset_mm = (0.0, 0.0)

        # пины по портам: слева — input/power, справа — output
        self.pins = []
        left = [p for p in self.ports
                if str(p.get("type", "INPUT")).upper() != "OUTPUT"]
        right = [p for p in self.ports
                 if str(p.get("type", "INPUT")).upper() == "OUTPUT"]

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
        """
        net_label = str(port.get("net_label", ""))
        if not net_label:
            return

        # строка пина в клетках от anchor
        row_cell = self.PADDING_ROWS // 2 + index * self.ROW_HEIGHT_CELLS

        if side == "left":
            col_cell = 0
            direction = Direction.LEFT
        else:
            col_cell = self.bbox_cols - 1
            direction = Direction.RIGHT

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