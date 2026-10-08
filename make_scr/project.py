# make_scr/project.py
"""Корневая сущность: загрузка дерева YAML → размещение → трассы → файлы.

Модель:
    - Sheet  — страница KiCad (.kicad_sch). Идентифицируется yaml_path.
               Один Sheet = один файл. Может быть инстансован N раз;
               контексты хранятся в sheet.sheet_ref_instances
               (SheetRefInstance), а не в «списке экземпляров» —
               сама страница всегда одна.
    - SheetRefComponent — ссылка на вложенный лист (X_*). Создаёт
               дочерний Sheet при загрузке и инстанцирует его поддерево
               одним вызовом Sheet.load(parent_sri=..., first_child_counter=...).
               При повторной регистрации (multi-instance) — через
               Sheet.register_from.
    - Placer — размещает на одной Sheet.
    - Router — трассирует одну Sheet.
    - Writer — пишет .kicad_sch; читает готовые comp.instances
               (ComponentInstance / SheetRefInstance) и сериализует
               их в (instances …) и (path …) (page …).
    - Project — тонкий оркестратор.

Идентификация листов:
    * Первоисточник — <stem>.yaml (stem = имя файла без .yaml).
    * Схема листа   — <stem>.kicad_sch.
    * Корневая страница — тоже лист: stem совпадает с именем проекта.
    * Связь листа со схемой — value_sch у X_* в родительском YAML.
    * Реестр листов — сам граф Sheet/SheetRefComponent. Отдельного
      списка project.sheets нет: всё выводится обходом от корня.

Корни проекта:
    У проекта может быть несколько независимых корней:
      * главный — self.root_sheet, загружается из self.root_path;
      * standalone — из root_page.standalone_sheets, независимые
        деревья, лежащие рядом с главным.
    Все корни лежат в self.roots = [root_sheet] + standalone.

    Каждый корень — это Sheet.load(...) с parent_sri=None
    (страница сама себя инстанцирует: создаёт 0-й SheetRefInstance
    и каскадно раздаёт вхождения компонентам). Никакого отдельного
    прохода «register_from для корня» снаружи не делается.

    Все операции, затрагивающие проект целиком (place_and_route,
    save, routes.txt, чистка предыдущих .kicad_sch), идут через
    _collect_all_sheets() — обход каждого корня и объединение
    без дубликатов. Операции, привязанные к конкретному дереву
    (flatten главного корня, iter_sheets), используют
    _collect_sheets(root) с нужным корнем.

Загрузка:
    Единая, рекурсивная. Project.load создаёт корневой Sheet через
    Sheet.load и передаёт ему инфраструктуру (source, libraries,
    load_errors). Дальше Sheet сам грузит компоненты; встречая X_*,
    вызывает SheetRefComponent(..., parent_sri=…,
    sheet_ref_start_counter=…) — тот находит/грузит дочерний Sheet
    и инстанцирует поддерево одним вызовом.

    Standalone-страницы (root_page.standalone_sheets) загружаются
    отдельно, как независимые корни (тоже Sheet.load с
    parent_sri=None). Их YAML — <stem>.yaml рядом с корневым.
    Каждый корень порождает своё поддерево; в дерево главного
    корня они не входят.

Проектные refdef:
    Свойство КОМПОНЕНТА в конкретном контексте. Вычисляется как
    ComponentInstance.refdef: designator для page=1, иначе
    make_refdes(designator, page). Project их не считает — они
    раздаются Sheet._load_components в момент инстанцирования
    (создание ComponentInstance с sheet_ref=parent_sri).

Схлопывание (flatten):
    Project.flatten() — плоская карта главного корня;
    Project.flatten_root(root) — плоская карта одного корня;
    Project.flatten_roots() — карты всех корней.
    Реализация — Sheet.flatten() (см. sheet.py, flat.Flattener).

Сохранение:
    Writer.write_project вызывается для каждого корня. Главный —
    со своим root_file_name (может отличаться от <stem>.kicad_sch),
    standalone — со своим out_file (<stem>.kicad_sch). Кеш
    Writer._written между вызовами не сбрасывается: если файл
    уже писался в рамках текущего save(), второй раз не пишется.

Политика ошибок загрузки:
    Ошибки собираются в self.load_errors (общий список на все корни).
    После загрузки Project.load() бросает ProjectLoadError, если
    список непуст.

Библиотеки проекта:
    LibraryManager — ленивая генерация .kicad_sym через JLC2KiCadLib.
    save() регистрирует библиотеки в sym-lib-table / fp-lib-table.
"""
from __future__ import annotations

import os
import re
from library_manager import LibraryManager
from pathlib import Path
from typing import Dict, List, Optional, Set, TYPE_CHECKING

import yaml

from constants import (
    ComponentKind,
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
# Project
# =========================================================

class Project:
    """Точка входа: загрузка, размещение, роутинг, сохранение.

    Attributes:
        root_path:    путь к корневому YAML.
        yaml_dir:     каталог корневого YAML.
        project_root: каталог проекта (по .kicad_pro).
        source:       KiCadSource — библиотека символов.
        libraries:    LibraryManager — генерация .kicad_sym.
        root_sheet:   главный корневой Sheet (после load).
        roots:        все корни проекта: [root_sheet] + standalone.
                      Используется _collect_all_sheets(),
                      flatten_roots() и внешней валидацией.
        root_data:    развёрнутый root_page из корневого YAML.
        load_errors:  накопитель ошибок загрузки (общий на все корни).
    """

    def __init__(self, root_yaml: str | Path):
        self.root_path = Path(root_yaml).resolve()
        self.yaml_dir = self.root_path.parent
        self.project_root = self._find_project_root(
            self.yaml_dir, yaml_stem=self.root_path.stem,
        )

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

    @classmethod
    def _find_project_root(
        cls,
        start: Path,
        yaml_stem: str,
    ) -> Path:
        """Каталог проекта — там, где лежит <yaml_stem>.kicad_pro.

        Правило единственное: имя .kicad_pro должно совпадать с
        именем корневого YAML. Ищем вверх по дереву от start.

        Любые другие .kicad_pro в каталоге игнорируются — они
        относятся к другим проектам, лежащим рядом.

        Каталог проекта нужен, чтобы:
          * считать libs/ от ${KIPRJMOD};
          * регистрировать библиотеки в sym-lib-table / fp-lib-table.

        Если нигде вверх по дереву нет <yaml_stem>.kicad_pro —
        возвращаем start (файлы создадутся рядом с YAML).
        """
        cur = Path(start).resolve()
        while True:
            if (cur / f"{yaml_stem}.kicad_pro").exists():
                return cur
            if cur.parent == cur:
                return Path(start).resolve()
            cur = cur.parent

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
        self.libraries = LibraryManager(self.project_root)
        self.load_errors.clear()

        # Главный корень: Sheet.load с parent_sri=None (по умолчанию)
        # создаёт 0-й SheetRefInstance и каскадно инстанцирует всё
        # поддерево — никакого внешнего register_from не нужно.
        self.root_sheet = Sheet.load(
            self.root_path,
            source=self.source,
            libraries=self.libraries,
            load_errors=self.load_errors,
            # parent_sri=None по умолчанию — корень проекта
            # first_child_counter=2 по умолчанию — номер первого X_*
        )

        # Standalone-корни: независимые деревья рядом с главным.
        standalone = self._load_standalone_roots()
        self.roots = [self.root_sheet] + standalone

        # Результат разбора библиотек сохраняем на диск.
        self.source.flush()

        if self.load_errors:
            log.error(
                "Загрузка проекта прервана: ошибок %d",
                len(self.load_errors),
                extra={
                    "stage": "load", "event": "load_failed",
                    "count": len(self.load_errors),
                },
            )
            for i, msg in enumerate(self.load_errors, 1):
                log.error("  [%d/%d] %s", i, len(self.load_errors), msg)

            raise ProjectLoadError(self.load_errors)

        # Сводка по всем корням (главный + standalone).
        all_sheets = self._collect_all_sheets()
        total_components = sum(len(s.components) for s in all_sheets)
        total_pins = sum(
            len(c.pins)
            for s in all_sheets
            for c in s.components.values()
        )
        total_nets = sum(len(s.netlist.nets) for s in all_sheets)
        log.info(
            "Загрузка завершена: корней %d, листов %d, "
            "компонентов %d, сетей %d",
            len(self.roots), len(all_sheets),
            total_components, total_nets,
            extra={
                "stage":   "load",
                "event":   "load_done",
                "project": self.root_data.get("project"),
                "counts": {
                    "roots":      len(self.roots),
                    "sheets":     len(all_sheets),
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
        ищется рядом с корневым: <yaml_dir>/<stem>.yaml.

        Каждый standalone грузится Sheet.load с parent_sri=None —
        он корень своего дерева, сам себя инстанцирует.

        Ошибки (нет YAML, ошибка загрузки) складываются в общий
        self.load_errors — как и для главного дерева.
        """
        entries = self.root_data.get("standalone_sheets") or []
        if not entries:
            return []

        out: List[Sheet] = []
        for entry in entries:
            stem = Path(str(entry)).stem
            yml = self.yaml_dir / f"{stem}.yaml"
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
                    # parent_sri=None → этот Sheet — корень дерева
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

    def _collect_sheets(self, root: Optional[Sheet] = None) -> List[Sheet]:
        """Собрать все Sheet'ы поддерева от указанного корня.

        Если root не задан — обходится главный корень (self.root_sheet),
        поведение как раньше. Если задан — обходится поддерево этого
        корня (используется для standalone-страниц).

        Обход: сам корень + все SheetRefComponent'ы рекурсивно
        вниз через child_sheet. Дубликаты (один файл через несколько
        X_*) отсекаются по id().
        """
        if root is None:
            root = self.root_sheet
        if root is None:
            return []

        seen: Set[int] = set()
        result: List[Sheet] = []

        def visit(sheet: Sheet) -> None:
            if id(sheet) in seen:
                return
            seen.add(id(sheet))
            result.append(sheet)
            for comp in sheet.components.values():
                if getattr(comp, "kind", None) != ComponentKind.SHEET_REF:
                    continue
                child = getattr(comp, "child_sheet", None)
                if child is not None:
                    visit(child)

        visit(root)
        return result

    def _collect_all_sheets(self) -> List[Sheet]:
        """Все Sheet'ы всех корней проекта без дубликатов.

        Проходит по self.roots (главный + standalone), для каждого
        корня обходит поддерево и собирает страницы. Дубликаты
        (один файл через несколько X_* или через несколько корней,
        если такое случится) отсекаются по id().

        Это то, что должно использоваться в place_and_route, save,
        routes.txt — везде, где нужно «работать со всем проектом».
        """
        seen: Set[int] = set()
        result: List[Sheet] = []
        for root in self.roots:
            for sheet in self._collect_sheets(root):
                if id(sheet) in seen:
                    continue
                seen.add(id(sheet))
                result.append(sheet)
        return result

    def iter_sheets(self):
        """Итератор по Sheet'ам ВСЕХ корней (главного + standalone).

        Для совместимости с прежним кодом: раньше возвращал только
        главное дерево. Теперь — все страницы всех корней. Если
        нужно ограничиться главным деревом, используйте
        _collect_sheets() без аргументов.
        """
        return iter(self._collect_all_sheets())

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
        """Разместить и трассировать все страницы всех корней проекта.

        Обход: главный корень + standalone. Для каждого листа
        вызывается _place_and_route_sheet, который делает
        auto_place → all_overlaps → route_all → create_sheet_pin_labels.

        Порядок обхода не важен: каждая страница обрабатывается
        независимо; standalone-деревья не пересекаются с главным.
        """
        sheets = self._collect_all_sheets()
        log.info(
            "Старт размещения и роутинга: страниц %d, корней %d",
            len(sheets), len(self.roots),
            extra={
                "stage":  "place",
                "event":  "place_start",
                "counts": {
                    "sheets": len(sheets),
                    "roots":  len(self.roots),
                },
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
        wires = router.route_all()          # сначала роутинг

        # Структурные метки SHEET_PIN_NAME у пинов X_* ЭТОЙ страницы.
        # Только после route_all: netlist наполнен, роутер не путает
        # эти метки со своими (FALLBACK/INTERNAL_NET_NAME).
        # Каскад по дереву — снаружи, через _collect_all_sheets() выше.
        sheet.create_sheet_pin_labels()

        log.info(
            "%s route_done wires=%d labels=%d junctions=%d",
            ctx(page=sheet.page),
            len(wires), len(sheet.labels), len(sheet.junctions),
            extra={
                "stage": "route",
                "event": "route_done",
                "counts": {
                    "wires":     len(wires),
                    "labels":    len(sheet.labels),
                    "junctions": len(sheet.junctions),
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

        Цели — имена файлов всех страниц всех корней:
          * главный корень — из root_data или по конвенции;
          * standalone и остальные — sheet.out_file.
        """
        targets: Set[str] = set()

        root_name = Path(
            self.root_data.get("file")
            or (self.root_path.stem + ".kicad_sch")
        ).name
        targets.add(root_name)

        for sheet in self._collect_all_sheets():
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
        1. Очистка .kicad_sch предыдущего прогона (все файлы всех корней).
        2. Регистрация библиотек в sym/fp-lib-table.
        3. Writer.write_project вызывается для каждого корня:
           главный — со своим root_file_name (может отличаться от
           <stem>.kicad_sch), standalone — со своим out_file.
           Writer._written между вызовами не сбрасывается, поэтому
           файлы, попавшие в два обхода, пишутся один раз.
        4. routes.txt — текстовая сводка по всем страницам всех корней.
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

        # Один Writer на все корни: кеш _written не сбрасывается,
        # _root_sheet переустанавливается на текущий корень внутри
        # write_project.
        writer = Writer()
        for root in self.roots:
            is_main = (root is self.root_sheet)
            writer.write_project(
                out_dir=out_dir,
                root_sheet=root,
                root_file_name=(root_file_name if is_main
                                else root.out_file),
                project_name=self._project_name(),
            )

        # routes.txt — по всем страницам всех корней.
        all_sheets = self._collect_all_sheets()
        routes = "\n".join(
            Writer(s).write_text() for s in all_sheets
        )
        (out_dir / "routes.txt").write_text(routes, encoding="utf-8")

        log.info(
            "Сохранение завершено: %s", out_dir,
            extra={
                "stage":  "save",
                "event":  "save_done",
                "out":    str(out_dir),
                "counts": {
                    "sheets": len(all_sheets),
                    "roots":  len(self.roots),
                },
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