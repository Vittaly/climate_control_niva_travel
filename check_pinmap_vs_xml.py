#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_pinmap_vs_xml.py — сверка main.yaml с XML STM32F103R(C-D-E)Tx.xml.

Структура XML (плоская):
  <Mcu>
    <Pin Name="VBAT" Position="1" Type="Power"/>
    <Pin Name="PC14-OSC32_IN" Position="3" Type="I/O">
       <Signal Name="GPIO"/>
       <Signal Name="RCC_OSC32_IN"/>
       ...
    </Pin>
    ...
  </Mcu>

Проверки:
  1. Позиция (1..64) есть в XML.
  2. Норм. имя слева от '->' совпадает с норм. именем пина XML.
  3. Каждый U1-пин в nets описан в mcu_pin_map.
  4. Ни один U1-пин не в нескольких цепях.
  5. INFO: пины с 'OSC'/'OSC32'/'TAMPER' в имени — специальные,
     проверить, что кварц не нужен.

Запуск:
    python3 check_pinmap_vs_xml.py
    python3 check_pinmap_vs_xml.py "STM32F103R(C-D-E)Tx.xml" main.yaml
"""
import os
import re
import sys
import xml.etree.ElementTree as ET

import yaml


def strip_ns(tag):
    return tag.split("}")[-1] if "}" in tag else tag


def norm(name):
    """'PA13/SWDIO'→'PA13'; 'PC14-OSC32_IN'→'PC14'; 'VSS_1'→'VSS_1'."""
    if name is None:
        return ""
    s = str(name).strip().strip("'\"")
    s = s.split("/", 1)[0]
    s = s.split("-", 1)[0]
    return s


def parse_xml(path):
    """Плоский поиск <Pin Name=... Position=...>. Возвращает (by_pos, name_funcs)."""
    tree = ET.parse(path)
    root = tree.getroot()
    by_pos = {}
    name_funcs = {}
    for el in root.iter():
        if strip_ns(el.tag) != "Pin":
            continue
        nm = el.attrib.get("Name")
        pos = el.attrib.get("Position")
        if not nm:
            continue
        # позиция: '1'..'64' — LQFP, 'A1'.. — BGA (пропускаем)
        try:
            pos_i = int(pos)
        except (TypeError, ValueError):
            continue
        by_pos[pos_i] = nm
        funcs = set()
        for sub in el.iter():
            if strip_ns(sub.tag) == "Signal":
                s = sub.attrib.get("Name")
                if s:
                    funcs.add(s)
        name_funcs[nm] = funcs
    return by_pos, name_funcs


def yaml_left(v):
    s = str(v).strip()
    if "->" in s:
        s = s.split("->", 1)[0]
    parts = s.split()
    return parts[0] if parts else ""


def find_xml():
    best = None
    for name in os.listdir("."):
        if not (name.startswith("STM32F103R") and name.endswith(".xml")):
            continue
        if "C-D-E" in name and "Tx" in name:
            return name
        if best is None:
            best = name
    return best


def main():
    if len(sys.argv) > 1 and sys.argv[1].endswith(".xml"):
        xml_path = sys.argv[1]
        yaml_path = sys.argv[2] if len(sys.argv) > 2 else "main.yaml"
    else:
        xml_path = find_xml()
        yaml_path = sys.argv[1] if len(sys.argv) > 1 else "main.yaml"

    if not xml_path or not os.path.exists(xml_path):
        print("XML не найден. Скачайте:")
        print("  curl -O 'https://raw.githubusercontent.com/"
              "STMicroelectronics/STM32_open_pin_data/master/mcu/"
              "STM32F103R(C-D-E)Tx.xml'")
        return 2

    print(f"XML:  {xml_path}")
    print(f"YAML: {yaml_path}")

    by_pos, name_funcs = parse_xml(xml_path)
    print(f"  пинов в XML: {len(by_pos)}")
    if by_pos:
        sample = ", ".join(f"{k}={by_pos[k]}"
                           for k in sorted(by_pos)[:5])
        print(f"  пример: {sample}")

    with open(yaml_path, encoding="utf-8") as f:
        doc = yaml.safe_load(f) or {}
    root = doc.get("root_page") or {}
    mcu = root.get("mcu_pin_map") or {}
    nets = root.get("nets") or {}

    problems = []
    infos = []

    # --- 1+2: позиция и имя ---
    for k, v in mcu.items():
        try:
            pos = int(k)
        except (ValueError, TypeError):
            problems.append(f"mcu_pin_map[{k!r}]: ключ не число")
            continue
        if pos not in by_pos:
            problems.append(f"mcu_pin_map[{k!r}]: нет в LQFP64")
            continue
        xml_name = by_pos[pos]
        yaml_name = yaml_left(v)
        if norm(xml_name) != norm(yaml_name):
            problems.append(
                f"mcu_pin_map[{k!r}]: yaml '{yaml_name}' != xml '{xml_name}'")
            continue
        # спецпины
        if any(t in xml_name for t in ("OSC", "TAMPER")):
            infos.append(
                f"mcu_pin_map[{k!r}]: '{xml_name}' — спецпин "
                f"(OSC/TAMPER). Использование как GPIO возможно, "
                f"но с ограничениями (не одновременно с кварцем, "
                f"ограниченный ток на PC13/14/15).")

    # --- 3: U1-пины в nets должны быть в mcu_pin_map ---
    used = {}
    for net, info in nets.items():
        for n in info.get("nodes") or []:
            if isinstance(n, dict) and n.get("component") == "U1":
                used.setdefault(str(n["pin"]), []).append(net)

    for pin in sorted(used, key=int):
        if pin not in mcu:
            problems.append(
                f"nets: U1.{pin} используется в {used[pin]}, "
                f"но не описан в mcu_pin_map")

    # --- 4: один U1-пин — не более одной цепи ---
    for pin, where in sorted(used.items(), key=lambda kv: int(kv[0])):
        if len(where) > 1:
            problems.append(
                f"nets: U1.{pin} в нескольких цепях: {where}")

    # --- 5: U1-пины в mcu_pin_map, но не используемые в nets ---
    # (не проблема, но полезно видеть)
    for pin in sorted(mcu, key=int):
        if pin not in used:
            xml_name = by_pos.get(int(pin), "?")
            # отдельно отметить питание/землю/BOOT0/NRST — их
            # в nets.mcu_pin_map может быть не видно (они в VCC/GND)
            if not any(t in xml_name.upper()
                       for t in ("VSS", "VDD", "VBAT", "VDDA", "BOOT0")):
                infos.append(
                    f"mcu_pin_map[{pin!r}] = {xml_name}: "
                    f"в цепях U1 не встречается")

    print("=" * 76)
    if problems:
        print(f"  ПРОБЛЕМЫ ({len(problems)}):")
        for p in problems:
            print(f"  ! {p}")
    else:
        print("  ✓ проблем не найдено")
    if infos:
        print(f"\n  ИНФО ({len(infos)}):")
        for i in infos:
            print(f"  i {i}")
    print("=" * 76)
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())