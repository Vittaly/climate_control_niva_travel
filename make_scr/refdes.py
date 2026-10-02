# refdes.py
"""Формирование проектных refdes из локального имени и номера страницы.

Формат (KiCad-валидный: буквенный префикс + цифры):
    refdes = <type_prefix> + page.zfill(W_P) + local_num.zfill(W_L)

Примеры:
    U1, page=1   → U0101
    U1, page=11  → U1101
    R55, page=11 → R1155
    LED32, page=5 → LED0532

Имена без числового суффикса (например, синтетические) возвращаются
как есть — верхний уровень сам должен гарантировать уникальность.
"""
import re

_W_P = 2   # цифр на page
_W_L = 2   # цифр на local

_REFDES_RE = re.compile(r"^([A-Za-z]+)(\d+)$")


def make_refdes(local: str, page: int) -> str:
    """Локальное имя + номер страницы → проектное имя."""
    m = _REFDES_RE.match(local)
    if not m:
        return local
    prefix, num = m.group(1), int(m.group(2))
    return f"{prefix}{page:0{_W_P}d}{num:0{_W_L}d}"


def parse_refdes(refdes: str) -> tuple[str, int, int] | None:
    """U1101 → ("U", 11, 1). None, если формат не наш."""
    m = _REFDES_RE.match(refdes)
    if not m:
        return None
    prefix, digits = m.group(1), m.group(2)
    if len(digits) != _W_P + _W_L:
        return None
    return prefix, int(digits[:_W_P]), int(digits[_W_P:])