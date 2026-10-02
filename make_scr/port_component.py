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

Direction → shape/side:
    Маппинг port_direction → shape и port_direction → side живёт
    ТОЛЬКО здесь, в _DIRECTION_TO_SHAPE и side_for_direction().
    Единственная точка входа — create(direction=...): shape и side
    вычисляются из direction и не могут разойтись.
    Потребители (project, writer) читают готовые comp.shape / comp.side
    либо зовут shape_for_direction() напрямую — но не дублируют
    маппинг у себя.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from component import Component
from constants import Axis, DEFAULT_GRID_MM, Direction
from logging_setup import get_logger
from pin import Pin

log = get_logger(__name__)


@dataclass(eq=False)
class PortComponent(Component):
    """Порт страницы как компонент.

    Attributes:
        net_name: имя порта = имя сети, к которой он привязан.
        shape:    форма пиктограммы ("input"/"output"/"bidirectional"/...).
                  Вычисляется из direction в create(); менять вручную
                  не следует.
        side:     "left" | "right" — сторона листа, куда встаёт порт.
                  Вычисляется из direction в create(); менять вручную
                  не следует.
    """
    net_name: str = ""
    shape: str = ""
    side: str = "right"
    direction: str = "INPUT"      # ← исходное port_direction из YAML
    description: str = ""         # ← description из YAML

    # ---- маппинг port_direction → shape hierarchical_label / sheet-pin ----
    # Единственное место в проекте, где этот маппинг определён.
    _DIRECTION_TO_SHAPE: ClassVar[dict[str, str]] = {
        "INPUT":         "input",
        "OUTPUT":        "output",
        "BIDIR":         "bidirectional",
        "BIDIRECTIONAL": "bidirectional",
        "TRISTATE":      "tri_state",
        "TRI_STATE":     "tri_state",
        "PASSIVE":       "passive",
    }

    # ---- габарит метки в клетках (для раскладки и choose_outward_angle) ----
    # При DEFAULT_GRID_MM = 1.27 мм высота строки текста ~ 2 клетки,
    # средняя ширина символа ~ 0.75 клетки.
    CHAR_WIDTH_CELLS = 0.75
    TEXT_HEIGHT_CELLS = 1
    PADDING_CELLS = 2       # пиктограмма + отступ
    V_GAP_CELLS = 1         # зазор по вертикали между соседними портами
    MIN_WIDTH_CELLS = 3     # нижняя граница для коротких имён

    # ---------- direction → shape / side ----------

    @classmethod
    def shape_for_direction(cls, direction: str) -> str:
        """port_direction из YAML → shape для KiCad.

        Без дефолта: неизвестное значение — ValueError. Ошибку лучше
        поймать на загрузке, чем молча получить input и сломанную
        иерархию.
        """
        key = str(direction).upper()
        if key not in cls._DIRECTION_TO_SHAPE:
            raise ValueError(
                f"неизвестный port_direction: {direction!r} "
                f"(ожидается одно из: "
                f"{', '.join(sorted(cls._DIRECTION_TO_SHAPE))})"
            )
        return cls._DIRECTION_TO_SHAPE[key]

    @classmethod
    def side_for_direction(cls, direction: str) -> str:
        """OUTPUT ставится на правый край листа, остальное — на левый."""
        return "right" if str(direction).upper() == "OUTPUT" else "left"

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
    def create(
        cls,
        designator: str,
        net_name: str,
        direction: str,
        description: str = "",
    ) -> "PortComponent":
        """Создаёт порт из port_direction.

        shape и side вычисляются из direction — рассинхронизация
        невозможна по построению. lib_id="" — сигнал «нет symbol».
        direction и description сохраняются как исходные — Sheet.read_ports
        отдаёт их дальше без пересчёта.

        Raises:
            ValueError: если direction не из _DIRECTION_TO_SHAPE.
        """
        return cls(
            designator=designator,
            name=net_name,
            lib_id="",
            bbox_size=(0, 0),
            pins=[],
            fields={},
            sheet=None,
            net_name=net_name,
            shape=cls.shape_for_direction(direction),
            side=cls.side_for_direction(direction),
            direction=str(direction).upper(),
            description=description,
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