# make_scr/project.py
"""Корневая сущность: YAML -> компоненты/нетлист -> размещение -> трассы -> файлы.

Модель:
    - Sheet  — страница KiCad (.kicad_sch): components, netlist, grid_mm.
    - Placer — размещает на одной Sheet; читает sheet.netlist/grid_mm.
    - Router — трассирует одну Sheet; пишет в sheet.labels/t_junctions.
    - Writer — пишет .kicad_sch; единственный, кто знает про uuid,
               page-номера и instance-пути (см. writer.py).
    - Project — оркестратор: грузит YAML, гоняет Placer/Router, отдаёт
               граф Writer'у.

Идентификация листов (единая для всей цепочки):
    * Первоисточник — sheets/<stem>.yaml (stem = имя файла без .yaml).
    * Схема листа   — <stem>.kicad_sch (в корне проекта или в out_dir).
    * Корневая страница — тоже лист: stem совпадает с именем проекта
      KiCad и .kicad_sch проекта.
    * Связь листа со схемой объявлена РОВНО один раз — атрибутом
      value_sch у соответствующего X_* в components корневого YAML.
    * Список листов к прогону нигде не хранится: он выводится как
      {X_*, встречающиеся в nets} ∪ standalone_sheets (там — stem'ы).

YAML живёт только внутри загрузки. Sheet о YAML не знает.
Нетлист — поле Sheet, у каждой страницы свой.

Модель данных о пинах МК:
    Источник истины о том, какие пины U1 используются и как — секция
    nets. Отдельной секции mcu_pin_map нет. Узел U1 в nets содержит:
        pinfunction — имя вывода из символа KiCad ('PA13', 'VBAT', ...)
        function    — короткая машинно-читаемая роль (опционально)
        description — человекочитаемое описание логики (опционально)
    Component.pin_by_name() привязывает пин по pinfunction. Смена
    корпуса не требует правок в узлах, если имя вывода не изменилось.

Модель портов (лист ↔ родитель):
    * Источник истины о портах — флаг is_hierarchical_port: true
      на сети ВНУТРИ дочернего YAML. Имя порта = имя сети.
    * Направление — port_direction: INPUT | OUTPUT у той же сети;
      по умолчанию INPUT. Устаревший верхний блок ports: не читается.
    * На родителе порт — узел сети через pinfunction: <имя_порта>.
      Связь «порт ребёнка ↔ корневая сеть» выводится по имени.
    * Для writer'а: после привязки пина к сети сохраняется
      pin.net_name — имя КОРНЕВОЙ сети. Writer пишет его в
      write_sheet_pin вместо pin.name, иначе разные инстансы
      одного листа сольют свои сети (MOTOR_A ×4 → одна сеть).

Модель аннотации refdes:
    Refdes — РЕЗУЛЬТАТ разворачивания иерархии, а не входные данные
    YAML. Схема не хранит «как должны выглядеть refdes» — они
    вычисляются как чистая функция от графа.

    Алгоритм (Project._compute_refdes):
        1. Depth-first обход дерева: корень → каждый X_* рекурсивно.
        2. Глобальные счётчики по префиксу (U, R, C, D, Q, J, L, SW,
           FB, ...) общие на весь проект.
        3. Для multi-instance файл обходится N раз, по одному разу
           на каждый X_*. Каждый обход продвигает счётчики дальше.
        4. Refdes корня РЕЗЕРВИРУЮТСЯ в счётчиках (чтобы дети не
           пересеклись), но маппинг для корня не сохраняется —
           корень не инстанцируется, Writer пишет его символы
           напрямую с их YAML-designator'ами.

    Порядок обхода детерминирован: dict в Python 3.7+ сохраняет
    порядок вставки, значит автор YAML управляет нумерацией,
    переставляя строки в components.

    _compute_refdes НЕ пишет в self — возвращает результат.
    save() фиксирует его в self._refdes_maps; внешняя валидация
    использует локальную переменную и не трогает состояние Project.

Модель сохранения:
    Всё, что относится к формату .kicad_sch — uuid страниц, page-
    номера, instance-пути, рекурсия по дереву, — живёт в Writer'е
    (см. writer.write_project). Project только собирает граф:
        * root_sheet     — корень обхода,
        * sheets         — {sheet_path: Sheet} всех листов,
        * refdes_maps    — результат _compute_refdes,
        * project_name   — имя проекта KiCad.
    Standalone-листы (без X_* в основном проекте) обходятся тем же
    Writer'ом отдельным вызовом write_project: у каждого свой
    мини-корень, своя нумерация страниц, свой uuid. Writer кэширует
    уже записанные sheet_path, поэтому повторная запись исключена.

Политика ошибок загрузки:
    Компонент, который не удалось собрать, НЕ теряется молча.
    Component.from_yaml либо возвращает Component, либо бросает
    DesignatorError/ComponentLoadError. Оба исключения
    перехватываются в _load_components, кладутся в self._load_errors
    и логируются на уровне ERROR с полным контекстом
    (designator/type/symbol/value/reason). После обхода всех
    компонентов и листов Project.load() бросает ProjectLoadError —
    до place_and_route/save дело не доходит.

    Дополнительно проверяется связность иерархии:
      * X_* без value_sch                      — ошибка;
      * value_sch без соответствующего YAML     — ошибка;
      * коллизия имён выходных .kicad_sch       — ошибка;
      * X_* без ни одной привязанной цепи       — ошибка (orphan);
      * standalone без <stem>.yaml              — ошибка.

Библиотеки проекта:
    * LibraryManager — ленивая генерация .kicad_sym через JLC2KiCadLib
      для тех component_types, у которых задан lcsc_id, но нет
      symbol и/или footprint. Генерация запускается в момент, когда
      впервые встретился компонент соответствующего типа.
      После генерации путь к .kicad_sym регистрируется в KiCadSource
      (kicad-sch-api), чтобы get_pins() нашёл новый символ.

    * save() регистрирует библиотеки LibraryManager в sym-lib-table /
      fp-lib-table выходного каталога. Источник данных — сам
      LibraryManager (имена и пути к .kicad_sym / .pretty), а не
      YAML: настройка библиотек — задача инфраструктуры пайплайна,
      а не описания схемы. Пути пишутся через ${KIPRJMOD}/, чтобы
      проект оставался переносимым.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

import yaml

from component import Component, ComponentLoadError
from constants import (
    Axis,
    DEFAULT_GRID_MM,
    DEFAULT_NET_TYPE,
    KIPRJMOD_VAR,
    LIB_TABLE_FILES,
    LIB_TABLE_ROOT_TOKENS,
    LIB_TABLE_TYPE_KICAD,
    LIB_TABLE_VERSION,
    LibTableKind,
    PathSearch,
    Symbol   
)
from kicad_source import KiCadSource
from logging_setup import ctx, get_logger
from placer import Placer
from router import Router
from sheet import Sheet
from sheet_ref import SheetRefComponent
from writer import Writer
from port_component import PortComponent

from designators import DesignatorError, validate_component_designator

log = get_logger(__name__)


class ProjectLoadError(Exception):
    """Загрузка проекта прервана: YAML несовместим с KiCad.

    Собирает все обнаруженные ошибки, чтобы не гонять пользователя
    по одному компоненту за раз.
    """
    def __init__(self, errors: list[str]):
        self.errors = list(errors)
        super().__init__(
            "Загрузка проекта прервана:\n  " + "\n  ".join(self.errors)
        )


# =========================================================
# LibraryManager: ленивая генерация пользовательских библиотек
# =========================================================

class LibraryManager:
    """Генерирует .kicad_sym по lcsc_id и отдаёт пути в KiCadSource.

    Жизненный цикл:
        LibraryManager — вспомогательный объект Project. Создаётся
        один раз в load(), регистрирует все сгенерированные
        библиотеки в KiCadSource по мере появления новых типов.

    Раскладка файлов:
        <base_dir>/libs/symbol/MyMCU.kicad_sym           — символы;
        <base_dir>/libs/MyFootprints.pretty/             — посадочные
                                                            места;
        <base_dir>/libs/MyFootprints.pretty/packages3d/  — 3D-модели.

    base_dir — каталог корневого YAML. Генерируемые библиотеки лежат
    рядом с исходниками проекта (не в out_dir), потому что это
    часть исходников, а не артефакт генерации.

    Имена библиотек — константы. В YAML не читаются и не
    переопределяются: настройка инфраструктуры не смешивается
    с описанием схемы.
    """

    SYM_LIB_NAME = "MyMCU"
    FP_LIB_NAME = "MyFootprints"

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)

        libs_root = self.base_dir / "libs"
        self.sym_dir = libs_root / "symbol"

        # Явное, без трюков:
        self.fp_dir = libs_root / f"{self.FP_LIB_NAME}.pretty"
        self.sym_lib_name = self.SYM_LIB_NAME
        self.fp_lib_name = self.FP_LIB_NAME

        # Уже разобранные типы — защита от повторного вызова
        # ensure_type для одного и того же type_name.
        self._resolved: Set[str] = set()

    # ---------- публичное ----------

    def ensure_type(self, type_name: str, tdef: dict) -> Optional[Path]:
        """Гарантирует, что для типа есть symbol и footprint.

        Порядок действий:
            1. Если в tdef уже есть и symbol, и footprint — ничего
               не делаем.
            2. Пытаемся найти символ/футпринт по lcsc_id в уже
               существующих файлах библиотеки.
            3. Если что-то не найдено — запускаем JLC2KiCadLib
               и пробуем снова.
            4. Прописываем найденные symbol/footprint обратно в tdef.

        Returns:
            Path к .kicad_sym, если файл библиотеки был изменён
            (только что сгенерирован), иначе None.

        Raises:
            RuntimeError — JLC2KiCadLib завершилась с ошибкой.
        """
        if type_name in self._resolved:
            return None
        self._resolved.add(type_name)

        lcsc_id = tdef.get("lcsc_id")
        if not lcsc_id:
            return None

        has_symbol = bool(tdef.get("symbol"))
        has_footprint = bool(tdef.get("footprint"))
        if has_symbol and has_footprint:
            return None

        sym_file = self.sym_dir / f"{self.sym_lib_name}.kicad_sym"

        # --- 1. Пытаемся найти в существующих файлах ---
        if not has_symbol and sym_file.exists():
            name = self._find_symbol_name(sym_file, lcsc_id)
            if name:
                tdef["symbol"] = f"{self.sym_lib_name}:{name}"
                has_symbol = True

        if not has_footprint and self.fp_dir.exists():
            name = self._find_footprint_name(self.fp_dir, lcsc_id)
            if name:
                tdef["footprint"] = f"{self.fp_lib_name}:{name}"
                has_footprint = True

        if has_symbol and has_footprint:
            return None

        # --- 2. Генерация ---
        self.sym_dir.mkdir(parents=True, exist_ok=True)
        self.fp_dir.mkdir(parents=True, exist_ok=True)

        cmd = [
            "JLC2KiCadLib",
            str(lcsc_id),
            "-dir", str(self.base_dir / "libs"),
            "-symbol_lib", self.sym_lib_name,
            "-footprint_lib", self.fp_lib_name,
            "-models", "STEP",
        ]
        log.info(
            "LibraryManager: генерация %s (lcsc_id=%s)",
            type_name, lcsc_id,
            extra={
                "stage":     "load",
                "event":     "lcsc_generate",
                "type_name": type_name,
                "lcsc_id":   str(lcsc_id),
            },
        )
        try:
            subprocess.run(
                cmd, check=True, capture_output=True, text=True, timeout=120,
            )
        except FileNotFoundError as e:
            raise RuntimeError(
                f"JLC2KiCadLib не установлен или не найден в PATH: {e}"
            ) from e
        except subprocess.TimeoutExpired as e:
            raise RuntimeError(
                f"JLC2KiCadLib таймаут при обработке {lcsc_id}"
            ) from e
        except subprocess.CalledProcessError as e:
            raise RuntimeError(
                f"JLC2KiCadLib вернул код {e.returncode} для {lcsc_id}: "
                f"{(e.stderr or '').strip()[:300]}"
            ) from e

        # --- 3. Пробуем найти после генерации ---
        if not has_symbol:
            name = self._find_symbol_name(sym_file, lcsc_id)
            if name:
                tdef["symbol"] = f"{self.sym_lib_name}:{name}"
        if not has_footprint:
            name = self._find_footprint_name(self.fp_dir, lcsc_id)
            if name:
                tdef["footprint"] = f"{self.fp_lib_name}:{name}"

        return sym_file if sym_file.exists() else None

    # ---------- данные для регистрации в sym/fp-lib-table ----------

    def library_entries(self) -> list[tuple[LibTableKind, str, Path]]:
        """[(kind, nickname, abs_path), ...] для sym-lib-table / fp-lib-table."""
        return [
            (LibTableKind.SYMBOL, self.sym_lib_name,
             self.sym_dir / f"{self.sym_lib_name}.kicad_sym"),
            (LibTableKind.FOOTPRINT, self.fp_lib_name,
             self.fp_dir),
        ]

    # ---------- поиск в сгенерированных файлах ----------

    def _find_symbol_name(self, sym_file: Path, lcsc_id: str) -> Optional[str]:
        """Ищет символ в .kicad_sym, в теле которого упомянут lcsc_id."""
        if not sym_file.exists():
            return None
        try:
            text = sym_file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return None

        needle = str(lcsc_id)
        for m in re.finditer(r'\(symbol\s+"([^"]+)"', text):
            name = m.group(1)
            tail = text[m.end():m.end() + 3000]
            if needle in tail:
                return name
        return None

    def _find_footprint_name(
        self, fp_dir: Path, lcsc_id: str,
    ) -> Optional[str]:
        """Ищет .kicad_mod, в тексте которого встречается lcsc_id."""
        if not fp_dir.exists():
            return None
        needle = str(lcsc_id)
        for f in fp_dir.glob("*.kicad_mod"):
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if needle in text:
                return f.stem
        return None


# =========================================================
# Project
# =========================================================

class Project:
    """Точка входа: загрузка, размещение, роутинг, сохранение."""

    def __init__(self, root_yaml: str | Path):
        """
        Args:
            root_yaml: путь к корневому YAML (sheets/<ROOT_STEM>.yaml).
        """
        self.root_path = Path(root_yaml)
        self.base_dir = self.root_path.parent

        self.source = KiCadSource()

        self.root_sheet: Optional[Sheet] = None
        self.sheets: Dict[str, Sheet] = {}       # key = имя .kicad_sch
        self.root_data: dict = {}
        # yaml_key (abs path) -> sheet_path: не грузим один YAML дважды
        self._loaded_yaml: Dict[str, str] = {}
        self._load_errors: list[str] = []
        # LibraryManager создаётся в load(), после _read_root().
        self._libraries: Optional[LibraryManager] = None

        # {X_*: {base_ref: project_ref}} — результат _compute_refdes,
        # фиксируется в save(). До save() пуст.
        self._refdes_maps: Dict[str, Dict[str, str]] = {}

        log.info(
            "Project создан: %s", self.root_path,
            extra={
                "stage": "init",
                "event": "project_created",
                "path":  str(self.root_path),
            },
        )

    # =========================================================
    # Загрузка
    # =========================================================

    def load(self) -> "Project":
        """Полный цикл загрузки: корневой YAML + рекурсивно все листы."""
        log.info(
            "Загрузка %s", self.root_path,
            extra={
                "stage": "load",
                "event": "load_start",
                "path":  str(self.root_path),
            },
        )

        self._load_errors.clear()
        self._read_root()

        # LibraryManager должен существовать до _load_components —
        # оттуда вызывается ensure_type() для lcsc_id-типов.
        self._libraries = LibraryManager(self.base_dir)

        grid_mm = float(self.root_data.get("grid_mm", DEFAULT_GRID_MM))
        self.root_sheet = Sheet(sheet_path="", grid_mm=grid_mm)
        self.sheets[""] = self.root_sheet

        self._load_components(self.root_sheet, self.root_data,
                              self.root_path)
        self._load_nets(self.root_sheet, self.root_data)
        self._log_components_with_nets(self.root_sheet)

        # Иерархия: листы, подключённые через X_* на корне.
        self._discover_sheets(self.root_sheet, self.root_data,
                              self.root_path)

        # Листы вне иерархии (без X_*): внешние силовые модули,
        # тестовые стенды — тоже должны стать .kicad_sch.
        self._load_standalone_sheets(
            self.root_data.get("standalone_sheets") or []
        )

        # Связность иерархии: каждый SheetRef должен быть подключён
        # хотя бы к одной цепи.
        self._check_sheet_refs_connected(self.root_sheet)

        # Результат разбора библиотек сохраняем на диск даже при
        # ошибках — чтобы следующий прогон не парсил те же символы.
        self.source.flush()

        # Никакого place_and_route, пока есть ошибки загрузки.
        if self._load_errors:
            raise ProjectLoadError(self._load_errors)

        total_components = sum(len(s.components) for s in self.sheets.values())
        total_pins = sum(
            len(c.pins)
            for s in self.sheets.values()
            for c in s.components.values()
        )
        total_nets = sum(len(s.netlist.nets) for s in self.sheets.values())
        log.info(
            "Загрузка завершена: листов %d, компонентов %d, сетей %d",
            len(self.sheets), total_components, total_nets,
            extra={
                "stage":   "load",
                "event":   "load_done",
                "project": self.root_data.get("project"),
                "counts": {
                    "sheets":     len(self.sheets),
                    "components": total_components,
                    "pins":       total_pins,
                    "nets":       total_nets,
                },
            },
        )
        return self

    def _read_root(self) -> None:
        """Читает корневой YAML и сохраняет секцию root_page."""
        with open(self.root_path, encoding="utf-8") as f:
            doc = yaml.safe_load(f) or {}

        if isinstance(doc, dict) and "root_page" in doc:
            self.root_data = doc.get("root_page") or {}
        else:
            self.root_data = doc

        log.debug(
            "root_page: project=%s, version=%s",
            self.root_data.get("project"),
            self.root_data.get("version"),
            extra={
                "stage":   "load",
                "event":   "root_page_read",
                "project": self.root_data.get("project"),
                "version": self.root_data.get("version"),
                "path":    str(self.root_path),
            },
        )

    # ---------- компоненты и сети ----------

    def _load_components(self, sheet: Sheet, data: dict,
                         yaml_path: Path) -> None:
        """Строит Component для всех записей data['components']."""
        types = data.get("component_types", {})
        for designator, cdef in data.get("components", {}).items():
            if cdef.get("symbol") == Symbol.HIERARCHICAL_SHEET:
                self._add_sheet_ref(sheet, designator, cdef, yaml_path)
                continue

            # --- Ленивая генерация библиотеки для этого типа ---
            tname = cdef.get("type")
            if (tname and tname in types
                    and self._libraries is not None):
                try:
                    lib_path = self._libraries.ensure_type(
                        tname, types[tname],
                    )
                except RuntimeError as e:
                    self._load_errors.append(
                        f"{yaml_path}: components.{designator}: {e}"
                    )
                    log.error(
                        "%s lcsc_generate_failed des=%s type=%s reason=%s",
                        ctx(page=sheet.page), designator, tname, e,
                        extra={
                            "stage":     "load",
                            "event":     "lcsc_generate_failed",
                            "component": designator,
                            "type_name": tname,
                            "reason":    str(e),
                        },
                    )
                    continue

                if lib_path is not None:
                    self.source.invalidate_lib(lib_path)
                    self.source.register_library(lib_path)

            try:
                comp = Component.from_yaml(
                    designator=designator,
                    cdef=cdef,
                    types=types,
                    source=self.source,
                    grid_mm=sheet.grid_mm,
                    page=sheet.page,
                )
            except DesignatorError as e:
                self._load_errors.append(
                    f"{yaml_path}: components.{designator}: {e}"
                )
                log.error(
                    "%s component_load_failed des=%s reason=%s",
                    ctx(page=sheet.page), designator, e,
                    extra={
                        "stage":     "load",
                        "event":     "component_load_failed",
                        "component": designator,
                        "reason":    "designator_invalid",
                    },
                )
                continue
            except ComponentLoadError as e:
                self._load_errors.append(f"{yaml_path}: {e}")
                log.error(
                    "%s component_load_failed des=%s type=%s symbol=%s "
                    "value=%s reason=%s hint=%s",
                    ctx(page=sheet.page), e.designator,
                    e.type_name, e.symbol, e.value, e.reason, e.hint,
                    extra={
                        "stage":     "load",
                        "event":     "component_load_failed",
                        "component": e.designator,
                        "type_name": e.type_name,
                        "symbol":    e.symbol,
                        "value":     e.value,
                        "reason":    e.reason,
                        "hint":      e.hint,
                    },
                )
                continue

            if comp is None:
                msg = (
                    f"{yaml_path}: components.{designator}: "
                    f"Component.from_yaml вернул None вместо Component "
                    f"(type={cdef.get('type')!r}, "
                    f"value={cdef.get('value')!r})"
                )
                self._load_errors.append(msg)
                log.error(
                    "%s component_load_returned_none des=%s type=%s value=%s",
                    ctx(page=sheet.page), designator,
                    cdef.get("type"), cdef.get("value"),
                    extra={
                        "stage":     "load",
                        "event":     "component_load_returned_none",
                        "component": designator,
                        "type_name": cdef.get("type"),
                        "value":     cdef.get("value"),
                    },
                )
                continue

            sheet.add_component(comp)

        # --- Порты страницы (сети с is_hierarchical_port: true) ---
        self._load_ports(sheet, data, yaml_path)

    def _add_sheet_ref(self, sheet: Sheet, designator: str,
                       cdef: dict, yaml_path: Path) -> None:
        """Создаёт SheetRefComponent для X_* на текущем листе."""
        value_sch = cdef.get("value_sch")
        if not value_sch:
            self._load_errors.append(
                f"{yaml_path}: components.{designator}: "
                f"нет value_sch — обязателен для Core:Hierarchical_Sheet"
            )
            log.error(
                "%s sheetref_no_value_sch des=%s",
                ctx(page=sheet.page), designator,
                extra={
                    "stage":     "load",
                    "event":     "sheetref_no_value_sch",
                    "component": designator,
                },
            )
            return

        # <stem>.kicad_sch → <stem>.yaml, каталог сохраняется
        sheet_file = str(Path(str(value_sch)).with_suffix(".yaml"))

        try:
            ref = SheetRefComponent.create(
                designator=designator,
                sheet_file=sheet_file,
                parent_yaml_path=yaml_path,
            )
        except DesignatorError as e:
            self._load_errors.append(
                f"{yaml_path}: components.{designator}: {e}"
            )
            log.error(
                "%s sheetref_load_failed des=%s reason=%s",
                ctx(page=sheet.page), designator, e,
                extra={
                    "stage":     "load",
                    "event":     "sheetref_load_failed",
                    "component": designator,
                    "reason":    "designator_invalid",
                },
            )
            return

        if ref is None:
            self._load_errors.append(
                f"{yaml_path}: components.{designator}: "
                f"SheetRefComponent.create вернул None "
                f"(value_sch={value_sch!r})"
            )
            log.error(
                "%s sheetref_returned_none des=%s value_sch=%s",
                ctx(page=sheet.page), designator, value_sch,
                extra={
                    "stage":     "load",
                    "event":     "sheetref_returned_none",
                    "component": designator,
                    "value":     value_sch,
                },
            )
            return

        sheet.add_component(ref)
        log.debug(
            "%s sheetref_added des=%s value_sch=%s pins=%d",
            ctx(page=sheet.page), designator, value_sch, len(ref.pins),
            extra={
                "stage":     "load",
                "event":     "sheetref_added",
                "component": designator,
                "value":     value_sch,
                "counts":    {"pins": len(ref.pins)},
            },
        )

    def _load_ports(self, sheet: Sheet, data: dict,
                    yaml_path: Path | None = None) -> None:
        """Создаёт PortComponent для каждой сети-порта листа."""
        from port_component import PortComponent

        nets = data.get("nets", {}) or {}

        for net_name, ndef in nets.items():
            if not isinstance(ndef, dict):
                continue
            if not ndef.get("is_hierarchical_port"):
                continue

            
            direction = str(ndef.get("port_direction", "INPUT")).upper()

            designator = f"PORT_{net_name}"
            where = (f"{yaml_path}: nets.{net_name}"
                    if yaml_path else f"nets.{net_name}")

            try:
                port = PortComponent.create(
                    designator=designator,
                    net_name=net_name,
                    direction=direction,
                )
            except DesignatorError as e:
                self._load_errors.append(f"{where}: {e}")
                log.error(
                    "%s port_load_failed des=%s net=%s reason=%s",
                    ctx(page=sheet.page), designator, net_name, e,
                    extra={
                        "stage":     "load",
                        "event":     "port_load_failed",
                        "component": designator,
                        "net":       net_name,
                        "reason":    "designator_invalid",
                    },
                )
                continue

            if port is None:
                self._load_errors.append(
                    f"{where}: порт не собран (net_label={net_name!r})"
                )
                log.error(
                    "%s port_load_returned_none des=%s net=%s",
                    ctx(page=sheet.page), designator, net_name,
                    extra={
                        "stage":     "load",
                        "event":     "port_load_returned_none",
                        "component": designator,
                        "net":       net_name,
                    },
                )
                continue

            sheet.add_component(port)

            log.debug(
                "%s port_added des=%s side=%s shape=%s direction=%s",
                ctx(page=sheet.page), port.designator, port.side, port.shape,
                direction,
                extra={
                    "stage":     "load",
                    "event":     "port_added",
                    "component": port.designator,
                    "net":       net_name,
                    "side":      port.side,
                    "shape":     port.shape,
                    "direction": direction,
                },
            )

    def _load_nets(self, sheet: Sheet, data: dict) -> None:
        """Регистрирует сети листа и привязывает их FQN-пины."""
        for net_name, ndef in data.get("nets", {}).items():
            attrs = ndef.get("attributes", {})
            sheet.netlist.add_net(
                net_name,
                attrs.get("type", DEFAULT_NET_TYPE),
                list(attrs.keys()),
            )
        for net_name, ndef in data.get("nets", {}).items():
            for node in ndef.get("nodes", []):
                self._bind_node(sheet, net_name, node)

        self._bind_ports_to_nets(sheet, data)
        self._bind_sheet_refs_to_nets(sheet, data)
        self._check_all_pins_connected(sheet)

    def _check_all_pins_connected(self, sheet: Sheet) -> None:
        """Сводка пинов без цепи — WARNING, не ошибка."""
        unbound = []
        for designator, comp in sheet.components.items():
            for pin in comp.pins:
                if pin.net_ref is None:
                    unbound.append((designator, pin.identifier, pin.name))

        if not unbound:
            return

        log.warning(
            "%s pins_unbound count=%d",
            ctx(page=sheet.page), len(unbound),
            extra={
                "stage":   "load",
                "event":   "pins_unbound",
                "counts":  {"pins": len(unbound)},
                "pins": [
                    {"component": d, "pin": n, "pin_name": nm}
                    for d, n, nm in unbound
                ],
            },
        )

        for d, n, nm in unbound:
            log.warning(
                "%s pin_unbound des=%s pin=%s pin_name=%s",
                ctx(page=sheet.page), d, n, nm,
                extra={
                    "stage":     "load",
                    "event":     "pin_unbound",
                    "component": d,
                    "pin":       n,
                    "pin_name":  nm,
                },
            )

    def _bind_ports_to_nets(self, sheet: Sheet, data: dict) -> None:
        """Привязывает FQN пина каждого порта к его сети."""
        from port_component import PortComponent

        for comp in sheet.components.values():
            if not isinstance(comp, PortComponent):
                continue
            net = sheet.netlist.nets.get(comp.net_name)
            if net is None:
                log.warning(
                    "%s net_missing port=%s net=%s",
                    ctx(page=sheet.page), comp.designator, comp.net_name,
                    extra={
                        "stage":     "load",
                        "event":     "net_missing",
                        "component": comp.designator,
                        "net":       comp.net_name,
                    },
                )
                continue
            pin = comp.pins[0]
            fqn = pin.fqn
            sheet.netlist.assign_pin_to_net(fqn, comp.net_name, pin=pin)
            pin.net_name = comp.net_name

            log.debug(
                "%s pin_bound port=%s pin=%s net=%s fqn=%s",
                ctx(page=sheet.page), comp.designator, pin.identifier,
                comp.net_name, fqn,
                extra={
                    "stage":     "load",
                    "event":     "pin_bound",
                    "component": comp.designator,
                    "pin":       pin.identifier,
                    "fqn":       fqn,
                    "net":       comp.net_name,
                    "kind":      "port",
                },
            )

    def _bind_sheet_refs_to_nets(self, sheet: Sheet, data: dict) -> None:
        """Привязывает FQN пинов SheetRef-ов к их сетям.

        Заодно проставляет shape для каждого порта родителя: маппинг
        direction → shape живёт в PortComponent.shape_for_direction,
        а не дублируется здесь. Writer читает готовое port["shape"].
        """
        from port_component import PortComponent

        for comp in sheet.components.values():
            if not getattr(comp, "is_sheet_ref", False):
                continue

            # ── Проставить shape портам родителя ────────────────────
            # Единственное место, где shape для sheet-pin вычисляется.
            # Тот же classmethod, что PortComponent.create() использует
            # для ребёнка — оба конца иерархии получают одно значение.
            for port in getattr(comp, "ports", []):
                port["shape"] = PortComponent.shape_for_direction(
                    port["direction"]
                )
            # ────────────────────────────────────────────────────────

            for pin in comp.pins:
                net_name = pin.identifier
                net = sheet.netlist.nets.get(net_name)
                if net is None:
                    log.debug(
                        "%s pin_unbound sheetref=%s pin=%s net=%s",
                        ctx(page=sheet.page), comp.designator,
                        pin.identifier, net_name,
                        extra={
                            "stage":     "load",
                            "event":     "pin_unbound",
                            "component": comp.designator,
                            "pin":       pin.identifier,
                            "net":       net_name,
                            "kind":      "sheet_ref",
                            "reason":    "net_not_found",
                        },
                    )
                    continue

                fqn = pin.fqn
                sheet.netlist.assign_pin_to_net(fqn, net_name, pin=pin)
                pin.net_name = net_name

                log.debug(
                    "%s pin_bound sheetref=%s pin=%s net=%s fqn=%s",
                    ctx(page=sheet.page), comp.designator, pin.identifier,
                    net_name, fqn,
                    extra={
                        "stage":     "load",
                        "event":     "pin_bound",
                        "component": comp.designator,
                        "pin":       pin.identifier,
                        "fqn":       fqn,
                        "net":       net_name,
                        "kind":      "sheet_ref",
                    },
                )

    def _bind_node(self, sheet: Sheet, net_name: str, node: dict) -> None:
        """Привязывает пин из YAML-узла к сети через FQN страницы."""
        designator = node.get("component")
        if not designator:
            log.warning(
                "%s node_skipped net=%s reason=no_component_key node=%r",
                ctx(page=sheet.page), net_name, node,
                extra={
                    "stage":  "load",
                    "event":  "node_skipped",
                    "net":    net_name,
                    "reason": "no_component_key",
                },
            )
            return

        pin_no = node.get("pin")
        pin_fn = node.get("pinfunction")

        if pin_no is None and pin_fn is None:
            self._load_errors.append(
                f"{sheet.page}: net={net_name}: {designator} — "
                f"узел без pin/pinfunction"
            )
            log.error(
                "%s node_no_pin des=%s net=%s",
                ctx(page=sheet.page), designator, net_name,
                extra={
                    "stage":     "load",
                    "event":     "node_no_pin",
                    "component": designator,
                    "net":       net_name,
                    "reason":    "no_pin_key",
                },
            )
            return

        if pin_no is not None and pin_fn is not None:
            log.warning(
                "%s node_ambiguous des=%s net=%s pin=%s pinfunction=%s — "
                "используется pin, уберите лишний ключ",
                ctx(page=sheet.page), designator, net_name, pin_no, pin_fn,
                extra={
                    "stage":       "load",
                    "event":       "node_ambiguous",
                    "component":   designator,
                    "net":         net_name,
                    "pin":         str(pin_no),
                    "pinfunction": str(pin_fn),
                    "reason":      "both_keys",
                },
            )

        comp = sheet.get_component(designator)
        if comp is None:
            log.warning(
                "%s node_skipped des=%s net=%s reason=no_component",
                ctx(page=sheet.page), designator, net_name,
                extra={
                    "stage":     "load",
                    "event":     "node_skipped",
                    "component": designator,
                    "net":       net_name,
                    "reason":    "component_not_on_sheet",
                },
            )
            return

        # Приоритет: pin, иначе pinfunction
        if pin_no is not None:
            pin = comp.pin_by_number(str(pin_no))
            key, key_val = "pin", str(pin_no)
        else:
            pin = comp.pin_by_name(str(pin_fn))
            key, key_val = "pinfunction", str(pin_fn)

        if pin is None:
            log.warning(
                "%s node_skipped des=%s %s=%s net=%s reason=no_pin",
                ctx(page=sheet.page), designator, key, key_val, net_name,
                extra={
                    "stage":     "load",
                    "event":     "node_skipped",
                    "component": designator,
                    "net":       net_name,
                    "reason":    "pin_not_found",
                    key:         key_val,
                },
            )
            return

        fqn = pin.fqn
        try:
            sheet.netlist.assign_pin_to_net(fqn, net_name, pin=pin)
        except ValueError:
            log.warning(
                "%s net_missing net=%s fqn=%s",
                ctx(page=sheet.page), net_name, fqn,
                extra={
                    "stage":     "load",
                    "event":     "net_missing",
                    "component": designator,
                    "net":       net_name,
                    "fqn":       fqn,
                },
            )
        else:
            pin.net_name = net_name
            log.debug(
                "%s pin_bound des=%s %s=%s net=%s fqn=%s",
                ctx(page=sheet.page), designator, key, key_val, net_name, fqn,
                extra={
                    "stage":     "load",
                    "event":     "pin_bound",
                    "component": designator,
                    key:         key_val,
                    "fqn":       fqn,
                    "net":       net_name,
                    "kind":      "node",
                },
            )

    # ---------- сводка пинов с сетями ----------

    def _log_components_with_nets(self, sheet: Sheet) -> None:
        """Сводка: один компонент — одна строка."""
        for designator, comp in sheet.components.items():

            def _fmt_pin(pin) -> str:
                net = pin.net_ref or "-"
                parts = [f"{designator}.{pin.identifier}"]
                if pin.name:
                    parts.append(f"[{pin.name}]")
                parts.append(
                    f"off=({pin.offset_mm[Axis.X]:.2f},"
                    f"{pin.offset_mm[Axis.Y]:.2f})"
                )
                parts.append(f"net={net}")
                return " ".join(parts)

            pins_str = " | ".join(_fmt_pin(p) for p in comp.pins)
            line = (
                f"{designator} ({comp.name}) "
                f"{comp.bbox_cols}x{comp.bbox_rows} (cols x rows), "
                f"пинов {len(comp.pins)}"
            )
            if pins_str:
                line = f"{line} | {pins_str}"

            log.info(
                "%s component_summary %s",
                ctx(page=sheet.page), line,
                extra={
                    "stage":        "load",
                    "event":        "component_summary",
                    "component":    designator,
                    "comp_name":    comp.name,
                    "size": {
                        "cols": comp.bbox_cols,
                        "rows": comp.bbox_rows,
                    },
                    "counts":       {"pins": len(comp.pins)},
                    "is_sheet_ref": bool(getattr(comp, "is_sheet_ref", False)),
                    "pins": [
                        {
                            "identifier": p.identifier,
                            "name":       p.name or None,
                            "offset_mm": {
                                "x": p.offset_mm[Axis.X],
                                "y": p.offset_mm[Axis.Y],
                            },
                            "net":        p.net_ref or None,
                        }
                        for p in comp.pins
                    ],
                },
            )

    # ---------- иерархические страницы ----------

    def _discover_sheets(self, parent: Sheet, data: dict,
                         parent_yaml_path: Path) -> None:
        """Находит ссылки Core:Hierarchical_Sheet и грузит их содержимое."""
        for designator, cdef in data.get("components", {}).items():
            if cdef.get("symbol") != Symbol.HIERARCHICAL_SHEET:
                continue

            value_sch = cdef.get("value_sch")
            if not value_sch:
                continue

            yaml_rel = str(Path(str(value_sch)).with_suffix(".yaml"))
            yaml_path = (parent_yaml_path.parent / yaml_rel).resolve()
            yaml_key = str(yaml_path)

            if yaml_key in self._loaded_yaml:
                log.debug(
                    "%s sheet_reused des=%s value_sch=%s -> %s",
                    ctx(page=parent.page), designator, value_sch,
                    self._loaded_yaml[yaml_key],
                    extra={
                        "stage":     "load",
                        "event":     "sheet_reused",
                        "component": designator,
                        "child":     self._loaded_yaml[yaml_key],
                    },
                )
                continue

            if not yaml_path.exists():
                self._load_errors.append(
                    f"{parent_yaml_path}: components.{designator}: "
                    f"value_sch={value_sch!r} → нет {yaml_rel}"
                )
                log.error(
                    "%s sheet_missing des=%s value_sch=%s path=%s",
                    ctx(page=parent.page), designator, value_sch,
                    str(yaml_path),
                    extra={
                        "stage":     "load",
                        "event":     "sheet_missing",
                        "component": designator,
                        "path":      str(yaml_path),
                    },
                )
                continue

            with open(yaml_path, encoding="utf-8") as f:
                sub_data = yaml.safe_load(f) or {}

            sub_out = f"{yaml_path.stem}.kicad_sch"

            if sub_out in self.sheets:
                self._load_errors.append(
                    f"{parent_yaml_path}: {yaml_rel}: выходной файл "
                    f"{sub_out!r} уже используется листом "
                    f"{self.sheets[sub_out].sheet_path or '<root>'}"
                )
                log.error(
                    "%s sheet_collision des=%s child=%s",
                    ctx(page=parent.page), designator, sub_out,
                    extra={
                        "stage":     "load",
                        "event":     "sheet_collision",
                        "component": designator,
                        "child":     sub_out,
                    },
                )
                continue

            sub_grid = float(sub_data.get("grid_mm", DEFAULT_GRID_MM))
            sub_sheet = Sheet(sheet_path=sub_out, grid_mm=sub_grid)
            self.sheets[sub_out] = sub_sheet
            self._loaded_yaml[yaml_key] = sub_out

            self._load_components(sub_sheet, sub_data, yaml_path)
            self._load_nets(sub_sheet, sub_data)
            self._log_components_with_nets(sub_sheet)
            self._discover_sheets(sub_sheet, sub_data, yaml_path)

            log.debug(
                "%s sheet_loaded des=%s value_sch=%s components=%d",
                ctx(page=sub_sheet.page), designator, value_sch,
                len(sub_sheet.components),
                extra={
                    "stage":     "load",
                    "event":     "sheet_loaded",
                    "component": designator,
                    "path":      str(yaml_path),
                    "counts": {
                        "components": len(sub_sheet.components),
                        "pins": sum(len(c.pins)
                                    for c in sub_sheet.components.values()),
                        "nets": len(sub_sheet.netlist.nets),
                    },
                },
            )

    def _load_standalone_sheets(self, items: Iterable) -> None:
        """Грузит YAML-описания схем, не входящих в иерархию проекта."""
        for item in items:
            if isinstance(item, dict):
                stem = item.get("stem") or item.get("id")
            else:
                stem = Path(str(item)).stem
            stem = (stem or "").strip()
            if not stem:
                self._load_errors.append(
                    f"standalone_sheets: пустой элемент {item!r}"
                )
                continue

            yaml_path = (self.root_path.parent / f"{stem}.yaml").resolve()
            yaml_key = str(yaml_path)

            if yaml_key in self._loaded_yaml:
                log.debug(
                    "standalone reused: %s -> %s",
                    stem, self._loaded_yaml[yaml_key],
                    extra={
                        "stage": "load",
                        "event": "standalone_reused",
                        "path":  str(yaml_path),
                    },
                )
                continue

            if not yaml_path.exists():
                self._load_errors.append(
                    f"standalone_sheets: {stem}: файл не найден "
                    f"({yaml_path})"
                )
                continue

            with open(yaml_path, encoding="utf-8") as f:
                sub_data = yaml.safe_load(f) or {}

            sub_out = f"{yaml_path.stem}.kicad_sch"

            if sub_out in self.sheets:
                self._load_errors.append(
                    f"standalone_sheets: {stem}: выходной файл "
                    f"{sub_out!r} уже используется листом "
                    f"{self.sheets[sub_out].sheet_path or '<root>'}"
                )
                continue

            sub_grid = float(sub_data.get("grid_mm", DEFAULT_GRID_MM))
            sub_sheet = Sheet(sheet_path=sub_out, grid_mm=sub_grid)
            self.sheets[sub_out] = sub_sheet
            self._loaded_yaml[yaml_key] = sub_out

            self._load_components(sub_sheet, sub_data, yaml_path)
            self._load_nets(sub_sheet, sub_data)
            self._log_components_with_nets(sub_sheet)
            self._discover_sheets(sub_sheet, sub_data, yaml_path)

            log.info(
                "%s standalone_loaded stem=%s components=%d nets=%d",
                ctx(page=sub_sheet.page), stem,
                len(sub_sheet.components), len(sub_sheet.netlist.nets),
                extra={
                    "stage": "load",
                    "event": "standalone_loaded",
                    "path":  str(yaml_path),
                    "counts": {
                        "components": len(sub_sheet.components),
                        "nets":       len(sub_sheet.netlist.nets),
                    },
                },
            )

    # ---------- проверки связности ----------

    def _check_sheet_refs_connected(self, sheet: Sheet) -> None:
        """SheetRef без единой привязанной цепи — вероятно, забыт в nets."""
        for comp in sheet.components.values():
            if not getattr(comp, "is_sheet_ref", False):
                continue
            if not comp.pins:
                continue
            if any(p.net_ref for p in comp.pins):
                continue
            self._load_errors.append(
                f"{sheet.page}: {comp.designator}: "
                f"ни один порт не привязан к цепи — "
                f"вероятно, X_* забыт в nets"
            )
            log.error(
                "%s sheet_ref_orphan des=%s",
                ctx(page=sheet.page), comp.designator,
                extra={
                    "stage":     "load",
                    "event":     "sheet_ref_orphan",
                    "component": comp.designator,
                },
            )

    # =========================================================
    # Аннотация refdes (по аналогии с KiCad-аннотатором)
    # =========================================================

    def _compute_refdes(self) -> Dict[str, Dict[str, str]]:
        counters: Dict[str, int] = {}
        taken: Set[str] = set()
        result: Dict[str, Dict[str, str]] = {}

        def next_ref(prefix: str) -> str:
            n = counters.get(prefix, 0) + 1
            while f"{prefix}{n}" in taken:
                n += 1
            counters[prefix] = n
            taken.add(f"{prefix}{n}")
            return f"{prefix}{n}"

        def try_reserve(ref: str) -> bool:
            """Зарезервировать оригинальный refdes, если он свободен."""
            if ref in taken:
                return False
            prefix = _refdes_prefix(ref)
            tail = ref[len(prefix):]
            if tail.isdigit():
                counters[prefix] = max(counters.get(prefix, 0), int(tail))
            taken.add(ref)
            return True

        def is_real(comp) -> bool:
            return (not getattr(comp, "is_sheet_ref", False)
                    and not getattr(comp, "is_port", False))

        def annotate(sheet: "Sheet", instance_des: str,
                    first_instance: bool) -> None:
            rm = result.setdefault(instance_des, {})
            for _, comp in sheet.components.items():
                if not is_real(comp):
                    continue
                base = comp.designator
                if first_instance and try_reserve(base):
                    rm[base] = base
                else:
                    rm[base] = next_ref(_refdes_prefix(base))

        def visit(sheet: "Sheet", instance_des: str,
                first_instance: bool, seen: Set[str]) -> None:
            annotate(sheet, instance_des, first_instance)
            for _, comp in sheet.components.items():
                if not getattr(comp, "is_sheet_ref", False):
                    continue
                child_file = Path(comp.sheet_file).with_suffix(
                    ".kicad_sch").name
                child_sheet = self.sheets.get(child_file)
                if child_sheet is None:
                    continue
                cf_first = child_file not in seen
                seen.add(child_file)
                visit(child_sheet, comp.designator, cf_first, seen)

        # 1. Корень — резервируем как есть.
        for _, comp in self.root_sheet.components.items():
            if is_real(comp):
                try_reserve(comp.designator)

        # 2. X_* в порядке появления в корневом YAML.
        seen: Set[str] = set()
        for _, comp in self.root_sheet.components.items():
            if not getattr(comp, "is_sheet_ref", False):
                continue
            child_file = Path(comp.sheet_file).with_suffix(
                ".kicad_sch").name
            child_sheet = self.sheets.get(child_file)
            if child_sheet is None:
                continue
            cf_first = child_file not in seen
            seen.add(child_file)
            visit(child_sheet, comp.designator, cf_first, seen)

        log.info(
            "annotation_done maps=%d refdes_total=%d counters=%s",
            len(result), sum(len(m) for m in result.values()),
            {k: v for k, v in sorted(counters.items())},
        )
        return result

    # =========================================================
    # Размещение и роутинг
    # =========================================================

    def place_and_route(self) -> "Project":
        """Раскладывает и трассирует каждую страницу отдельно."""
        log.info(
            "Старт размещения и роутинга: страниц %d", len(self.sheets),
            extra={
                "stage":  "place",
                "event":  "place_start",
                "counts": {"sheets": len(self.sheets)},
            },
        )
        for sheet in self.sheets.values():
            self._place_and_route_sheet(sheet)
        return self

    def _place_and_route_sheet(self, sheet: Sheet) -> None:
        """Размещает и трассирует одну страницу."""
        log.info(
            "%s place_start components=%d",
            ctx(page=sheet.page), len(sheet.components),
            extra={
                "stage":  "place",
                "event":  "sheet_place_start",
                "counts": {"components": len(sheet.components)},
            },
        )

        placer = Placer(sheet)
        for comp in sheet.components.values():
            placer.register_component(comp)

        strategy_used = placer.auto_place()
        log.info(
            "%s place_strategy strategy=%s",
            ctx(page=sheet.page), strategy_used,
            extra={
                "stage":    "place",
                "event":    "place_strategy",
                "strategy": strategy_used,
            },
        )

        placer.all_overlaps()

        router = Router.from_placer(placer, PathSearch.ASTAR)
        wires = router.route_all()

        log.info(
            "%s route_done wires=%d labels=%d t_junctions=%d",
            ctx(page=sheet.page),
            len(wires), len(sheet.labels), len(sheet.t_junctions),
            extra={
                "stage": "route",
                "event": "route_done",
                "counts": {
                    "wires":       len(wires),
                    "labels":      len(sheet.labels),
                    "t_junctions": len(sheet.t_junctions),
                },
            },
        )

    # =========================================================
    # Сохранение
    # =========================================================

    def _clean_previous_schematics(self, out_dir: Path) -> None:
        """Удалить .kicad_sch прошлого прогона.

        kicad-sch-api дополняет файл при save, а не перезаписывает;
        поэтому перед прогоном удаляем ровно те .kicad_sch, которые
        сейчас перезапишем. Посторонние файлы в out_dir не трогаем.
        """
        targets: set[str] = set()

        root_name = Path(
            self.root_data.get("file")
            or (self.root_path.stem + ".kicad_sch")
        ).name
        targets.add(root_name)

        for sheet in self.sheets.values():
            if sheet.sheet_path:
                targets.add(Path(sheet.sheet_path).name)

        for name in targets:
            path = out_dir / name
            if not path.exists():
                continue
            try:
                path.unlink()
                log.info(
                    "Удалён %s перед перезаписью", name,
                    extra={
                        "stage": "save",
                        "event": "previous_sch_removed",
                        "path":  str(path),
                    },
                )
            except OSError as e:
                log.warning(
                    "Не удалось удалить %s: %s", name, e,
                    extra={
                        "stage":  "save",
                        "event":  "previous_sch_remove_failed",
                        "path":   str(path),
                        "reason": str(e),
                    },
                )

    def save(self, out_dir: str | Path = "out") -> Path:
        """Сохраняет .kicad_sch всего проекта + routes.txt.

        Порядок:
        1. Очистка .kicad_sch предыдущего прогона.
        2. Регистрация библиотек в sym/fp-lib-table.
        3. Автоаннотация refdes: _compute_refdes → self._refdes_maps.
        4. Writer.write_project от основного корня: обход дерева,
           генерация uuid и page-номеров, запись .kicad_sch.
        5. Standalone-листы: ещё один проход Writer'а. Тот же
           инстанс Writer'а не перезапишет уже записанные файлы
           (writer.written), но даст standalone-листам собственные
           мини-корни с собственной нумерацией.
        6. routes.txt — текстовая сводка по всем страницам.
        """
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        self._clean_previous_schematics(out_dir)
        self._ensure_library_tables(out_dir)

        # Автоаннотация refdes.
        self._refdes_maps = self._compute_refdes()

        root_file_name = Path(
            self.root_data.get("file")
            or (self.root_path.stem + ".kicad_sch")
        ).name

        project_name = self._project_name()

        writer = Writer()
        writer.write_project(
            out_dir=out_dir,
            root_sheet=self.root_sheet,
            root_file_name=root_file_name,
            sheets=self.sheets,
            refdes_maps=self._refdes_maps,
            project_name=project_name,
        )

        # Standalone-листы — те, что не были задеты обходом от корня.
        for sheet_path, sheet in list(self.sheets.items()):
            if not sheet_path:
                continue                    # корень уже записан
            if sheet_path in writer.written:
                continue                    # записан через иерархию

            log.info(
                "%s standalone_save path=%s",
                ctx(page=sheet.page), sheet_path,
                extra={
                    "stage": "save",
                    "event": "standalone_save",
                    "sheet": sheet_path,
                },
            )

            writer.write_project(
                out_dir=out_dir,
                root_sheet=sheet,
                root_file_name=sheet_path,
                sheets=self.sheets,
                refdes_maps=self._refdes_maps,
                project_name=project_name,
            )

        # routes.txt — текстовая сводка по всем страницам.
        routes = "\n".join(
            Writer(sheet).write_text() for sheet in self.sheets.values()
        )
        (out_dir / "routes.txt").write_text(routes, encoding="utf-8")

        log.info(
            "Сохранение завершено: %s", out_dir,
            extra={
                "stage":  "save",
                "event":  "save_done",
                "out":    str(out_dir),
                "counts": {"sheets": len(self.sheets)},
            },
        )
        return out_dir

    # ---------- вспомогательное для save ----------

    def _project_name(self) -> str:
        """Имя проекта для блока (instances (project "...")).

        Источник истины — имя .kicad_pro. По конвенции проекта оно
        совпадает со stem корневого YAML и с именем .kicad_sch:
            climate_control_niva_travel.kicad_pro
            climate_control_niva_travel.yaml
            climate_control_niva_travel.kicad_sch

        Именно это имя KiCad использует в (instances (project "...")).
        Поле root_page.project в YAML — человекочитаемое название для
        титульного блока.
        """
        return self.root_path.stem

    # =========================================================
    # Библиотеки проекта (sym-lib-table / fp-lib-table)
    # =========================================================

    def _ensure_library_tables(self, out_dir: Path) -> None:
        """Регистрирует библиотеки LibraryManager в sym/fp-lib-table."""
        if self._libraries is None:
            return

        for kind, name, abs_path in self._libraries.library_entries():
            try:
                rel_path = os.path.relpath(abs_path, out_dir)
            except ValueError:
                rel_path = str(abs_path)

            self._ensure_lib_table(out_dir, kind, {name: rel_path})

    def _ensure_lib_table(
        self,
        out_dir: Path,
        kind: LibTableKind,
        libs: dict,
    ) -> None:
        """Дополняет одну таблицу (sym или fp) записями из libs."""
        table_file = out_dir / LIB_TABLE_FILES[kind]
        root_token = LIB_TABLE_ROOT_TOKENS[kind]

        if table_file.exists():
            content = table_file.read_text(encoding="utf-8")
        else:
            content = f"({root_token} (version {LIB_TABLE_VERSION})\n)\n"
            log.info(
                "Создаётся %s", table_file.name,
                extra={
                    "stage": "save",
                    "event": "lib_table_created",
                    "path":  str(table_file),
                },
            )

        existing_names = set(re.findall(r'\(name\s+"([^"]+)"\)', content))

        added: list[str] = []
        for name, rel_path in libs.items():
            if name in existing_names:
                log.debug(
                    "%s: библиотека '%s' уже зарегистрирована — пропуск",
                    table_file.name, name,
                    extra={
                        "stage": "save",
                        "event": "lib_already_registered",
                        "lib":   name,
                        "path":  str(table_file),
                    },
                )
                continue

            full_path = (out_dir / rel_path).resolve()
            if not full_path.exists():
                log.warning(
                    "%s: библиотека '%s' → %s не найдена (запись "
                    "всё равно будет добавлена)",
                    table_file.name, name, full_path,
                    extra={
                        "stage": "save",
                        "event": "lib_path_missing",
                        "lib":   name,
                        "path":  str(full_path),
                    },
                )

            uri = (
                str(rel_path)
                if str(rel_path).startswith("$")
                else f"{KIPRJMOD_VAR}/{rel_path}"
            )

            entry = (
                f'  (lib (name "{name}")'
                f'(type "{LIB_TABLE_TYPE_KICAD}")'
                f'(uri "{uri}")'
                f'(options "")(descr ""))\n'
            )

            idx = content.rfind(")")
            content = content[:idx] + entry + content[idx:]
            added.append(name)

        if added:
            table_file.write_text(content, encoding="utf-8")
            log.info(
                "%s: зарегистрированы библиотеки: %s",
                table_file.name, ", ".join(added),
                extra={
                    "stage": "save",
                    "event": "lib_table_updated",
                    "path":  str(table_file),
                    "libs":  added,
                },
            )


# =========================================================
# Вспомогательное: префикс refdes, форма порта
# =========================================================

def _refdes_prefix(ref: str) -> str:
    """Буквенная часть refdes: 'U1' → 'U', 'LED11' → 'LED'."""
    return "".join(c for c in ref if not c.isdigit()) or ref


def _default_port_shape(direction: str) -> str:
    """Форма hierarchical_label по port_direction сети-порта."""
    return {
        "INPUT":  "input",
        "OUTPUT": "output",
        "BIDIR":  "bidirectional",
    }.get(str(direction).upper(), "input")