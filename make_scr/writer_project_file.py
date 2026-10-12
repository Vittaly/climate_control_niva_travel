# writer_project_file.py
"""Синхронизация .kicad_pro с генерируемыми .kicad_sch.

Вход — Sheet-объекты (первоисточник). Модуль сам извлекает из них
всё необходимое в момент записи:
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

Принцип: UUID и имя файла живут ТОЛЬКО в объекте Sheet. Нигде
не кэшируются — читаются из объекта в момент формирования JSON
для .kicad_pro. Никаких промежуточных кортежей с UUID, никаких
ключей словарей из UUID.

Остальные секции .kicad_pro (board, net_settings, bom_*, annotation,
variants, erc, cvpcb, pcbnew, ...) не трогаются.

Идемпотентность:
    flush() сравнивает подпись полей до/после применения состояния
    и не пишет файл, если они не изменились.

Отладка:
    Модуль логирует через стандартный logging. Чтобы видеть
    диагностику, включите уровень INFO для логгера
    'writer_project_file'. Ключевые строки:
      register_root: uuid=... out_file=... page=... id=...
      flush: pro_path=... existed=... roots=... uuids=[...]
      flush: before==after=... top_level=... sheets_count=...
      flush: written to ...
      flush: skipped (no change)
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Iterable, Iterator, List


from logging_setup import get_logger
logger = get_logger(__name__)

__all__ = [
    "ProjectFileSync",
    "update_project_file",
]


class ProjectFileSync:
    """Накопитель корневых Sheet-объектов + синхронизатор .kicad_pro.

    Хранит ТОЛЬКО ссылки на объекты Sheet. Всё остальное (uuid,
    имя файла, имя листа, список дочерних) извлекается из объектов
    в момент flush(). Никаких строковых UUID вне объектов.

    Порядок корней сохраняется по порядку регистрации. Повторная
    регистрация того же объекта (по идентичности) игнорируется.
    """

    def __init__(self, out_dir: Path, project_name: str):
        self.out_dir = Path(out_dir)
        self.project_name = str(project_name)
        self.pro_path = self.out_dir / f"{self.project_name}.kicad_pro"

        # Список корневых Sheet-объектов. Только ссылки — никаких
        # копий uuid/filename/name.
        self._roots: List[Any] = []

        logger.info(
            "ProjectFileSync: out_dir=%s project_name=%r pro_path=%s",
            self.out_dir, self.project_name, self.pro_path,
        )

    # ── регистрация ─────────────────────────────────────────

    def register_root(self, root_sheet: Any) -> None:
        """Зарегистрировать корневой Sheet-объект.

        Все атрибуты (uuid, out_file, page) берутся из объекта
        в момент flush. Здесь только накапливаем ссылки.
        """
        if root_sheet is None:
            logger.info("register_root: root_sheet is None — skipped")
            return
        if any(existing is root_sheet for existing in self._roots):
            logger.info(
                "register_root: already registered id=%r — skipped",
                id(root_sheet),
            )
            return
        self._roots.append(root_sheet)
        logger.info(
            "register_root: uuid=%r out_file=%r page=%r id=%r",
            getattr(root_sheet, "uuid", None),
            getattr(root_sheet, "out_file", None),
            getattr(root_sheet, "page", None),
            id(root_sheet),
        )

    def register_roots(self, roots: Iterable[Any]) -> None:
        """Зарегистрировать список корневых Sheet-объектов."""
        for root in roots:
            self.register_root(root)

    # ── сброс ───────────────────────────────────────────────

    def forget(self) -> None:
        """Очистить накопленное состояние (для нового прогона)."""
        self._roots.clear()
        logger.info("forget: roots cleared")

    # ── синхронизация ───────────────────────────────────────

    def flush(self) -> bool:
        """Записать .kicad_pro, если поля синхронизации изменились.

        Возвращает True, если файл создан или перезаписан.
        """
        existed = self.pro_path.exists()

        logger.info(
            "flush: pro_path=%s existed=%s roots=%d uuids=%s",
            self.pro_path, existed, len(self._roots),
            [getattr(r, "uuid", None) for r in self._roots],
        )

        try:
            data = self._load_or_create()
        except OSError as e:
            logger.error("flush: cannot read %s: %s", self.pro_path, e)
            return False
        except json.JSONDecodeError as e:
            logger.error("flush: invalid JSON in %s: %s", self.pro_path, e)
            return False

        before = _sync_signature(data)

        _apply_sync(data, self.pro_path.name,
                    self._roots, self.project_name)

        after = _sync_signature(data)

        schematic = data.get("schematic") or {}
        logger.info(
            "flush: before==after=%s top_level=%s sheets_count=%d",
            before == after,
            schematic.get("top_level_sheets"),
            len(schematic.get("sheets", []) or []),
        )

        if existed and before == after:
            logger.info("flush: skipped (no change) file=%s",
                        self.pro_path)
            return False

        try:
            self.out_dir.mkdir(parents=True, exist_ok=True)
            with open(self.pro_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent="\t", ensure_ascii=False)
                f.write("\n")
            logger.info("flush: written to %s", self.pro_path)
        except OSError as e:
            logger.error("flush: cannot write %s: %s", self.pro_path, e)
            return False

        return True

    # ── чтение / каркас ─────────────────────────────────────

    def _load_or_create(self) -> dict:
        """Загрузить существующий .kicad_pro или вернуть каркас."""
        if not self.pro_path.exists():
            logger.info("_load_or_create: creating empty skeleton for %s",
                        self.pro_path.name)
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
    """Одноразово обновить .kicad_pro из списка корневых Sheet-объектов."""
    sync = ProjectFileSync(out_dir, project_name)
    sync.register_roots(roots)
    return sync.flush()


# ─────────────────────────────────────────────────────────────
# Обход дерева
# ─────────────────────────────────────────────────────────────

def _iter_sheet_refs(sheet: Any, visited: set) -> Iterator[Any]:
    """Рекурсивно yield'ить все SHEET_REF-компоненты дерева.

    visited — множество уже обойдённых Sheet-объектов (по id),
    защищает от повторного спуска в один лист (multi-instance,
    циклические ссылки).
    """
    if sheet is None or id(sheet) in visited:
        return
    visited.add(id(sheet))

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
        return (
            hasattr(comp, "child_sheet")
            and hasattr(comp, "sheet_file")
        )


# ─────────────────────────────────────────────────────────────
# Применение к data
# ─────────────────────────────────────────────────────────────

def _apply_sync(
    data: dict,
    pro_filename: str,
    roots: List[Any],
    project_name: str,
) -> None:
    """Заполнить поля .kicad_pro из объектов Sheet.

    roots — список корневых Sheet-объектов (ссылки).
    Всё остальное (uuid, filename, name, дочерние) читается
    из объектов прямо здесь, в момент формирования JSON.
    """
    meta = data.setdefault("meta", {})
    meta["filename"] = pro_filename

    schematic = data.setdefault("schematic", {})

    # top_level_sheets — из корневых объектов.
    top_level = []
    for root in roots:
        uid = getattr(root, "uuid", None)
        if not uid:
            logger.warning(
                "_apply_sync: root without uuid skipped, id=%r",
                id(root),
            )
            continue
        filename = getattr(root, "out_file", "") or ""
        name = getattr(root, "page", None) or project_name
        top_level.append({
            "filename": filename,
            "name": name,
            "uuid": uid,
        })
    schematic["top_level_sheets"] = top_level

    # sheets — плоский список [uuid, name].
    # Обход корней делается ЗДЕСЬ, на месте, без промежуточных
    # структур. Дубли по uuid отбрасываются.
    full: List[List[str]] = []
    seen_uuid: set = set()
    visited_sheets: set = set()

    def _append(sheet_obj: Any, name_attr: str) -> None:
        uid = getattr(sheet_obj, "uuid", None)
        if not uid:
            return
        if uid in seen_uuid:
            return
        seen_uuid.add(uid)
        name = (
            getattr(sheet_obj, name_attr, None)
            or getattr(sheet_obj, "page", None)
            or getattr(sheet_obj, "designator", "")
            or ""
        )
        full.append([uid, str(name)])

    for root in roots:
        _append(root, "page")
        for ref in _iter_sheet_refs(root, visited_sheets):
            _append(ref, "sheet_name")

    
    data["sheets"] = full

    logger.info(
        "_apply_sync: top_level=%d sheets=%d",
        len(top_level), len(full),
    )


def _sync_signature(data: dict) -> tuple:
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
        logger.warning("_backup_broken: moved %s to %s",
                       pro_path, backup)
    except OSError as e:
        logger.error("_backup_broken: failed for %s: %s", pro_path, e)


def _make_empty_project_data(filename: str) -> dict:
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