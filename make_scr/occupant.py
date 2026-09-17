# make_scr/occupant.py
"""Объекты, занимающие клетки карты.

Клетка либо ссылается на Occupant, либо свободна (её нет в карте).
Понятия «улица» нет: улица — пустой зазор между ячейками раскладки,
а не свойство клетки.

Конкретные типы:
    ComponentBody — внутри габарита компонента, не пин;
    PinCell       — клетка пина;
    WireCell      — клетка проложенного провода.

Каждый тип сам знает:
    owner()       — чей это объект (designator) или None;
    allows(net)   — можно ли провести трассу сети net через клетку.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING

from constants import OccupantKind

if TYPE_CHECKING:
    from component import Component
    from pin import Pin
    from wire import Wire


class Occupant:
    """Базовый класс для всего, что занимает клетку.

    Наследники реализуют allows() и, при необходимости, owner().
    """
    kind: OccupantKind

    def owner(self) -> Optional[str]:
        """designator компонента-владельца или None."""
        return None

    def allows(self, net: str) -> bool:
        """Можно ли провести трассу сети net через эту клетку."""
        return False


@dataclass(eq=False)
class ComponentBody(Occupant):
    """Габарит компонента вне клеток пинов.

    Внутрь габарита трассы не пускаются — там корпус.
    """
    component: "Component"
    kind: OccupantKind = OccupantKind.COMPONENT_BODY

    def owner(self) -> Optional[str]:
        return self.component.designator

    def allows(self, net: str) -> bool:
        return False


@dataclass(eq=False)
class PinCell(Occupant):
    """Клетка пина.

    Разрешает вход только сети, к которой привязан пин.
    """
    component: "Component"
    pin: "Pin"
    kind: OccupantKind = OccupantKind.PIN

    def owner(self) -> Optional[str]:
        return self.component.designator

    def allows(self, net: str) -> bool:
        return self.pin.net_ref == net


@dataclass(eq=False)
class WireCell(Occupant):
    """Клетка, занятая проложенным проводом.

    Разрешает вход только той же сети.
    """
    wire: "Wire"
    kind: OccupantKind = OccupantKind.WIRE

    def owner(self) -> Optional[str]:
        return None

    def allows(self, net: str) -> bool:
        return self.wire.net_name == net
