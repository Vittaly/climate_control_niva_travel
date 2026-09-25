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

Двухуровневый кэш:
    * _pins_memo / _bbox_memo — в памяти процесса, мемоизация на
      время одного прогона;
    * CACHE_FILE (pickle)     — на диске, сохраняется между
      запусками.

Зачем диск-кэш:
    Парсинг .kicad_sym через kicad-sch-api стоит ~30 секунд на
    27 библиотек (Device, Transistor_FET, Regulator_Linear,
    Connector_Generic, Connector_JST, MCU_ST_STM32F1 и т.д.).
    Кэш ksa держится только в памяти процесса и теряется при
    выходе. Свой _pins_memo мы сериализуем на диск и загружаем
    при следующем старте — так повторные прогоны обходятся без
    пересборки дерева S-выражений.

Инвалидация:
    Кэш НЕ инвалидируется автоматически при обновлении
    KiCad-библиотек. CACHE_VERSION защищает от изменения
    формата pin_dict — старые файлы игнорируются. Для ручного
    сброса: удалить ~/.cache/make_scr/ или вызвать
    clear_persistent_cache().
"""
from __future__ import annotations

import pickle
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import kicad_sch_api as ksa

from logging_setup import get_logger

log = get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────
# Диск-кэш
# ─────────────────────────────────────────────────────────────────────

# Расположение: ~/.cache/make_scr/ (Linux XDG-совместимо).
CACHE_DIR = Path.home() / ".cache" / "make_scr"
CACHE_FILE = CACHE_DIR / "kicad_source.pkl"

# Версия схемы кэша. Поднимать при изменении формата pin_dict
# или логики get_pins — старые файлы будут проигнорированы.
CACHE_VERSION = 1


def clear_persistent_cache() -> None:
    """Удалить диск-кэш KiCadSource.

    Вызывается вручную (например, из main.py по флагу
    --clear-kicad-cache), когда библиотеки KiCad обновились и
    нужно пересобрать кэш с нуля.
    """
    if CACHE_FILE.exists():
        try:
            CACHE_FILE.unlink()
            log.info("Кэш KiCadSource удалён: %s", CACHE_FILE)
        except OSError as e:
            log.warning("Не удалось удалить кэш %s: %s", CACHE_FILE, e)
    else:
        log.debug("Кэш KiCadSource уже отсутствует: %s", CACHE_FILE)


# ─────────────────────────────────────────────────────────────────────
# KiCadSource
# ─────────────────────────────────────────────────────────────────────

class KiCadSource:
    """Провайдер метаданных символов KiCad с мемоизацией.

    Двухуровневый кэш:
        * _pins_memo / _bbox_memo — в памяти процесса;
        * CACHE_FILE (pickle)     — на диске, между запусками.

    flush() вызывается явно в Project.load() перед возможным
    raise ProjectLoadError — чтобы результат разбора сохранился
    даже при ошибке в YAML.
    """

    def __init__(self) -> None:
        """Открывает кэш символов kicad_sch_api и подгружает диск-кэш."""
        self._cache = ksa.get_symbol_cache()
        self._pins_memo: Dict[str, List[dict]] = {}
        self._bbox_memo: Dict[str, Tuple[float, float, float, float]] = {}
        self._dirty = False
        self._load_persistent_cache()
        log.debug(
            "KiCadSource инициализирован (кэш на диске: %d символов)",
            len(self._pins_memo),
        )

    # ---------- диск-кэш ----------

    def _load_persistent_cache(self) -> None:
        """Загружает _pins_memo/_bbox_memo из CACHE_FILE.

        Молча пропускает отсутствующий/битый/устаревший кэш —
        в этом случае работаем как раньше, с нуля.
        """
        if not CACHE_FILE.exists():
            return
        try:
            with CACHE_FILE.open("rb") as f:
                data = pickle.load(f)
        except (pickle.UnpicklingError, EOFError, OSError) as e:
            log.warning("Кэш KiCadSource битый (%s), удаляю", e)
            try:
                CACHE_FILE.unlink()
            except OSError:
                pass
            return

        if not isinstance(data, dict):
            log.warning("Кэш KiCadSource неожиданного типа, игнорирую")
            return

        if data.get("version") != CACHE_VERSION:
            log.debug(
                "Кэш KiCadSource версии %s, ожидаю %s — игнорирую",
                data.get("version"), CACHE_VERSION,
            )
            return

        pins = data.get("pins")
        bbox = data.get("bbox")
        if isinstance(pins, dict):
            self._pins_memo = pins
        if isinstance(bbox, dict):
            self._bbox_memo = bbox

    def _save_persistent_cache(self) -> None:
        """Сохраняет _pins_memo/_bbox_memo на диск атомарно.

        Пишем во временный файл и делаем replace — атомарная
        подмена на уровне ФС. Так при падении в момент записи
        старый кэш не портится.
        """
        if not self._dirty:
            return
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            tmp = CACHE_FILE.with_suffix(".pkl.tmp")
            with tmp.open("wb") as f:
                pickle.dump(
                    {
                        "version": CACHE_VERSION,
                        "pins":    self._pins_memo,
                        "bbox":    self._bbox_memo,
                    },
                    f,
                    protocol=5,
                )
            tmp.replace(CACHE_FILE)
            self._dirty = False
        except OSError as e:
            log.warning("Кэш KiCadSource не сохранён: %s", e)

    def flush(self) -> None:
        """Явно сохранить диск-кэш.

        Вызывается из Project.load() до возможного raise — чтобы
        результат разбора библиотек не потерялся, даже если в
        YAML есть ошибки.
        """
        self._save_persistent_cache()

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

        Результат мемоизируется в памяти процесса и на диске.
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
        self._dirty = True
        log.debug("Пины %s: %d шт.", lib_id, len(pins))
        return pins

    def get_symbol_bbox_mm(
        self, lib_id: str,
    ) -> Tuple[float, float, float, float]:
        """Габаритный прямоугольник символа в мм: (min_x, min_y, max_x, max_y).

        Использует готовое свойство SymbolDefinition.bounding_box —
        оно уже учитывает графические примитивы и пины.
        Результат мемоизируется в памяти процесса и на диске.
        """
        if lib_id in self._bbox_memo:
            return self._bbox_memo[lib_id]

        symbol = self._get_symbol(lib_id)
        bbox = symbol.bounding_box
        self._bbox_memo[lib_id] = bbox
        self._dirty = True
        log.debug("BBox %s: %s", lib_id, bbox)
        return bbox