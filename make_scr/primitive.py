# primitive.py
"""Базовый элемент схемы: uuid в формате KiCad.

Все объекты .kicad_sch, которые сериализуются как самостоятельные
элементы (symbol, label, hierarchical_label, sheet, sheet_pin, wire,
junction, no_connect, bus_entry), имеют uuid. Этот модуль даёт
общий предок с полем uuid и валидацией формата.

Классы-наследники — dataclass'ы с kw_only=True, чтобы поле uuid
(с дефолтом) не конфликтовало с обязательными полями наследников.
Все вызовы в проекте и без того идут через именованные аргументы.
"""
from __future__ import annotations

import re
import uuid as _uuid_mod
from dataclasses import dataclass, field


_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def new_uuid() -> str:
    """Свежий UUID в формате KiCad (8-4-4-4-12 через дефис)."""
    return str(_uuid_mod.uuid4())


@dataclass(kw_only=True)
class Primitive:
    """Общий предок всех элементов схемы.

    Единственная гарантия — непустой uuid в формате KiCad.
    Всё остальное (позиция, пины, связи, лист-владелец) —
    контракт конкретного наследника.
    """

    uuid: str = field(default_factory=new_uuid)

    def __post_init__(self) -> None:
        if not self.uuid or not _UUID_RE.match(self.uuid):
            raise ValueError(
                f"{type(self).__name__}: uuid={self.uuid!r} "
                f"не в формате 8-4-4-4-12"
            )
