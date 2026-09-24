#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mcu_model.py — генератор SPICE-модели STM32F103RCT6 по сценарию.

Файл лежит в корне проекта. Хелпер с электрикой кремния —
spice/lib/stm32f103rc_helpers.lib (рукописный, не трогается).

Что делает:
  * Читает sheets/main.yaml → mcu_pin_map (какие пины задействованы
    в проекте, их направление, куда подключены).
  * Находит в main.yaml:spice.models модель с маркером auto_ports
    (сейчас — одна, STM32F103RCT6).
  * Читает sheets/<stem>.yaml → scenarios (какие сценарии есть,
    какие пины трогает каждый из них через mcu_state / connect).
  * Для каждого сценария, который реально дёргает МК, пишет
    spice/<scenario>_mcu.sub — субсхему STM32F103RCT6, в которой
    инстанцированы ТОЛЬКО задействованные шаблоны (output/input/
    analog из хелпера). Никаких 20 B-источников вхолостую.

Формат вывода: spice/<scenario>_mcu.sub
    .INCLUDE spice/lib/stm32f103rc_helpers.lib
    .subckt STM32F103RCT6 <все порты из mcu_pin_map>
      ...
    .ends

Порты субсхемы стабильны (все net из mcu_pin_map), но внутри —
только те X-инстансы, что нужны сценарию. Незадействованные
порты остаются заглушками: ни резисторов, ни ёмкостей, ни
B-источников, никакой работы на каждом шаге интегрирования.

Запуск:
    python3 mcu_model.py                # только сгенерировать
    python3 mcu_model.py --list         # показать, что будет сделано
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, Iterable, Optional

import yaml


PROJ = Path(__file__).resolve().parent
MAIN_YAML_DEFAULT = PROJ / "sheets" / "main.yaml"
SHEETS_DIR_DEFAULT = PROJ / "sheets"
SPICE_DIR_DEFAULT = PROJ / "spice"

# Путь к хелперу — относительно корня проекта (оттуда запускается ngspice).
HELPERS_REL = "spice/lib/stm32f103rc_helpers.lib"

MCU_MODEL_NAME = "STM32F103RCT6"


# ─────────────────────────────────────────────────────────────────────
# Загрузка
# ─────────────────────────────────────────────────────────────────────

def load_main(main_yaml: Path = MAIN_YAML_DEFAULT) -> dict:
    return yaml.safe_load(open(main_yaml, encoding="utf-8"))["root_page"]


def iter_sheets(main_cfg: dict,
                sheets_dir: Path = SHEETS_DIR_DEFAULT
                ) -> Iterable[tuple[str, dict]]:
    """Все stem'ы листов проекта (иерархические + standalone).

    Yield (stem, sheet_data). Файл читается, если существует.
    Список выводится так же, как в run_e2e.py: по value_sch
    из components.X_* и по standalone_sheets.
    """
    stems = set()

    for c in (main_cfg.get("components") or {}).values():
        if c.get("symbol") == "Core:Hierarchical_Sheet" and c.get("value_sch"):
            stems.add(Path(c["value_sch"]).stem)

    for item in (main_cfg.get("standalone_sheets") or []):
        if isinstance(item, dict):
            stems.add(item.get("stem") or item.get("id"))
        else:
            stems.add(Path(str(item)).stem)

    for stem in sorted(s for s in stems if s):
        yml = sheets_dir / f"{stem}.yaml"
        if not yml.exists():
            continue
        data = yaml.safe_load(open(yml, encoding="utf-8")) or {}
        yield stem, data


# ─────────────────────────────────────────────────────────────────────
# mcu_pin_map: представления
# ─────────────────────────────────────────────────────────────────────

def mcu_signals(main_cfg: dict) -> Dict[str, dict]:
    """{signal: {num, net, direction, ...}} — только пины с net."""
    out = {}
    for num, p in (main_cfg.get("mcu_pin_map") or {}).items():
        if not p.get("net"):
            continue
        sig = p.get("signal")
        if not sig:
            continue
        out[sig] = {
            "num": num,
            "net": p["net"],
            "direction": p.get("direction"),
            "pull": p.get("pull", "none"),
            "output_mode": p.get("output_mode", "push_pull"),
            "r_out_ohm": p.get("r_out_ohm"),
        }
    return out


def mcu_ports(main_cfg: dict) -> list[str]:
    """Все порты субсхемы — уникальные net из mcu_pin_map, по номеру пина.

    Тот же порядок обязателен в kicad_to_spice.py, когда он строит
    строку XU1 в .cir. Оба места читают mcu_pin_map и итерируют
    одинаково — sorted по int(num).
    """
    ports = []
    seen = set()
    for num in sorted((main_cfg.get("mcu_pin_map") or {}),
                      key=lambda x: int(x)):
        net = main_cfg["mcu_pin_map"][num].get("net")
        if not net or net in seen:
            continue
        seen.add(net)
        ports.append(net)
    return ports


# ─────────────────────────────────────────────────────────────────────
# Какие сценарии трогают МК и какие пины
# ─────────────────────────────────────────────────────────────────────

def mcu_model_names(main_cfg: dict) -> set[str]:
    """Имена моделей корня с маркером auto_ports — сейчас это один МК.

    Читает main.yaml:spice.models (корневой реестр). auto_ports —
    маркер «порты выводятся из mcu_pin_map, а не из nodes».
    """
    models = (main_cfg.get("spice") or {}).get("models") or {}
    return {name for name, m in models.items()
            if isinstance(m, dict) and m.get("auto_ports")}


def scenario_uses_mcu(scenario: dict, mcu_models: set[str]) -> bool:
    for entry in (scenario.get("deck") or []):
        for kind, body in entry.items():
            if kind == "subckt" and body.get("model") in mcu_models:
                return True
    return False


def signals_used_by_scenario(main_cfg: dict, scenario: dict) -> set[str]:
    """Объединение mcu_state и connect этого сценария."""
    sig_by_net = {p["net"]: sig for sig, p in mcu_signals(main_cfg).items()}
    used: set[str] = set()

    for sig in (scenario.get("mcu_state") or {}):
        used.add(sig)

    for entry in (scenario.get("deck") or []):
        for kind, body in entry.items():
            if kind != "subckt":
                continue
            for port_net in (body.get("connect") or {}):
                sig = sig_by_net.get(port_net)
                if sig:
                    used.add(sig)

    return used


# ─────────────────────────────────────────────────────────────────────
# Выбор шаблона
# ─────────────────────────────────────────────────────────────────────

# Какие аргументы у шаблонов (порядок как в _stm32_*.subckt в хелпере).
_TEMPLATE_ARGS = {
    "_stm32_out":      ("pin", "vdd", "vss"),
    "_stm32_out_pwm":  ("pin", "vdd", "vss"),
    "_stm32_od":       ("pin", "vss"),
    "_stm32_od_pwm":   ("pin", "vss"),
    "_stm32_in":       ("pin", "vss"),
    "_stm32_in_pu":    ("pin", "vdd", "vss"),
    "_stm32_in_pd":    ("pin", "vss"),
    "_stm32_boot0":    ("pin", "vss"),
    "_stm32_ain":      ("pin", "vss"),
}


def shape_for(sig: str, pin: dict, state) -> tuple[str, dict]:
    """(имя шаблона, params) для одного пина.

    state — значение из scenario.mcu_state[sig], либо None.
      * int 0/1           — статический output;
      * {"pwm": {...}}    — ШИМ-output;
      * None              — не задан, дефолт STATE=0.
    """
    direction = pin["direction"]

    if sig == "BOOT0":
        return "_stm32_boot0", {}

    if direction == "output":
        mode = pin.get("output_mode", "push_pull")
        is_pwm = isinstance(state, dict) and "pwm" in state
        if is_pwm:
            tpl = ("_stm32_out_pwm" if mode == "push_pull"
                   else "_stm32_od_pwm")
            p = state["pwm"]
            params = {
                "FREQ":  p["freq_hz"],
                "DUTY":  p["duty"],
                "PHASE": p.get("phase", 0),
            }
            return tpl, params
        tpl = "_stm32_out" if mode == "push_pull" else "_stm32_od"
        val = int(state) if state is not None else 0
        return tpl, {"STATE": val}

    if direction in ("input", "bidir"):
        pull = pin.get("pull", "none")
        tpl = {"none": "_stm32_in",
               "up":   "_stm32_in_pu",
               "down": "_stm32_in_pd"}[pull]
        return tpl, {}

    if direction == "analog_in":
        return "_stm32_ain", {}

    raise ValueError(
        f"signal {sig!r}: direction={direction!r} не поддержан"
    )


def _emit_instance(sig: str, pin: dict, tpl: str, params: dict) -> str:
    """Строка X-инстанса шаблона."""
    args = []
    for arg in _TEMPLATE_ARGS[tpl]:
        if arg == "pin":
            args.append(pin["net"])
        elif arg == "vdd":
            args.append("VDD_INT")
        elif arg == "vss":
            args.append("VSS_INT")
    pstr = ""
    if params:
        pstr = " " + " ".join(f"{k}={v}" for k, v in params.items())
    return f"X{sig}_{tpl.lstrip('_')} {' '.join(args)} {tpl}{pstr}"


# ─────────────────────────────────────────────────────────────────────
# Генерация одного сценария
# ─────────────────────────────────────────────────────────────────────

def generate_scenario(main_cfg: dict, stem: str, scenario: dict,
                      out_dir: Path = SPICE_DIR_DEFAULT) -> Optional[Path]:
    """Сгенерировать spice/<scenario>_mcu.sub. None, если МК не нужен."""
    mcu_models = mcu_model_names(main_cfg)
    if not mcu_models:
        return None
    if not scenario_uses_mcu(scenario, mcu_models):
        return None

    sigs = mcu_signals(main_cfg)
    ports = mcu_ports(main_cfg)
    state = scenario.get("mcu_state") or {}
    sname = scenario["name"]

    # --- валидации ---
    outputs = {s for s, p in sigs.items() if p["direction"] == "output"}
    bad_state = set(state) - outputs
    if bad_state:
        raise ValueError(
            f"{stem}/{sname}: mcu_state задан для не-выходных пинов: "
            f"{sorted(bad_state)}"
        )

    used = signals_used_by_scenario(main_cfg, scenario)
    missing = used - set(sigs)
    if missing:
        raise ValueError(
            f"{stem}/{sname}: mcu_state/connect ссылается на сигналы "
            f"вне mcu_pin_map (или без net): {sorted(missing)}"
        )

    # --- сборка ---
    lines = [
        f"* {MCU_MODEL_NAME} subset для сценария {sname} ({stem})",
        f"* Сгенерировано mcu_model.py. НЕ редактировать вручную.",
        f"* Задействованных пинов: {len(used)}.",
        "",
        f".INCLUDE {HELPERS_REL}",
        "",
        f".subckt {MCU_MODEL_NAME}",
        "+ " + " ".join(ports),
        "",
        "* --- склейка питания в VDD_INT / VSS_INT ---",
    ]

    vdd_seen, vss_seen = set(), set()
    for sig, p in sigs.items():
        if p["direction"] != "power":
            continue
        net = p["net"]
        if sig.startswith("VDD") or sig == "VBAT":
            if net not in vdd_seen:
                vdd_seen.add(net)
                lines.append(f"R_VDD_{sig}  {net}  VDD_INT  R_STUB_PWR")
        elif sig.startswith("VSS") or sig == "VSSA":
            if net not in vss_seen:
                vss_seen.add(net)
                lines.append(f"R_VSS_{sig}  {net}  VSS_INT  R_STUB_PWR")

    lines.append("")
    lines.append("* --- задействованные сценарием пины ---")

    for sig in sorted(used):
        p = sigs[sig]
        if p["direction"] == "power":
            continue  # уже обработано
        tpl, params = shape_for(sig, p, state.get(sig))
        lines.append(_emit_instance(sig, p, tpl, params))

    lines.append("")
    lines.append(f".ends {MCU_MODEL_NAME}")

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{sname}_mcu.sub"
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_path


# ─────────────────────────────────────────────────────────────────────
# Полный проход
# ─────────────────────────────────────────────────────────────────────

def generate_all(main_yaml: Path = MAIN_YAML_DEFAULT,
                 out_dir: Path = SPICE_DIR_DEFAULT,
                 list_only: bool = False) -> int:
    """Сгенерировать .sub для всех сценариев, где встречается МК.

    Возвращает число сгенерированных файлов.
    """
    sheets_dir = main_yaml.parent
    main_cfg = load_main(main_yaml)
    count = 0

    for stem, sheet_data in iter_sheets(main_cfg, sheets_dir):
        for sc in (sheet_data.get("scenarios") or []):
            if list_only:
                mcu_models = mcu_model_names(main_cfg)
                if scenario_uses_mcu(sc, mcu_models):
                    used = signals_used_by_scenario(main_cfg, sc)
                    print(f"  {stem}/{sc['name']}: {len(used)} пинов")
                continue
            path = generate_scenario(main_cfg, stem, sc, out_dir)
            if path:
                used = signals_used_by_scenario(main_cfg, sc)
                rel = path.relative_to(PROJ) if path.is_relative_to(PROJ) else path
                print(f"OK -> {rel} ({len(used)} пинов)")
                count += 1

    if not list_only and count == 0:
        print("Сценариев с MCU не найдено.")
    return count


def main(argv: list[str]) -> int:
    list_only = "--list" in argv
    try:
        generate_all(list_only=list_only)
    except (ValueError, FileNotFoundError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))