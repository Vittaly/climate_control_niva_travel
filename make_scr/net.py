# make_scr/net.py
"""Сеть: пины и провода.

Сеть хранит:
    - FQN-ключи пинов, привязанных к ней;
    - проложенные провода (Wire) этой сети.

Провода принадлежат сети, а не странице: страница — контейнер
компонентов, сеть — владелец своих соединений.

Логирование идёт через префикс ctx(page, net, comp, pin) — см.
logging_setup.ctx. Пропущенные поля в середине префикса выводятся
как [-], чтобы сохранить позицию; хвостовые опускаются.
"""
from dataclasses import dataclass, field
from typing import Dict, List

from constants import DEFAULT_NET_TYPE
from logging_setup import get_logger, ctx
from wire import Wire
from pin import Pin

log = get_logger(__name__)


@dataclass
class NetRef:
    """Лёгкая ссылка на сеть по имени."""
    name: str


@dataclass
class Net:
    """Электрическая сеть.

    Attributes:
        name:     имя сети ("VCC_3V3").
        net_type: категория (POWER, GND, DIGITAL_SIGNAL, ...).
        flags:    список атрибутов из YAML.
        pins:     FQN-ключи пинов, привязанных к сети.
        wires:    проложенные провода этой сети.
    """
    name: str
    net_type: str = DEFAULT_NET_TYPE
    flags: List[str] = field(default_factory=list)
    pins: Dict[str, Pin] = field(default_factory=dict)
    wires: List[Wire] = field(default_factory=list)

    # ---------- добавление ----------

    def add_wire(self, wire: Wire) -> None:
        """Добавляет провод к сети.

        Raises:
            ValueError: если провод принадлежит другой сети.
        """
        if wire.net_name != self.name:
            raise ValueError(
                f"Провод сети {wire.net_name} не может быть добавлен "
                f"в сеть {self.name}"
            )
        self.wires.append(wire)

        # Контракт Wire зафиксирован в wire.py:
        #   start: Pin                 — пин-начало (обязателен)
        #   end:   Optional[Pin]       — пин-конец; None для T-врезки
        #   segments() -> List[WireSegment]
        #   length: int
        # Никаких getattr-угадываний: если Wire изменится, падать
        # лучше на AttributeError в тесте, а не молча печатать "?".
        start_pin: Pin = wire.start
        end_pin = wire.end

        src = start_pin.local_key
        dst = end_pin.local_key if end_pin is not None else "T"

        comp = start_pin.component.designator \
            if start_pin.component is not None else None
        page = None
        if start_pin.component is not None \
                and start_pin.component.sheet is not None:
            page = start_pin.component.sheet.page or None

        log.debug(
            "%s wire %s -> %s segments=%d cells=%d",
            ctx(page=page, net=self.name, comp=comp, pin=start_pin.number),
            src, dst, len(wire.segments()), wire.length,
        )

    # ---------- проверки ----------

    def contains(self, cell) -> bool:
        """Проходит ли через клетку хоть один провод этой сети."""
        return any(w.contains(cell) for w in self.wires)

    def is_fully_routed(self) -> bool:
        """Все ли пины сети соединены.

        Для дерева достаточно, чтобы проводов было не меньше, чем
        пинов минус один. Для циклических сетей это не критерий, но
        как грубая оценка работает.
        """
        if len(self.pins) < 2:
            return True
        return len(self.wires) >= len(self.pins) - 1

    @property
    def total_length(self) -> int:
        """Суммарная длина всех проводов сети в клетках."""
        return sum(w.length for w in self.wires)