# cell.py
"""Точка на сетке: (col, row) с покомпонентной арифметикой."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Cell:
    """Клетка сетки. Неизменяемая, поддерживает + и -."""
    col: int
    row: int

    def __add__(self, other: "Cell") -> "Cell":
        """Покомпонентное сложение клеток."""
        return Cell(self.col + other.col, self.row + other.row)

    def __sub__(self, other: "Cell") -> "Cell":
        """Покомпонентное вычитание клеток."""
        return Cell(self.col - other.col, self.row - other.row)