# sheet.py
"""Иерархическая страница проекта — файл KiCad .kicad_sch.

Лист — это ФАЙЛ, идентифицируемый yaml_path. Один и тот же файл
может быть инстанцирован многократно (actuator_channel × 4). Каждое
присутствие описывается SheetInstance в self.instances.

Корень определяется по факту:
    instances пуст ⇔ Sheet — корень (или standalone-топ).
    Первый вызов Sheet.load создаёт Sheet без instances — это корень.
    Каждый SheetRefComponent сразу регистрирует SheetInstance ребёнку —
    поэтому дочерние всегда непусты.

Загрузка — единая, рекурсивная:
    Sheet.load(yaml_path, ...) читает YAML, создаёт Sheet, грузит
    содержимое. Встретив X_* (symbol=Core:Hierarchical_Sheet),
    _load_components вызывает SheetRefComponent(designator, self,
    sheet_file). Конструктор SheetRefComponent сам:
        * ищет уже загруженный дочерний Sheet через find_sheet от корня,
        * если нет — вызывает Sheet.load(child_yaml, ...) — рекурсия,
        * читает порты дочернего Sheet,
        * создаёт SheetInstance для каждого контекста self,
        * регистрирует их через child_sheet.register_instance.

    Один YAML = один Sheet. find_sheet обходит дерево вниз по
    child_sheet от корня и не даёт загрузить один файл дважды.

Инфраструктура (source, libraries, load_errors):
    Создаётся при первом вызове Sheet.load (корень). Дочерние
    получают те же объекты через параметры — общий счётчик ошибок,
    общая библиотека символов.

Проектные refdes:
    Sheet не знает про refdes своих компонентов. При регистрации
    инстанса Sheet раздаёт ссылку на него каждому компоненту через
    comp.add_instance(inst). Компонент сам вычисляет своё проектное
    имя (make_refdes(designator, inst.page)).

Роутер пишет в страницу:
    - sheet.labels       — метки-заглушки на неудачных пинах;
    - sheet.t_junctions  — T-врезки в существующие сети.

Схлопывание поддерева (flatten):
    Sheet.flatten() собирает FlatNetMap для этого листа и всего его
    поддерева. Точка старта — любой Sheet, а не обязательно корень
    проекта: если нужна карта только части дерева, достаточно
    вызвать flatten() у нужной страницы.

    Реализация — в flat.Flattener, ленивый импорт: sheet.py не
    тянет flat.py, пока flatten() не вызван впервые. Это убирает
    цикл импорта (flat.py типизируется на Sheet).

Геометрия:
    Sheet хранит ТОЛЬКО components. Позиция каждого компонента — в
    самом компоненте (anchor_page_mm). Sheet делегирует запросы
    геометрии в Component.
"""
from __future__ import annotations

import uuid as uuid_mod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple, TYPE_CHECKING

import yaml

from cell import Cell
from component import Component, ComponentLoadError
from constants import Axis, DEFAULT_GRID_MM, Symbol
from designators import DesignatorError
from logging_setup import ctx, get_logger
from netlist import Netlist

from routing_types import FallbackLabel, TJunction

if TYPE_CHECKING:
    from flat import FlatNetMap
    from kicad_source import KiCadSource
    from libraries import LibraryManager
    from sheet_instance import SheetInstance

log = get_logger(__name__)


@dataclass(eq=False)
class Sheet:
    """Одна страница проекта — файл .kicad_sch.

    Сравнение — по идентичности (eq=False). Хэш — по yaml_path.
    """

    yaml_path: Path
    uuid: str = ""
    grid_mm: float = DEFAULT_GRID_MM

    components: Dict[str, Component] = field(default_factory=dict, repr=False)
    instances: List["SheetInstance"] = field(default_factory=list, repr=False)
    netlist: Netlist = field(default_factory=Netlist, repr=False)

    paths: List[List[Cell]] = field(default_factory=list, repr=False)
    labels: List[FallbackLabel] = field(default_factory=list, repr=False)
    t_junctions: List[TJunction] = field(default_factory=list, repr=False)

    source: Optional["KiCadSource"] = field(default=None, repr=False)
    libraries: Optional["LibraryManager"] = field(default=None, repr=False)
    load_errors: List[str] = field(default_factory=list, repr=False)

    # =========================================================
    # Вычисляемые идентификаторы
    # =========================================================

    @property
    def stem(self) -> str:
        return self.yaml_path.stem

    @property
    def sheet_path(self) -> str:
        return f"{self.stem}.kicad_sch"

    @property
    def page(self) -> str:
        return self.stem

    @property
    def out_file(self) -> str:
        return self.sheet_path

    @property
    def fqn_prefix(self) -> str:
        return self.stem

    @property
    def is_root(self) -> bool:
        """Корень ⇔ instances пуст."""
        return not self.instances

    def __hash__(self) -> int:
        return hash(self.yaml_path)

    # =========================================================
    # Загрузка из YAML
    # =========================================================

    @classmethod
    def load(
        cls,
        yaml_path: Path,
        *,
        source=None,
        libraries=None,
        load_errors=None,
    ) -> "Sheet":
        """Прочитать YAML и создать Sheet.

        Не ищет уже загруженный — это работа SheetRefComponent.find_sheet.
        Всегда создаёт новый Sheet.
        """
        yaml_path = yaml_path.resolve()
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}

        # Корневой YAML может быть обёрнут в root_page: — тогда
        # содержимое лежит внутри. Дочерние YAML без обёртки.
        if isinstance(data, dict) and "root_page" in data:
            data = data.get("root_page") or {}

        sheet = cls(
            yaml_path=yaml_path,
            uuid=str(uuid_mod.uuid4()),
            grid_mm=float(data.get("grid_mm", DEFAULT_GRID_MM)),
            source=source,
            libraries=libraries,
            load_errors=load_errors if load_errors is not None else [],
        )

        sheet._load_contents(data, yaml_path)
        return sheet

    def _load_contents(self, data: dict, yaml_path: Path) -> None:
        """Сети до компонентов: _bind_node вяжет пины к сетям, а
        SheetRefComponent читает порты из netlist ДОЧЕРНЕГО Sheet —
        у него они уже готовы, потому что load(child) рекурсивен и
        вернул полностью загруженный Sheet.
        """
        self._load_components(data, yaml_path)
        self._load_nets(data, yaml_path)
        

    def _load_components(self, data: dict, yaml_path: Path) -> None:
        """Компоненты листа: обычные + X_*."""
        from sheet_ref import SheetRefComponent, SheetRefError

        types = data.get("component_types", {}) or {}

        for designator, cdef in (data.get("components") or {}).items():
            # ── X_* — ссылка на вложенный лист. ──
            if cdef.get("symbol") == Symbol.HIERARCHICAL_SHEET:
                value_sch = cdef.get("value_sch")
                if not value_sch:
                    self.load_errors.append(
                        f"{yaml_path}: components.{designator}: "
                        f"нет value_sch"
                    )
                    log.error(
                        "%s sheetref_no_value_sch des=%s",
                        ctx(page=self.page), designator,
                    )
                    continue

                sheet_file = str(Path(value_sch).with_suffix(".yaml"))
                try:
                    ref = SheetRefComponent(designator, self, sheet_file)
                except SheetRefError as e:
                    self.load_errors.append(
                        f"{yaml_path}: components.{designator}: {e}"
                    )
                    log.error(
                        "%s sheetref_load_failed des=%s reason=%s",
                        ctx(page=self.page), designator, e,
                    )
                    continue

                self.add_component(ref)
                continue

            # ── Обычный компонент. ──
            tname = cdef.get("type")
            if tname and tname in types and self.libraries is not None:
                try:
                    lib_path = self.libraries.ensure_type(
                        tname, types[tname],
                    )
                except RuntimeError as e:
                    self.load_errors.append(
                        f"{yaml_path}: components.{designator}: {e}"
                    )
                    log.error(
                        "%s lcsc_generate_failed des=%s type=%s reason=%s",
                        ctx(page=self.page), designator, tname, e,
                    )
                    continue
                if lib_path is not None:
                    self.source.invalidate_lib(lib_path)
                    self.source.register_library(lib_path)

            try:
                comp = Component.from_yaml(
                    designator=designator,
                    cdef=cdef,
                    types=types,
                    source=self.source,
                    grid_mm=self.grid_mm,
                    page=self.page,
                )
            except (DesignatorError, ComponentLoadError) as e:
                self.load_errors.append(f"{yaml_path}: {e}")
                log.error(
                    "%s component_load_failed des=%s reason=%s",
                    ctx(page=self.page), designator, e,
                )
                continue

            self.add_component(comp)

        self._load_ports(data, yaml_path)

    # ---------- сети ----------

    def _load_nets(self, data: dict, yaml_path: Path) -> None:
        from constants import DEFAULT_NET_TYPE

        for net_name, ndef in (data.get("nets") or {}).items():
            attrs = ndef.get("attributes", {})
            self.netlist.add_net(
                net_name,
                attrs.get("type", DEFAULT_NET_TYPE),
                list(attrs.keys()),
            )

        for net_name, ndef in (data.get("nets") or {}).items():
            for node in ndef.get("nodes", []) or []:
                self._bind_node(net_name, node, yaml_path)

        self._bind_ports_to_nets(data)
        self._bind_sheet_refs_to_nets(data)
        self._check_all_pins_connected()

    def _load_ports(self, data: dict, yaml_path: Path) -> None:
        """Создать PortComponent для каждой сети-порта листа."""
        from port_component import PortComponent

        for net_name, ndef in (data.get("nets") or {}).items():
            if not isinstance(ndef, dict):
                continue
            if not ndef.get("is_hierarchical_port"):
                continue

            direction = str(ndef.get("port_direction", "INPUT")).upper()
            designator = f"PORT_{net_name}"

            try:
                direction = str(ndef.get("port_direction", "INPUT")).upper()
                description = ndef.get("description", "") or ""
                designator = f"PORT_{net_name}"

                port = PortComponent.create(
                    designator=designator,
                    net_name=net_name,
                    direction=direction,
                    description=description,
)
            except DesignatorError as e:
                log.error(
                    "%s port_load_failed des=%s net=%s reason=%s",
                    ctx(page=self.page), designator, net_name, e,
                )
                continue
            if port is None:
                log.error(
                    "%s port_load_returned_none des=%s net=%s",
                    ctx(page=self.page), designator, net_name,
                )
                continue

            self.add_component(port)

    # ---------- привязка пинов ----------

    def _bind_node(self, net_name: str, node: dict, yaml_path: Path) -> None:
        designator = node.get("component")
        if not designator:
            log.warning(
                "%s node_skipped net=%s reason=no_component_key",
                ctx(page=self.page), net_name,
            )
            return

        pin_no = node.get("pin")
        pin_fn = node.get("pinfunction")

        if pin_no is None and pin_fn is None:
            self.load_errors.append(
                f"{self.page}: net={net_name}: {designator} — "
                f"узел без pin/pinfunction"
            )
            return

        comp = self.get_component(designator)
        if comp is None:
            log.warning(
                "%s node_skipped des=%s net=%s reason=no_component",
                ctx(page=self.page), designator, net_name,
            )
            return

        if pin_no is not None:
            pin = comp.pin_by_number(str(pin_no))
        else:
            pin = comp.pin_by_name(str(pin_fn))

        if pin is None:
            log.warning(
                "%s node_skipped des=%s net=%s reason=no_pin",
                ctx(page=self.page), designator, net_name,
            )
            return

        try:
            self.netlist.assign_pin_to_net(pin.fqn, net_name, pin=pin)
        except ValueError:
            log.warning(
                "%s net_missing net=%s fqn=%s",
                ctx(page=self.page), net_name, pin.fqn,
            )
        else:
            pin.net_name = net_name

    def _bind_ports_to_nets(self, data: dict) -> None:
        from port_component import PortComponent

        for comp in self.components.values():
            if not isinstance(comp, PortComponent):
                continue
            net = self.netlist.nets.get(comp.net_name)
            if net is None:
                continue
            pin = comp.pins[0]
            self.netlist.assign_pin_to_net(pin.fqn, comp.net_name, pin=pin)
            pin.net_name = comp.net_name

    def _bind_sheet_refs_to_nets(self, data: dict) -> None:
        from port_component import PortComponent

        for comp in self.components.values():
            if not getattr(comp, "is_sheet_ref", False):
                continue

            for port in getattr(comp, "ports", []):
                port["shape"] = PortComponent.shape_for_direction(
                    port["direction"]
                )

            for pin in comp.pins:
                net_name = pin.identifier
                net = self.netlist.nets.get(net_name)
                if net is None:
                    continue
                self.netlist.assign_pin_to_net(pin.fqn, net_name, pin=pin)
                pin.net_name = net_name

    def _check_all_pins_connected(self) -> None:
        unbound = []
        for designator, comp in self.components.items():
            for pin in comp.pins:
                if pin.net_ref is None:
                    unbound.append((designator, pin.identifier, pin.name))

        if not unbound:
            return

        log.warning(
            "%s pins_unbound count=%d",
            ctx(page=self.page), len(unbound),
        )

    # =========================================================
    # Порты — утилита для SheetRefComponent
    # =========================================================

    def read_ports(self) -> List[dict]:
        from port_component import PortComponent
        return [
            {
                "net_label":   comp.net_name,
                "direction":   comp.direction,
                "description": comp.description,
            }
            for comp in self.components.values()
            if isinstance(comp, PortComponent)
        ]

    # =========================================================
    # Компоненты
    # =========================================================

    def add_component(self, comp: Component) -> None:
        comp.sheet = self
        self.components[comp.designator] = comp

        if not getattr(comp, "is_sheet_ref", False) \
                and not comp.designator.startswith("X_"):
            for inst in self.instances:
                comp.add_instance(inst)

        log.debug("[%s] добавлен компонент %s", self.page, comp.fqn)

    def get_component(self, designator: str) -> Optional[Component]:
        return self.components.get(designator)

    # =========================================================
    # Инстансы листа
    # =========================================================

    def register_instance(self, inst: "SheetInstance") -> None:
        for existing in self.instances:
            if existing is inst:
                return
        self.instances.append(inst)

        for local, comp in self.components.items():
            if getattr(comp, "is_sheet_ref", False):
                continue
            if local.startswith("X_"):
                continue
            comp.add_instance(inst)

    @property
    def has_instances(self) -> bool:
        return bool(self.instances)

    @property
    def pages(self) -> List[int]:
        return [inst.page for inst in self.instances]

    def instance_at_page(self, page: int) -> Optional["SheetInstance"]:
        for inst in self.instances:
            if inst.page == page:
                return inst
        return None

    def instance_at_path(self, path: str) -> Optional["SheetInstance"]:
        for inst in self.instances:
            if inst.path == path:
                return inst
        return None

    # =========================================================
    # FQN
    # =========================================================

    def fqn(self, designator: str) -> str:
        return f"{self.fqn_prefix}/{designator}"

    def fqn_pin(self, local_key: str) -> str:
        return f"{self.fqn_prefix}/{local_key}"

    def local_key(self, fqn: str) -> Optional[str]:
        prefix = f"{self.fqn_prefix}/"
        return fqn[len(prefix):] if fqn.startswith(prefix) else None

    # =========================================================
    # Схлопывание поддерева
    # =========================================================

    def flatten(self) -> "FlatNetMap":
        """Плоская карта сетей этого листа и всего его поддерева.

        Точка старта — сам Sheet. Если это корень проекта, карта
        эквивалентна плоскому нетлисту kicad-cli для корневой схемы.
        Если это промежуточная страница, карта описывает поддерево
        от неё вниз — внешний контекст (анцесторы) не учитывается.

        Возвращает FlatNetMap; имена сетей нестабильны (KiCad
        переименовывает VCC_12V → /X_FOO/VCC_12V при флаттенинге),
        сравнение — через FlatNetMap.partition().

        Ленивый импорт Flattener: sheet.py не тянет flat.py, пока
        flatten() не вызван впервые. Это убирает цикл импорта
        (flat.py типизируется на Sheet).
        """
        from flat import Flattener

        return Flattener(
            root=self,
            refdes_maps=self._compute_refdes_maps(),
        ).build()

    def _compute_refdes_maps(self) -> Dict[str, Dict[str, str]]:
        """{X_des: {local_des: project_ref}} для X_* в этом поддереве.

        Для каждого X_*-компонента в поддереве от self:
            * собирается множество страниц его инстансов (inst.page);
            * для каждого локального компонента дочернего листа
              выбирается инстанс, page которого попадает в это
              множество, и refdes вычисляется через
              make_refdes(local_des, inst.page).

        Для одноинстансных листов карта тождественна (local ==
        project), но всё равно заполняется — чтобы не разветвлять
        логику у потребителя (Flattener).

        Обход идёт рекурсивно от self вниз; внешние X_* (в
        анцесторах self) сюда не попадают — они не порождают
        листов этого поддерева.
        """

    def _compute_refdes_maps(self) -> Dict[str, Dict[str, str]]:
        """Плоский dict {X_designator: {local_des: project_ref}}.

        Каждый Sheet отвечает только за свои X_* и за своих прямых детей:
        для каждого X_* строит карту переименования локальных refdes
        дочернего листа в проектные, потом складывает с тем, что вернули
        дети. Ключи (designators X_*) уникальны в дереве, так что merge
        безопасен.
        """
        from refdes import make_refdes

        out: Dict[str, Dict[str, str]] = {}

        for des, comp in self.components.items():
            if not getattr(comp, "is_sheet_ref", False):
                continue
            child = getattr(comp, "child_sheet", None)
            if child is None:
                continue

            # Page этого инстанса ребёнка — child_instance, не comp.instances
            # (у SheetRefComponent instances всегда пуст).
            child_inst = getattr(comp, "child_instance", None)
            if child_inst is None:
                continue
            x_page = child_inst.page

            rm: Dict[str, str] = {}
            for local_des, local_comp in child.components.items():
                if getattr(local_comp, "is_sheet_ref", False):
                    continue
                if local_des.startswith("X_"):
                    continue

                project_ref = None
                for inst in local_comp.instances:
                    if inst.page == x_page:
                        project_ref = make_refdes(local_des, inst.page)
                        break
                rm[local_des] = project_ref or local_des

            out[des] = rm

            # Дети добавляют свои карты сами.
            out.update(child._compute_refdes_maps())

        return out
    

    # =========================================================
    # Накопители роутера
    # =========================================================

    def reset_routing_marks(self) -> None:
        self.labels.clear()
        self.t_junctions.clear()
        log.debug("[%s] накопители роутера сброшены", self.page)

    # =========================================================
    # Делегирование геометрии в Component
    # =========================================================

    def component_bbox(self, designator: str) -> Tuple[int, int, int, int]:
        return self._comp(designator).bbox_page_cell()

    def bbox_origin_cell(self, designator: str) -> Cell:
        return self._comp(designator).bbox_origin_cell()

    def pin_mm(self, designator: str, pin_number: str) -> Tuple[float, float]:
        comp = self._comp(designator)
        pin = comp.pin_by_number(pin_number)
        if pin is None:
            raise KeyError(
                f"[{self.page}] пин не найден: {designator}:{pin_number}"
            )
        return comp.abs_pin_mm(pin)

    def pin_cell(self, designator: str, pin_number: str) -> Cell:
        comp = self._comp(designator)
        pin = comp.pin_by_number(pin_number)
        if pin is None:
            raise KeyError(
                f"[{self.page}] пин не найден: {designator}:{pin_number}"
            )
        return comp.abs_pin_cell(pin)

    def anchor_mm(self, designator: str) -> Tuple[float, float]:
        comp = self._comp(designator)
        if comp.anchor_page_mm is None:
            raise RuntimeError(
                f"[{self.page}] {designator}: anchor_page_mm не установлен"
            )
        return comp.anchor_page_mm

    def iter_occupied_cells(self, designator: str
                            ) -> Iterator[Tuple[int, int]]:
        return self._comp(designator).iter_occupied_cells()

    def iter_pin_cells(self, designator: str) -> Iterator[Tuple[int, int]]:
        return self._comp(designator).iter_pin_cells()

    def _comp(self, designator: str) -> Component:
        comp = self.components.get(designator)
        if comp is None:
            raise KeyError(f"[{self.page}] компонент не найден: {designator}")
        return comp