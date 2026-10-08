# sheet_ref.py
"""Ссылка на вложенный лист (X_*) как компонент.

SheetRefComponent — обычный Component для Sheet, Placer, Router:
    - Sheet кладёт его в sheet.components;
    - Placer раскладывает как обычный компонент;
    - Router видит его пины как endpoints сетей;
    - Writer рисует (sheet (uuid ...)) вместо components.add.

Создание и инстанцирование:
    SheetRefComponent(designator, parent_sheet, sheet_file,
                      parent_sri=..., sheet_ref_start_counter=2)

    parent_sri — SheetRefInstance родительского контекста: то
    вхождение X_*, внутри которого нарисован наш X_*. Для X_*
    в корневой странице parent_sri — 0-й SheetRefInstance корня
    (is_local=True, page=1).

    sheet_ref_start_counter — KiCad-номер нашего X_* (2 у первой
    вложенной, 3 у следующей, ...). Родительский Sheet выдаёт его
    при обходе своих компонентов.

    Конструктор:
        1. Создать свой SheetRefInstance (component=self,
           parent=parent_sri, page=sheet_ref_start_counter).
           Пока держим его локально — self.instances появляется
           только в Component.__init__ (через super().__init__).
        2. Найти корень дерева: my_sri.root_sheet — подъём по
           parent-цепочке до 0-го SheetRefInstance, у которого
           _local_sheet есть корневой Sheet.
        3. Найти уже загруженный Sheet: root.find_sheet(stem).
        4. Если найден — инстанцировать в новом контексте через
           register_from (multi-instance).
           Если не найден — загрузить через Sheet.load(
           parent_sri=my_sri, first_child_counter=…).
        5. Прочитать порты целевой страницы (нужны до super().__init__,
           чтобы __post_init__ посчитал bbox/pins).
        6. super().__init__ — создаёт базовые поля Component
           (в т.ч. self.instances = []), вызывает __post_init__.
        7. После super() — append my_sri в self.instances и
           сохранение self.child_sheet.

    on_new_context(parent_sri, *, sheet_ref_start_counter) — метод
    для случая multi-instance: X_* уже существует, но родительский
    Sheet инстанцируется в очередном контексте. Создаёт
    дополнительный SheetRefInstance и рекурсивно инстанцирует
    поддерево.

Номера:
    page — KiCad-номер страницы (1 у корня, 2+ у вложенных).
    next_counter_after_subtree — следующий свободный номер после
    всего поддерева этого X_*. Читает родительский
    Sheet._load_components, чтобы следующий X_* начал с этого
    значения. Счётчик течёт вниз аргументом, наверх — возвращаемым
    значением.

Идентичность:
        uuid:         uuid X_* в родителе (Primitive default_factory);
        sheet:        родительский Sheet (унаследовано от Component);
        child_sheet:  прямая ссылка на целевую страницу;
        instances:    SheetRefInstance[] — вхождения X_* в дереве,
                      по одному на контекст. Первый создаётся в
                      конструкторе, остальные — в on_new_context.
        ports:        интерфейс символа (снимок с child_sheet).

    sheet_file / sheet_name — не поля, а свойства (см. ниже).

Порты:
    Порт целевой страницы — сеть с is_hierarchical_port: true.
    Интерфейс считывается ОДИН РАЗ в конструкторе и становится
    собственным состоянием символа (self.ports/pins/bbox_size).

Семантика pin.direction:
    side="left"  → pin.direction = RIGHT (в тело);
    side="right" → pin.direction = LEFT  (в тело).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional, Tuple

from constants import ComponentKind, Direction
from logging_setup import get_logger
from pin import Pin

from component import Component
from sheet_ref_instance import SheetRefInstance

if TYPE_CHECKING:
    from sheet import Sheet


log = get_logger(__name__)


class SheetRefError(Exception):
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
        child_sheet:   целевая страница (файл, куда ведёт X_*).
        ports:         интерфейс символа — снимок портов child_sheet.
        instances:     SheetRefInstance[] — вхождения X_* в дереве.
                       Первое создаётся в конструкторе, остальные —
                       через on_new_context при повторной регистрации
                       родителя (multi-instance).
        next_counter_after_subtree: следующий свободный номер после
                       всего поддерева этого X_*. Читает родительский
                       Sheet._load_components для нумерации
                       следующего X_*.
    """

    child_sheet: Optional["Sheet"] = field(default=None, repr=False)
    ports: List[dict] = field(default_factory=list)
    instances: List[SheetRefInstance] = field(
        default_factory=list, repr=False,
    )
    next_counter_after_subtree: int = field(
        default=0, compare=False, repr=False,
    )

    CHAR_WIDTH_CELLS = 1
    ROW_HEIGHT_CELLS = 2
    PADDING_ROWS = 4
    MIN_WIDTH_CELLS = 16
    MIN_HEIGHT_CELLS = 8
    GAP_CELLS = 2
    SIDE_PADDING_CELLS = 1

    # ─────────────── конструктор ───────────────

    def __init__(self, designator, parent_sheet, sheet_file, *,
                 parent_sri: SheetRefInstance,
                 sheet_ref_start_counter: int):
        """Создать SheetRefComponent и инстанцировать его в контексте.

        parent_sri — SheetRefInstance родителя. Для X_* в корне —
        0-й SRI корня (is_local=True).

        sheet_ref_start_counter — KiCad-номер этого X_*.

        Побочный эффект: целевая страница получает этот SRI в свой
        sheet_ref_instances и инстанцируется в этом контексте —
        через Sheet.load (первый визит) или child_sheet.register_from
        (multi-instance).
        """
        from sheet import Sheet

        # 1. Свой SheetRefInstance — держим локально. В self.instances
        #    положим после super().__init__: instances создаётся
        #    в Component.__init__.
        my_sri = SheetRefInstance(
            component=self,
            parent=parent_sri,
            page=sheet_ref_start_counter,
        )

        # 2. Корень дерева — подъём по parent-цепочке.
        root = my_sri.root_sheet

        # 3. Целевой YAML.
        parent_yaml = parent_sheet.yaml_path
        child_yaml = (parent_yaml.parent
                      / Path(sheet_file).with_suffix(".yaml")).resolve()
        if not child_yaml.exists():
            raise SheetRefError(designator, f"нет {child_yaml.name}")

        # 4. Уже загружен? Спрашиваем корень (рекурсивный поиск вниз).
        child_sheet = root.find_sheet(child_yaml.stem)

        if child_sheet is None:
            # Первый визит: load + инстанцирование в этом контексте
            # одним вызовом (Sheet.load сам запускает каскад).
            child_sheet = Sheet.load(
                child_yaml,
                source=root.source,
                libraries=root.libraries,
                load_errors=root.load_errors,
                parent_sri=my_sri,
                first_child_counter=sheet_ref_start_counter + 1,
            )
            after_subtree = child_sheet._next_counter
        else:
            # Multi-instance: файл уже в дереве. Инстанцируем в новом
            # контексте: вложенные X_* получат дополнительные SRI,
            # обычные компоненты — дополнительные CI.
            after_subtree = child_sheet.register_from(
                my_sri,
                sheet_ref_start_counter=sheet_ref_start_counter + 1,
            )

        self.next_counter_after_subtree = after_subtree

        # 5. Интерфейс символа — до super().__init__, чтобы наш
        #    __post_init__ посчитал bbox/pins по self.ports.
        self.ports = child_sheet.read_ports()

        super().__init__(
            designator=designator, name=designator, lib_id="",
            bbox_size=(0, 0), pins=[], fields={}, sheet=parent_sheet,
        )

        # 6. После super().__init__ self.instances уже создан —
        #    добавляем свой SRI (единственный элемент для этого X_*
        #    в первом контексте).
        self.instances.append(my_sri)
        self.child_sheet = child_sheet

    # ─────────────── каскад: multi-instance ───────────────

    def on_new_context(
        self,
        parent_sri: SheetRefInstance,
        *,
        sheet_ref_start_counter: int,
    ) -> int:
        """Создать дополнительный SheetRefInstance в новом контексте.

        Вызывается Sheet.register_from, когда родительский Sheet
        переиспользуется (multi-instance): этот X_* уже создан в
        первом контексте, а сейчас должен появиться ещё в одном.

        Создаёт SheetRefInstance с page=sheet_ref_start_counter,
        рекурсивно инстанцирует целевую страницу. Возвращает
        next_counter — следующий свободный номер после всего
        поддерева.
        """
        my_page = sheet_ref_start_counter
        sri = SheetRefInstance(
            component=self,
            parent=parent_sri,
            page=my_page,
        )
        self.instances.append(sri)

        if self.child_sheet is None:
            return my_page + 1

        return self.child_sheet.register_from(
            sri,
            sheet_ref_start_counter=my_page + 1,
        )

    # ─────────────── производные доступы ───────────────

    @property
    def sheet_file(self) -> str:
        """Относительный путь до целевого YAML от родительского."""
        if self.child_sheet is None:
            return ""
        parent_dir = self.sheet.yaml_path.parent
        try:
            return str(self.child_sheet.yaml_path.relative_to(parent_dir))
        except ValueError:
            return str(self.child_sheet.yaml_path)

    @property
    def sheet_name(self) -> str:
        return self.designator

    # ─────────────── порты ───────────────

    @staticmethod
    def _is_output(port: dict) -> bool:
        return str(port.get("direction", "INPUT")).upper() == "OUTPUT"

    @classmethod
    def _split_ports(cls, ports):
        left = [p for p in ports if not cls._is_output(p)]
        right = [p for p in ports if cls._is_output(p)]
        return left, right

    @classmethod
    def _label_cells(cls, ports) -> int:
        max_len = max(
            (len(str(p.get("net_label", ""))) for p in ports), default=0,
        )
        return int(round(max_len * cls.CHAR_WIDTH_CELLS))

    @classmethod
    def _compute_bbox_cols(cls, left, right) -> int:
        left_cells = cls._label_cells(left)
        right_cells = cls._label_cells(right)
        gap = cls.GAP_CELLS if (left and right) else 0
        padding = 2 * cls.SIDE_PADDING_CELLS
        return max(cls.MIN_WIDTH_CELLS,
                   left_cells + gap + right_cells + padding)

    @classmethod
    def _compute_bbox_rows(cls, n_ports, ports_per_side_max) -> int:
        return max(cls.MIN_HEIGHT_CELLS,
                   cls.PADDING_ROWS + ports_per_side_max * cls.ROW_HEIGHT_CELLS)

    def __post_init__(self):
        if not self.ports:
            self.ports = []
        left, right = self._split_ports(self.ports)
        self.bbox_size = (
            self._compute_bbox_cols(left, right),
            self._compute_bbox_rows(len(self.ports),
                                    max(len(left), len(right))),
        )
        self.anchor_offset_mm = (0.0, 0.0)

        self.pins = []
        for i, port in enumerate(left):
            self._add_pin(port, side="left", index=i)
        for i, port in enumerate(right):
            self._add_pin(port, side="right", index=i)
        for pin in self.pins:
            pin.component = self

    def _add_pin(self, port: dict, side: str, index: int) -> None:
        net_label = str(port.get("net_label", ""))
        if not net_label:
            return
        fc, _fr = self.frame_size
        row_in_frame = self.PADDING_ROWS // 2 + index * self.ROW_HEIGHT_CELLS
        if side == "left":
            col_in_frame = 0
            direction = Direction.RIGHT
        else:
            col_in_frame = fc - 1
            direction = Direction.LEFT
        col_cell = col_in_frame + 1
        row_cell = row_in_frame + 1
        self.pins.append(Pin(
            owner=self.designator,
            number=None,
            name=net_label,
            offset_mm=(col_cell * self.grid_mm, row_cell * self.grid_mm),
            direction=direction,
        ))

    @property
    def frame_size(self) -> Tuple[int, int]:
        fc, fr = self.bbox_size
        return (fc - 2, fr - 2)

    @property
    def frame_offset_mm(self) -> Tuple[float, float]:
        return (self.grid_mm, self.grid_mm)

    @property
    def kind(self) -> "ComponentKind":
        return ComponentKind.SHEET_REF