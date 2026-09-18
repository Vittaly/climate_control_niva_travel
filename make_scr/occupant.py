# make_scr/occupant.py
"""Объекты, занимающие клетки карты.

Клетка либо ссылается на Occupant, либо свободна (её нет в карте).

Конкретные типы:
    ComponentBody — внутри габарита компонента, не пин;
    PinCell       — клетка пина (endpoint одной сети);
    WireCell      — клетка проложенного провода.

WireCell хранит СПИСОК проводов (1 или 2). Две разные сети могут
делить клетку только если обе проходят транзитом и перпендикулярно
друг другу (крест). Это разрешено в KiCad: пересечение без общего
endpoint'а не соединяет провода. Проверка совместимости делается
в router_impl/rules.py (нужен контекст входа/выхода — угол), а не
здесь: occupant отвечает только за состав клетки.

Каждый тип сам знает:
    owner()       — чей это объект (designator) или None;
    allows(net)   — можно ли провести трассу сети net через клетку
                    (без учёта направления входа);
    wires()       — список проводов в клетке (для WireCell);
    has_foreign_wire(net) — есть ли в клетке чужая сеть.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, TYPE_CHECKING

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
        """Можно ли провести трассу сети net через эту клетку.

        Без учёта направления входа. Для WireCell с двумя разными
        сетями возвращает True только для своей сети: чужая сеть
        должна проверяться rules.py с контекстом угла.
        """
        return False

    def wires(self) -> List["Wire"]:
        """Список проводов в клетке. По умолчанию пустой."""
        return []

    def has_foreign_wire(self, net: str) -> bool:
        """Есть ли в клетке провод чужой сети."""
        return any(w.net_name != net for w in self.wires())


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
    """Клетка, занятая одним или двумя проводами.

    Атрибуты:
        wires: список проводов. Обычно 1. Два — только если провода
               разных сетей и оба проходят клетку транзитом
               перпендикулярно (крест). Проверка совместимости
               живёт в rules.py: там есть доступ к углу входа и
               могут быть вычислены ориентации сегментов.

    Совместимость со старой моделью:
        .wire   — свойство, возвращает первый провод. Оставлено
                  для кода, который ещё не перешёл на .wires().
    """

    wires: List["Wire"] = field(default_factory=list)
    kind: OccupantKind = OccupantKind.WIRE

    # ---------- совместимость со старой моделью ----------

    @property
    def wire(self) -> Optional["Wire"]:
        """Первый провод клетки. Совместимость со старым API."""
        return self.wires[0] if self.wires else None

    # ---------- API Occupant ----------

    def owner(self) -> Optional[str]:
        return None

    def allows(self, net: str) -> bool:
        """Разрешает только ту сеть, что уже есть в клетке.

        Чужая сеть формально не разрешена здесь — она может быть
        разрешена в rules.py, если вход перпендикулярен ориентации
        чужих сегментов.
        """
        return any(w.net_name == net for w in self.wires)

    def wires(self) -> List["Wire"]:
        return self.wires

    # ---------- служебное ----------

    def add_wire(self, wire: "Wire") -> bool:
        """Добавляет провод. Не дублирует по объекту.

        Returns:
            True — если провод добавлен;
            False — если такой провод уже есть.
        """
        for w in self.wires:
            if w is wire:
                return False
        self.wires.append(wire)
        return True

    def remove_wire(self, wire: "Wire") -> None:
        """Удаляет провод из клетки, если он там есть."""
        self.wires = [w for w in self.wires if w is not wire]

    def net_names(self) -> List[str]:
        """Имена сетей, занимающих клетку."""
        return [w.net_name for w in self.wires]