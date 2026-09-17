# pin.py
"""Пин компонента: локальная сущность внутри компонента.

Хранит СМЕЩЕНИЕ от якоря (offset_mm) в системе страницы (Y↓).
Реальные координаты пина на странице вычисляются как:
    abs_pin_mm = anchor_page_mm + pin.offset_mm

Пины НЕ привязаны к клеткам: они могут лежать между клетками.
Клетки используются только для роутинга (округление abs_pin_mm).

direction — направление пина в KiCad-семантике: «от точки подключения
к телу». Для пина, лежащего на верхней грани символа, это обычно DOWN;
для пина на нижней грани — UP; на левой — RIGHT; на правой — LEFT.

direction в этом классе всегда достоверное: оно либо совпадает с
библиотечным orientation, либо переопределено в Component.from_yaml
по геометрии (outward). Библиотечное orientation в Pin не хранится —
оно используется только в момент создания для сравнения и warning.
"""
from dataclasses import dataclass, field
from typing import Optional, Tuple, TYPE_CHECKING

from constants import (
    Axis,
    DEFAULT_DIRECTION,
    DEFAULT_GRID_MM,
    Direction,
    GRID_EPSILON_MM,
)

if TYPE_CHECKING:
    from component import Component


@dataclass(eq=False)
class Pin:
    """Пин компонента.

    Attributes:
        owner:      локальный designator компонента-владельца ("U1").
        number:     номер пина ("1", "A", ...).
        name:       имя пина из символа ("VDD", "PA0", ...).
        offset_mm:  (x_mm, y_mm) — смещение пина от якоря
                    (система страницы, Y↓). Пин может лежать
                    не на сетке.
        direction:  направление вывода (KiCad-семантика: «в тело»).
        net_ref:    имя сети, к которой привязан пин (или None).
        component:  обратная ссылка на Component.
        alias_of:   если пин — alias другого пина (тот же пад),
                    ссылка на канонический пин.
    """
    owner: str
    number: str
    name: str
    offset_mm: Tuple[float, float]
    direction: Direction = DEFAULT_DIRECTION
    net_ref: Optional[str] = None
    component: Optional["Component"] = field(default=None, repr=False)
    alias_of: Optional["Pin"] = field(default=None, repr=False)

    # ---------- хэш / идентичность ----------

    def __hash__(self) -> int:
        return hash((self.owner, self.number))

    @property
    def local_key(self) -> str:
        """Локальный ключ пина: "U1:42"."""
        return f"{self.owner}:{self.number}"

    @property
    def fqn(self) -> str:
        """Полный ключ пина с префиксом страницы."""
        if self.component is not None and self.component.sheet is not None:
            return f"{self.component.fqn}:{self.number}"
        return self.local_key

    # ---------- удобные свойства ----------

    @property
    def offset_x(self) -> float:
        """Смещение пина от якоря по X (мм)."""
        return self.offset_mm[Axis.X]

    @property
    def offset_y(self) -> float:
        """Смещение пина от якоря по Y (мм)."""
        return self.offset_mm[Axis.Y]

    @property
    def on_grid(self) -> bool:
        """Лежит ли смещение пина точно на сетке (в мм).

        Проверяет, что offset_x/offset_y кратны DEFAULT_GRID_MM.
        Используется для отладки — но в новой модели пин может
        быть не на сетке, это норма.
        """
        return (
            abs(self.offset_x % DEFAULT_GRID_MM) < GRID_EPSILON_MM and
            abs(self.offset_y % DEFAULT_GRID_MM) < GRID_EPSILON_MM
        )

    # ---------- alias ----------

    @property
    def is_alias(self) -> bool:
        """Является ли пин alias другого пина (тот же пад)."""
        return self.alias_of is not None

    @property
    def canonical(self) -> "Pin":
        """Канонический пин: сам пин или его alias-родитель."""
        return self.alias_of if self.alias_of is not None else self