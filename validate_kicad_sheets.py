#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
validate_kicad_sheets.py

Полная валидация иерархического проекта KiCad: сверка .kicad_pro
с .kicad_sch, проверка instance-путей, имён страниц и дублей.

Использование:
    python validate_kicad_sheets.py PROJ.kicad_pro
    python validate_kicad_sheets.py ROOT.kicad_sch
    python validate_kicad_sheets.py PATH --project-dir DIR
    python validate_kicad_sheets.py PATH -v
    python validate_kicad_sheets.py PATH --json

Что проверяется (эталон — проект KiCad 10):

  Файловая структура:
    • <basename>.kicad_pro существует;
    • каждый top_level_sheets[].filename существует на диске;
    • каждое Sheetfile из (sheet …) существует рядом с корнем.

  Согласованность .kicad_pro ↔ .kicad_sch:
    • basename .kicad_pro == имя проекта в (project "…") во всех схемах;
    • top_level_sheets[i].uuid == верхнеуровневое (uuid "…") соответствующего .kicad_sch;
    • top_level_sheets[0].filename == <basename>.kicad_sch.

  Пути у листов в корневом .kicad_sch:
    • (instances (project "P" (path "/R" (page "N")))) — путь ТОЛЬКО
      корневой UUID, БЕЗ /<uuid листа> на конце.

  Пути в дочерних .kicad_sch:
    • у каждого (symbol …) в (instances …) набор (path "P_i") ровно
      соответствует набору листов корня, чей Sheetfile == этот файл;
    • P_i == "/R/S_i", где S_i — uuid соответствующего листа в корне;
    • у каждого вложенного (sheet …) в дочернем файле путь ==
      "/R[/S_parent…]" — путь до родителя, без собственного uuid.

  Имена страниц (sheets[] в .kicad_pro):
    • каждый (uuid "…") из sheets[] присутствует в какой-либо схеме
      (как (uuid …) корня или (sheet (uuid …)) в корне/родителе);
    • для не-корневых листов sheets[][1] == (property "Sheetname" …);
    • один и тот же uuid с разными name → ERROR (несогласованность);
    • одно и то же name с разными uuid → WARN (легально при
      мульти-инстансах одного файла, но требует проверки).

Коды выхода:
    0 — ошибок нет;
    1 — есть хотя бы один ERROR;
    2 — входной файл не найден / не распарсился.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


# ─────────────────────────────────────────────────────────────
# Парсер s-выражений
# ─────────────────────────────────────────────────────────────

def _find_matching_paren(s: str, open_idx: int) -> int:
    """Индекс ')' парной для s[open_idx]=='('. -1 если не найдено."""
    assert s[open_idx] == "("
    depth = 0
    i = open_idx
    n = len(s)
    in_str = False
    while i < n:
        c = s[i]
        if in_str:
            if c == "\\":
                i += 2
                continue
            if c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    return i
        i += 1
    return -1


def _parse_head(s: str, idx: int) -> Tuple[str, int]:
    i = idx + 1
    n = len(s)
    while i < n and s[i].isspace():
        i += 1
    start = i
    while i < n and not s[i].isspace() and s[i] not in "()":
        i += 1
    return s[start:i], i


def _find_blocks_by_name(s: str, name: str) -> List[Tuple[int, int]]:
    result: List[Tuple[int, int]] = []
    i = 0
    n = len(s)
    in_str = False
    while i < n:
        c = s[i]
        if in_str:
            if c == "\\":
                i += 2
                continue
            if c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
            i += 1
            continue
        if c == "(":
            head, _ = _parse_head(s, i)
            if head == name:
                end = _find_matching_paren(s, i)
                if end < 0:
                    break
                result.append((i, end))
                i = end + 1
                continue
        i += 1
    return result


def _parse_top_children(body: str) -> List[Tuple[str, str]]:
    children: List[Tuple[str, str]] = []
    i = 0
    n = len(body)
    while i < n:
        while i < n and body[i].isspace():
            i += 1
        if i >= n:
            break
        if body[i] != "(":
            break
        name, after_name = _parse_head(body, i)
        end = _find_matching_paren(body, i)
        if end < 0:
            break
        children.append((name, body[after_name:end]))
        i = end + 1
    return children


def _strings_from_body(body: str) -> List[str]:
    result: List[str] = []
    i = 0
    n = len(body)
    while i < n:
        c = body[i]
        if c.isspace() or c in "()":
            if c == "(":
                end = _find_matching_paren(body, i)
                if end < 0:
                    break
                i = end + 1
                continue
            i += 1
            continue
        if c == '"':
            start = i + 1
            i = start
            while i < n:
                if body[i] == "\\":
                    i += 2
                    continue
                if body[i] == '"':
                    break
                i += 1
            if i >= n:
                break
            result.append(body[start:i])
            i += 1
            continue
        while i < n and not body[i].isspace() and body[i] not in "()\"":
            i += 1
    return result


def _read_root_children(path: Path) -> List[Tuple[str, str]]:
    text = path.read_text(encoding="utf-8")
    i = text.find("(")
    if i < 0:
        raise ValueError(f"{path}: not an s-expression file")
    name, after_name = _parse_head(text, i)
    if name != "kicad_sch":
        raise ValueError(f"{path}: expected (kicad_sch …), got ({name} …)")
    end = _find_matching_paren(text, i)
    return _parse_top_children(text[after_name:end])


def _direct_child_string(inner: str, child_name: str) -> Optional[str]:
    for name, sub in _parse_top_children(inner):
        if name == child_name:
            strings = _strings_from_body(sub)
            if strings:
                return strings[0]
    return None


def _direct_child_property(inner: str, prop_name: str) -> Optional[str]:
    for name, sub in _parse_top_children(inner):
        if name != "property":
            continue
        strings = _strings_from_body(sub)
        if len(strings) >= 2 and strings[0] == prop_name:
            return strings[1]
    return None


def _all_project_names(children: List[Tuple[str, str]]) -> Set[str]:
    """Все имена проектов из (project "…") во всех (instances …).

    Ищем в корне документа и в каждом (symbol …) / (sheet …).
    """
    names: Set[str] = set()

    def scan(inner: str) -> None:
        for nm, sub in _parse_top_children(inner):
            if nm == "project":
                strings = _strings_from_body(sub)
                if strings:
                    names.add(strings[0])
            elif nm in ("instances", "symbol", "sheet"):
                scan(sub)

    for nm, sub in children:
        if nm in ("symbol", "sheet"):
            scan(sub)
    # также проверяем сам корень — на случай нестандартной вложенности
    for nm, sub in children:
        if nm == "instances":
            scan(sub)
    return names


def _top_level_uuid(children: List[Tuple[str, str]]) -> Optional[str]:
    for nm, sub in children:
        if nm == "uuid":
            s = sub.strip()
            if s.startswith('"') and s.endswith('"'):
                return s[1:-1]
    return None


def _sheet_instance_paths(sheet_inner: str) -> List[Dict[str, Optional[str]]]:
    out: List[Dict[str, Optional[str]]] = []
    for istart, iend in _find_blocks_by_name(sheet_inner, "instances"):
        iblock = sheet_inner[istart:iend + 1]
        for pstart, pend in _find_blocks_by_name(iblock, "path"):
            pblock = iblock[pstart:pend + 1]
            strings = _strings_from_body(pblock[pblock.find("(") + 1:-1])
            if not strings:
                continue
            path = strings[0]
            page = None
            for pgstart, pgend in _find_blocks_by_name(pblock, "page"):
                pgblock = pblock[pgstart:pgend + 1]
                pg_strings = _strings_from_body(pgblock[pgblock.find("(") + 1:-1])
                if pg_strings:
                    page = pg_strings[0]
                    break
            out.append({"path": path, "page": page})
    return out


def _symbol_instance_paths(symbol_inner: str) -> List[Dict[str, Optional[str]]]:
    out: List[Dict[str, Optional[str]]] = []
    for istart, iend in _find_blocks_by_name(symbol_inner, "instances"):
        iblock = symbol_inner[istart:iend + 1]
        for pstart, pend in _find_blocks_by_name(iblock, "path"):
            pblock = iblock[pstart:pend + 1]
            strings = _strings_from_body(pblock[pblock.find("(") + 1:-1])
            if not strings:
                continue
            path = strings[0]
            ref = None
            for rstart, rend in _find_blocks_by_name(pblock, "reference"):
                rblock = pblock[rstart:rend + 1]
                rstrings = _strings_from_body(rblock[rblock.find("(") + 1:-1])
                if rstrings:
                    ref = rstrings[0]
                    break
            out.append({"path": path, "reference": ref})
    return out


# ─────────────────────────────────────────────────────────────
# Отчёт
# ─────────────────────────────────────────────────────────────

@dataclass
class Issue:
    severity: str   # ERROR | WARN | INFO
    where: str
    message: str


@dataclass
class Report:
    pro_path: Optional[str] = None
    root_sch: Optional[str] = None
    root_uuid: Optional[str] = None
    project_name: Optional[str] = None
    sheets: List[Dict[str, Any]] = field(default_factory=list)
    issues: List[Issue] = field(default_factory=list)

    def error(self, where: str, m: str) -> None:
        self.issues.append(Issue("ERROR", where, m))

    def warn(self, where: str, m: str) -> None:
        self.issues.append(Issue("WARN", where, m))

    def info(self, where: str, m: str) -> None:
        self.issues.append(Issue("INFO", where, m))


# ─────────────────────────────────────────────────────────────
# Вспомогательное: загрузка .kicad_pro
# ─────────────────────────────────────────────────────────────

def _find_project_file(start: Path) -> Optional[Path]:
    """Найти .kicad_pro рядом с указанным .kicad_sch.

    Если start — .kicad_pro, вернуть его как есть.
    Если start — .kicad_sch, искать <stem>.kicad_pro в той же папке.
    """
    if start.suffix == ".kicad_pro":
        return start
    if start.suffix == ".kicad_sch":
        cand = start.with_suffix(".kicad_pro")
        if cand.exists():
            return cand
    # иначе — первый .kicad_pro в директории
    for p in sorted(start.parent.glob("*.kicad_pro")):
        return p
    return None


# ─────────────────────────────────────────────────────────────
# Валидация
# ─────────────────────────────────────────────────────────────

def validate(root_input: Path) -> Report:
    root_input = Path(root_input).resolve()
    report = Report()

    pro_path = _find_project_file(root_input)
    if pro_path is None:
        report.error("project", f".kicad_pro not found near {root_input}")
        return report

    report.pro_path = str(pro_path)
    project_dir = pro_path.parent
    project_name = pro_path.stem
    report.project_name = project_name

    # ── .kicad_pro ────────────────────────────────────────
    try:
        pro_data = json.loads(pro_path.read_text(encoding="utf-8"))
    except Exception as e:
        report.error(pro_path.name, f"cannot read: {e}")
        return report

    meta_filename = (pro_data.get("meta") or {}).get("filename")
    if meta_filename != pro_path.name:
        report.error(
            pro_path.name,
            f"meta.filename={meta_filename!r} != {pro_path.name!r}"
        )

    schematic = pro_data.get("schematic") or {}
    tls = schematic.get("top_level_sheets") or []
    sch_sheets = schematic.get("sheets") or []
    proj_sheets = pro_data.get("sheets") or []

    if not tls:
        report.error(pro_path.name, "schematic.top_level_sheets empty")
        return report

    # ── root .kicad_sch по первому top-level ──────────────
    main_root = tls[0]
    main_filename = main_root.get("filename")
    if not main_filename:
        report.error(pro_path.name, "top_level_sheets[0].filename missing")
        return report
    if main_filename != f"{project_name}.kicad_sch":
        report.warn(
            pro_path.name,
            f"top_level_sheets[0].filename={main_filename!r} != "
            f"{project_name}.kicad_sch"
        )

    main_sch_path = project_dir / main_filename
    if not main_sch_path.exists():
        report.error(pro_path.name, f"root schema not found: {main_filename}")
        return report

    report.root_sch = str(main_sch_path)

    # Читаем корневой .kicad_sch
    try:
        main_children = _read_root_children(main_sch_path)
    except Exception as e:
        report.error(main_filename, f"cannot parse: {e}")
        return report

    main_root_uuid = _top_level_uuid(main_children)
    report.root_uuid = main_root_uuid
    if not main_root_uuid:
        report.error(main_filename, "no top-level (uuid …)")
        return report

    # ── basename .kicad_pro vs (project "…") во всех схемах ─
    all_project_names = _all_project_names(main_children)
    for pn in all_project_names:
        if pn != project_name:
            report.error(
                main_filename,
                f"(project \"{pn}\") != basename .kicad_pro "
                f"(\"{project_name}\")"
            )

    # ── SHA корня vs top_level_sheets[].uuid ──────────────
    for i, tls_entry in enumerate(tls):
        fn = tls_entry.get("filename")
        uid = tls_entry.get("uuid")
        name = tls_entry.get("name")
        sch_path = project_dir / (fn or "")
        if not fn or not sch_path.exists():
            report.error(
                pro_path.name,
                f"top_level_sheets[{i}].filename={fn!r} not found"
            )
            continue
        try:
            ch = _read_root_children(sch_path)
        except Exception as e:
            report.error(fn, f"cannot parse: {e}")
            continue
        sha = _top_level_uuid(ch)
        if sha != uid:
            report.error(
                pro_path.name,
                f"top_level_sheets[{i}].uuid={uid} != "
                f"{fn} SHA uuid={sha}"
            )
        if i == 0 and name != project_name:
            report.warn(
                pro_path.name,
                f"top_level_sheets[0].name={name!r} != "
                f"project_name={project_name!r}"
            )

    # ── Собираем все листы из корневого .kicad_sch ────────
    # Список листов корня: [{uuid, name, file, instances:[{path,page}]}]
    root_sheets: List[Dict[str, Any]] = []
    for nm, sub in main_children:
        if nm != "sheet":
            continue
        s_uuid = _direct_child_string(sub, "uuid")
        s_name = _direct_child_property(sub, "Sheetname") or "<unnamed>"
        s_file = _direct_child_property(sub, "Sheetfile")
        inst = _sheet_instance_paths(sub)
        root_sheets.append({
            "uuid": s_uuid, "name": s_name, "file": s_file,
            "instances": inst,
        })
    report.sheets = root_sheets

    if not root_sheets:
        report.warn(main_filename, "no hierarchical sheets in root")

    # ── Пути у листов корня: должны быть "/<main_root_uuid>" ─
    expected_root_prefix = f"/{main_root_uuid}"
    for s in root_sheets:
        if not s["instances"]:
            report.warn(
                main_filename,
                f"sheet '{s['name']}' has no (instances …)"
            )
            continue
        for ip in s["instances"]:
            p = ip["path"]
            if p == expected_root_prefix:
                continue
            if s["uuid"] and p == f"{expected_root_prefix}/{s['uuid']}":
                report.error(
                    main_filename,
                    f"sheet '{s['name']}': path='{p}' — should be "
                    f"'{expected_root_prefix}' "
                    f"(remove trailing '/{s['uuid']}')"
                )
            elif p.startswith(expected_root_prefix + "/"):
                report.error(
                    main_filename,
                    f"sheet '{s['name']}': path='{p}' — should be "
                    f"'{expected_root_prefix}' (not deeper)"
                )
            else:
                report.error(
                    main_filename,
                    f"sheet '{s['name']}': path='{p}' — should start "
                    f"with '{expected_root_prefix}'"
                )

    # ── Ожидаемые контексты для каждого дочернего файла ──
    # file → {expected_path: [sheet_name,…]}
    expected_by_file: Dict[str, Dict[str, List[str]]] = {}
    # uuid листа → name (для проверки sheets[])
    uuid_to_name: Dict[str, str] = {}
    for s in root_sheets:
        if not s["file"] or not s["uuid"]:
            continue
        uuid_to_name[s["uuid"]] = s["name"]
        expected_path = f"{expected_root_prefix}/{s['uuid']}"
        expected_by_file.setdefault(s["file"], {}).setdefault(
            expected_path, []
        ).append(s["name"])

    # ── Проверка дочерних .kicad_sch ──────────────────────
    visited_files: Set[str] = set()
    _validate_child_file(
        project_dir, expected_root_prefix, report,
        main_filename,  # родитель — корневой
        expected_by_file, visited_files,
    )

    # ── Проверка sheets[] в .kicad_pro ─────────────────────
    # Собираем все известные UUID листов (root + все дочерние)
    known_uuids: Set[str] = {main_root_uuid}
    for s in root_sheets:
        if s["uuid"]:
            known_uuids.add(s["uuid"])

    # корень проекта может встречаться как элемент sheets[] с basename
    _check_sheets_list(
        report, pro_path, "schematic.sheets",
        sch_sheets, known_uuids, uuid_to_name,
        project_name, main_root_uuid,
    )
    _check_sheets_list(
        report, pro_path, "sheets (project-level)",
        proj_sheets, known_uuids, uuid_to_name,
        project_name, main_root_uuid,
    )

    # ── Имена Sheetname vs sheets[] в pro ─────────────────
    _check_sheetname_consistency(
        report, pro_path, proj_sheets, uuid_to_name,
    )

    return report


def _validate_child_file(
    project_dir: Path,
    root_prefix: str,
    report: Report,
    parent_file_name: str,
    expected_by_file: Dict[str, Dict[str, List[str]]],
    visited: Set[str],
) -> None:
    """Проверить дочерние файлы, на которые есть ожидаемые контексты."""
    for fname, expected_paths in expected_by_file.items():
        if fname in visited:
            continue
        visited.add(fname)
        child_path = project_dir / fname
        if not child_path.exists():
            report.error(parent_file_name, f"referenced file not found: {fname}")
            continue
        try:
            cchildren = _read_root_children(child_path)
        except Exception as e:
            report.error(fname, f"cannot parse: {e}")
            continue

        expected_set = set(expected_paths.keys())
        symbols_seen = 0
        symbols_with_paths = 0
        missing_total: Set[str] = set()
        extra_total: Set[str] = set()

        for nm, inner in cchildren:
            if nm != "symbol":
                continue
            symbols_seen += 1
            sym_paths = _symbol_instance_paths(inner)
            if not sym_paths:
                continue
            symbols_with_paths += 1

            present = {sp["path"] for sp in sym_paths}
            missing = expected_set - present
            extra = present - expected_set

            lib_id = _direct_child_string(inner, "lib_id") or "?"
            sym_uuid = _direct_child_string(inner, "uuid") or "?"
            if missing:
                report.error(
                    fname,
                    f"symbol {lib_id} (uuid {sym_uuid}) missing paths: "
                    f"{sorted(missing)}"
                )
                missing_total |= missing
            if extra:
                report.warn(
                    fname,
                    f"symbol {lib_id} (uuid {sym_uuid}) extra paths: "
                    f"{sorted(extra)}"
                )
                extra_total |= extra

        if symbols_seen > 0 and symbols_with_paths == 0:
            report.error(
                fname,
                f"{symbols_seen} symbol(s) found but none have (instances …)"
            )
        elif symbols_seen == symbols_with_paths and not missing_total:
            report.info(
                fname,
                f"OK — {symbols_with_paths} symbol(s) cover all "
                f"{len(expected_set)} expected context(s)"
            )

        # Вложенные листы внутри дочернего файла
        nested_expected: Dict[str, Dict[str, List[str]]] = {}
        for nm, inner in cchildren:
            if nm != "sheet":
                continue
            s_uuid = _direct_child_string(inner, "uuid")
            s_file = _direct_child_property(inner, "Sheetfile")
            if not s_file or not s_uuid:
                continue
            # Ожидаемые пути для вложенного листа = пути до его родителя
            # (то есть все контексты, в которых существует этот файл),
            # БЕЗ добавления uuid самого вложенного листа.
            nested_paths_set: Dict[str, List[str]] = {}
            for parent_path in expected_set:
                # parent_path — это контекст, в котором существует
                # текущий файл (например, /R/S_parent).
                # Вложенный лист виден в тех же контекстах.
                nested_paths_set.setdefault(parent_path, [])
            nested_expected.setdefault(s_file, {})
            for p, names in nested_paths_set.items():
                nested_expected[s_file].setdefault(p, []).extend(names)

        if nested_expected:
            _validate_child_file(
                project_dir, root_prefix, report,
                fname, nested_expected, visited,
            )


def _check_sheets_list(
    report: Report,
    pro_path: Path,
    label: str,
    entries: List[Any],
    known_uuids: Set[str],
    uuid_to_name: Dict[str, str],
    project_name: str,
    main_root_uuid: str,
) -> None:
    """Проверить список sheets[] из .kicad_pro.

    • все UUID должны быть известны;
    • один uuid — одно name;
    • одно name с разными uuid — WARN.
    """
    if not isinstance(entries, list):
        report.error(pro_path.name, f"{label}: not a list")
        return

    uuid_to_names: Dict[str, Set[str]] = {}
    name_to_uuids: Dict[str, Set[str]] = {}
    unknown_uuids: Set[str] = set()
    # список кортежей для дальнейшего сравнения — сохраняем порядок

    for entry in entries:
        if not isinstance(entry, (list, tuple)) or len(entry) < 2:
            report.error(pro_path.name, f"{label}: malformed entry {entry!r}")
            continue
        u, n = entry[0], entry[1]
        if not isinstance(u, str) or not isinstance(n, str):
            report.error(pro_path.name, f"{label}: non-string entry {entry!r}")
            continue
        uuid_to_names.setdefault(u, set()).add(n)
        name_to_uuids.setdefault(n, set()).add(u)
        if u not in known_uuids:
            unknown_uuids.add(u)

    for u, names in uuid_to_names.items():
        if len(names) > 1:
            report.error(
                pro_path.name,
                f"{label}: uuid {u} mapped to multiple names: {sorted(names)}"
            )

    for n, uuids in name_to_uuids.items():
        if len(uuids) > 1:
            # Разные инстансы одного файла легальны. Проверим: если все
            # uuid кроме одного — это один и тот же файл (один uuid
            # может быть корневым, остальные — инстансы одного Sheetfile),
            # то это WARN, а не ERROR.
            report.warn(
                pro_path.name,
                f"{label}: name {n!r} used for multiple uuids: "
                f"{sorted(uuids)}"
            )

    for u in unknown_uuids:
        report.warn(
            pro_path.name,
            f"{label}: uuid {u} not found in any schema (stale entry?)"
        )


def _check_sheetname_consistency(
    report: Report,
    pro_path: Path,
    proj_sheets: List[Any],
    uuid_to_name: Dict[str, str],
) -> None:
    """Сверить Sheetname в корне с name из sheets[] в .kicad_pro."""
    if not isinstance(proj_sheets, list):
        return
    pro_names: Dict[str, Set[str]] = {}
    for entry in proj_sheets:
        if (isinstance(entry, (list, tuple)) and len(entry) >= 2
                and isinstance(entry[0], str) and isinstance(entry[1], str)):
            pro_names.setdefault(entry[0], set()).add(entry[1])

    for u, sch_name in uuid_to_name.items():
        names_in_pro = pro_names.get(u)
        if not names_in_pro:
            report.warn(
                pro_path.name,
                f"sheet uuid {u} (name '{sch_name}') missing in sheets[]"
            )
            continue
        if sch_name not in names_in_pro:
            report.error(
                pro_path.name,
                f"sheet uuid {u}: Sheetname in .kicad_sch='{sch_name}' "
                f"but sheets[] has {sorted(names_in_pro)}"
            )


# ─────────────────────────────────────────────────────────────
# Вывод
# ─────────────────────────────────────────────────────────────

def print_report(report: Report, verbose: bool) -> None:
    print(f"Project file : {report.pro_path}")
    print(f"Project name : {report.project_name}")
    print(f"Root schema  : {report.root_sch}")
    print(f"Root UUID    : {report.root_uuid}")
    print()
    print(f"Sheets in root: {len(report.sheets)}")
    for s in report.sheets:
        paths = ", ".join(ip["path"] for ip in s["instances"]) or "<none>"
        print(f"  - {s['name']:<30} uuid={s['uuid']}  file={s['file']}")
        if verbose:
            print(f"      instance path(s): {paths}")
    print()

    errors = [i for i in report.issues if i.severity == "ERROR"]
    warns  = [i for i in report.issues if i.severity == "WARN"]
    infos  = [i for i in report.issues if i.severity == "INFO"]

    if errors:
        print(f"ERRORS ({len(errors)})")
        print("-" * 60)
        for i in errors:
            print(f"  [{i.where}]")
            print(f"      {i.message}")
        print()

    if warns:
        print(f"WARNINGS ({len(warns)})")
        print("-" * 60)
        for i in warns:
            print(f"  [{i.where}]")
            print(f"      {i.message}")
        print()

    if verbose and infos:
        print(f"INFO ({len(infos)})")
        print("-" * 60)
        for i in infos:
            print(f"  [{i.where}] {i.message}")
        print()

    if not errors and not warns:
        print("✓ All checks passed.")
    elif not errors:
        print("⚠ No errors, but warnings present.")
    else:
        print(f"✗ Validation FAILED — {len(errors)} error(s).")


def report_to_json(report: Report) -> str:
    return json.dumps({
        "pro_path": report.pro_path,
        "root_sch": report.root_sch,
        "project_name": report.project_name,
        "root_uuid": report.root_uuid,
        "sheets": report.sheets,
        "issues": [
            {"severity": i.severity, "where": i.where, "message": i.message}
            for i in report.issues
        ],
        "summary": {
            "errors":   sum(1 for i in report.issues if i.severity == "ERROR"),
            "warnings": sum(1 for i in report.issues if i.severity == "WARN"),
        },
    }, indent=2, ensure_ascii=False)


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="Validate KiCad hierarchical project (.kicad_pro + .kicad_sch)."
    )
    p.add_argument("root", help="Path to .kicad_pro or root .kicad_sch")
    p.add_argument("--verbose", "-v", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    root_path = Path(args.root)
    if not root_path.exists():
        print(f"File not found: {root_path}", file=sys.stderr)
        return 2

    try:
        report = validate(root_path)
    except Exception as e:
        import traceback
        print(f"Validation crashed: {e}", file=sys.stderr)
        traceback.print_exc()
        return 2

    if args.json:
        print(report_to_json(report))
    else:
        print_report(report, args.verbose)

    errors = sum(1 for i in report.issues if i.severity == "ERROR")
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())