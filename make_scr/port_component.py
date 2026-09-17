# port_component.py
"""Порт страницы как компонент.

Порт — обычный Component для Sheet, Placer и Router:
    - Sheet кладёт его в sheet.components;
    - Placer раскладывает по краям листа;
    - Router тянет провод к его пину через abs_pin_mm;
    - Writer рисует hierarchical_label вместо components.add.

Точка привязки (anchor) — кончик пиктограммы hierarchical_label.
Текст метки уходит НАРУЖУ листа:
    side="left"  → текст влево от anchor;
    side="right" → текст вправо от anchor.
Провод роутера подходит к anchor изнутри листа.

Отличие от обычного Component — пустой lib_id: символа в KiCad нет.
Это сигнал для writer.py: рисовать hierarchical_label, не symbol.

Геометрия:
    bbox_size — размер метки порта в клетках (насколько текст
        вылезает наружу листа + запас).
    anchor_offset_mm = (0, 0) — anchor совпадает с левым-верхним
        углом bbox.
    pin.offset_mm — смещение единственного пина от anchor
        (система страницы, Y↓).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from component import Component
from constants import Axis, DEFAULT_GRID_MM, Direction
from logging_setup import get_logger
from pin import Pin

if TYPE_CHECKING:
    pass

log = get_logger(__name__)


@dataclass(eq=False)
class PortComponent(Component):
    """Порт страницы как компонент.

    Attributes:
        net_name: имя порта = имя сети, к которой он привязан.
        shape:    форма пиктограммы ("input"/"output"/"bidirectional"/...).
        side:     "left" | "right" — сторона листа, куда встаёт порт.
    """
    net_name: str = ""
    shape: str = "input"
    side: str = "right"

    # ---- габарит метки в клетках (для раскладки и choose_outward_angle) ----
    # При DEFAULT_GRID_MM = 1.27 мм высота строки текста ~ 2 клетки,
    # средняя ширина символа ~ 0.75 клетки.
    CHAR_WIDTH_CELLS = 0.75
    TEXT_HEIGHT_CELLS = 1
    PADDING_CELLS = 2       # пиктограмма + отступ
    V_GAP_CELLS = 1         # зазор по вертикали между соседними портами
    MIN_WIDTH_CELLS = 3     # нижняя граница для коротких имён

    def __post_init__(self):
        # если net_name не задан — берём name
        if not self.net_name:
            self.net_name = self.name

        # bbox_size: (cols, rows) в клетках.
        #   cols — насколько текст метки вылезает наружу листа;
        #   rows — высота текста + зазор по вертикали.
        # Оба используются:
        #   - placer'ом для раскладки (шаг по вертикали = rows);
        #   - stub.choose_outward_angle для выбора направления отростка.
        bbox_cols = max(
            self.MIN_WIDTH_CELLS,
            int(round(len(self.net_name) * self.CHAR_WIDTH_CELLS))
            + self.PADDING_CELLS,
        )
        bbox_rows = self.TEXT_HEIGHT_CELLS + self.V_GAP_CELLS
        self.bbox_size = (bbox_cols, bbox_rows)

        # anchor_offset_mm = (0, 0): anchor — кончик пиктограммы,
        # совпадает с левым-верхним углом bbox.
        self.anchor_offset_mm = (0.0, 0.0)

        # единственный пин порта: offset_mm от anchor (anchor = bbox.min)
        if not self.pins:
            # Пин стоит у границы bbox, СМОТРЯЩЕЙ ВНУТРЬ ЛИСТА:
            #   side="left"  → пин у ПРАВОЙ границы (col = bbox_cols-1),
            #                  отросток пойдёт вправо (внутрь листа);
            #   side="right" → пин у ЛЕВОЙ границы (col = 0),
            #                  отросток пойдёт влево (внутрь листа).
            if self.side == "left":
                col_cell = self.bbox_cols - 1
                pin_dir = Direction.RIGHT
            else:
                col_cell = 0
                pin_dir = Direction.LEFT

            offset_x = col_cell * self.grid_mm
            offset_y = 0.0

            self.pins = [Pin(
                owner=self.designator,
                number="1",
                name=self.net_name,
                offset_mm=(offset_x, offset_y),
                direction=pin_dir,
            )]
            for pin in self.pins:
                pin.component = self

    # ---------- удобный конструктор ----------

    @classmethod
    def create(cls, designator: str, net_name: str,
               shape: str = "input", side: str = "right"
               ) -> "PortComponent":
        """Создаёт порт без указания символа KiCad.

        lib_id="" — сигнал «нет symbol в библиотеке». Используется:
            - в writer.py: рисовать hierarchical_label, не components.add.
        """
        return cls(
            designator=designator,
            name=net_name,
            lib_id="",            # у порта нет symbol
            bbox_size=(0, 0),     # пересчитается в __post_init__
            pins=[],
            fields={},
            sheet=None,
            net_name=net_name,
            shape=shape,
            side=side,
        )

    # ---------- маркеры для writer / stub ----------

    @property
    def is_port(self) -> bool:
        """True — отличает порт от обычного компонента без isinstance.

        В writer.py: рисовать hierarchical_label вместо components.add.
        """
        return True

    @property
    def text_outward_cells(self) -> int:
        """Сколько клеток текст метки уходит наружу листа.

        Полезно плейсеру: насколько origin порта должен отстоять
        от границы поля компонентов, чтобы текст не обрезался.
        """
        return self.bbox_cols