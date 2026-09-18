# designators.py
"""Правила именования reference designator компонента на странице.

Инвариант: reference компонента — это <1..4 латинских буквы><номер>.
Кириллица, '_', '-', '.', пробелы, имя без номера — недопустимы.
Именно поэтому KiCad отвергает C_VM, R_TOP, R_ILIM, R_BOT, C_FB
(см. лог writer: 'Invalid reference format').

Порты (PORT_*) — НЕ компоненты. Они пишутся как иерархические метки
и живут в отдельном классе; Component такого имени иметь не может.
"""
from __future__ import annotations

import re

# KiCad reference: 1..4 латинских буквы + минимум одна цифра.
REF_RE = re.compile(r"^[A-Za-z]{1,4}[0-9]+$")

# Всё, что не ASCII-буква/цифра, в reference недопустимо.
BAD_CHAR_RE = re.compile(r"[^A-Za-z0-9]")


class DesignatorError(ValueError):
    """Недопустимый reference designator компонента."""


def validate_component_designator(
    designator: str, *, page: str | None = None
) -> str:
    """Проверяет reference компонента. Возвращает designator.

    Raises:
        DesignatorError: если имя не KiCad-совместимо.
    """
    where = f"[{page}] " if page else ""

    if not isinstance(designator, str) or not designator:
        raise DesignatorError(
            f"{where}designator должен быть непустой строкой, "
            f"получено {designator!r}"
        )

    bad = BAD_CHAR_RE.findall(designator)
    if bad:
        raise DesignatorError(
            f"{where}недопустимый designator {designator!r}: "
            f"символы {bad!r}. KiCad допускает только латинские буквы "
            f"и цифры, например C1, R2, U3, но не C_VM, R_TOP, R_ILIM."
        )

    if not REF_RE.match(designator):
        raise DesignatorError(
            f"{where}designator {designator!r} не соответствует формату "
            f"KiCad reference: 1..4 латинских буквы + номер (C1, R100, U5)."
        )

    return designator
