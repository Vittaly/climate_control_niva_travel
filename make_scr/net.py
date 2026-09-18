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

        # Контекст префикса: [page] [net] [comp] [pin].
        # Атрибуты wire могут называться по-разному — берём через
        # getattr с разумными дефолтами, чтобы модуль не падал,
        # если Wire эволюционирует.
        page = getattr(wire, "page", None) or getattr(wire, "sheet", None)
        comp = getattr(wire, "owner", None) or getattr(wire, "comp", None)
        pin = getattr(wire, "port", None) or getattr(wire, "pin", None)

        src = getattr(wire, "src_fqn", None) or getattr(wire, "from_fqn", "?")
        dst = getattr(wire, "dst_fqn", None) or getattr(wire, "to_fqn", "?")

        # segments — метод, нужен вызов
        segments = getattr(wire, "segments", None)
        if callable(segments):
            seg = len(segments())
        else:
            seg = len(getattr(wire, "points", []) or [])

        log.debug(
            "%s wire %s -> %s segments=%d",
            ctx(page=page, net=self.name, comp=comp, pin=pin),
            src, dst, seg,
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