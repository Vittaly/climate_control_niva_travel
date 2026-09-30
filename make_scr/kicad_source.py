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

Локальные библиотеки:
    Проект может генерировать собственные .kicad_sym (например,
    через JLC2KiCadLib) и складывать их в libs/symbol/. Такие
    библиотеки kicad-sch-api сам НЕ видит: он сканирует только
    стандартные пути KiCad и переменные окружения, а sym-lib-table
    проекта не читает. Поэтому LibraryManager отдаёт пути наружу,
    а KiCadSource регистрирует их через register_library().

    register_library() идемпотентен по абсолютному пути. Если файл
    библиотеки изменился (JLC2KiCadLib дописал символ), вызывающий
    должен дёрнуть invalidate_lib(path) — иначе kicad-sch-api
    отдаст старое содержимое из своего кэша.

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

    Отдельно: сгенерированные проектом библиотеки (MyMCU и т.п.)
    живут вне стандартных путей KiCad, поэтому их содержимое
    в _pins_memo тоже может устареть. Если вы перегенерировали
    .kicad_sym — либо bump CACHE_VERSION, либо вызовите
    clear_persistent_cache() перед прогоном.
"""
from __future__ import annotations

import pickle
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

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

    Локальные библиотеки:
        Передаются в конструктор (local_lib_paths) или добавляются
        позже через register_library(). Регистрация нужна ДО первого
        обращения к символам из этой библиотеки через get_pins().

    flush() вызывается явно в Project.load() перед возможным
    raise ProjectLoadError — чтобы результат разбора сохранился
    даже при ошибке в YAML.
    """

    def __init__(
        self,
        local_lib_paths: Optional[Iterable[Path]] = None,
    ) -> None:
        """Открывает кэш символов kicad_sch_api и подгружает диск-кэш.

        Args:
            local_lib_paths: необязательный список путей к .kicad_sym,
                которые нужно зарегистрировать в kicad-sch-api до
                первого get_pins(). Обычно сюда приходит результат
                LibraryManager.resolve_all() при полном прогреве.
        """
        self._cache = ksa.get_symbol_cache()
        self._pins_memo: Dict[str, List[dict]] = {}
        self._bbox_memo: Dict[str, Tuple[float, float, float, float]] = {}
        self._dirty = False

        # Зарегистрированные локальные библиотеки: abs path → True.
        # Регистрируем ДО первого get_pins — иначе символы из них
        # будут не видны kicad-sch-api.
        self._registered_libs: Set[str] = set()
        for p in (local_lib_paths or ()):
            self.register_library(Path(p))

        self._load_persistent_cache()
        log.debug(
            "KiCadSource инициализирован (кэш: %d символов, libs: %d)",
            len(self._pins_memo), len(self._registered_libs),
        )

    # ---------- регистрация локальных библиотек ----------

    def register_library(self, path: Path) -> None:
        """Добавляет .kicad_sym в кэш kicad-sch-api.

        Идемпотентно по абсолютному пути. Ошибки не пробрасываются:
        отсутствие файла или несовместимость API kicad-sch-api не
        должны валить прогон. В худшем случае символ не найдётся
        в get_pins() — Component.from_yaml упадёт с понятным
        ComponentLoadError.

        Если файл библиотеки изменился после регистрации, вызовите
        invalidate_lib(path), чтобы kicad-sch-api перечитал его.
        """
        p = Path(path).resolve()
        key = str(p)
        if key in self._registered_libs:
            return
        if not p.exists():
            log.warning("Локальная библиотека не найдена: %s", p)
            return

        # В разных версиях kicad-sch-api метод называется по-разному.
        # Основной путь — add_library_path(<file>); fallback —
        # discover_libraries([<dir>]).
        registered = False
        if hasattr(self._cache, "add_library_path"):
            try:
                self._cache.add_library_path(key)
                registered = True
            except Exception as e:
                log.warning(
                    "add_library_path(%s) не удался: %s", key, e,
                )

        if not registered and hasattr(self._cache, "discover_libraries"):
            try:
                self._cache.discover_libraries([str(p.parent)])
                registered = True
            except Exception as e:
                log.warning(
                    "discover_libraries(%s) не удался: %s",
                    p.parent, e,
                )

        if not registered:
            log.warning(
                "kicad-sch-api не умеет регистрировать %s: "
                "нет подходящего метода в SymbolLibraryCache", p,
            )
            return

        self._registered_libs.add(key)
        log.info("Локальная библиотека зарегистрирована: %s", p.name)

    def invalidate_lib(self, path: Path) -> None:
        """Сбрасывает кэш kicad-sch-api для одной библиотеки.

        Вызывать после того, как JLC2KiCadLib дописал символ в уже
        зарегистрированный файл — иначе get_symbol отдаст старое
        содержимое.

        Также удаляет из memo все lib_id, относящиеся к этой
        библиотеке, чтобы следующая get_pins перечитала пины
        из обновлённого файла.
        """
        p = Path(path).resolve()
        key = str(p)
        if key not in self._registered_libs:
            return

        lib_stem = p.stem  # "MyMCU" для MyMCU.kicad_sym

        # 1. Сбрасываем внутренний кэш kicad-sch-api.
        #    Порядок методов также версионно-зависим; пробуем
        #    несколько вариантов.
        try:
            if hasattr(self._cache, "clear_cache"):
                self._cache.clear_cache()
                if hasattr(self._cache, "add_library_path"):
                    self._cache.add_library_path(key)
            elif hasattr(self._cache, "reload"):
                self._cache.reload(key)
            elif hasattr(self._cache, "forget"):
                self._cache.forget(key)
                if hasattr(self._cache, "add_library_path"):
                    self._cache.add_library_path(key)
            else:
                log.debug(
                    "invalidate_lib: неизвестный API для сброса кэша; "
                    "пробую добавить путь повторно",
                )
                if hasattr(self._cache, "add_library_path"):
                    self._cache.add_library_path(key)
        except Exception as e:
            log.warning("invalidate_lib(%s): %s", p, e)

        # 2. Чистим наш memo по этой библиотеке.
        prefix = f"{lib_stem}:"
        stale = [k for k in self._pins_memo if k.startswith(prefix)]
        for k in stale:
            self._pins_memo.pop(k, None)
        stale_bbox = [k for k in self._bbox_memo if k.startswith(prefix)]
        for k in stale_bbox:
            self._bbox_memo.pop(k, None)
        if stale or stale_bbox:
            self._dirty = True

        log.info("Kicad-sch-api кэш сброшен для %s", p.name)

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