# sheet_instance.py
"""Один факт инстанцирования Sheet в дереве проекта.

Модель:
    Лист (Sheet) — это файл .kicad_sch. Один и тот же файл может быть
    инстанцирован многократно (actuator_channel × 4). Каждое такое
    присутствие описывается SheetInstance.

    SheetInstance создаётся в SheetRefComponent.__init__ и сразу
    регистрируется в дочернем Sheet через register_instance. Один
    SheetRefComponent порождает ровно один SheetInstance.

Хранимые поля:
    sheet:  Sheet — лист, который инстанцируется.
    via:    SheetRefComponent — X_* в родителе, через который создан
            этот instance. Всегда задан: SheetInstance создаётся
            только конструктором SheetRefComponent.
    parent: Optional[SheetInstance] — инстанс родительского Sheet.
            None у прямых детей корня (у корня нет своего instance).
    page:   int — сквозной номер страницы в дереве. Присвоен при
            создании, не меняется.

Производные значения:
    uuid — uuid X_*, через который создан instance. Это тот же
           идентификатор, что writer пишет в (sheet (uuid ...))
           родительского файла. Не хранится — берётся у via.

    path — instance-путь KiCad: /<root_uuid>/<x1_uuid>/.../<this_uuid>/.
           Первый сегмент — uuid корневого Sheet (файла корня), далее
           uuid-ы X_* по цепочке parent. Вычисляется на месте.

    root_sheet — корневой Sheet дерева. Находится подъёмом по parent
                 до конца, оттуда via.sheet.

    root_uuid — uuid корневого Sheet (первый сегмент path).
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from sheet import Sheet
    from sheet_ref import SheetRefComponent


@dataclass(eq=False)
class SheetInstance:
    """Одно инстанцирование Sheet в дереве проекта.

    Attributes:
        sheet:   лист (файл .kicad_sch), который инстанцируется.
        via:     SheetRefComponent — X_* в родителе. Всегда задан.
        parent:  инстанс родительского Sheet, или None для прямых
                 детей корня.
        page:    сквозной номер страницы (1..N) в порядке обхода
                 дерева. У корневого SheetInstance page=1, у
                 остальных — по мере создания.
    """
    sheet:  "Sheet"
    via:    "SheetRefComponent"
    parent: Optional["SheetInstance"]
    page:   int

    # ---------- идентичность ----------

    def __hash__(self) -> int:
        """Хэш по uuid (uuid X_* в родителе). Уникален в проекте."""
        return hash(self.uuid)

    # ---------- uuid и путь ----------

    @property
    def uuid(self) -> str:
        """uuid этого узла дерева — uuid X_*, через который создан.

        Тот же идентификатор, что writer пишет в (sheet (uuid ...))
        родительского .kicad_sch. Не хранится отдельно: единственный
        источник — via.uuid.
        """
        return self.via.uuid

    @cached_property
    def path(self) -> str:
        """Instance-путь KiCad: /<root_uuid>/<x1_uuid>/.../<this_uuid>/.

        Первый сегмент — uuid корневого Sheet (файла корня), далее —
        uuid-ы X_* по цепочке parent (включая self). Цепочка parent
        не меняется после построения дерева, поэтому значение
        кэшируется.
        """
        parts = []
        node: Optional[SheetInstance] = self
        while node is not None:
            parts.append(node.uuid)
            node = node.parent
        parts.reverse()
        return "/" + "/".join([self.root_uuid, *parts]) + "/"

    # ---------- корень дерева ----------

    @cached_property
    def root_sheet(self) -> "Sheet":
        """Корневой Sheet дерева, к которому относится instance.

        Подъём по parent до конца; корневой Sheet — это via.sheet
        того X_*, у которого parent is None. То есть для прямых
        детей корня: parent=None, via.sheet — корневой Sheet.
        Для внуков: цепочка приводит к тому же корневому Sheet.
        """
        node = self
        while node.parent is not None:
            node = node.parent
        return node.via.sheet

    @cached_property
    def root_uuid(self) -> str:
        """uuid корневого Sheet (первый сегмент path)."""
        return self.root_sheet.uuid

    # ---------- вспомогательные ----------

    @property
    def designator(self) -> str:
        """Локальный designator X_*, через который создан instance."""
        return self.via.designator

    @property
    def stem(self) -> str:
        """Stem листа, который инстанцируется."""
        return self.sheet.stem

    def __repr__(self) -> str:
        return (
            f"SheetInstance("
            f"sheet={self.sheet.stem!r}, "
            f"via={self.via.designator!r}, "
            f"page={self.page})"
        )