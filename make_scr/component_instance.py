# component_instance.py
"""Одно вхождение Component в дереве проекта.

Используется только для обычных символов и портов. Sheet-ref имеет
свой отдельный SheetRefInstance и не оборачивается в
ComponentInstance.

Хранение:
    component  — символ (Component, PortComponent, …);
    sheet_ref  — SheetRefInstance контекста, в котором символ
                 появился. Это либо 0-й SheetRefInstance корневой
                 страницы (page=1), либо SheetRefInstance какого-то
                 X_* родительской страницы (page≥2).

    Оба поля обязательны: ComponentInstance создаётся только внутри
    Sheet._load_components / Sheet.register_from, где parent_sri
    всегда известен.

Нумерация:
    page вхождения = sheet_ref.page — KiCad-номер страницы, где
    символ нарисован. Для корневой страницы это 1, для вложенной —
    номер соответствующего X_*.

    refdef — производное от designator и page:
        page == 1  → designator                    "R1"
        page ≥ 2   → make_refdes(designator, page) "R2_M2"

    Это ровно то, что KiCad пишет в (reference …) блока
    (instances …) символа.

Instance-путь:
    container_path = sheet_ref.content_path — путь страницы, где
    символ физически нарисован. Идёт в (path …) того же блока.

Соответствие KiCad:
    R1 в корне:              page=1  refdef="R1"     path="/<root>"
    R2 через X_MIDDLE:       page=2  refdef="R2_M2"  path="/<root>/<XM>"
    R3 через X_DOWN:         page=3  refdef="R3_M3"  path="/<root>/<XM>/<XD>"
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from typing import TYPE_CHECKING

from refdes import make_refdes

if TYPE_CHECKING:
    from component import Component
    from sheet_ref_instance import SheetRefInstance


@dataclass(eq=False)
class ComponentInstance:
    """Одно вхождение Component в дереве.

    Attributes:
        component:  Component — символ.
        sheet_ref:  SheetRefInstance — контекст, в котором символ
                    появился. Номер страницы и путь берутся отсюда.
                    Всегда задан: ComponentInstance создаётся только
                    при инстанцировании страницы в конкретном
                    контексте.
    """
    component: "Component"
    sheet_ref: "SheetRefInstance"

    def __hash__(self) -> int:
        return hash((id(self.component), id(self.sheet_ref)))

    # ---------- идентичность ----------

    @property
    def designator(self) -> str:
        return self.component.designator

    # ---------- номер страницы ----------

    @property
    def page(self) -> int:
        """KiCad-номер страницы, где нарисован символ.

        Делегат к sheet_ref.page. Для корневой страницы 1, для
        вложенной — номер соответствующего X_*.
        """
        return self.sheet_ref.page

    # ---------- проектный идентификатор ----------

    @property
    def refdef(self) -> str:
        """Проектное имя вхождения.

        page == 1 → designator.
        page ≥ 2  → make_refdes(designator, page) — "R2_M2".

        KiCad пишет это значение в (reference …) блока
        (instances …) символа в его собственном .kicad_sch.
        """
        if self.page == 1:
            return self.component.designator
        return make_refdes(self.component.designator, self.page)

    # ---------- instance-пути ----------

    @cached_property
    def container_path(self) -> str:
        """Instance-путь страницы, где физически нарисован символ.

        Делегат к sheet_ref.content_path.
        """
        return self.sheet_ref.content_path

    @cached_property
    def content_path(self) -> str:
        """У обычного символа целевой страницы нет — совпадает с
        container_path. Оставлено для симметрии с SheetRefInstance."""
        return self.container_path

    def __repr__(self) -> str:
        return (f"ComponentInstance(des={self.designator!r}, "
                f"refdef={self.refdef!r}, "
                f"page={self.page}, "
                f"sheet_ref={self.sheet_ref!r})")