# make_scr/router_map.py
"""Карта занятости для роутера.

Клетка -> Occupant. Если ключа нет — клетка свободна.

Тип RouterMap — синоним для Dict[(col, row), Occupant]. Используется
в Placer.build_router_map и Router.
"""
from typing import Dict, Tuple

from occupant import Occupant

# (col, row) -> Occupant
RouterMap = Dict[Tuple[int, int], Occupant]