#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
patch_writer_sheets.py — добавляет в writer.py запись вложенных листов
(X_* с symbol=Core:Hierarchical_Sheet) и sheet_pin-ов на них.

Что делает:
    1. Находит метод write_sheet в классе Writer.
    2. Вставляет блок add_sheet + блок sheet_pin сразу после цикла
       по компонентам (после "обычных компонентов и портов").
    3. В конец класса Writer вставляет методы _sheet_size_mm
       и _add_sheet_pins.
    4. Делает writer.py.bak.
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path


MARK_BLOCK = "# --- SHEET-PATCH: write_sheet block ---"
MARK_METHODS = "# --- SHEET-PATCH: methods ---"


def die(msg: str) -> None:
    print(f"ОШИБКА: {msg}", file=sys.stderr)
    sys.exit(1)


# =========================================================
# Блок для вставки в write_sheet
# =========================================================

SHEET_BLOCK = f'''
        {MARK_BLOCK}
        # ---------- Вложенные листы (X_*) ----------
        sheet_objs = {{}}
        for designator, cdef in sheet.data.get("components", {{}}).items():
            if cdef.get("symbol") != "Core:Hierarchical_Sheet":
                continue
            pos = (sheet.placer.positions.get(designator)
                   if sheet.placer else None)
            if pos is None:
                log.warning("[%s] лист %s: нет позиции, пропускаю",
                            label, designator)
                continue
            x_mm, y_mm = self.cell_to_mm(pos)

            w_mm, h_mm = self._sheet_size_mm(sheet, cdef)
            filename = cdef.get(
                "value_sch",
                cdef.get("value",
                         f"schematics/{{designator.lower()}}.kicad_sch"),
            )
            try:
                sobj = sch.add_sheet(
                    name=designator,
                    filename=filename,
                    position=(x_mm, y_mm),
                    size=(w_mm, h_mm),
                )
                sheet_objs[designator] = (
                    sobj, (x_mm, y_mm, w_mm, h_mm), cdef)
                n_sheets += 1
            except Exception as e:
                log.error("[%s] add_sheet %s: %s",
                          label, designator, e)

        # ---------- Sheet pins ----------
        for designator, (sobj, rect, cdef) in sheet_objs.items():
            n_sheet_pins += self._add_sheet_pins(
                sch, sobj, rect, cdef, sheet, label)
        # --- конец SHEET-PATCH блока ---
'''


# =========================================================
# Методы для вставки в конец класса Writer
# =========================================================

METHODS_BLOCK = f'''
    {MARK_METHODS}
    # =========================================================
    # Вложенные листы
    # =========================================================

    def _sheet_size_mm(self, parent_sheet, cdef: dict) -> tuple[float, float]:
        """Размер .kicad_sch листа (мм) по числу портов дочернего YAML.

        Ширина — под длинное имя порта; высота — по числу портов.
        """
        from pathlib import Path as _P
        import yaml as _yaml

        yaml_file = cdef.get("value", "")
        sub_data = {{}}
        try:
            p = _P(parent_sheet.yaml_path).parent / yaml_file
            sub_data = _yaml.safe_load(p.read_text(encoding="utf-8")) or {{}}
        except Exception as e:
            log.warning("sheet_size: не прочитал %s: %s", yaml_file, e)

        ports = sub_data.get("ports", []) or []
        n = len(ports)
        label_max = max(
            (len(str(p.get("net_label", ""))) for p in ports),
            default=8,
        )

        w_mm = max(30.0, 12.0 + label_max * 1.27)
        rows = max(4, n + 2)
        h_mm = rows * 2.54
        return (w_mm, h_mm)

    def _add_sheet_pins(self, sch, sobj, rect, cdef,
                        parent_sheet, label: str) -> int:
        """Добавляет sheet_pin-ы на рамку листа по его портам."""
        from pathlib import Path as _P
        import yaml as _yaml

        x_mm, y_mm, w_mm, h_mm = rect

        uid = (getattr(sobj, "uuid", None)
               or getattr(sobj, "id", None))
        if uid is None and isinstance(sobj, str):
            uid = sobj
        if uid is None:
            log.warning("[%s] sheet_pin: нет UUID для %s",
                        label, cdef.get("description", "?"))
            return 0

        yaml_file = cdef.get("value", "")
        sub = {{}}
        try:
            p = _P(parent_sheet.yaml_path).parent / yaml_file
            sub = _yaml.safe_load(p.read_text(encoding="utf-8")) or {{}}
        except Exception as e:
            log.warning("[%s] sheet_pin: не прочитал %s: %s",
                        label, yaml_file, e)
            return 0

        ports = sub.get("ports", []) or []
        if not ports:
            return 0

        left = sorted(
            [p for p in ports
             if str(p.get("type", "INPUT")).upper() not in ("OUTPUT",)],
            key=lambda p: p.get("net_label", ""),
        )
        right = sorted(
            [p for p in ports
             if str(p.get("type", "INPUT")).upper() == "OUTPUT"],
            key=lambda p: p.get("net_label", ""),
        )

        grid_mm = self.cell_size_mm
        n_added = 0

        for side, items in (("left", left), ("right", right)):
            for i, p in enumerate(items):
                net = p.get("net_label", "")
                if not net:
                    continue
                ptype = str(p.get("type", "INPUT")).upper()
                shape = ("passive" if ptype == "POWER"
                         else "output" if ptype == "OUTPUT"
                         else "input")
                py = y_mm + 5 * grid_mm + i * 2 * grid_mm
                if py > y_mm + h_mm - 2 * grid_mm:
                    log.warning("[%s] sheet_pin %s.%s: не влез",
                                label, cdef.get("description"), net)
                    continue
                offset = ((y_mm + h_mm) - py) if side == "left" \\
                    else (py - y_mm)

                mgr = getattr(sch, "sheets", None)
                fn = None
                if mgr is not None and hasattr(mgr, "add_sheet_pin"):
                    fn = mgr.add_sheet_pin
                elif hasattr(sch, "add_sheet_pin"):
                    fn = sch.add_sheet_pin
                if fn is None:
                    log.warning("[%s] sheet_pin: нет add_sheet_pin",
                                label)
                    return n_added
                try:
                    fn(uid, net, shape, side, offset)
                    n_added += 1
                except Exception as e:
                    log.warning("[%s] sheet_pin %s.%s: %s",
                                label, cdef.get("description"), net, e)

        return n_added
    # --- конец SHEET-PATCH методов ---
'''


# =========================================================
# Патч
# =========================================================

def find_method(text: str, name: str, cls_start: int = 0) -> int:
    """Находит начало метода def name( после cls_start."""
    m = re.search(rf"^(\s*)def\s+{re.escape(name)}\s*\(",
                  text[cls_start:], flags=re.MULTILINE)
    return cls_start + m.start() if m else -1


def find_method_end(text: str, start: int, base_indent: str) -> int:
    """Возвращает индекс начала следующей строки с отступом <= base_indent
    или len(text), если метод последний."""
    for m in re.finditer(rf"^{base_indent}(?=\S)",
                         text[start:], flags=re.MULTILINE):
        return start + m.start()
    return len(text)


def find_class(text: str, name: str) -> tuple[int, int]:
    """(start, end) класса с данным именем."""
    m = re.search(rf"^class\s+{re.escape(name)}\b.*?:\s*\n",
                  text, flags=re.MULTILINE | re.DOTALL)
    if not m:
        return -1, -1
    start = m.start()
    # конец класса — первая строка с отступом 0 (не пустая)
    for m2 in re.finditer(r"^\S", text[m.end():], flags=re.MULTILINE):
        return start, m.end() + m2.start()
    return start, len(text)


def patch(path: Path) -> None:
    if not path.exists():
        die(f"{path.name} не найден")

    text = path.read_text(encoding="utf-8")

    if MARK_BLOCK in text or MARK_METHODS in text:
        print("writer.py уже пропатчен — пропускаю")
        return

    # --- ищем класс Writer ---
    cls_start, cls_end = find_class(text, "Writer")
    if cls_start < 0:
        die("класс Writer не найден в writer.py")

    # --- ищем метод write_sheet внутри Writer ---
    ws_pos = find_method(text, "write_sheet", cls_start)
    if ws_pos < 0 or ws_pos > cls_end:
        die("метод write_sheet не найден в классе Writer")

    # отступ метода
    line_start = text.rfind("\n", 0, ws_pos) + 1
    base_indent = re.match(r"\s*", text[line_start:]).group(0)

    # --- ищем конец цикла по компонентам внутри write_sheet ---
    # ориентир: последний sch.components.add(...) внутри write_sheet
    ws_end = find_method_end(text, ws_pos, base_indent)
    ws_body = text[ws_pos:ws_end]

    # ищем последний components.add внутри метода
    m_add = None
    for m_add in re.finditer(r"sch\.components\.add\s*\(", ws_body):
        pass
    if m_add is None:
        die("не найден sch.components.add в write_sheet")

    # конец строки с этим вызовом + все последующие строки того же блока
    # (закрывающая скобка + except)
    add_pos = ws_pos + m_add.end()
    # найдём конец блока try/except после этого вызова:
    # ищем "except" после add_pos до ws_end
    m_exc = re.search(r"^\s*except\b",
                      text[add_pos:ws_end], flags=re.MULTILINE)
    if not m_exc:
        # нет try/except — вставим сразу после add-вызова,
        # найдя конец строки
        nl = text.find("\n", add_pos)
        insert_at = nl + 1
    else:
        # ищем конец блока except (первую строку с меньшим отступом)
        exc_pos = add_pos + m_exc.start()
        exc_line_start = text.rfind("\n", 0, exc_pos) + 1
        exc_indent = re.match(r"\s*", text[exc_line_start:]).group(0)
        # конец блока except — следующая строка с отступом <= exc_indent
        exc_end = find_method_end(text, exc_line_start, exc_indent)
        insert_at = exc_end

    # --- вставляем SHEET_BLOCK с правильным отступом ---
    body_indent = base_indent + "    "  # отступ тела метода (4)
    block = "\n".join(
        (body_indent + ln[8:]) if ln.startswith(" " * 8) else ln
        for ln in SHEET_BLOCK.splitlines()
    )
    text = text[:insert_at] + block + "\n" + text[insert_at:]

    # --- вставляем METHODS_BLOCK в конец класса Writer ---
    # пересчитываем cls_end после вставки
    cls_start, cls_end = find_class(text, "Writer")
    # вставляем перед закрывающей границей класса
    # (перед первой строкой с отступом 0 после класса)
    methods = "\n".join(
        ("    " + ln[4:]) if ln.startswith("    ") else ln
        for ln in METHODS_BLOCK.splitlines()
    )
    text = text[:cls_end] + methods + "\n" + text[cls_end:]

    # --- добавляем импорты (если нет) ---
    if "import yaml as _yaml" not in text:
        # добавляем после последнего import в шапке
        m_imp = None
        for m_imp in re.finditer(r"^(?:from|import)\s+\S+.*$",
                                 text, flags=re.MULTILINE):
            pass
        if m_imp:
            insert = m_imp.end()
            text = (text[:insert] + "\nimport yaml as _yaml"
                    + text[insert:])

    # --- сохраняем ---
    bak = path.with_suffix(path.suffix + ".bak")
    if not bak.exists():
        shutil.copy2(path, bak)
        print(f"[backup] {path.name} -> {bak.name}")
    path.write_text(text, encoding="utf-8")
    print(f"[writer] {path.name}: добавлены блок add_sheet и методы")


# =========================================================
# main
# =========================================================

def main() -> None:
    root = Path.cwd()
    target = root / "writer.py"
    if not target.exists():
        die(f"writer.py не найден в {root}")

    patch(target)

    print()
    print("=" * 60)
    print("Готово. Проверь:")
    print("  python -c 'import writer; print(\"writer ok\")'")
    print("  diff writer.py.bak writer.py")
    print("=" * 60)


if __name__ == "__main__":
    main()