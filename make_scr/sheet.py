# sheet.py
"""Иерархическая страница проекта.

Двусторонняя связь: Sheet знает свои Component, Component знает свой Sheet.

Роутер пишет в страницу:
    - sheet.labels       — метки-заглушки на неудачных пинах;
    - sheet.t_junctions  — T-врезки в существующие сети.
Сам Router эти списки у себя не хранит.

Геометрия:
    Sheet хранит ТОЛЬКО перечень компонентов (components).
    Позиция каждого компонента — в самом компоненте (anchor_page_mm).
    Sheet делегирует запросы геометрии в Component:
        sheet.pin_mm(d, p)      → comp.abs_pin_mm(pin)
        sheet.pin_cell(d, p)    → comp.abs_pin_cell(pin)
        sheet.component_bbox(d) → comp.bbox_page_cell()
        sheet.anchor_mm(d)      → comp.anchor_page_mm
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

from cell import Cell
from component import Component
from logging_setup import get_logger
from placer import Placer
from router import Router
from routing_types import FallbackLabel, TJunction

log = get_logger(__name__)


@dataclass(eq=False)
class Sheet:
    """Одна иерархическая страница проекта.

    Сравнение — по идентичности (eq=False). Хэш — по sheet_path.

    Attributes:
        designator:  локальное имя листа ("X_ACT"); "" для корня.
        sheet_path:  полный путь от корня ("" для корня, "X_ACT",
                     "X_ACT/MOTOR_A" для вложенного).
        yaml_path:   путь к YAML-описанию.
        data:        распарсенный YAML.
        components:  локальный designator -> Component.
        placer:      Placer после place_and_route.
        router:      Router после place_and_route.
        paths:       трассы страницы.
        labels:      метки-заглушки (заполняет Router).
        t_junctions: T-врезки (заполняет Router).
    """
    designator: str
    sheet_path: str
    yaml_path: Path
    data: dict = field(default_factory=dict, repr=False)
    components: Dict[str, Component] = field(default_factory=dict, repr=False)
    placer: Optional[Placer] = field(default=None, repr=False)
    router: Optional[Router] = field(default=None, repr=False)
    paths: List[List[Cell]] = field(default_factory=list, repr=False)

    # ---------- накопители роутера ----------
    labels: List[FallbackLabel] = field(default_factory=list, repr=False)
    t_junctions: List[TJunction] = field(default_factory=list, repr=False)

    # ---------- хэш / идентичность ----------

    def __hash__(self) -> int:
        """Хэш по sheet_path — уникален в проекте, не меняется."""
        return hash(self.sheet_path)

    # ---------- метаданные ----------

    @property
    def name(self) -> str:
        """Человекочитаемое имя страницы (page_name)."""
        return self.data.get("page_name", self.designator or "root")

    @property
    def out_file(self) -> str:
        """Имя выходного .kicad_sch."""
        src = self.data.get("file", f"{self.designator or 'root'}.kicad_sch")
        return Path(src).name

    # ---------- управление компонентами ----------

    def add_component(self, comp: Component) -> None:
        """Добавляет компонент и проставляет обратную ссылку comp.sheet.

        Args:
            comp: компонент с локальным designator.
        """
        comp.sheet = self
        self.components[comp.designator] = comp
        log.debug("[%s] добавлен компонент %s",
                  self.sheet_path or "root", comp.fqn)

    def get_component(self, designator: str) -> Optional[Component]:
        """Возвращает компонент по локальному designator или None."""
        return self.components.get(designator)

    # ---------- FQN ----------

    def fqn(self, designator: str) -> str:
        """Полное имя компонента с префиксом страницы.

        Args:
            designator: локальный designator компонента ("U1").
        """
        return f"{self.sheet_path}/{designator}" \
            if self.sheet_path else designator

    def fqn_pin(self, local_key: str) -> str:
        """Полное имя пина по его локальному ключу.

        Args:
            local_key: локальный ключ "U2:5".
        """
        return f"{self.sheet_path}/{local_key}" \
            if self.sheet_path else local_key

    def local_key(self, fqn: str) -> Optional[str]:
        """Обратное: FQN -> локальный ключ, если он наш. Иначе None.

        Args:
            fqn: FQN-ключ пина или компонента.
        """
        if not self.sheet_path:
            return fqn if "/" not in fqn else None
        prefix = f"{self.sheet_path}/"
        return fqn[len(prefix):] if fqn.startswith(prefix) else None

    # ---------- сброс накопителей роутера ----------

    def reset_routing_marks(self) -> None:
        """Очищает метки и T-врезки перед новым прогоном роутера.

        Полезно вызывать в начале route_all, если страница
        переразводится несколько раз (routing_driven).
        """
        self.labels.clear()
        self.t_junctions.clear()
        log.debug("[%s] накопители роутера сброшены",
                  self.sheet_path or "root")

    # ---------- делегирование геометрии в Component ----------

    def component_bbox(self, designator: str) -> Tuple[int, int, int, int]:
        """(col0, row0, col1, row1) — прямоугольник на странице (клетки).

        Делегирует в Component.bbox_page_cell().

        Args:
            designator: локальное обозначение компонента.

        Returns:
            (col0, row0, col1, row1) — bbox_page в клетках.

        Raises:
            KeyError: если компонент не найден.
            RuntimeError: если anchor_page_mm не установлен.
        """
        comp = self.components.get(designator)
        if comp is None:
            raise KeyError(f"[{self.sheet_path or 'root'}] "
                           f"компонент не найден: {designator}")
        return comp.bbox_page_cell()

    def bbox_origin_cell(self, designator: str) -> Cell:
        """Левый-верхний угол bbox на странице (клетки).

        Делегирует в Component.bbox_origin_cell().
        """
        comp = self.components.get(designator)
        if comp is None:
            raise KeyError(f"[{self.sheet_path or 'root'}] "
                           f"компонент не найден: {designator}")
        return comp.bbox_origin_cell()

    def pin_mm(self, designator: str, pin_number: str) -> Tuple[float, float]:
        """Реальная точка пина на странице (мм).

        Делегирует в Component.abs_pin_mm(pin).
        """
        comp = self.components.get(designator)
        if comp is None:
            raise KeyError(f"[{self.sheet_path or 'root'}] "
                           f"компонент не найден: {designator}")
        pin = comp.pin_by_number(pin_number)
        if pin is None:
            raise KeyError(f"[{self.sheet_path or 'root'}] "
                           f"пин не найден: {designator}:{pin_number}")
        return comp.abs_pin_mm(pin)

    def pin_cell(self, designator: str, pin_number: str) -> Cell:
        """Клетка пина на странице.

        Делегирует в Component.abs_pin_cell(pin).
        """
        comp = self.components.get(designator)
        if comp is None:
            raise KeyError(f"[{self.sheet_path or 'root'}] "
                           f"компонент не найден: {designator}")
        pin = comp.pin_by_number(pin_number)
        if pin is None:
            raise KeyError(f"[{self.sheet_path or 'root'}] "
                           f"пин не найден: {designator}:{pin_number}")
        return comp.abs_pin_cell(pin)

    def anchor_mm(self, designator: str) -> Tuple[float, float]:
        """Точка якоря на странице (мм).

        Делегирует в Component.anchor_page_mm.
        """
        comp = self.components.get(designator)
        if comp is None:
            raise KeyError(f"[{self.sheet_path or 'root'}] "
                           f"компонент не найден: {designator}")
        if comp.anchor_page_mm is None:
            raise RuntimeError(
                f"[{self.sheet_path or 'root'}] компонент {designator}: "
                f"anchor_page_mm не установлен"
            )
        return comp.anchor_page_mm

    def iter_occupied_cells(self, designator: str
                            ) -> Iterator[Tuple[int, int]]:
        """Клетки, занятые габаритом компонента.

        Делегирует в Component.iter_occupied_cells().
        """
        comp = self.components.get(designator)
        if comp is None:
            raise KeyError(f"[{self.sheet_path or 'root'}] "
                           f"компонент не найден: {designator}")
        return comp.iter_occupied_cells()

    def iter_pin_cells(self, designator: str) -> Iterator[Tuple[int, int]]:
        """Клетки пинов компонента.

        Делегирует в Component.iter_pin_cells().
        """
        comp = self.components.get(designator)
        if comp is None:
            raise KeyError(f"[{self.sheet_path or 'root'}] "
                           f"компонент не найден: {designator}")
        return comp.iter_pin_cells()