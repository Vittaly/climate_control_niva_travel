# make_scr/project.py
"""Корневая сущность: YAML -> компоненты/нетлист -> размещение -> трассы -> файлы.

Модель:
    - Sheet  — страница KiCad (.kicad_sch): components, netlist, grid_mm.
    - Placer — размещает на одной Sheet; читает sheet.netlist/grid_mm.
    - Router — трассирует одну Sheet; пишет в sheet.labels/t_junctions.
    - Writer — пишет .kicad_sch одной Sheet; читает sheet.grid_mm/netlist.
    - Project — оркестратор: грузит YAML, гоняет Placer/Router, сохраняет.

YAML живёт только внутри загрузки. Sheet о YAML не знает.
Нетлист — поле Sheet, у каждой страницы свой.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

import yaml

from component import Component
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
        # yaml_rel -> sheet_path: не грузим один YAML дважды
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
        self._discover_sheets(self.root_sheet, self.root_data)

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

        Args:
            sheet:     страница, в которую добавляются компоненты.
            data:      распарсенный YAML (локальный для загрузчика).
            yaml_path: путь к YAML — нужен SheetRefComponent, чтобы
                       найти дочерний YAML.
        """
        types = data.get("component_types", {})
        for designator, cdef in data.get("components", {}).items():
            if cdef.get("symbol") == Symbol.HIERARCHICAL_SHEET:
                # ссылка на вложенный лист — как компонент
                sheet_file = cdef.get("value", "")
                ref = SheetRefComponent.create(
                    designator=designator,
                    sheet_file=sheet_file,
                    parent_yaml_path=yaml_path,
                )
                sheet.add_component(ref)
                log.debug(
                    "%s sheetref_added des=%s file=%s pins=%d",
                    ctx(page=sheet.page), designator, sheet_file,
                    len(ref.pins),
                    extra={
                        "stage":     "load",
                        "event":     "sheetref_added",
                        "component": designator,
                        "value":     sheet_file,
                        "counts":    {"pins": len(ref.pins)},
                    },
                )
                continue

            try:
                comp = Component.from_yaml(
                    designator=designator,
                    cdef=cdef,
                    types=types,
                    source=self.source,
                    grid_mm=sheet.grid_mm,
                )
            except DesignatorError as e:
                # не добавляем в sheet и не роняем весь цикл —
                # соберём все ошибки и упадём одним списком
                self._load_errors.append(
                    f"{yaml_path}: components.{designator}: {e}"
                )
                continue

            if comp:
                sheet.add_component(comp)

        # --- Порты страницы (data['ports']) ---
        self._load_ports(sheet, data, yaml_path)

    def _load_ports(self, sheet: Sheet, data: dict,
                    yaml_path: Path | None = None) -> None:
        """Создаёт PortComponent для каждого порта из data['ports'].

        Сети ещё не зарегистрированы в netlist (это делает _load_nets
        сразу после), поэтому FQN пинов регистрируются отдельно —
        в _load_nets, где все сети уже есть.

        Ошибки именования порта (не PORT_<NET>, пустой net_name)
        не роняют загрузку сразу, а копятся в self._load_errors:
        Project.load() в конце бросит ProjectLoadError со списком.
        Так пользователь видит сразу все проблемы, а не по одной.

        Args:
            sheet:     страница, в которую добавляются порты.
            data:      распарсенный YAML (локальный для загрузчика).
            yaml_path: путь к YAML — для читаемых сообщений об ошибках.
        """
        from port_component import PortComponent

        ports = data.get("ports", []) or []
        if not ports:
            return

        for p in ports:
            net_label = p.get("net_label", "")
            if not net_label:
                # молча пропускаем, как и раньше: у порта без net_label
                # нет смысла в designator'е
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
                continue

            if port is None:
                self._load_errors.append(
                    f"{where}: порт не собран "
                    f"(net_label={net_label!r}, type={ptype!r})"
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
        """Регистрирует сети листа и привязывает их FQN-пины.

        Здесь же — регистрация пинов портов и пинов SheetRef
        (вложенных листов): к этому моменту все сети уже добавлены
        в sheet.netlist, и FQN можно безопасно привязать.
        """
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

        # --- Пины портов: регистрация в сетях ---
        self._bind_ports_to_nets(sheet, data)

        # --- Пины SheetRef: регистрация в сетях ---
        self._bind_sheet_refs_to_nets(sheet, data)

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
        """Привязывает пин из YAML-узла к сети через FQN страницы."""
        designator = node["component"]
        pin_no = str(node["pin"])

        comp = sheet.get_component(designator)
        if comp is None:
            log.debug(
                "%s node_skipped des=%s pin=%s net=%s reason=no_component",
                ctx(page=sheet.page), designator, pin_no, net_name,
                extra={
                    "stage":     "load",
                    "event":     "node_skipped",
                    "component": designator,
                    "pin":       pin_no,
                    "net":       net_name,
                    "reason":    "component_not_on_sheet",
                },
            )
            return

        pin = comp.pin_by_number(pin_no)
        if pin is None:
            log.debug(
                "%s node_skipped des=%s pin=%s net=%s reason=no_pin",
                ctx(page=sheet.page), designator, pin_no, net_name,
                extra={
                    "stage":     "load",
                    "event":     "node_skipped",
                    "component": designator,
                    "pin":       pin_no,
                    "net":       net_name,
                    "reason":    "pin_not_found",
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
                    "pin":       pin_no,
                    "fqn":       fqn,
                    "net":       net_name,
                },
            )
        else:
            log.debug(
                "%s pin_bound des=%s pin=%s net=%s fqn=%s",
                ctx(page=sheet.page), designator, pin_no, net_name, fqn,
                extra={
                    "stage":     "load",
                    "event":     "pin_bound",
                    "component": designator,
                    "pin":       pin_no,
                    "fqn":       fqn,
                    "net":       net_name,
                    "kind":      "node",
                },
            )

    # ---------- сводка пинов с сетями ----------

    def _log_components_with_nets(self, sheet: Sheet) -> None:
        """Сводка: один компонент — одна строка.

        Пины идут inline в формате:
            <des>.<pin> [<pin_name>] off=(x,y) net=<net>
        Имя пина печатается только если оно непустое. Полный
        структурированный список пинов уходит в extra["pins"].
        """
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

    def _discover_sheets(self, parent: Sheet, data: dict) -> None:
        """Находит ссылки Core:Hierarchical_Sheet и грузит их содержимое.

        ВАЖНО: SheetRefComponent для родителя создаётся отдельно —
        в _load_components. Здесь мы только читаем дочерние YAML
        и рекурсивно строим для них Sheet-объекты.

        Ключ в self.sheets — имя выходного .kicad_sch. Один YAML
        грузится ровно один раз: второй инстанс (X2 того же sub.yaml)
        видит, что yaml_rel уже в _loaded_yaml, и пропускается.
        """
        for designator, cdef in data.get("components", {}).items():
            if cdef.get("symbol") != Symbol.HIERARCHICAL_SHEET:
                continue

            yaml_rel = str(cdef["value"])
            yaml_path = self.base_dir / yaml_rel

            # --- уже грузили этот YAML? просто пропускаем ---
            if yaml_rel in self._loaded_yaml:
                log.debug(
                    "%s sheet_reused des=%s file=%s -> %s",
                    ctx(page=parent.page), designator, yaml_rel,
                    self._loaded_yaml[yaml_rel],
                    extra={
                        "stage":     "load",
                        "event":     "sheet_reused",
                        "component": designator,
                        "child":     self._loaded_yaml[yaml_rel],
                    },
                )
                continue

            if not yaml_path.exists():
                log.warning(
                    "%s sheet_missing des=%s file=%s path=%s",
                    ctx(page=parent.page), designator, yaml_rel,
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
                sub_data = yaml.safe_load(f)

            # имя выходного .kicad_sch: data["file"] или <stem>.kicad_sch
            sub_out = Path(
                sub_data.get("file", f"{Path(yaml_rel).stem}.kicad_sch")
            ).name
            sub_grid = float(sub_data.get("grid_mm", DEFAULT_GRID_MM))

            sub_sheet = Sheet(sheet_path=sub_out, grid_mm=sub_grid)
            self.sheets[sub_out] = sub_sheet
            self._loaded_yaml[yaml_rel] = sub_out

            self._load_components(sub_sheet, sub_data, yaml_path)
            self._load_nets(sub_sheet, sub_data)
            self._log_components_with_nets(sub_sheet)
            self._discover_sheets(sub_sheet, sub_data)

            log.debug(
                "%s sheet_loaded des=%s file=%s components=%d",
                ctx(page=sub_sheet.page), designator, yaml_rel,
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
        """Размещает и трассирует одну страницу.

        SheetRef-компоненты (X_*) попадают в placer как обычные
        компоненты: у них есть bbox_size и pins — Placer сам их
        разложит.
        """
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

        # routes.txt — сводка по всем страницам, склеенная построчно.
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