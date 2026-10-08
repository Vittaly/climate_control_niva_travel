# sheet.py
"""Иерархическая страница проекта — файл KiCad .kicad_sch.

Лист — это ФАЙЛ, идентифицируемый yaml_path. Один и тот же файл
может быть инстансован многократно (actuator_channel × 4) — но
сама страница одна.

Симметрия с SheetRefComponent:
    SheetRefComponent.instances     — SheetRefInstance вхождений X_*
                                      в дереве.
    Sheet.sheet_ref_instances       — SheetRefInstance вхождений,
                                      которые ведут на эту страницу
                                      (плюс 0-й — «страница сама»).

    У КАЖДОЙ страницы всегда есть 0-й SheetRefInstance:
        component=None, parent=None, page=1, _local_sheet=self.
    Это «паспорт» страницы как корня самой себя — не зависит от
    того, вкладывают ли её куда-то. Если страница включена как
    дочерняя (parent_sri задан при загрузке), в sheet_ref_instances
    добавляется ЕЩЁ и parent_sri.

    is_root ⇔ среди вхождений только 0-й (все is_local=True).

Загрузка и инстанцирование (одна фаза):
    Sheet.load(yaml_path, *, parent_sri=None, first_child_counter=2)
    читает YAML, создаёт Sheet, создаёт 0-й SheetRefInstance и
    сразу инстанцирует поддерево.

        parent_sri is None → страница корень. Контекстом
            инстанцирования служит 0-й SheetRefInstance.
        parent_sri задан  → страница дочерняя. 0-й SheetRefInstance
            остаётся в sheet_ref_instances, дополнительно туда
            добавляется parent_sri. Контекст инстанцирования —
            parent_sri (0-й в каскаде не участвует).

    _load_components(data, path, *, parent_sri,
                     sheet_ref_start_counter) -> next_counter:
        * обычным компонентам сразу даёт ComponentInstance
          с sheet_ref=parent_sri;
        * для каждого X_* создаёт SheetRefComponent(parent_sri=…,
          sheet_ref_start_counter=…), который сам в своём
          конструкторе создаёт SheetRefInstance и инстанцирует
          целевую страницу;
        * возвращает следующий свободный номер после всего
          поддерева.

    Контекст течёт сверху вниз через аргумент parent_sri, номера —
    через sheet_ref_start_counter.

Корень дерева:
    Нигде не хранится. Вычисляется в SheetRefComponent через
    my_sri.root_sheet — подъём по parent-цепочке до верхнего SRI,
    у которого parent is None (это 0-й SRI корневой страницы,
    его _local_sheet — корневой Sheet).

Multi-instance:
    SheetRefComponent.__init__ при первом визите грузит дочернюю
    через Sheet.load(parent_sri=my_sri, first_child_counter=N+1).
    При повторном визите (файл уже в дереве) вызывает на дочерней
    child_sheet.register_from(my_sri, sheet_ref_start_counter=N+1) —
    тот же каскад, только без перечитывания YAML.

    register_from:
        * добавляет parent_sri в self.sheet_ref_instances;
        * обычным компонентам даёт ЕЩЁ ОДИН ComponentInstance
          с sheet_ref=parent_sri;
        * у вложенных X_* вызывает on_new_context, который создаёт
          ещё один SheetRefInstance и рекурсивно дёргает
          register_from в целевой странице.

Проектные refdef:
    Sheet не знает про refdef компонентов. При инстанцировании
    Sheet раздаёт ComponentInstance; у них refdef/путь — производные.

Роутер и структурные метки:
    - sheet.labels     — LabelComponent;
    - sheet.junctions  — Junction.

Схлопывание поддерева:
    Sheet.flatten() собирает FlatNetMap через flat.Flattener.

Геометрия:
    Sheet хранит ТОЛЬКО components. Позиция каждого компонента — в
    самом компоненте (anchor_page_mm).
"""
from __future__ import annotations

import uuid as uuid_mod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple, TYPE_CHECKING

import yaml

from cell import Cell
from component import Component, ComponentLoadError
from component_instance import ComponentInstance
from constants import (
    Axis,
    ComponentKind,
    DEFAULT_GRID_MM,
    Direction,
    Symbol,
)
from designators import DesignatorError
from logging_setup import ctx, get_logger
from junction import Junction
from label_component import LabelComponent
from netlist import Netlist
from primitive import Primitive
from sheet_ref_instance import SheetRefInstance

if TYPE_CHECKING:
    from flat import FlatNetMap
    from kicad_source import KiCadSource
    from libraries import LibraryManager

log = get_logger(__name__)


@dataclass(eq=False, kw_only=True)
class Sheet(Primitive):
    """Одна страница проекта — файл .kicad_sch.

    Сравнение — по идентичности (eq=False). Хэш — по yaml_path.
    """

    yaml_path: Path
    grid_mm: float = DEFAULT_GRID_MM

    components: Dict[str, Component] = field(default_factory=dict, repr=False)

    # Контексты, в которых эта страница появилась в дереве.
    #
    # Первый элемент всегда 0-й SheetRefInstance (is_local=True,
    # page=1) — «страница как корень самой себя».
    #
    # Далее — по одному SheetRefInstance на каждый контекст
    # родителя (обычно один, при multi-instance — несколько).
    # У корня проекта дополнительных вхождений нет: список = [0-й].
    sheet_ref_instances: List[SheetRefInstance] = field(
        default_factory=list, repr=False,
    )

    netlist: Netlist = field(default_factory=Netlist, repr=False)

    paths: List[List[Cell]] = field(default_factory=list, repr=False)
    labels: List[LabelComponent] = field(default_factory=list, repr=False)
    junctions: List[Junction] = field(default_factory=list, repr=False)

    source: Optional["KiCadSource"] = field(default=None, repr=False)
    libraries: Optional["LibraryManager"] = field(default=None, repr=False)
    load_errors: List[str] = field(default_factory=list, repr=False)

    # Следующий свободный номер sheet-ref после всего поддерева
    # этой страницы. Проставляется в Sheet.load; читается
    # родительским SheetRefComponent для передачи следующему X_*.
    _next_counter: int = field(default=2, repr=False, compare=False)

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
        """Корень ⇔ среди вхождений только 0-й (is_local=True).

        У корня проекта sheet_ref_instances = [0-й]. Если страница
        включена как дочерняя, к 0-му добавляется parent_sri
        (is_local=False) — условие перестаёт выполняться.
        """
        return all(sri.is_local for sri in self.sheet_ref_instances)

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
        parent_sri: Optional[SheetRefInstance] = None,
        first_child_counter: int = 2,
    ) -> "Sheet":
        """Загрузить страницу и инстанцировать поддерево.

        parent_sri — SheetRefInstance родительского X_* (None для
        корня). 0-й SheetRefInstance (is_local=True, page=1) создаётся
        ВСЕГДА — это «паспорт» страницы как корня самой себя.

        Если parent_sri is None — страница корень: 0-й используется
        как контекст инстанцирования.

        Если parent_sri задан — страница дочерняя: 0-й остаётся в
        sheet_ref_instances, дополнительно туда же добавляется
        parent_sri. Контекст инстанцирования — parent_sri.

        first_child_counter — номер первого вложенного X_* этой
        страницы. Для корня по умолчанию 2 (KiCad резервирует 1 за
        корнем). Для дочерней SheetRefComponent передаёт
        sheet_ref_start_counter + 1 от собственного номера.

        Возвращённый Sheet имеет проставленный _next_counter —
        следующий свободный номер после всего поддерева. Родитель
        читает его, чтобы продолжить нумерацию своих X_*.
        """
        yaml_path = yaml_path.resolve()
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
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

        # 0-й SheetRefInstance — у ВСЕХ страниц. Паспорт:
        # страница как корень самой себя, uuid = sheet.uuid.
        sri0 = SheetRefInstance(
            component=None,
            parent=None,
            page=1,
            _local_sheet=sheet,
        )
        sheet.sheet_ref_instances.append(sri0)

        # Контекст инстанцирования: для корня — 0-й, для дочерней —
        # parent_sri (который ещё и добавляется в список вхождений).
        if parent_sri is None:
            context_sri = sri0
        else:
            sheet.sheet_ref_instances.append(parent_sri)
            context_sri = parent_sri

        # Компоненты + сети + инстанцирование поддерева.
        sheet._next_counter = sheet._load_components(
            data, yaml_path,
            parent_sri=context_sri,
            sheet_ref_start_counter=first_child_counter,
        )
        sheet._load_nets(data, yaml_path)

        return sheet

    def _load_components(
        self,
        data: dict,
        yaml_path: Path,
        *,
        parent_sri: SheetRefInstance,
        sheet_ref_start_counter: int,
    ) -> int:
        """Загрузить компоненты листа и инстанцировать поддерево.

        Обычные компоненты сразу получают ComponentInstance с
        sheet_ref=parent_sri. X_* создаются как SheetRefComponent
        с проброшенными parent_sri и sheet_ref_start_counter — их
        конструктор сам создаст SheetRefInstance и инстанцирует
        целевое поддерево.

        Возвращает next_counter — следующий свободный номер после
        всего поддерева этого листа.
        """
        from sheet_ref import SheetRefComponent, SheetRefError

        types = data.get("component_types", {}) or {}
        next_counter = sheet_ref_start_counter

        for designator, cdef in (data.get("components") or {}).items():
            # ── X_* — вложенный лист. ──
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
                    ref = SheetRefComponent(
                        designator, self, sheet_file,
                        parent_sri=parent_sri,
                        sheet_ref_start_counter=next_counter,
                    )
                except SheetRefError as e:
                    self.load_errors.append(
                        f"{yaml_path}: components.{designator}: {e}"
                    )
                    log.error(
                        "%s sheetref_load_failed des=%s reason=%s",
                        ctx(page=self.page), designator, e,
                    )
                    continue

                next_counter = ref.next_counter_after_subtree
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

            comp.instances.append(ComponentInstance(
                component=comp,
                sheet_ref=parent_sri,
            ))
            self.add_component(comp)

        self._load_ports(data, yaml_path, parent_sri=parent_sri)
        return next_counter

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

    def _load_ports(
        self,
        data: dict,
        yaml_path: Path,
        *,
        parent_sri: SheetRefInstance,
    ) -> None:
        """Создать PortComponent для каждой сети-порта листа.

        Порт — тоже Component; ему сразу даётся ComponentInstance
        с sheet_ref=parent_sri (тем же контекстом, что и обычные
        компоненты). Без этого PortComponent не имеет доступа к
        своему page / контексту.
        """
        from port_component import PortComponent

        for net_name, ndef in (data.get("nets") or {}).items():
            if not isinstance(ndef, dict):
                continue
            if not ndef.get("is_hierarchical_port"):
                continue

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

            port.instances.append(ComponentInstance(
                component=port,
                sheet_ref=parent_sri,
            ))
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
            if getattr(comp, "kind", None) != ComponentKind.SHEET_REF:
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
        log.debug("[%s] добавлен компонент %s", self.page, comp.fqn)

    def get_component(self, designator: str) -> Optional[Component]:
        return self.components.get(designator)

    # =========================================================
    # Поиск загруженной страницы
    # =========================================================

    def find_sheet(self, stem: str) -> Optional["Sheet"]:
        """Найти загруженную страницу по stem в поддереве от self.

        Рекурсивный обход вниз: сам Sheet, затем все вложенные
        SheetRefComponent.child_sheet. Один YAML = один Sheet, поэтому
        stem уникален в дереве — вернёт ровно одну страницу или None.

        Вызывается на корне. Корень у SheetRefComponent получается
        подъёмом по parent-цепочке (my_sri.root_sheet).
        """
        if self.stem == stem:
            return self

        from sheet_ref import SheetRefComponent

        for comp in self.components.values():
            if not isinstance(comp, SheetRefComponent):
                continue
            cs = comp.child_sheet
            if cs is None:
                continue
            found = cs.find_sheet(stem)
            if found is not None:
                return found
        return None

    # =========================================================
    # Каскадная регистрация контекста (multi-instance)
    # =========================================================

    def register_from(
        self,
        parent_sri: SheetRefInstance,
        *,
        sheet_ref_start_counter: int,
    ) -> int:
        """Инстанцировать УЖЕ ЗАГРУЖЕННУЮ страницу в новом контексте.

        Вызывается SheetRefComponent.__init__, когда файл уже
        находится в дереве (multi-instance). Первый визит идёт
        через Sheet.load — register_from тогда не зовётся.

        Действия:
            * добавляет parent_sri в self.sheet_ref_instances
              (0-й SRI уже лежит там — он создан в Sheet.load);
            * каждому обычному компоненту даёт ЕЩЁ ОДИН
              ComponentInstance с sheet_ref=parent_sri;
            * каждому вложенному X_* — вызывает on_new_context,
              который создаёт ещё один SheetRefInstance и рекурсивно
              дёргает register_from в целевой странице.

        Возвращает next_counter — следующий свободный номер после
        всего поддерева.
        """
        from sheet_ref import SheetRefComponent

        self.sheet_ref_instances.append(parent_sri)

        next_counter = sheet_ref_start_counter

        for comp in self.components.values():
            if isinstance(comp, SheetRefComponent):
                next_counter = comp.on_new_context(
                    parent_sri,
                    sheet_ref_start_counter=next_counter,
                )
            else:
                comp.instances.append(ComponentInstance(
                    component=comp,
                    sheet_ref=parent_sri,
                ))

        return next_counter

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
        from flat import Flattener

        return Flattener(
            root=self,
            refdes_maps=self._compute_refdes_maps(),
        ).build()

    def _compute_refdes_maps(self) -> Dict[str, Dict[str, str]]:
        """Плоский dict {X_designator: {local_des: project_refdef}}.

        Каждый Sheet отвечает только за свои X_* и за своих прямых
        детей. Ключи уникальны в пределах одного Sheet.

        Использует 0-е вхождение (comp.instances[0]). При
        мульти-инстансе родителя карты надо собирать по каждому
        вхождению отдельно — TODO для Flattener.
        """
        from sheet_ref import SheetRefComponent

        out: Dict[str, Dict[str, str]] = {}

        for des, comp in self.components.items():
            if not isinstance(comp, SheetRefComponent):
                continue
            child = comp.child_sheet
            if child is None or not comp.instances:
                continue

            sri = comp.instances[0]

            rm: Dict[str, str] = {}
            for local_des, local_comp in child.components.items():
                if isinstance(local_comp, SheetRefComponent):
                    continue
                if local_des.startswith("X_"):
                    continue
                if getattr(local_comp, "kind", None) == ComponentKind.LABEL:
                    continue

                project_ref = None
                for ci in local_comp.instances:
                    if ci.sheet_ref is sri:
                        project_ref = ci.refdef
                        break
                rm[local_des] = project_ref or local_des

            out[des] = rm
            out.update(child._compute_refdes_maps())

        return out

    # =========================================================
    # Накопители роутера и структурных меток
    # =========================================================

    def add_junction(self, j: Junction) -> None:
        j.sheet = self
        self.junctions.append(j)

    def add_label(self, lbl: LabelComponent) -> None:
        lbl.sheet = self
        self.labels.append(lbl)

    def create_sheet_pin_labels(self) -> None:
        from label_component import LabelComponent, LabelReason

        grid = self.grid_mm
        created = 0

        for comp in self.components.values():
            if getattr(comp, "kind", None) != ComponentKind.SHEET_REF:
                continue

            anchor = getattr(comp, "anchor_page_mm", None)
            if anchor is None:
                continue
            fc, fr = comp.frame_size
            ox, oy = comp.frame_offset_mm
            fx = anchor[Axis.X] + ox
            fw = (fc - 1) * grid

            for pin in comp.pins:
                net_name = getattr(pin, "net_name", None) or pin.identifier
                if not net_name:
                    continue
                net = self.netlist.nets.get(net_name)
                if net is None:
                    log.warning(
                        "%s sheet_pin_label net_missing net=%s pin=%s",
                        ctx(page=self.page), net_name, pin.local_key,
                    )
                    continue

                try:
                    pin_mm = comp.abs_pin_mm(pin)
                except Exception as e:
                    log.warning(
                        "%s sheet_pin_label geom_failed pin=%s err=%s",
                        ctx(page=self.page, comp=comp.designator),
                        pin.local_key, e,
                    )
                    continue

                if abs(pin_mm[Axis.X] - fx) < grid / 2:
                    direction = Direction.RIGHT
                elif abs(pin_mm[Axis.X] - (fx + fw)) < grid / 2:
                    direction = Direction.LEFT
                else:
                    log.warning(
                        "%s sheet_pin_label off_frame pin=%s x=%.3f "
                        "frame=[%.3f..%.3f]",
                        ctx(page=self.page, comp=comp.designator,
                            pin=pin.local_key),
                        pin.local_key, pin_mm[Axis.X], fx, fx + fw,
                    )
                    continue

                already = any(
                    lbl.name == net.name
                    and abs(lbl.anchor_page_mm[0] - pin_mm[0]) < 1e-9
                    and abs(lbl.anchor_page_mm[1] - pin_mm[1]) < 1e-9
                    for lbl in self.labels
                )
                if already:
                    continue

                lbl = LabelComponent(
                    net=net,
                    direction=direction,
                    reason=LabelReason.SHEET_PIN_NAME,
                    anchor_page_mm=pin_mm,
                )
                self.add_label(lbl)
                created += 1

        if created:
            log.info(
                "%s sheet_pin_labels created=%d",
                ctx(page=self.page), created,
            )

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