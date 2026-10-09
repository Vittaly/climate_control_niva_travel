# writer_instances_fix.py
"""Постобработка .kicad_sch после sch.save():

1) merge_project_instances_file(path) — слияние повторных
   (project "X" ...) блоков в один с общим списком путей.

2) fix_sheet_instance_paths_file(path) — дописать uuid листа вторым
   сегментом instance path у (sheet ...) в главном файле.

─────────────────────────────────────────────────────────────
1. Слияние (project ...) блоков
─────────────────────────────────────────────────────────────

Проблема:
    kicad_sch_api пишет по одному (project "…") на каждый instance:

        (instances
          (project "p" (path "/a" (reference "R1") (unit 1)))
          (project "p" (path "/b" (reference "R2") (unit 1)))
          (project "p" (path "/c" (reference "R3") (unit 1))))

    KiCad 8+ ожидает один (project "…") со списком путей:

        (instances
          (project "p"
            (path "/a" (reference "R1") (unit 1))
            (path "/b" (reference "R2") (unit 1))
            (path "/c" (reference "R3") (unit 1))))

    При неверном формате KiCad берёт первый попавшийся project, и
    переключение контекстов (переключение между X_*) не меняет
    reference символа.

─────────────────────────────────────────────────────────────
2. Дописать uuid листа в instance path у (sheet ...)
─────────────────────────────────────────────────────────────

Проблема:
    kicad_sch_api при sch.save() пишет (sheet (instances) (project "…"
    (path "/<root>" (page "N")))) — только корневой сегмент.

    KiCad 7+ ожидает для листа, лежащего внутри страницы, полный
    путь до листа: /<root>/<sheet-uuid>. Именно такой префикс
    стоит у символов внутри дочернего .kicad_sch. Если в главном
    файле путь укорочен — KiCad не находит нужный инстанс
    символа в дочернем файле и показывает первый попавшийся
    Reference всем экземплярам листа.

Решение:
    Проходим по всем (sheet ...) блокам. Для каждого:
      1. читаем его (uuid "X");
      2. внутри его же (instances …) каждое (path "P" заменяем
         на (path "P/X", если /X там ещё нет.
    Идемпотентно.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional, Tuple


# ─────────────────────────────────────────────────────────────
# Примитивы разбора s-expr
# ─────────────────────────────────────────────────────────────

def _find_matching_paren(s: str, open_idx: int) -> int:
    """Индекс ')' парной для s[open_idx]=='('.

    Учитывает строки в двойных кавычках и экранирование \\".
    Возвращает -1, если парной нет.
    """
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
    """s[idx] == '('. Возвращает (имя_первого_атома, индекс_после_имени)."""
    i = idx + 1
    n = len(s)
    while i < n and s[i].isspace():
        i += 1
    start = i
    while i < n and not s[i].isspace() and s[i] not in "()":
        i += 1
    return s[start:i], i


def _find_blocks_by_name(s: str, name: str) -> List[Tuple[int, int]]:
    """Все блоки (name ...) на любом уровне вложенности.

    Учитывает строки в двойных кавычках — не путает скобки внутри
    строк с границами блоков.
    """
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


def _find_instances_blocks(s: str) -> List[Tuple[int, int]]:
    """Все (start, end) блоков (instances ...) на любом уровне вложенности."""
    return _find_blocks_by_name(s, "instances")


def _parse_top_children(body: str) -> List[Tuple[str, str]]:
    """body — содержимое внутри (...) (без внешних скобок).

    Возвращает список (name, inner_body) для всех верхнеуровневых
    (... ...) внутри body.
    """
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
        inner = body[after_name:end]
        children.append((name, inner))
        i = end + 1
    return children


def _parse_project_name(inner: str) -> Tuple[str, str]:
    """inner — содержимое (project "name" ...). Возвращает (name, rest)."""
    i = 0
    n = len(inner)
    while i < n and inner[i].isspace():
        i += 1
    if i >= n or inner[i] != '"':
        return "", inner
    i += 1
    start = i
    while i < n:
        c = inner[i]
        if c == "\\":
            i += 2
            continue
        if c == '"':
            break
        i += 1
    name = inner[start:i]
    rest = inner[i + 1:]
    return name, rest


def _collapse_ws(block: str) -> str:
    """Сжать многострочный блок в одну строку, сохранив содержимое строк."""
    out: List[str] = []
    i = 0
    n = len(block)
    prev_space = False
    in_str = False
    while i < n:
        c = block[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(block[i + 1])
                i += 2
                continue
            if c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
            out.append(c)
        elif c.isspace():
            if not prev_space and out:
                out.append(" ")
            prev_space = True
        else:
            out.append(c)
            prev_space = False
        i += 1
    return "".join(out).strip()


def _extract_path_blocks(inner: str) -> List[str]:
    """Вытащить все (path ...) блоки из inner как однострочные строки."""
    result: List[str] = []
    i = 0
    n = len(inner)
    while i < n:
        if inner[i] == "(":
            name, _ = _parse_head(inner, i)
            if name == "path":
                end = _find_matching_paren(inner, i)
                if end < 0:
                    break
                result.append(_collapse_ws(inner[i:end + 1]))
                i = end + 1
                continue
        i += 1
    return result


# ─────────────────────────────────────────────────────────────
# 1. Пересборка одного блока (instances ...) — слияние project
# ─────────────────────────────────────────────────────────────

def _rebuild_instances(block: str, indent: str) -> Optional[str]:
    """block — (instances ...) целиком. Возвращает пересобранный текст
    или None, если в блоке нет (project ...) — тогда не трогаем.

    indent — строка отступа (табы) под уровень (instances ...).
    """
    name, after_name = _parse_head(block, 0)
    if name != "instances":
        return None
    body = block[after_name:-1]  # без внешних скобок

    children = _parse_top_children(body)
    if not children:
        return None

    # Группируем project по имени; остальные сохраняем как есть
    groups: dict[str, List[str]] = {}
    order: List[str] = []
    other: List[Tuple[str, str]] = []

    for cname, cinner in children:
        if cname == "project":
            pname, rest = _parse_project_name(cinner)
            if pname not in groups:
                groups[pname] = []
                order.append(pname)
            groups[pname].extend(_extract_path_blocks(rest))
        else:
            other.append((cname, cinner))

    if not groups:
        return None

    lines: List[str] = []
    lines.append(f"{indent}(instances")
    for pname in order:
        lines.append(f'{indent}\t(project "{pname}"')
        for path_block in groups[pname]:
            lines.append(f"{indent}\t\t{path_block}")
        lines.append(f"{indent}\t)")
    for cname, cinner in other:
        lines.append(f"{indent}({cname}{cinner})")
    lines.append(f"{indent})")
    return "\n".join(lines)


def merge_project_instances_text(text: str) -> str:
    """Обработать весь текст .kicad_sch, слить project-блоки.

    Работает идемпотентно: если формат уже правильный, вернёт text.
    """
    blocks = _find_instances_blocks(text)
    if not blocks:
        return text

    out: List[str] = []
    prev_end = 0

    for start, end in blocks:
        line_start = text.rfind("\n", 0, start) + 1
        indent_str = text[line_start:start]
        indent = indent_str if indent_str.strip() == "" else ""

        block = text[start:end + 1]
        rebuilt = _rebuild_instances(block, indent)

        out.append(text[prev_end:start])
        if rebuilt is not None:
            out.append(rebuilt)
        else:
            out.append(block)
        prev_end = end + 1

    out.append(text[prev_end:])
    return "".join(out)


def merge_project_instances_file(path: Path) -> bool:
    """Прочитать файл, слить project-блоки, перезаписать.

    Возвращает True, если файл изменился.
    """
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False

    new_text = merge_project_instances_text(text)
    if new_text == text:
        return False

    try:
        path.write_text(new_text, encoding="utf-8")
    except OSError:
        return False

    return True


# ─────────────────────────────────────────────────────────────
# 2. Фикс instance path у (sheet ...) — дописать uuid листа
# ─────────────────────────────────────────────────────────────

def _append_sheet_uuid(m: "re.Match", sheet_uuid: str) -> str:
    """Заменитель для re.sub: (path "P" -> (path "P/<sheet_uuid>".

    Не трогает, если /<sheet_uuid> уже присутствует в P.
    """
    prefix = m.group(1)
    path = m.group(2)
    suffix = m.group(3)
    if path.endswith("/" + sheet_uuid):
        return m.group(0)
    if ("/" + sheet_uuid) in path:
        return m.group(0)
    return f"{prefix}{path}/{sheet_uuid}{suffix}"


def _fix_one_sheet_block(block: str) -> str:
    """В одном (sheet ...) блоке: взять uuid, дописать его ко всем
    (path "..." внутри его (instances ...).
    """
    m = re.search(r'\(uuid\s+"([^"]+)"\)', block)
    if not m:
        return block
    sheet_uuid = m.group(1)

    inst_blocks = _find_blocks_by_name(block, "instances")
    if not inst_blocks:
        return block

    out: List[str] = []
    prev = 0
    for istart, iend in inst_blocks:
        iblock = block[istart:iend + 1]
        fixed_iblock = re.sub(
            r'(\(path\s+")(/[^"]*)(")',
            lambda mm, _u=sheet_uuid: _append_sheet_uuid(mm, _u),
            iblock,
        )
        out.append(block[prev:istart])
        out.append(fixed_iblock)
        prev = iend + 1
    out.append(block[prev:])
    return "".join(out)


def fix_sheet_instance_paths_text(text: str) -> str:
    """Обработать весь текст .kicad_sch: в каждом (sheet ...) блоке
    дописать uuid листа ко всем (path "...") в его (instances …).

    Идемпотентно: если путь уже полный, вернёт text без изменений.
    """
    sheets = _find_blocks_by_name(text, "sheet")
    if not sheets:
        return text

    out: List[str] = []
    prev = 0
    for start, end in sheets:
        block = text[start:end + 1]
        fixed = _fix_one_sheet_block(block)
        out.append(text[prev:start])
        out.append(fixed)
        prev = end + 1
    out.append(text[prev:])
    return "".join(out)


def fix_sheet_instance_paths_file(path: Path) -> bool:
    """Прочитать файл, дописать uuid листа в (path …) у (sheet …),
    перезаписать.

    Возвращает True, если файл изменился.
    """
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False

    new_text = fix_sheet_instance_paths_text(text)
    if new_text == text:
        return False

    try:
        path.write_text(new_text, encoding="utf-8")
    except OSError:
        return False

    return True