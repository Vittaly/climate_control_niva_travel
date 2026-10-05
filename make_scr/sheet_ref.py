# sheet_ref.py
"""Ссылка на вложенный лист (X_*) как компонент.

SheetRefComponent — обычный Component для Sheet, Placer, Router:
    - Sheet кладёт его в sheet.components;
    - Placer раскладывает как обычный компонент;
    - Router видит его пины как endpoints сетей;
    - Writer рисует add_sheet вместо components.add.

Создание — через конструктор:
    SheetRefComponent(designator, parent_sheet, sheet_file)

    Конструктор сам делает всё, что относится к X_*:
      1. Резолвит дочерний YAML относительно YAML родительского Sheet.
      2. Просит Sheet.load получить/загрузить дочерний Sheet
         (один YAML = один Sheet, find_sheet от корня).
      3. Читает порты дочернего Sheet из его netlist
         (child_sheet.read_ports()).
      4. Заполняет унаследованные поля Component через super().__init__.
         В конце Component.__init__ вызывает __post_init__ — уже
         SheetRef-версию (метод переопределён), где считаются bbox
         и пины.
      5. Создаёт SheetInstance ребёнка (в контексте parent_sheet) и
         регистрирует его через child_sheet.register_instance.
         Ссылка на этот SheetInstance сохраняется в self.child_instance.

Идентичность и инстанцирование:
    SheetRefComponent описывает X_* в родительском файле. У него
    три ссылки, отражающие стороны отношения:
        - sheet:           родительский Sheet (унаследовано от Component,
                           проставляется в super().__init__);
        - uuid:            uuid этого X_* в родителе. Назначается один
                           раз при создании. Используется как
                           (sheet (uuid ...)) в родительском .kicad_sch
                           и как сегмент instance-путей потомков;
        - child_instance:  SheetInstance ребёнка, созданный этим X_*.
                           Из него доступны child_sheet, child_page.

    Лист может быть инстанцирован через несколько X_*. У каждого —
    свой SheetRefComponent со своим uuid и своим child_instance.
    Один child_sheet. Число SheetInstance у ребёнка равно числу X_*,
    которые на него ссылаются.

Источник истины о портах — дочерний Sheet, уже загруженный из YAML:
    Порт — это сеть с флагом is_hierarchical_port: true в дочернем
    YAML. Имя порта = имя сети. Направление (для размещения пина на
    левом/правом краю) — из port_direction у той же сети, по
    умолчанию INPUT.

Отличия от PortComponent:
    - не один фиктивный пин, а столько, сколько портов в дочернем Sheet;
    - lib_id="" — тот же сигнал «нет symbol в KiCad»;
    - is_sheet_ref=True — отдельный маркер для Writer.

Пины листа соответствуют портам дочерней страницы. Для sheet-ref-пина
number == name == имя порта. Резолв таких пинов идёт через
pin_by_name, никогда через pin_by_number с числом.

Семантика pin.direction:
    Как в PortComponent и в символах KiCad, pin.direction смотрит
    «в тело» компонента:
        side="left"  → пин на ЛЕВОМ краю bbox,  direction=RIGHT (внутрь)
        side="right" → пин на ПРАВОМ краю bbox, direction=LEFT  (внутрь)
    stub.py инвертирует pin.direction (opposite) и получает
    направление отводки НАРУЖУ bbox.
"""
from __future__ import annotations

import uuid as uuid_mod
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Iterator, List, Optional, Tuple

from constants import Axis, DEFAULT_GRID_MM, ComponentKind, Direction
from logging_setup import get_logger
from pin import Pin

from component import Component
from sheet_instance import SheetInstance

if TYPE_CHECKING:
    from sheet import Sheet


log = get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────
# Ошибка сборки SheetRef
# ─────────────────────────────────────────────────────────────────────

class SheetRefError(Exception):
    """SheetRefComponent не смог собрать порты дочернего листа.

    Причины:
        - родительский Sheet не связан с yaml_path;
        - дочерний YAML не найден;
        - дочерний Sheet не читается.
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


@dataclass(eq=False, kw_only=True)
class SheetRefComponent(Component):
    """Ссылка на вложенный лист как компонент.

    Attributes:
        sheet_file:      относительный путь к YAML дочернего листа
                         ("power_supply.yaml" или "sheets/power_supply.yaml").
        sheet_name:      имя листа в KiCad (X_PWR).
        ports:           список портов дочернего Sheet (нормализованные
                         dict'ы с ключами net_label, direction, description).
        uuid:            uuid этого X_* в родителе. Назначается один раз
                         при создании, не меняется. Идёт в (sheet (uuid ...))
                         родительского .kicad_sch и как сегмент
                         instance-путей.
        child_instance:  SheetInstance ребёнка, созданный этим X_*.
                         Устанавливается в конструкторе.
    """
    sheet_file: str = ""
    sheet_name: str = ""
    ports: List[dict] = field(default_factory=list)
    uuid: str = ""
    child_instance: Optional[SheetInstance] = field(
        default=None, repr=False,
    )

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

    # ─────────────── конструктор ───────────────

    def __init__(self, designator, parent_sheet, sheet_file):
        from sheet import Sheet

        # Корень: если у parent_sheet есть instances — он дочерний,
        # берём корень через подъём. Если instances пусто — parent_sheet
        # сам корень.
        if parent_sheet.instances:
            root_sheet = parent_sheet.instances[0].root_sheet
        else:
            root_sheet = parent_sheet

        parent_yaml = parent_sheet.yaml_path
        child_yaml = (parent_yaml.parent
                      / Path(sheet_file).with_suffix(".yaml")).resolve()
        if not child_yaml.exists():
            raise SheetRefError(designator, f"нет {child_yaml.name}")

        # find_sheet — обход дерева от root_sheet через child_instance.
        child_sheet = SheetRefComponent.find_sheet(root_sheet,
                                                   child_yaml.stem)
        if child_sheet is None:
            child_sheet = Sheet.load(
                child_yaml,
                source=root_sheet.source,
                libraries=root_sheet.libraries,
                load_errors=root_sheet.load_errors,
            )

        ports = child_sheet.read_ports()

        # Свои поля — ДО super().__init__, чтобы __post_init__ (наш)
        # уже видел self.ports.
        self.sheet_file = sheet_file
        self.sheet_name = designator
        self.ports = ports
        self.uuid = str(uuid_mod.uuid4())

        super().__init__(
            designator=designator, name=designator, lib_id="",
            bbox_size=(0, 0), pins=[], fields={}, sheet=parent_sheet,
        )

        # Контекст parent_sheet: его instance, либо None (корень).
        parent_inst = (parent_sheet.instances[0]
                       if parent_sheet.instances else None)

        child_inst = SheetInstance(
            sheet=child_sheet,
            via=self,
            parent=parent_inst,
            page=SheetRefComponent._next_page_number(root_sheet),
        )
        self.child_instance = child_inst
        child_sheet.register_instance(child_inst)

    # ─────────────── производные доступы к ребёнку ───────────────

    @property
    def child_sheet(self) -> Optional["Sheet"]:
        """Sheet ребёнка — через child_instance."""
        return self.child_instance.sheet if self.child_instance else None

    @property
    def child_page(self) -> Optional[int]:
        """Page инстанса ребёнка."""
        return self.child_instance.page if self.child_instance else None

    # ─────────────── поиск по дереву ───────────────

    @classmethod
    def find_sheet(
        cls,
        root_sheet: "Sheet",
        stem: str,
    ) -> Optional["Sheet"]:
        """Найти Sheet по stem в дереве от root_sheet.

        Обход вниз через components → child_instance.
        """
        for comp in root_sheet.components.values():
            if not isinstance(comp, cls):
                continue
            ci = comp.child_instance
            if ci is None:
                continue
            if ci.sheet.stem == stem:
                return ci.sheet
            found = cls.find_sheet(ci.sheet, stem)
            if found is not None:
                return found
        return None

    # ─────────────── нумерация страниц ───────────────

    @classmethod
    def _next_page_number(cls, root_sheet: "Sheet") -> int:
        """Следующий свободный номер страницы в дереве от root_sheet.

        Корень занял page=1, остальные SheetInstance — по одному на
        каждый созданный. Обходим дерево вниз через components →
        child_instance → child_sheet.
        """
        n = 1                              # корень
        for _ in cls._walk_all_instances(root_sheet):
            n += 1
        return n + 1

    @classmethod
    def _walk_all_instances(cls, sheet: "Sheet") -> Iterator[SheetInstance]:
        """DFS всех SheetInstance дерева от sheet."""
        for comp in sheet.components.values():
            if not isinstance(comp, cls):
                continue
            ci = comp.child_instance
            if ci is None:
                continue
            yield ci
            yield from cls._walk_all_instances(ci.sheet)

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

        Вызывается автоматически из Component.__init__ (при вызове
        super().__init__() родителя — тот вызывает self.__post_init__,
        то есть эту версию).

        На входе self.ports — уже нормализованный список dict'ов с
        ключами net_label, direction, description.
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
        где frame_offset_cols = 1.

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

    # ─────────────── маркеры ───────────────

   

    @property
    def frame_size(self) -> Tuple[int, int]:
        fc, fr = self.bbox_size
        return (fc - 2, fr - 2)

    @property
    def frame_offset_mm(self) -> Tuple[float, float]:
        return (self.grid_mm, self.grid_mm)

    @property
    def kind(self) -> "ComponentKind":
        """Тип компонента. Переопределяется наследниками.

        У обычного символа — SYMBOL; PortComponent, SheetRefComponent,
        LabelComponent возвращают свой тип.
        """
        
        return ComponentKind.SHEET_REF