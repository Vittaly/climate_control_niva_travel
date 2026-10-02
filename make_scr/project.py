# make_scr/project.py
"""Корневая сущность: загрузка дерева YAML → размещение → трассы → файлы.

Модель:
    - Sheet  — страница KiCad (.kicad_sch). Идентифицируется yaml_path.
               Один Sheet = один файл. Может быть инстанцирован N раз,
               это выражается списком sheet.instances.
    - SheetRefComponent — ссылка на вложенный лист (X_*). Создаёт
               дочерний Sheet при загрузке и регистрирует его инстансы.
    - Placer — размещает на одной Sheet.
    - Router — трассирует одну Sheet.
    - Writer — пишет .kicad_sch; читает готовые comp.instances и
               sheet.instances, сериализует в блок (instances …).
    - Project — тонкий оркестратор.

Идентификация листов:
    * Первоисточник — <stem>.yaml (stem = имя файла без .yaml).
    * Схема листа   — <stem>.kicad_sch.
    * Корневая страница — тоже лист: stem совпадает с именем проекта.
    * Связь листа со схемой — value_sch у X_* в родительском YAML.
    * Реестр листов — сам граф Sheet/SheetRefComponent. Отдельного
      списка project.sheets нет: всё выводится обходом от корня.

Загрузка:
    Единая, рекурсивная. Project.load создаёт корневой Sheet и
    передаёт ему инфраструктуру (source, libraries, load_errors,
    page_counter). Дальше Sheet сам грузит компоненты; встречая X_*,
    вызывает SheetRefComponent(...) — тот находит/грузит дочерний
    Sheet и регистрирует его инстансы.

    Standalone-страницы (root_page.standalone_sheets) загружаются
    отдельно, как независимые корни. Их YAML — <stem>.yaml рядом
    с корневым. Каждый корень порождает своё поддерево; в дерево
    главного корня они не входят.

Проектные refdes:
    Свойство КОМПОНЕНТА в конкретном инстансе. Вычисляется как
    make_refdes(designator, inst.page) через ComponentInstance.
    Project их не считает — они раздаются Sheet.register_instance
    в момент создания SheetInstance.

Схлопывание (flatten):
    Project.flatten() — плоская карта главного корня;
    Project.flatten_root(root) — плоская карта одного корня;
    Project.flatten_roots() — карты всех корней.
    Реализация — Sheet.flatten() (см. sheet.py, flat.Flattener).

Сохранение:
    Writer.write_project получает корневой Sheet и сериализует
    (instances ...) из готовых comp.instances. Никаких refdes_maps
    в сигнатуре — они не нужны.

Политика ошибок загрузки:
    Ошибки собираются в self.load_errors (общий список на дерево).
    После загрузки Project.load() бросает ProjectLoadError, если
    список непуст.

Библиотеки проекта:
    LibraryManager — ленивая генерация .kicad_sym через JLC2KiCadLib.
    save() регистрирует библиотеки в sym-lib-table / fp-lib-table.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Set, TYPE_CHECKING

import yaml

from constants import (
    KIPRJMOD_VAR,
    LIB_TABLE_FILES,
    LIB_TABLE_ROOT_TOKENS,
    LIB_TABLE_TYPE_KICAD,
    LIB_TABLE_VERSION,
    LibTableKind,
    PathSearch,
)
from kicad_source import KiCadSource
from logging_setup import ctx, get_logger
from placer import Placer
from router import Router
from sheet import Sheet
from writer import Writer

if TYPE_CHECKING:
    from flat import FlatNetMap

log = get_logger(__name__)


class ProjectLoadError(Exception):
    """Загрузка проекта прервана: YAML несовместим с KiCad.

    Собирает все обнаруженные ошибки, чтобы не гонять пользователя
    по одному компоненту за раз.
    """
    def __init__(self, errors: List[str]):
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
    """

    SYM_LIB_NAME = "MyMCU"
    FP_LIB_NAME = "MyFootprints"

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)

        libs_root = self.base_dir / "libs"
        self.sym_dir = libs_root / "symbol"

        self.fp_dir = libs_root / f"{self.FP_LIB_NAME}.pretty"
        self.sym_lib_name = self.SYM_LIB_NAME
        self.fp_lib_name = self.FP_LIB_NAME

        self._resolved: Set[str] = set()

    # ---------- публичное ----------

    def ensure_type(self, type_name: str, tdef: dict) -> Optional[Path]:
        """Гарантирует, что для типа есть symbol и footprint.

        Порядок действий:
            1. Если в tdef уже есть и symbol, и footprint — ничего
               не делаем.
            2. Пытаемся найти символ/футпринт по lcsc_id в уже
               существующих файлах библиотеки.
            3. Если что-то не найдено — запускаем JLC2KiCadLib.
            4. Прописываем найденные symbol/footprint обратно в tdef.

        Returns:
            Path к .kicad_sym, если файл библиотеки был изменён,
            иначе None.

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

        if not has_symbol:
            name = self._find_symbol_name(sym_file, lcsc_id)
            if name:
                tdef["symbol"] = f"{self.sym_lib_name}:{name}"
        if not has_footprint:
            name = self._find_footprint_name(self.fp_dir, lcsc_id)
            if name:
                tdef["footprint"] = f"{self.fp_lib_name}:{name}"

        return sym_file if sym_file.exists() else None

    def library_entries(self) -> List[tuple]:
        """[(kind, nickname, abs_path), ...] для sym-lib-table / fp-lib-table."""
        return [
            (LibTableKind.SYMBOL, self.sym_lib_name,
             self.sym_dir / f"{self.sym_lib_name}.kicad_sym"),
            (LibTableKind.FOOTPRINT, self.fp_lib_name,
             self.fp_dir),
        ]

    # ---------- поиск в сгенерированных файлах ----------

    def _find_symbol_name(self, sym_file: Path, lcsc_id: str) -> Optional[str]:
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
    """Точка входа: загрузка, размещение, роутинг, сохранение.

    Attributes:
        root_path:   путь к корневому YAML.
        base_dir:    каталог корневого YAML.
        source:      KiCadSource — библиотека символов.
        libraries:   LibraryManager — генерация .kicad_sym.
        root_sheet:  главный корневой Sheet (после load).
        roots:       все корни проекта: [root_sheet] + standalone.
                     Используется flatten_roots() и внешней валидацией.
        root_data:   развёрнутый root_page из корневого YAML.
        load_errors: накопитель ошибок загрузки (общий на все корни).
    """

    def __init__(self, root_yaml: str | Path):
        self.root_path = Path(root_yaml).resolve()
        self.base_dir = self.root_path.parent

        self.source: Optional[KiCadSource] = None
        self.libraries: Optional[LibraryManager] = None

        self.root_sheet: Optional[Sheet] = None
        self.roots: List[Sheet] = []
        self.root_data: dict = {}

        self.load_errors: List[str] = []

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
        """Загрузить корневой YAML, главное дерево и standalone-корни.

        Единственная точка входа для загрузки. Всё остальное —
        Sheet.load и SheetRefComponent — работают рекурсивно,
        используя общие объекты: source, libraries, load_errors.
        """
        log.info(
            "Загрузка %s", self.root_path,
            extra={
                "stage": "load",
                "event": "load_start",
                "path":  str(self.root_path),
            },
        )

        # Корневой YAML отдельно: root_page может быть обёрнут.
        self._read_root()

        self.source = KiCadSource()
        self.libraries = LibraryManager(self.base_dir)
        self.load_errors.clear()

        # Главный корень: рекурсивная загрузка дерева.
        self.root_sheet = Sheet.load(
            self.root_path,
            source=self.source,
            libraries=self.libraries,
            load_errors=self.load_errors,
        )

        # Standalone-корни: независимые деревья рядом с главным.
        standalone = self._load_standalone_roots()
        self.roots = [self.root_sheet] + standalone

        # Результат разбора библиотек сохраняем на диск.
        self.source.flush()

        if self.load_errors:
            raise ProjectLoadError(self.load_errors)

        sheets = self._collect_sheets()
        total_components = sum(len(s.components) for s in sheets)
        total_pins = sum(
            len(c.pins)
            for s in sheets
            for c in s.components.values()
        )
        total_nets = sum(len(s.netlist.nets) for s in sheets)
        log.info(
            "Загрузка завершена: корней %d, листов главного дерева %d, "
            "компонентов %d, сетей %d",
            len(self.roots), len(sheets), total_components, total_nets,
            extra={
                "stage":   "load",
                "event":   "load_done",
                "project": self.root_data.get("project"),
                "counts": {
                    "roots":      len(self.roots),
                    "sheets":     len(sheets),
                    "components": total_components,
                    "pins":       total_pins,
                    "nets":       total_nets,
                },
            },
        )
        return self

    def _read_root(self) -> None:
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

    def _load_standalone_roots(self) -> List[Sheet]:
        """Загрузить standalone-страницы как независимые корни.

        Список — root_page.standalone_sheets в корневом YAML.
        Каждый элемент — путь к .kicad_sch; соответствующий YAML
        ищется рядом с корневым: <base_dir>/<stem>.yaml.

        Ошибки (нет YAML, ошибка загрузки) складываются в общий
        self.load_errors — как и для главного дерева.
        """
        entries = self.root_data.get("standalone_sheets") or []
        if not entries:
            return []

        out: List[Sheet] = []
        for entry in entries:
            stem = Path(str(entry)).stem
            yml = self.base_dir / f"{stem}.yaml"
            if not yml.exists():
                msg = f"standalone_sheets: нет {yml}"
                self.load_errors.append(msg)
                log.error("%s", msg, extra={
                    "stage": "load",
                    "event": "standalone_yaml_missing",
                    "stem":  stem,
                    "path":  str(yml),
                })
                continue

            try:
                sheet = Sheet.load(
                    yml,
                    source=self.source,
                    libraries=self.libraries,
                    load_errors=self.load_errors,
                )
            except Exception as e:
                msg = f"standalone {stem}: {e}"
                self.load_errors.append(msg)
                log.error("%s", msg, extra={
                    "stage": "load",
                    "event": "standalone_load_failed",
                    "stem":  stem,
                    "path":  str(yml),
                    "reason": str(e),
                })
                continue

            out.append(sheet)
            log.info(
                "Standalone-корень загружен: %s",
                sheet.sheet_path,
                extra={
                    "stage": "load",
                    "event": "standalone_loaded",
                    "stem":  stem,
                    "path":  str(yml),
                },
            )
        return out

    # =========================================================
    # Обход загруженного дерева
    # =========================================================

    def _collect_sheets(self) -> List[Sheet]:
        """Собрать все Sheet'ы главного дерева, обойдя от корня.

        Обход: корневой Sheet + все SheetRefComponent'ы рекурсивно
        вниз через child_sheet. Дубликаты (один файл через несколько
        X_*) отсекаются по id().

        Standalone-корни сюда НЕ попадают: это независимые деревья,
        они доступны через self.roots.
        """
        if self.root_sheet is None:
            return []

        seen: Set[int] = set()
        result: List[Sheet] = []

        def visit(sheet: Sheet) -> None:
            if id(sheet) in seen:
                return
            seen.add(id(sheet))
            result.append(sheet)
            for comp in sheet.components.values():
                if not getattr(comp, "is_sheet_ref", False):
                    continue
                child = getattr(comp, "child_sheet", None)
                if child is not None:
                    visit(child)

        visit(self.root_sheet)
        return result

    def iter_sheets(self):
        """Итератор по Sheet'ам главного дерева (корень + дочерние).

        Standalone-корни — в self.roots; отдельного итератора для
        них не заводим, чтобы не плодить API.
        """
        return iter(self._collect_sheets())

    # =========================================================
    # Схлопывание иерархии
    # =========================================================

    def flatten(self) -> "FlatNetMap":
        """Плоская карта главного корня. Делегат в root_sheet.flatten().

        Совместимость с прежним build_from_project(proj): то же
        поведение для корневой схемы.
        """
        if self.root_sheet is None:
            raise RuntimeError("Project.flatten: root_sheet не загружен")
        return self.root_sheet.flatten()

    def flatten_root(self, root: Sheet) -> "FlatNetMap":
        """Плоская карта поддерева одного корня (главного или standalone)."""
        return root.flatten()

    def flatten_roots(self) -> Dict[str, "FlatNetMap"]:
        """{sheet_path: FlatNetMap} — карта на каждый корень проекта.

        Карты независимы: PinRef'ы и имена сетей разных корней
        нельзя сливать в одну, потому что совпадение refdes или
        имён сетей между корнями не означает совпадения сущностей.

        Для сверки с kicad-cli каждый корень экспортируется отдельно
        и сравнивается со своей картой.
        """
        return {r.sheet_path: r.flatten() for r in self.roots}

    # =========================================================
    # Размещение и роутинг
    # =========================================================

    def place_and_route(self) -> "Project":
        sheets = self._collect_sheets()
        log.info(
            "Старт размещения и роутинга: страниц %d", len(sheets),
            extra={
                "stage":  "place",
                "event":  "place_start",
                "counts": {"sheets": len(sheets)},
            },
        )
        for sheet in sheets:
            self._place_and_route_sheet(sheet)
        return self

    def _place_and_route_sheet(self, sheet: Sheet) -> None:
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
        сейчас перезапишем. Посторонние файлы не трогаем.
        """
        targets: Set[str] = set()

        # Имя корневого файла — из root_data или по конвенции.
        root_name = Path(
            self.root_data.get("file")
            or (self.root_path.stem + ".kicad_sch")
        ).name
        targets.add(root_name)

        for sheet in self._collect_sheets():
            if not sheet.is_root:
                targets.add(sheet.sheet_path)

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
        3. Writer.write_project от корня: обход дерева, запись
           всех .kicad_sch. Writer читает готовые comp.instances и
           sheet.instances (уже заполнены при загрузке через
           SheetRefComponent/register_instance).
        4. routes.txt — текстовая сводка по всем страницам.
        """
        if self.root_sheet is None:
            raise RuntimeError("Project.save: root_sheet не загружен")

        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        self._clean_previous_schematics(out_dir)
        self._ensure_library_tables(out_dir)

        root_file_name = Path(
            self.root_data.get("file")
            or (self.root_path.stem + ".kicad_sch")
        ).name

        writer = Writer()
        writer.write_project(
            out_dir=out_dir,
            root_sheet=self.root_sheet,
            root_file_name=root_file_name,
            project_name=self._project_name(),
        )

        routes = "\n".join(
            Writer(sheet).write_text() for sheet in self._collect_sheets()
        )
        (out_dir / "routes.txt").write_text(routes, encoding="utf-8")

        log.info(
            "Сохранение завершено: %s", out_dir,
            extra={
                "stage":  "save",
                "event":  "save_done",
                "out":    str(out_dir),
                "counts": {"sheets": len(self._collect_sheets())},
            },
        )
        return out_dir

    def _project_name(self) -> str:
        return self.root_path.stem

    # =========================================================
    # Библиотеки проекта (sym-lib-table / fp-lib-table)
    # =========================================================

    def _ensure_library_tables(self, out_dir: Path) -> None:
        if self.libraries is None:
            return

        for kind, name, abs_path in self.libraries.library_entries():
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

        added: List[str] = []
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