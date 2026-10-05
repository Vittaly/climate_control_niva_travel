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
    new_uuid,
)
from primitive import Primitive

if TYPE_CHECKING:
    from component import Component


@dataclass(eq=False, kw_only=True)
class Pin(Primitive):
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
    # ── обязательные (без дефолта) ──
    owner: str
    offset_mm: Tuple[float, float]

    # ── опциональные (с дефолтом) ──
    number: Optional[str] = None
    name: Optional[str] = None
    direction: Direction = DEFAULT_DIRECTION
    net_ref: Optional[str] = None
    component: Optional["Component"] = field(default=None, repr=False)
    alias_of: Optional["Pin"] = field(default=None, repr=False)
    uuid: str = field(default_factory=new_uuid)
    sim_port: Optional[str] = None

    # ---------- хэш / идентичность ----------

    def __hash__(self) -> int:
        return hash((self.owner, self.number))

    def __post_init__(self):
        super().__post_init__()
        if not self.number and not self.name:
            raise ValueError(
                f"Pin без number и name: owner={self.owner!r} — "
                f"у пина должен быть хотя бы один идентификатор"
            )

    @property
    def identifier(self) -> str:
        """Идентификатор пина внутри компонента.

        Обычный пин — номер ('42', 'PA13'): KiCad адресует его по
        number, name — только подпись.
        Sheet-пин — имя порта ('VCC_12V'): номера у него в KiCad нет,
        единственный идентификатор — name.

        Всегда возвращает непустую строку при корректной загрузке.
        Пустой identifier — баг в Component/Pin, который стоит ловить
        в __post_init__: у пина должен быть хотя бы number или name.
        """
        return self.number or self.name or ""

    @property
    def local_key(self) -> str:
        """Локальный ключ пина: 'U1:42' или 'X_POWER_SUPPLY:VCC_12V'."""
        return f"{self.owner}:{self.identifier}"

    @property
    def fqn(self) -> str:
        """Полный ключ пина с префиксом страницы."""
        if self.component is not None and self.component.sheet is not None:
            return f"{self.component.fqn}:{self.identifier}"
        return self.local_key

    # ---------- удобные свойства ----------

    @property
    def contact_mm(self) -> Optional[Tuple[float, float]]:
        """Точка контакта пина на странице, в мм (Y↓).

        abs_pin_mm = anchor_page_mm + offset_mm.
        Возвращает None, если пин не привязан к компоненту
        или у компонента ещё нет anchor_page_mm.

        Используется writer'ом для anchor'а fallback-метки:
        anchor = contact_mm, direction = pin.direction (без инверсии),
        текст рисуется против вектора направления, то есть наружу.
        """
        comp = self.component
        if comp is None or comp.anchor_page_mm is None:
            return None
        ax, ay = comp.anchor_page_mm
        return (ax + self.offset_x, ay + self.offset_y)
    
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