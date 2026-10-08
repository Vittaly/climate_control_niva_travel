# sheet_ref_instance.py
"""Вхождение SheetRefComponent в дереве.

Один класс для 0-го вхождения (страница как корень) и для реальных
вхождений X_*. Различие — в значении component:

    0-е:           component is None,  _local_sheet задан, parent is None
    X_* в корне:   component задан,    parent = 0-й SRI корня
    X_* вложенный: component задан,    parent = SRI родительского X_*

Правила вычисления свойств одинаковы для всех:
    uuid            = component.uuid  если component, иначе _local_sheet.uuid
    page            = прямое поле (KiCad-номер: 1 у корня, 2+ у вложенных)
    container_path  = parent.content_path  если parent;
                      иначе "/<uuid родительской страницы>"  для X_* в корне;
                      иначе "/"                              для 0-го
    content_path    = rstrip(container_path, "/") + "/" + uuid

Никаких веток "если 0-й — то так, если реальный — то этак":
различие уходит в значения полей и в один if (parent is None).

Номер страницы:
    page — KiCad-номер, без внутреннего сдвига.
        Корень проекта:              page = 1
        Первая вложенная страница:   page = 2
        Вторая вложенная:            page = 3
        ...

    Выдаётся при создании SheetRefInstance:
        - 0-й SRI корня — Sheet.load_root ставит page=1;
        - реальный X_* — родительский Sheet._load_components
          передаёт sheet_ref_start_counter в SheetRefComponent.__init__,
          тот кладёт его в page своего SRI. Тот же номер используется
          для следующего контекста того же X_* в on_new_context.

    Значение 0 — дефолт датакласса, не должен встречаться в
    полностью загруженном дереве.

Корень дерева:
    root_sheet — вычисляемое свойство: подъём по parent-цепочке
    до верхнего SRI. Верхний SRI — 0-й (component=None), его
    _local_sheet есть корневой Sheet. Никакого отдельного поля
    «_load_root» нигде не хранится.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from sheet import Sheet
    from sheet_ref import SheetRefComponent


@dataclass(eq=False)
class SheetRefInstance:
    """Одно вхождение X_* (0-е или реальное).

    Attributes:
        component:    SheetRefComponent — символ X_*; None для
                      0-го вхождения («сама страница как корень»).
        parent:       SheetRefInstance родительского контекста.
                      None для 0-го; для X_* в корне — 0-й SRI
                      корневой страницы.
        page:         KiCad-номер страницы:
                        1 у корня,
                        2 у первой вложенной,
                        3 у следующей, и т.д.
                      Поле, не производное: назначается при создании
                      SheetRefInstance (Sheet.load_root для 0-го;
                      SheetRefComponent.__init__ / on_new_context —
                      для реальных).
    """
    component: Optional["SheetRefComponent"] = None
    parent: Optional[SheetRefInstance] = None
    page: int = 0

    # Приватное поле, только для 0-го: сама страница, которую он
    # представляет. У реальных вхождений не задано — их страница
    # берётся через component.child_sheet.
    _local_sheet: Optional["Sheet"] = field(
        default=None, repr=False, compare=False,
    )

    def __hash__(self) -> int:
        return hash((id(self.component), id(self.parent)))

    # ---------- классификация ----------

    @property
    def is_local(self) -> bool:
        """True для 0-го вхождения — страница как корень."""
        return self.component is None

    # ---------- корень дерева ----------

    @cached_property
    def root_sheet(self) -> "Sheet":
        """Корень дерева, в котором находится это вхождение.

        Подъём по parent-цепочке до верхнего SRI. Верхний — 0-й
        (is_local=True, component=None), его _local_sheet есть
        корневой Sheet.

        Корень вычисляется, не хранится: единственный источник
        истины — цепочка parent'ов от этого SRI вверх.
        """
        node: SheetRefInstance = self
        while node.parent is not None:
            node = node.parent
        return node._local_sheet

    # ---------- общий доступ к странице и uuid ----------

    @property
    def target_sheet(self) -> "Sheet":
        """Страница, к которой относится вхождение.

        0-е         → сама страница (_local_sheet).
        Реальное    → component.child_sheet (целевая X_*).
        """
        if self.component is not None:
            return self.component.child_sheet
        return self._local_sheet

    @property
    def uuid(self) -> str:
        """uuid последнего сегмента content_path.

        0-е         → uuid страницы (страница сама становится
                      сегментом пути).
        Реальное    → uuid X_*-символа.
        """
        if self.component is not None:
            return self.component.uuid
        return self._local_sheet.uuid

    # ---------- пути ----------

    @cached_property
    def container_path(self) -> str:
        """Путь страницы, где нарисован X_* (или корень для 0-го).

        Реальное с parent   → content_path родителя.
        X_* в корне         → /<uuid страницы-родителя>.
        0-е                 → /  (корень без собственного uuid).
        """
        if self.parent is not None:
            return self.parent.content_path
        # Нет родителя. У X_* в корне «родитель» — это страница,
        # в которой он нарисован (component.sheet). У 0-го
        # родителя нет вообще — он и есть корень.
        if self.component is not None:
            return f"/{self.component.sheet.uuid}"
        return "/"

    @cached_property
    def content_path(self) -> str:
        """Путь содержимого страницы, к которой относится вхождение.

        Единая формула: <container_path без trailing />/<uuid>.
        Она даёт корректный результат и для 0-го (корень → путь
        самой страницы), и для реальных (путь целевой страницы).
        """
        base = self.container_path.rstrip("/")
        return f"{base}/{self.uuid}"

    def __repr__(self) -> str:
        if self.is_local:
            tag = f"<local:{self._local_sheet.stem}>"
        else:
            tag = self.component.designator
        p = "-" if self.parent is None else (
            self.parent.component.designator
            if self.parent.component is not None
            else "<local>"
        )
        return (f"SheetRefInstance({tag}, "
                f"page={self.page}, "
                f"parent={p!r})")