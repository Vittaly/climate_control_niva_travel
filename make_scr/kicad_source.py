# make_scr/kicad_source.py
"""Мост к kicad_sch_api: lib_id -> пины и bbox символа.

Библиотека kicad-sch-api (модуль library.cache) отдаёт SymbolDefinition
с готовыми полями:
    symbol.pins           — List[SchematicPin]
    symbol.bounding_box   — (min_x, min_y, max_x, max_y) в мм

Поля SchematicPin:
    number, name          — str
    position              — Point(x, y) в мм
    rotation              — float (угол 0/90/180/270)
    pin_type              — PinType enum
    pin_shape             — PinShape enum
    length                — float

Класс не знает про Component/Cell/Pin. Единственная задача —
достать метаданные символа из библиотеки KiCad и закэшировать их.
"""
from typing import Dict, List, Tuple

import kicad_sch_api as ksa

from logging_setup import get_logger

log = get_logger(__name__)


class KiCadSource:
    """Провайдер метаданных символов KiCad с мемоизацией."""

    def __init__(self):
        """Открывает глобальный кэш символов kicad_sch_api."""
        self._cache = ksa.get_symbol_cache()
        self._pins_memo: Dict[str, List[dict]] = {}
        self._bbox_memo: Dict[str, Tuple[float, float, float, float]] = {}
        log.debug("KiCadSource инициализирован")

    # ---------- внутреннее ----------

    def _get_symbol(self, lib_id: str):
        """Достаёт символ из библиотеки.

        Raises:
            KeyError: если символ не найден в кэше kicad_sch_api.
        """
        sym = self._cache.get_symbol(lib_id)
        if sym is None:
            log.error("Символ не найден: %s", lib_id)
            raise KeyError(f"Символ не найден: {lib_id}")
        return sym

    # ---------- публичное ----------

    def get_pins(self, lib_id: str) -> List[dict]:
        """Возвращает список пинов символа в исходных мм KiCad.

        Каждый элемент:
            {"number", "name", "x_mm", "y_mm",
             "orientation", "electrical_type", "shape"}

        Поля SchematicPin из kicad-sch-api:
            number         — str
            name           — str
            position.x/y   — Point в мм
            rotation       — float, наш "orientation"
            pin_type       — PinType enum, .value даёт "input"/"passive"/...
            pin_shape      — PinShape enum, .value даёт "line"/"inverted"/...

        Результат мемоизируется по lib_id.
        """
        if lib_id in self._pins_memo:
            return self._pins_memo[lib_id]

        symbol = self._get_symbol(lib_id)
        pins: List[dict] = []

        for pin in symbol.pins:
            rotation = float(getattr(pin, "rotation", 0))

            pin_type = getattr(pin, "pin_type", None)
            if pin_type is not None and hasattr(pin_type, "value"):
                electrical_type = pin_type.value
            else:
                electrical_type = str(pin_type) if pin_type else ""

            pin_shape = getattr(pin, "pin_shape", None)
            if pin_shape is not None and hasattr(pin_shape, "value"):
                shape = pin_shape.value
            else:
                shape = str(pin_shape) if pin_shape else ""

            pins.append({
                "number": str(pin.number),
                "name": str(pin.name),
                "x_mm": float(pin.position.x),
                "y_mm": float(pin.position.y),
                "orientation": rotation,
                "electrical_type": electrical_type,
                "shape": shape,
            })

        self._pins_memo[lib_id] = pins
        log.debug("Пины %s: %d шт.", lib_id, len(pins))
        return pins

    def get_symbol_bbox_mm(self, lib_id: str) -> Tuple[float, float, float, float]:
        """Габаритный прямоугольник символа в мм: (min_x, min_y, max_x, max_y).

        Использует готовое свойство SymbolDefinition.bounding_box —
        оно уже учитывает графические примитивы и пины.
        Результат мемоизируется.
        """
        if lib_id in self._bbox_memo:
            return self._bbox_memo[lib_id]

        symbol = self._get_symbol(lib_id)
        bbox = symbol.bounding_box
        self._bbox_memo[lib_id] = bbox
        log.debug("BBox %s: %s", lib_id, bbox)
        return bbox