# writer_project_file.py
"""Синхронизация .kicad_pro с генерируемыми .kicad_sch.

Вход — Sheet-объекты (первоисточник). Модуль сам извлекает из них
всё необходимое:
    * UUID, имя и имя файла — из корневого Sheet-объекта;
    * плоский список всех листов — рекурсивным обходом дерева
      SHEET_REF-компонентов от каждого корня.

Модель использования:
    Stateful:
        sync = ProjectFileSync(out_dir, "my_project")
        sync.register_root(root_sheet)
        sync.register_root(standalone_sheet)
        sync.flush()

    One-shot:
        update_project_file(out_dir,
                            project_name="my_project",
                            roots=[root1, root2])

Что синхронизируется в .kicad_pro:
    meta.filename
    schematic.top_level_sheets[]  == [{filename, name, uuid}, ...]
    schematic.sheets[]            == [[uuid, name], ...]  полный список
    sheets[]                      == [[uuid, name], ...]  project-level,
                                                          то же содержимое

Порядок в списках: сначала корни (в порядке регистрации), затем
SHEET_REF-листы (в порядке обхода дерева в глубину). Дубли по
uuid отбрасываются — первая встреченная запись сохраняется.

Остальные секции .kicad_pro (board, net_settings, bom_*, annotation,
variants, erc, cvpcb, pcbnew, ...) не трогаются.

Идемпотентность:
    flush() сравнивает подпись полей до/после применения состояния
    и не пишет файл, если они не изменились.
"""
from __future__ import annotations

import json
import logging
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple


logger = logging.getLogger(__name__)

__all__ = [
    "ProjectFileSync",
    "update_project_file",
]


# Типы записей во внутренних списках.
RootEntry  = Tuple[str, str, str]   # (uuid, filename, name)
SheetEntry = Tuple[str, str]        # (uuid, name)


class ProjectFileSync:
    """Накопитель корневых Sheet-объектов + синхронизатор .kicad_pro.

    UUID, имена и дерево SHEET_REF-компонентов извлекаются из
    Sheet-объектов при flush(). Снаружи передаются только сами
    объекты — никаких строковых UUID.

    Порядок корней сохраняется по порядку регистрации (OrderedDict).
    Повторная регистрация того же uuid перезаписывает запись, но
    сохраняет её исходную позицию.
    """

    def __init__(self, out_dir: Path, project_name: str):
        self.out_dir = Path(out_dir)
        self.project_name = str(project_name)
        self.pro_path = self.out_dir / f"{self.project_name}.kicad_pro"

        # uuid → (root_sheet, filename)
        self._roots: "OrderedDict[str, Tuple[Any, str]]" = OrderedDict()

    # ── регистрация ─────────────────────────────────────────

    def register_root(
        self,
        root_sheet: Any,
        filename: Optional[str] = None,
    ) -> None:
        """Зарегистрировать корневой Sheet-объект.

        Args:
            root_sheet: Sheet-объект корня. UUID и page берутся
                        из него.
            filename:   имя файла, в который записан корень
                        (может отличаться от root_sheet.out_file,
                        если так задано в YAML). Если None —
                        используется root_sheet.out_file.
        """
        if root_sheet is None:
            return
        uuid_ = getattr(root_sheet, "uuid", None)
        if not uuid_:
            logger.warning(
                "register_root: root sheet without uuid skipped")
            return
        if filename is None:
            filename = getattr(root_sheet, "out_file", "") or ""
        self._roots[uuid_] = (root_sheet, filename)

    def register_roots(self, roots: Iterable[Any]) -> None:
        """Зарегистрировать список корневых Sheet-объектов.

        Корни регистрируются в порядке перечисления. Повторная
        регистрация того же корня сохраняет исходную позицию.
        """
        for root in roots:
            self.register_root(root)

    # ── сброс ───────────────────────────────────────────────

    def forget(self) -> None:
        """Очистить накопленное состояние (для нового прогона)."""
        self._roots.clear()

    # ── синхронизация ───────────────────────────────────────

    def flush(self) -> bool:
        """Записать .kicad_pro, если поля синхронизации изменились.

        Возвращает True, если файл создан или перезаписан.
        """
        existed = self.pro_path.exists()
        try:
            data = self._load_or_create()
        except OSError as e:
            logger.error("cannot read %s: %s", self.pro_path, e)
            return False
        except json.JSONDecodeError as e:
            logger.error("invalid JSON in %s: %s", self.pro_path, e)
            return False

        before = _sync_signature(data)

        roots_data, sheets_data = self._collect()
        _apply_sync(data, self.pro_path.name, roots_data, sheets_data)

        after = _sync_signature(data)
        if existed and before == after:
            return False

        try:
            self.out_dir.mkdir(parents=True, exist_ok=True)
            with open(self.pro_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent="\t", ensure_ascii=False)
                f.write("\n")
        except OSError as e:
            logger.error("cannot write %s: %s", self.pro_path, e)
            return False

        return True

    # ── извлечение данных из Sheet-объектов ─────────────────

    def _collect(self) -> Tuple[List[RootEntry], List[SheetEntry]]:
        """Собрать roots_data и sheets_data из зарегистрированных корней.

        Возвращает:
            roots_data:  [(uuid, filename, name), ...]
            sheets_data: [(uuid, name), ...] — плоский список всех
                         листов, начиная с корней.

        Обход дерева: от каждого корня рекурсивно по SHEET_REF-
        компонентам. Каждый Sheet и SHEET_REF посещается один раз,
        даже если лист инстансирован несколько раз.
        """
        roots_data: List[RootEntry] = []
        sheets_data: List[SheetEntry] = []
        seen: set = set()

        # 1. Сами корни — в порядке регистрации.
        for root_uuid, (root_sheet, filename) in self._roots.items():
            if root_uuid in seen:
                continue
            seen.add(root_uuid)
            name = getattr(root_sheet, "page", None) or self.project_name
            roots_data.append((root_uuid, filename, name))
            sheets_data.append((root_uuid, name))

        # 2. Все SHEET_REF-компоненты во всех корнях.
        # visited_sheets защищает от повторного обхода одного
        # Sheet-объекта через несколько родителей (actuator_channel × 4).
        visited_sheets: set = set()
        for _root_uuid, (root_sheet, _filename) in self._roots.items():
            for sheet_ref in _iter_sheet_refs(root_sheet, visited_sheets):
                ref_uuid = getattr(sheet_ref, "uuid", None)
                if not ref_uuid or ref_uuid in seen:
                    continue
                seen.add(ref_uuid)
                ref_name = (
                    getattr(sheet_ref, "sheet_name", None)
                    or getattr(sheet_ref, "designator", "")
                    or ""
                )
                sheets_data.append((ref_uuid, ref_name))

        return roots_data, sheets_data

    # ── чтение / каркас ─────────────────────────────────────

    def _load_or_create(self) -> Dict[str, Any]:
        """Загрузить существующий .kicad_pro или вернуть каркас.

        Отличия от старой версии:
          * OSError (нет доступа, файл занят) пробрасывается —
            вызывающий flush() логирует и возвращает False.
          * JSONDecodeError пробрасывается, файл откладывается
            в .bak, но НЕ подменяется пустым каркасом молча —
            иначе терялись бы пользовательские настройки.
        """
        if not self.pro_path.exists():
            return _make_empty_project_data(self.pro_path.name)

        text = self.pro_path.read_text(encoding="utf-8")
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            _backup_broken(self.pro_path)
            raise

        if not isinstance(data, dict):
            _backup_broken(self.pro_path)
            raise json.JSONDecodeError(
                "root JSON is not an object", text, 0)
        return data


# ─────────────────────────────────────────────────────────────
# Функциональный API
# ─────────────────────────────────────────────────────────────

def update_project_file(
    out_dir: Path,
    *,
    project_name: str,
    roots: Iterable[Any],
) -> bool:
    """Одноразово обновить .kicad_pro из списка корневых Sheet-объектов.

    Для каждого корня берётся uuid, page (или project_name как
    fallback) и out_file. Имя файла корня при необходимости можно
    переопределить через stateful-API.
    """
    sync = ProjectFileSync(out_dir, project_name)
    sync.register_roots(roots)
    return sync.flush()


# ─────────────────────────────────────────────────────────────
# Обход дерева
# ─────────────────────────────────────────────────────────────

def _iter_sheet_refs(sheet: Any, visited: set) -> Iterator[Any]:
    """Рекурсивно yield'ить все SHEET_REF-компоненты дерева.

    visited — множество уже обойдённых Sheet-объектов; защищает
    от повторного спуска в один и тот же лист (multi-instance,
    циклические ссылки).
    """
    if sheet is None or sheet in visited:
        return
    visited.add(sheet)

    for comp in getattr(sheet, "components", {}).values():
        if not _is_sheet_ref(comp):
            continue
        yield comp
        child = getattr(comp, "child_sheet", None)
        if child is not None:
            yield from _iter_sheet_refs(child, visited)


def _is_sheet_ref(comp: Any) -> bool:
    """Является ли компонент ссылкой на лист (SHEET_REF)."""
    kind = getattr(comp, "kind", None)
    if kind is None:
        return False
    try:
        from constants import ComponentKind
        return kind == ComponentKind.SHEET_REF
    except Exception:
        # Fallback: у SHEET_REF есть child_sheet и sheet_file,
        # у обычных символов — нет.
        return (
            hasattr(comp, "child_sheet")
            and hasattr(comp, "sheet_file")
        )


# ─────────────────────────────────────────────────────────────
# Применение к data
# ─────────────────────────────────────────────────────────────

def _apply_sync(
    data: Dict[str, Any],
    pro_filename: str,
    roots: List[RootEntry],
    sheets: List[SheetEntry],
) -> None:
    meta = data.setdefault("meta", {})
    meta["filename"] = pro_filename

    # Единый полный список [uuid, name]: сначала корни, потом SHEET_REF'ы.
    seen: set = set()
    full: List[List[str]] = []
    for root_uuid, _root_filename, root_name in roots:
        if not root_uuid or root_uuid in seen:
            continue
        seen.add(root_uuid)
        full.append([root_uuid, root_name])
    for sheet_uuid, sheet_name in sheets:
        if not sheet_uuid or sheet_uuid in seen:
            continue
        seen.add(sheet_uuid)
        full.append([sheet_uuid, sheet_name])

    schematic = data.setdefault("schematic", {})

    schematic["top_level_sheets"] = [
        {"filename": fn, "name": nm, "uuid": u}
        for u, fn, nm in roots
    ]

    schematic["sheets"] = full
    data["sheets"] = full


def _sync_signature(data: Dict[str, Any]) -> Tuple[str, str, str, str]:
    schematic = data.get("schematic") or {}
    meta = data.get("meta") or {}
    return (
        json.dumps(schematic.get("top_level_sheets"), sort_keys=True),
        json.dumps(schematic.get("sheets"), sort_keys=True),
        json.dumps(data.get("sheets"), sort_keys=True),
        str(meta.get("filename") or ""),
    )


def _backup_broken(pro_path: Path) -> None:
    backup = pro_path.with_suffix(pro_path.suffix + ".bak")
    try:
        if backup.exists():
            backup.unlink()
        pro_path.rename(backup)
    except OSError:
        pass


def _make_empty_project_data(filename: str) -> Dict[str, Any]:
    return {
        "board": {
            "design_settings": {"defaults": {}, "rules": {}},
        },
        "meta": {
            "filename": filename,
            "version": 3,
        },
        "net_settings": {
            "classes": [],
            "meta": {"version": 5},
        },
        "schematic": {
            "annotate_start_num": 0,
            "annotation": {"method": 1, "sort_order": 0},
            "meta": {"version": 1},
            "sheets": [],
            "top_level_sheets": [],
        },
        "sheets": [],
    }