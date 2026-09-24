# make_scr/project.py
"""Корневая сущность: YAML -> компоненты/нетлист -> размещение -> трассы -> файлы.

Модель:
    - Sheet  — страница KiCad (.kicad_sch): components, netlist, grid_mm.
    - Placer — размещает на одной Sheet; читает sheet.netlist/grid_mm.
    - Router — трассирует одну Sheet; пишет в sheet.labels/t_junctions.
    - Writer — пишет .kicad_sch одной Sheet; читает sheet.grid_mm/netlist.
    - Project — оркестратор: грузит YAML, гоняет Placer/Router, сохраняет.

Идентификация листов (единая для всей цепочки):
    * Первоисточник — sheets/<stem>.yaml (stem = имя файла без .yaml).
    * Схема листа   — <stem>.kicad_sch (в корне проекта или в out_dir).
    * Связь листа со схемой объявлена РОВНО один раз — атрибутом
      value_sch у соответствующего X_* в main.yaml.components.
      Имена X_* — производные, на семантику листа не влияют.
    * Никакие page_name / file внутри sheets/*.yaml не читаются.
    * Список листов к прогону нигде не хранится: он выводится как
      {X_*, встречающиеся в nets} ∪ standalone_sheets (там — stem'ы).

YAML живёт только внутри загрузки. Sheet о YAML не знает.
Нетлист — поле Sheet, у каждой страницы свой.

Политика ошибок загрузки:
    Компонент, который не удалось собрать, НЕ теряется молча.
    Component.from_yaml либо возвращает Component, либо бросает
    DesignatorError/ComponentLoadError. Оба исключения
    перехватываются в _load_components, кладутся в self._load_errors
    и логируются на уровне ERROR с полным контекстом
    (designator/type/symbol/value/reason). После обхода всех
    компонентов и листов Project.load() бросает ProjectLoadError —
    до place_and_route/save дело не доходит, сломанный нетлист не
    генерируется.

    Дополнительно проверяется связность иерархии:
      * X_* без value_sch                      — ошибка;
      * value_sch без соответствующего YAML     — ошибка;
      * коллизия имён выходных .kicad_sch       — ошибка;
      * X_* без ни одной привязанной цепи       — ошибка (orphan);
      * standalone без <stem>.yaml              — ошибка.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, Optional

import yaml

from component import Component, ComponentLoadError
from constants import Axis, DEFAULT_GRID_MM, DEFAULT_NET_TYPE, Symbol
from kicad_source import KiCadSource
from logging_setup import ctx, get_logger
from placer import Placer
from router import Router
from sheet import Sheet
from sheet_ref import SheetRefComponent
from writer import Writer

from designators import DesignatorError, validate_component_designator

log = get_logger(__name__)


class ProjectLoadError(Exception):
    """Загрузка проекта прервана: YAML несовместим с KiCad.

    Собирает все обнаруженные ошибки, чтобы не гонять пользователя
    по одному компоненту за раз.
    """
    def __init__(self, errors: list[str]):
        self.errors = list(errors)
        super().__init__(
            "Загрузка проекта прервана:\n  " + "\n  ".join(self.errors)
        )


class Project:
    """Точка входа: загрузка, размещение, роутинг, сохранение."""

    def __init__(self, root_yaml: str | Path):
        """
        Args:
            root_yaml: путь к main.yaml.
        """
        self.root_path = Path(root_yaml)
        self.base_dir = self.root_path.parent

        self.source = KiCadSource()

        self.root_sheet: Optional[Sheet] = None
        self.sheets: Dict[str, Sheet] = {}       # key = имя .kicad_sch
        self.root_data: dict = {}
        # yaml_key (abs path) -> sheet_path: не грузим один YAML дважды
        self._loaded_yaml: Dict[str, str] = {}
        self._load_errors: list[str] = []

        log.info(
            "Project создан: %s", self.root_path,
            extra={
                "stage": "init",
                "event": "project_created",
                "path":  str(self.root_path),
            },
        )

    # =========================================================
    # Загрузка
    # =========================================================

    def load(self) -> "Project":
        """Полный цикл загрузки: main.yaml + рекурсивно все листы."""
        log.info(
            "Загрузка %s", self.root_path,
            extra={
                "stage": "load",
                "event": "load_start",
                "path":  str(self.root_path),
            },
        )

        self._load_errors.clear()
        self._read_root()

        grid_mm = float(self.root_data.get("grid_mm", DEFAULT_GRID_MM))
        self.root_sheet = Sheet(sheet_path="", grid_mm=grid_mm)
        self.sheets[""] = self.root_sheet

        self._load_components(self.root_sheet, self.root_data,
                              self.root_path)
        self._load_nets(self.root_sheet, self.root_data)
        self._log_components_with_nets(self.root_sheet)

        # Иерархия: листы, подключённые через X_* на корне.
        self._discover_sheets(self.root_sheet, self.root_data,
                              self.root_path)

        # Листы вне иерархии (без X_*): внешние силовые модули,
        # тестовые стенды — тоже должны стать .kicad_sch.
        # В main.yaml — список stem'ов: ['fan_driver_testbench', ...].
        self._load_standalone_sheets(
            self.root_data.get("standalone_sheets") or []
        )

        # Связность иерархии: каждый SheetRef должен быть подключён
        # хотя бы к одной цепи. Иначе он есть в схеме, но не в nets —
        # это либо опечатка в YAML, либо забытый узел. Прогон такого
        # проекта создаст «висящий» лист и несогласованный нетлист.
        self._check_sheet_refs_connected(self.root_sheet)

        # Никакого place_and_route, пока есть ошибки загрузки.
        if self._load_errors:
            raise ProjectLoadError(self._load_errors)

        total_components = sum(len(s.components) for s in self.sheets.values())
        total_pins = sum(
            len(c.pins)
            for s in self.sheets.values()
            for c in s.components.values()
        )
        total_nets = sum(len(s.netlist.nets) for s in self.sheets.values())
        log.info(
            "Загрузка завершена: листов %d, компонентов %d, сетей %d",
            len(self.sheets), total_components, total_nets,
            extra={
                "stage":   "load",
                "event":   "load_done",
                "project": self.root_data.get("project"),
                "counts": {
                    "sheets":     len(self.sheets),
                    "components": total_components,
                    "pins":       total_pins,
                    "nets":       total_nets,
                },
            },
        )
        return self

    def _read_root(self) -> None:
        """Читает main.yaml и сохраняет секцию root_page."""
        with open(self.root_path, encoding="utf-8") as f:
            doc = yaml.safe_load(f)
        self.root_data = doc["root_page"]
        log.debug(
            "root_page: project=%s, version=%s",
            self.root_data.get("project"),
            self.root_data.get("version"),
            extra={
                "stage":   "load",
                "event":   "root_page_read",
                "project": self.root_data.get("project"),
                "version": self.root_data.get("version"),
                "path":    str(self.root_path),
            },
        )

    # ---------- компоненты и сети ----------

    def _load_components(self, sheet: Sheet, data: dict,
                         yaml_path: Path) -> None:
        """Строит Component для всех записей data['components'].

        X_* (Core:Hierarchical_Sheet) не пропускаются — они создаются
        как SheetRefComponent: дают габарит, пины по портам дочернего
        YAML и место в placer.positions.

        После обычных компонентов добавляет PortComponent для каждой
        записи data['ports'] (порты страницы).

        Политика ошибок:
            - DesignatorError     — designator не проходит валидацию;
            - ComponentLoadError  — компонент в принципе не собирается
              (нет type / type не описан / нет symbol / symbol
              отсутствует в библиотеке);
            - отсутствие value_sch у X_* — ошибка конфигурации.

            Все ошибки накапливаются в self._load_errors и логируются
            на уровне ERROR с полным контекстом. Ветка comp is None —
            защита от будущих регрессий в Component.from_yaml; она
            тоже уходит в _load_errors, а не молча пропускается.
        """
        types = data.get("component_types", {})
        for designator, cdef in data.get("components", {}).items():
            if cdef.get("symbol") == Symbol.HIERARCHICAL_SHEET:
                self._add_sheet_ref(sheet, designator, cdef, yaml_path)
                continue

            try:
                comp = Component.from_yaml(
                    designator=designator,
                    cdef=cdef,
                    types=types,
                    source=self.source,
                    grid_mm=sheet.grid_mm,
                    page=sheet.page,
                )
            except DesignatorError as e:
                self._load_errors.append(
                    f"{yaml_path}: components.{designator}: {e}"
                )
                log.error(
                    "%s component_load_failed des=%s reason=%s",
                    ctx(page=sheet.page), designator, e,
                    extra={
                        "stage":     "load",
                        "event":     "component_load_failed",
                        "component": designator,
                        "reason":    "designator_invalid",
                    },
                )
                continue
            except ComponentLoadError as e:
                self._load_errors.append(f"{yaml_path}: {e}")
                log.error(
                    "%s component_load_failed des=%s type=%s symbol=%s "
                    "value=%s reason=%s hint=%s",
                    ctx(page=sheet.page), e.designator,
                    e.type_name, e.symbol, e.value, e.reason, e.hint,
                    extra={
                        "stage":     "load",
                        "event":     "component_load_failed",
                        "component": e.designator,
                        "type_name": e.type_name,
                        "symbol":    e.symbol,
                        "value":     e.value,
                        "reason":    e.reason,
                        "hint":      e.hint,
                    },
                )
                continue

            if comp is None:
                msg = (
                    f"{yaml_path}: components.{designator}: "
                    f"Component.from_yaml вернул None вместо Component "
                    f"(type={cdef.get('type')!r}, "
                    f"value={cdef.get('value')!r})"
                )
                self._load_errors.append(msg)
                log.error(
                    "%s component_load_returned_none des=%s type=%s value=%s",
                    ctx(page=sheet.page), designator,
                    cdef.get("type"), cdef.get("value"),
                    extra={
                        "stage":     "load",
                        "event":     "component_load_returned_none",
                        "component": designator,
                        "type_name": cdef.get("type"),
                        "value":     cdef.get("value"),
                    },
                )
                continue

            sheet.add_component(comp)

        # --- Порты страницы (data['ports']) ---
        self._load_ports(sheet, data, yaml_path)

    def _add_sheet_ref(self, sheet: Sheet, designator: str,
                       cdef: dict, yaml_path: Path) -> None:
        """Создаёт SheetRefComponent для X_* на текущем листе.

        value_sch — единственный источник имени дочернего YAML:
        <stem>.kicad_sch → <stem>.yaml (сохраняя подкаталог).
        Отсутствие value_sch — ошибка, X_* в схему не попадает.
        """
        value_sch = cdef.get("value_sch")
        if not value_sch:
            self._load_errors.append(
                f"{yaml_path}: components.{designator}: "
                f"нет value_sch — обязателен для Core:Hierarchical_Sheet"
            )
            log.error(
                "%s sheetref_no_value_sch des=%s",
                ctx(page=sheet.page), designator,
                extra={
                    "stage":     "load",
                    "event":     "sheetref_no_value_sch",
                    "component": designator,
                },
            )
            return

        # <stem>.kicad_sch → <stem>.yaml, каталог сохраняется
        sheet_file = str(Path(str(value_sch)).with_suffix(".yaml"))

        try:
            ref = SheetRefComponent.create(
                designator=designator,
                sheet_file=sheet_file,
                parent_yaml_path=yaml_path,
            )
        except DesignatorError as e:
            self._load_errors.append(
                f"{yaml_path}: components.{designator}: {e}"
            )
            log.error(
                "%s sheetref_load_failed des=%s reason=%s",
                ctx(page=sheet.page), designator, e,
                extra={
                    "stage":     "load",
                    "event":     "sheetref_load_failed",
                    "component": designator,
                    "reason":    "designator_invalid",
                },
            )
            return

        if ref is None:
            self._load_errors.append(
                f"{yaml_path}: components.{designator}: "
                f"SheetRefComponent.create вернул None "
                f"(value_sch={value_sch!r})"
            )
            log.error(
                "%s sheetref_returned_none des=%s value_sch=%s",
                ctx(page=sheet.page), designator, value_sch,
                extra={
                    "stage":     "load",
                    "event":     "sheetref_returned_none",
                    "component": designator,
                    "value":     value_sch,
                },
            )
            return

        sheet.add_component(ref)
        log.debug(
            "%s sheetref_added des=%s value_sch=%s pins=%d",
            ctx(page=sheet.page), designator, value_sch, len(ref.pins),
            extra={
                "stage":     "load",
                "event":     "sheetref_added",
                "component": designator,
                "value":     value_sch,
                "counts":    {"pins": len(ref.pins)},
            },
        )

    def _load_ports(self, sheet: Sheet, data: dict,
                    yaml_path: Path | None = None) -> None:
        """Создаёт PortComponent для каждого порта из data['ports']."""
        from port_component import PortComponent

        ports = data.get("ports", []) or []
        if not ports:
            return

        for p in ports:
            net_label = p.get("net_label", "")
            if not net_label:
                continue

            ptype = str(p.get("type", "INPUT")).upper()
            shape = p.get("shape") or _default_port_shape(ptype)
            side = "left" if ptype in ("INPUT", "POWER") else "right"

            designator = f"PORT_{net_label}"
            where = (f"{yaml_path}: ports.{net_label}"
                     if yaml_path else f"ports.{net_label}")

            try:
                port = PortComponent.create(
                    designator=designator,
                    net_name=net_label,
                    shape=shape,
                    side=side,
                )
            except DesignatorError as e:
                self._load_errors.append(f"{where}: {e}")
                log.error(
                    "%s port_load_failed des=%s net=%s reason=%s",
                    ctx(page=sheet.page), designator, net_label, e,
                    extra={
                        "stage":     "load",
                        "event":     "port_load_failed",
                        "component": designator,
                        "net":       net_label,
                        "reason":    "designator_invalid",
                    },
                )
                continue

            if port is None:
                self._load_errors.append(
                    f"{where}: порт не собран "
                    f"(net_label={net_label!r}, type={ptype!r})"
                )
                log.error(
                    "%s port_load_returned_none des=%s net=%s type=%s",
                    ctx(page=sheet.page), designator, net_label, ptype,
                    extra={
                        "stage":     "load",
                        "event":     "port_load_returned_none",
                        "component": designator,
                        "net":       net_label,
                        "port_type": ptype,
                    },
                )
                continue

            sheet.add_component(port)

            log.debug(
                "%s port_added des=%s side=%s shape=%s",
                ctx(page=sheet.page), port.designator, side, shape,
                extra={
                    "stage":     "load",
                    "event":     "port_added",
                    "component": port.designator,
                    "net":       net_label,
                    "side":      side,
                    "shape":     shape,
                    "port_type": ptype,
                },
            )

    def _load_nets(self, sheet: Sheet, data: dict) -> None:
        """Регистрирует сети листа и привязывает их FQN-пины."""
        for net_name, ndef in data.get("nets", {}).items():
            attrs = ndef.get("attributes", {})
            sheet.netlist.add_net(
                net_name,
                attrs.get("type", DEFAULT_NET_TYPE),
                list(attrs.keys()),
            )
        for net_name, ndef in data.get("nets", {}).items():
            for node in ndef.get("nodes", []):
                self._bind_node(sheet, net_name, node)

        self._bind_ports_to_nets(sheet, data)
        self._bind_sheet_refs_to_nets(sheet, data)
        self._check_all_pins_connected(sheet)

    def _check_all_pins_connected(self, sheet: Sheet) -> None:
        """Сводка пинов без цепи — WARNING, не ошибка.

        Пин, не упомянутый в nets:, — это сознательно неподключённый
        пин (NC, резерв, внешний порт). Такое поведение допустимо,
        загрузка НЕ прерывается.

        Ошибка возникает только в _bind_node: если пин УПОМЯНУТ в nets,
        но не найден в компоненте. Здесь же мы просто логируем список
        «висящих» пинов для справки — чтобы автор видел, что не забыл
        о них, но это не блокирует сборку.
        """
        unbound = []
        for designator, comp in sheet.components.items():
            for pin in comp.pins:
                if pin.net_ref is None:
                    unbound.append((designator, pin.number, pin.name or "—"))

        if not unbound:
            return

        log.warning(
            "%s pins_unbound count=%d",
            ctx(page=sheet.page), len(unbound),
            extra={
                "stage":   "load",
                "event":   "pins_unbound",
                "counts":  {"pins": len(unbound)},
                "pins": [
                    {"component": d, "pin": n, "pin_name": nm}
                    for d, n, nm in unbound
                ],
            },
        )

        for d, n, nm in unbound:
            log.warning(
                "%s pin_unbound des=%s pin=%s pin_name=%s",
                ctx(page=sheet.page), d, n, nm,
                extra={
                    "stage":     "load",
                    "event":     "pin_unbound",
                    "component": d,
                    "pin":       n,
                    "pin_name":  nm,
                },
            )

    def _bind_ports_to_nets(self, sheet: Sheet, data: dict) -> None:
        """Привязывает FQN пина каждого порта к его сети."""
        from port_component import PortComponent

        for comp in sheet.components.values():
            if not isinstance(comp, PortComponent):
                continue
            net = sheet.netlist.nets.get(comp.net_name)
            if net is None:
                log.warning(
                    "%s net_missing port=%s net=%s",
                    ctx(page=sheet.page), comp.designator, comp.net_name,
                    extra={
                        "stage":     "load",
                        "event":     "net_missing",
                        "component": comp.designator,
                        "net":       comp.net_name,
                    },
                )
                continue
            pin = comp.pins[0]
            fqn = f"{sheet.fqn(comp.designator)}:{pin.number}"
            sheet.netlist.assign_pin_to_net(fqn, comp.net_name, pin=pin)

            log.debug(
                "%s pin_bound port=%s pin=%s net=%s fqn=%s",
                ctx(page=sheet.page), comp.designator, pin.number,
                comp.net_name, fqn,
                extra={
                    "stage":     "load",
                    "event":     "pin_bound",
                    "component": comp.designator,
                    "pin":       pin.number,
                    "fqn":       fqn,
                    "net":       comp.net_name,
                    "kind":      "port",
                },
            )

    def _bind_sheet_refs_to_nets(self, sheet: Sheet, data: dict) -> None:
        """Привязывает FQN пинов SheetRef-ов к их сетям."""
        for comp in sheet.components.values():
            if not getattr(comp, "is_sheet_ref", False):
                continue

            for pin in comp.pins:
                net_name = pin.number  # для SheetRef номер = имя порта
                net = sheet.netlist.nets.get(net_name)
                if net is None:
                    log.debug(
                        "%s pin_unbound sheetref=%s pin=%s net=%s",
                        ctx(page=sheet.page), comp.designator,
                        pin.number, net_name,
                        extra={
                            "stage":     "load",
                            "event":     "pin_unbound",
                            "component": comp.designator,
                            "pin":       pin.number,
                            "net":       net_name,
                            "kind":      "sheet_ref",
                            "reason":    "net_not_found",
                        },
                    )
                    continue

                fqn = f"{sheet.fqn(comp.designator)}:{pin.number}"
                sheet.netlist.assign_pin_to_net(fqn, net_name, pin=pin)

                log.debug(
                    "%s pin_bound sheetref=%s pin=%s net=%s fqn=%s",
                    ctx(page=sheet.page), comp.designator, pin.number,
                    net_name, fqn,
                    extra={
                        "stage":     "load",
                        "event":     "pin_bound",
                        "component": comp.designator,
                        "pin":       pin.number,
                        "fqn":       fqn,
                        "net":       net_name,
                        "kind":      "sheet_ref",
                    },
                )

    def _bind_node(self, sheet: Sheet, net_name: str, node: dict) -> None:
        """Привязывает пин из YAML-узла к сети через FQN страницы.

        Узел задаётся одним из двух способов:
            {component: Q2, pin: '3'}          — по номеру вывода;
            {component: Q2, pinfunction: 'D'}  — по имени вывода в символе.

        Приоритет — «pin если задан, иначе pinfunction». Если заданы
        оба, pin выигрывает, но пишется WARNING: смешанная форма
        маскирует неоднозначность и её лучше избегать.

        Пропуски (компонента нет на листе, пина нет у компонента,
        заданы оба ключа, не задано ни одного) пишутся на уровне
        WARNING: это всегда индикатор проблемы загрузки — либо
        компонент не был добавлен (что ловится в _load_components),
        либо в YAML указан несуществующий пин / неоднозначный узел.
        """
        designator = node.get("component")
        if not designator:
            log.warning(
                "%s node_skipped net=%s reason=no_component_key node=%r",
                ctx(page=sheet.page), net_name, node,
                extra={
                    "stage":  "load",
                    "event":  "node_skipped",
                    "net":    net_name,
                    "reason": "no_component_key",
                },
            )
            return

        pin_no = node.get("pin")
        pin_fn = node.get("pinfunction")

        if pin_no is None and pin_fn is None:
             # Раньше был WARNING, теперь копим в _load_errors.
        # Ошибка не теряется, а блокирует load() в конце.
            self._load_errors.append(
                f"{sheet.page}: net={net_name}: {designator} "
                f"{key}={key_val!r} — пин не найден в символе "
                f"(доступные: {sorted(p.name for p in comp.pins if p.name) or '—'})"
            )
            return

        if pin_no is not None and pin_fn is not None:
            log.warning(
                "%s node_ambiguous des=%s net=%s pin=%s pinfunction=%s — "
                "используется pin, уберите лишний ключ",
                ctx(page=sheet.page), designator, net_name, pin_no, pin_fn,
                extra={
                    "stage":       "load",
                    "event":       "node_ambiguous",
                    "component":   designator,
                    "net":         net_name,
                    "pin":         str(pin_no),
                    "pinfunction": str(pin_fn),
                    "reason":      "both_keys",
                },
            )
            # pin выигрывает, продолжаем

        comp = sheet.get_component(designator)
        if comp is None:
            log.warning(
                "%s node_skipped des=%s net=%s reason=no_component",
                ctx(page=sheet.page), designator, net_name,
                extra={
                    "stage":     "load",
                    "event":     "node_skipped",
                    "component": designator,
                    "net":       net_name,
                    "reason":    "component_not_on_sheet",
                },
            )
            return

        # Приоритет: pin, иначе pinfunction
        if pin_no is not None:
            pin = comp.pin_by_number(str(pin_no))
            key, key_val = "pin", str(pin_no)
        else:
            pin = comp.pin_by_name(str(pin_fn))
            key, key_val = "pinfunction", str(pin_fn)

        if pin is None:
            log.warning(
                "%s node_skipped des=%s %s=%s net=%s reason=no_pin",
                ctx(page=sheet.page), designator, key, key_val, net_name,
                extra={
                    "stage":     "load",
                    "event":     "node_skipped",
                    "component": designator,
                    "net":       net_name,
                    "reason":    "pin_not_found",
                    key:         key_val,
                },
            )
            return

        fqn = pin.fqn
        try:
            sheet.netlist.assign_pin_to_net(fqn, net_name, pin=pin)
        except ValueError:
            log.warning(
                "%s net_missing net=%s fqn=%s",
                ctx(page=sheet.page), net_name, fqn,
                extra={
                    "stage":     "load",
                    "event":     "net_missing",
                    "component": designator,
                    "net":       net_name,
                    "fqn":       fqn,
                },
            )
        else:
            log.debug(
                "%s pin_bound des=%s %s=%s net=%s fqn=%s",
                ctx(page=sheet.page), designator, key, key_val, net_name, fqn,
                extra={
                    "stage":     "load",
                    "event":     "pin_bound",
                    "component": designator,
                    key:         key_val,
                    "fqn":       fqn,
                    "net":       net_name,
                    "kind":      "node",
                },
            )

    # ---------- сводка пинов с сетями ----------

    def _log_components_with_nets(self, sheet: Sheet) -> None:
        """Сводка: один компонент — одна строка."""
        for designator, comp in sheet.components.items():

            def _fmt_pin(pin) -> str:
                net = pin.net_ref or "-"
                parts = [f"{designator}.{pin.number}"]
                if pin.name:
                    parts.append(f"[{pin.name}]")
                parts.append(
                    f"off=({pin.offset_mm[Axis.X]:.2f},"
                    f"{pin.offset_mm[Axis.Y]:.2f})"
                )
                parts.append(f"net={net}")
                return " ".join(parts)

            pins_str = " | ".join(_fmt_pin(p) for p in comp.pins)
            line = (
                f"{designator} ({comp.name}) "
                f"{comp.bbox_cols}x{comp.bbox_rows} (cols x rows), "
                f"пинов {len(comp.pins)}"
            )
            if pins_str:
                line = f"{line} | {pins_str}"

            log.info(
                "%s component_summary %s",
                ctx(page=sheet.page), line,
                extra={
                    "stage":        "load",
                    "event":        "component_summary",
                    "component":    designator,
                    "comp_name":    comp.name,
                    "size": {
                        "cols": comp.bbox_cols,
                        "rows": comp.bbox_rows,
                    },
                    "counts":       {"pins": len(comp.pins)},
                    "is_sheet_ref": bool(getattr(comp, "is_sheet_ref", False)),
                    "pins": [
                        {
                            "number":    p.number,
                            "name":      p.name or None,
                            "offset_mm": {
                                "x": p.offset_mm[Axis.X],
                                "y": p.offset_mm[Axis.Y],
                            },
                            "net":       p.net_ref or None,
                        }
                        for p in comp.pins
                    ],
                },
            )

    # ---------- иерархические страницы ----------

    def _discover_sheets(self, parent: Sheet, data: dict,
                         parent_yaml_path: Path) -> None:
        """Находит ссылки Core:Hierarchical_Sheet и грузит их содержимое.

        SheetRefComponent для родителя создаётся в _load_components.
        Здесь читаются дочерние YAML и рекурсивно строятся Sheet.

        Правила:
          * yaml_rel выводится из value_sch: <stem>.kicad_sch → <stem>.yaml.
            Никакие 'value:' / 'file:' / 'page_name' из YAML не читаются.
          * Имя выходного .kicad_sch — всегда <stem>.kicad_sch.
          * Один YAML грузится один раз: повторный X_* (тот же
            value_sch) видит yaml_key в _loaded_yaml и пропускается.
          * Коллизия выходных имён между разными YAML — ошибка,
            иначе save() перезапишет лист.
        """
        for designator, cdef in data.get("components", {}).items():
            if cdef.get("symbol") != Symbol.HIERARCHICAL_SHEET:
                continue

            value_sch = cdef.get("value_sch")
            if not value_sch:
                # уже записано в _add_sheet_ref, но повторим, чтобы
                # не пытаться открыть YAML с пустым путём ниже
                continue

            yaml_rel = str(Path(str(value_sch)).with_suffix(".yaml"))
            yaml_path = (parent_yaml_path.parent / yaml_rel).resolve()
            yaml_key = str(yaml_path)

            if yaml_key in self._loaded_yaml:
                log.debug(
                    "%s sheet_reused des=%s value_sch=%s -> %s",
                    ctx(page=parent.page), designator, value_sch,
                    self._loaded_yaml[yaml_key],
                    extra={
                        "stage":     "load",
                        "event":     "sheet_reused",
                        "component": designator,
                        "child":     self._loaded_yaml[yaml_key],
                    },
                )
                continue

            if not yaml_path.exists():
                self._load_errors.append(
                    f"{parent_yaml_path}: components.{designator}: "
                    f"value_sch={value_sch!r} → нет {yaml_rel}"
                )
                log.error(
                    "%s sheet_missing des=%s value_sch=%s path=%s",
                    ctx(page=parent.page), designator, value_sch,
                    str(yaml_path),
                    extra={
                        "stage":     "load",
                        "event":     "sheet_missing",
                        "component": designator,
                        "path":      str(yaml_path),
                    },
                )
                continue

            with open(yaml_path, encoding="utf-8") as f:
                sub_data = yaml.safe_load(f) or {}

            sub_out = f"{yaml_path.stem}.kicad_sch"

            if sub_out in self.sheets:
                self._load_errors.append(
                    f"{parent_yaml_path}: {yaml_rel}: выходной файл "
                    f"{sub_out!r} уже используется листом "
                    f"{self.sheets[sub_out].sheet_path or '<root>'}"
                )
                log.error(
                    "%s sheet_collision des=%s child=%s",
                    ctx(page=parent.page), designator, sub_out,
                    extra={
                        "stage":     "load",
                        "event":     "sheet_collision",
                        "component": designator,
                        "child":     sub_out,
                    },
                )
                continue

            sub_grid = float(sub_data.get("grid_mm", DEFAULT_GRID_MM))
            sub_sheet = Sheet(sheet_path=sub_out, grid_mm=sub_grid)
            self.sheets[sub_out] = sub_sheet
            self._loaded_yaml[yaml_key] = sub_out

            self._load_components(sub_sheet, sub_data, yaml_path)
            self._load_nets(sub_sheet, sub_data)
            self._log_components_with_nets(sub_sheet)
            self._discover_sheets(sub_sheet, sub_data, yaml_path)

            log.debug(
                "%s sheet_loaded des=%s value_sch=%s components=%d",
                ctx(page=sub_sheet.page), designator, value_sch,
                len(sub_sheet.components),
                extra={
                    "stage":     "load",
                    "event":     "sheet_loaded",
                    "component": designator,
                    "path":      str(yaml_path),
                    "counts": {
                        "components": len(sub_sheet.components),
                        "pins": sum(len(c.pins)
                                    for c in sub_sheet.components.values()),
                        "nets": len(sub_sheet.netlist.nets),
                    },
                },
            )

    def _load_standalone_sheets(self, items: Iterable) -> None:
        """Грузит YAML-описания схем, не входящих в иерархию проекта.

        Формат элемента списка в main.yaml:
            standalone_sheets:
              - fan_driver_testbench            # stem (рекомендуется)
              - fan_driver_testbench.yaml       # допускается, эквивалентно
              - { stem: fan_driver_testbench }  # явная форма

        Резолв:
            sheets/<stem>.yaml    — всегда в SHEETS_DIR
                                    (parent от main.yaml).
            <stem>.kicad_sch      — имя выходного файла.
        """
        for item in items:
            if isinstance(item, dict):
                stem = item.get("stem") or item.get("id")
            else:
                stem = Path(str(item)).stem
            stem = (stem or "").strip()
            if not stem:
                self._load_errors.append(
                    f"standalone_sheets: пустой элемент {item!r}"
                )
                continue

            yaml_path = (self.root_path.parent / f"{stem}.yaml").resolve()
            yaml_key = str(yaml_path)

            if yaml_key in self._loaded_yaml:
                log.debug(
                    "standalone reused: %s -> %s",
                    stem, self._loaded_yaml[yaml_key],
                    extra={
                        "stage": "load",
                        "event": "standalone_reused",
                        "path":  str(yaml_path),
                    },
                )
                continue

            if not yaml_path.exists():
                self._load_errors.append(
                    f"standalone_sheets: {stem}: файл не найден "
                    f"({yaml_path})"
                )
                continue

            with open(yaml_path, encoding="utf-8") as f:
                sub_data = yaml.safe_load(f) or {}

            sub_out = f"{yaml_path.stem}.kicad_sch"

            if sub_out in self.sheets:
                self._load_errors.append(
                    f"standalone_sheets: {stem}: выходной файл "
                    f"{sub_out!r} уже используется листом "
                    f"{self.sheets[sub_out].sheet_path or '<root>'}"
                )
                continue

            sub_grid = float(sub_data.get("grid_mm", DEFAULT_GRID_MM))
            sub_sheet = Sheet(sheet_path=sub_out, grid_mm=sub_grid)
            self.sheets[sub_out] = sub_sheet
            self._loaded_yaml[yaml_key] = sub_out

            self._load_components(sub_sheet, sub_data, yaml_path)
            self._load_nets(sub_sheet, sub_data)
            self._log_components_with_nets(sub_sheet)
            self._discover_sheets(sub_sheet, sub_data, yaml_path)

            log.info(
                "%s standalone_loaded stem=%s components=%d nets=%d",
                ctx(page=sub_sheet.page), stem,
                len(sub_sheet.components), len(sub_sheet.netlist.nets),
                extra={
                    "stage": "load",
                    "event": "standalone_loaded",
                    "path":  str(yaml_path),
                    "counts": {
                        "components": len(sub_sheet.components),
                        "nets":       len(sub_sheet.netlist.nets),
                    },
                },
            )

    # ---------- проверки связности ----------

    def _check_sheet_refs_connected(self, sheet: Sheet) -> None:
        """SheetRef без единой привязанной цепи — вероятно, забыт в nets.

        Ошибки копятся в self._load_errors с путём к YAML и именем
        компонента, чтобы пользователь видел все орфаны сразу.
        """
        for comp in sheet.components.values():
            if not getattr(comp, "is_sheet_ref", False):
                continue
            if not comp.pins:
                # SheetRef без портов — сам по себе подозрителен, но
                # пустой YAML-лист формально валиден; это отдельный
                # случай, здесь не наш инвариант.
                continue
            if any(p.net_ref for p in comp.pins):
                continue
            self._load_errors.append(
                f"{sheet.page}: {comp.designator}: "
                f"ни один порт не привязан к цепи — "
                f"вероятно, X_* забыт в nets"
            )
            log.error(
                "%s sheet_ref_orphan des=%s",
                ctx(page=sheet.page), comp.designator,
                extra={
                    "stage":     "load",
                    "event":     "sheet_ref_orphan",
                    "component": comp.designator,
                },
            )

    # =========================================================
    # Размещение и роутинг
    # =========================================================

    def place_and_route(self) -> "Project":
        """Раскладывает и трассирует каждую страницу отдельно."""
        log.info(
            "Старт размещения и роутинга: страниц %d", len(self.sheets),
            extra={
                "stage":  "place",
                "event":  "place_start",
                "counts": {"sheets": len(self.sheets)},
            },
        )
        for sheet in self.sheets.values():
            self._place_and_route_sheet(sheet)
        return self

    def _place_and_route_sheet(self, sheet: Sheet) -> None:
        """Размещает и трассирует одну страницу."""
        log.info(
            "%s place_start components=%d",
            ctx(page=sheet.page), len(sheet.components),
            extra={
                "stage":  "place",
                "event":  "sheet_place_start",
                "counts": {"components": len(sheet.components)},
            },
        )

        placer = Placer(sheet)
        for comp in sheet.components.values():
            placer.register_component(comp)

        strategy_used = placer.auto_place()
        log.info(
            "%s place_strategy strategy=%s",
            ctx(page=sheet.page), strategy_used,
            extra={
                "stage":    "place",
                "event":    "place_strategy",
                "strategy": strategy_used,
            },
        )

        placer.all_overlaps()

        router = Router.from_placer(placer)
        wires = router.route_all()

        log.info(
            "%s route_done wires=%d labels=%d t_junctions=%d",
            ctx(page=sheet.page),
            len(wires), len(sheet.labels), len(sheet.t_junctions),
            extra={
                "stage": "route",
                "event": "route_done",
                "counts": {
                    "wires":       len(wires),
                    "labels":      len(sheet.labels),
                    "t_junctions": len(sheet.t_junctions),
                },
            },
        )

    # =========================================================
    # Сохранение
    # =========================================================

    def save(self, out_dir: str | Path = "out") -> Path:
        """Сохраняет .kicad_sch для каждой страницы + routes.txt."""
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        for sheet_path, sheet in self.sheets.items():
            if sheet_path == "":
                out_name = Path(
                    self.root_data.get("file", "root.kicad_sch")
                ).name
            else:
                out_name = sheet.sheet_path

            writer = Writer(sheet)
            writer.write_sheet(out_dir / out_name)
            log.info(
                "%s save_done out=%s",
                ctx(page=sheet.page), out_name,
                extra={
                    "stage": "save",
                    "event": "sheet_saved",
                    "out":   str(out_dir / out_name),
                },
            )

        routes = "\n".join(
            Writer(sheet).write_text() for sheet in self.sheets.values()
        )
        (out_dir / "routes.txt").write_text(routes, encoding="utf-8")
        log.info(
            "Сохранение завершено: %s", out_dir,
            extra={
                "stage":  "save",
                "event":  "save_done",
                "out":    str(out_dir),
                "counts": {"sheets": len(self.sheets)},
            },
        )
        return out_dir


# =========================================================
# Порты страницы: вспомогательное
# =========================================================

def _default_port_shape(ptype: str) -> str:
    """Форма hierarchical_label по типу порта из YAML."""
    return {
        "POWER": "passive",
        "GND": "passive",
        "INPUT": "input",
        "OUTPUT": "output",
        "BIDIR": "bidirectional",
        "ANALOG": "passive",
        "DIGITAL_SIGNAL": "input",
    }.get(ptype, "input")