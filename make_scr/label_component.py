# label_component.py
"""Локальная метка на схеме — label в терминах KiCad.

Не Component: у метки нет designator, lib_id, пинов, bbox и
instances. Самостоятельный элемент листа, как Wire или Junction.

Хранится в sheet.labels отдельным списком и не смешивается
с sheet.components. Общее с другими элементами листа — uuid
(через Primitive).

Связь с сетью — ссылкой на Net. Имя метки не хранится полем,
а извлекается из net.name: имя живёт в сети, метка на неё
ссылается. Переименование сети автоматически отражается
на метке.

Порядок загрузки:
    Метка создаётся только после того, как объект Net
    зарегистрирован в Netlist. В Sheet это значит — не раньше
    _load_nets; в роутере — не раньше route_all, где цикл
    уже идёт по netlist.nets.

Поле reason объясняет, почему метка появилась:
    SHEET_PIN_NAME    — имя корневой сети рядом с X_*-пином
                        (создаётся при загрузке, живёт постоянно);
    INTERNAL_NET_NAME — имя внутренней сети (роутер, при прогоне);
    FALLBACK          — аварийная метка (роутер, при провале);
    USER              — ручная метка (если когда-нибудь появятся).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Tuple, TYPE_CHECKING

from constants import Direction
from net import Net
from primitive import Primitive

if TYPE_CHECKING:
    from sheet import Sheet


class LabelReason(str, Enum):
    """Почему метка появилась на листе.

    Влияет на жизненный цикл: структурные (SHEET_PIN_NAME, USER)
    живут постоянно, роутерные (INTERNAL_NET_NAME, FALLBACK) —
    до следующего reset_routing_marks.
    """
    SHEET_PIN_NAME     = "sheet_pin_name"
    INTERNAL_NET_NAME  = "internal_net_name"
    FALLBACK           = "fallback"
    USER               = "user"


@dataclass(eq=False, kw_only=True)
class LabelComponent(Primitive):
    """Локальная метка на схеме.

    Имя метки не хранится полем: оно всегда равно net.name.
    Имя сети в модели — строка, у метки — проекция этой строки.
    """

    net: Net
    direction: Direction
    reason: LabelReason
    anchor_page_mm: Tuple[float, float]
    sheet: Optional["Sheet"] = field(default=None, repr=False)

    @property
    def name(self) -> str:
        """Текст метки = имя сети, к которой она относится."""
        return self.net.name

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.net.name:
            raise ValueError(
                f"LabelComponent {self.uuid}: сеть без имени"
            )

    def __hash__(self) -> int:
        return hash(self.uuid)

    def __repr__(self) -> str:
        x, y = self.anchor_page_mm
        return (
            f"<Label {self.name!r} @ ({x:.2f}, {y:.2f}) "
            f"reason={self.reason.value}>"
        )