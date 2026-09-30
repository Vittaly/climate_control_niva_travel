#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_pins_vs_xml.py — сверка узлов U1 в nets с официальным XML CubeMX.

Модель данных: единственный источник истины о том, какие пины МК
используются и как — секция `nets` в main.yaml. Секция `mcu_pin_map`
упразднена и не читается.

Узел U1 в nets описывается полями:
    pinfunction — имя вывода из символа KiCad ('PA13', 'VBAT', 'VREF+', ...)
    function    — короткая роль (необязательно): 'power_in', 'SWDIO', ...
    description — человекочитаемое описание логики (необязательно)

Сверка с XML CubeMX:
    * Имя из `pinfunction` нормализуется и ищется среди имён пинов XML.
    * Проверяется, что пин U1 не встречается больше чем в одной цепи.
    * Если у узла указан `pin` (номер) — он должен совпадать с позицией
      этого имени в XML.

Запуск:
    python3 check_pins_vs_xml.py
    python3 check_pins_vs_xml.py 'STM32G071R(6-8-B)Tx.xml' sheets/main.yaml
"""
import os
import sys
import xml.etree.ElementTree as ET

import yaml


# ─────────────────────────────────────────────────────────────────────
# Парсинг XML CubeMX
# ─────────────────────────────────────────────────────────────────────

def strip_ns(tag):
    return tag.split("}")[-1] if "}" in tag else tag


def norm(name):
    """'PF2 - NRST'→'PF2'; 'PA11 [PA9]'→'PA11'; 'PC14-OSC32_IN (PC14)'→'PC14'."""
    if name is None:
        return ""
    s = str(name).strip().strip("'\"")
    s = s.split("[", 1)[0]         # PA12 [PA10]
    s = s.split("/", 1)[0]         # PA13/SWDIO
    s = s.split("-", 1)[0]         # PF2 - NRST, PC15-OSC32_OUT
    s = s.split("(", 1)[0]         # ... (PC15)
    return s.strip()


def parse_xml(path):
    """Парсит CubeMX-XML, возвращает:
        by_pos        — {position(int): xml_name}
        by_name       — {norm(xml_name): [positions]}
        type_by_pos   — {position(int): 'I/O'|'Power'|'MonoIO'|'NC'}
        package, refname
    """
    tree = ET.parse(path)
    root = tree.getroot()

    package = root.attrib.get("Package", "")
    refname = root.attrib.get("RefName", "")

    by_pos = {}
    type_by_pos = {}
    is_variant = {}

    for el in root.iter():
        if strip_ns(el.tag) != "Pin":
            continue
        nm = el.attrib.get("Name")
        pos = el.attrib.get("Position")
        typ = el.attrib.get("Type", "")
        variant = el.attrib.get("Variant", "")
        if not nm or not pos:
            continue
        try:
            pos_i = int(pos)
        except (TypeError, ValueError):
            continue  # BGA-позиции пропускаем

        # Дубликат (Variant): невариантная запись имеет приоритет.
        if pos_i in by_pos:
            if variant:
                continue
            # пришла невариантная — перезаписываем
        by_pos[pos_i] = nm
        type_by_pos[pos_i] = typ
        is_variant[pos_i] = bool(variant)

    by_name = {}
    for pos, nm in by_pos.items():
        by_name.setdefault(norm(nm), []).append(pos)

    return by_pos, by_name, type_by_pos, package, refname


def find_xml():
    """Ищет STM32G0*.xml в текущем каталоге, приоритет — LQFP64 (RBTx/RB)."""
    candidates = [
        n for n in os.listdir(".")
        if n.endswith(".xml") and n.startswith("STM32G0")
    ]
    for n in candidates:
        if "RBTx" in n or "R(6-8-B)Tx" in n:
            return n
    for n in candidates:
        if "R" in n and "x" in n:
            return n
    return candidates[0] if candidates else None


# ─────────────────────────────────────────────────────────────────────
# Основная логика
# ─────────────────────────────────────────────────────────────────────

def collect_u1_nodes(nets: dict) -> dict:
    """Собирает узлы U1 из nets.

    Возвращает {key: {'pinfunction':..., 'pin':..., 'nets':[...]}},
    где key — нормализованное имя pinfunction (или '?pin=<n>' если
    pinfunction не задан).
    """
    used = {}
    for net_name, ndef in nets.items():
        for node in ndef.get("nodes") or []:
            if not isinstance(node, dict):
                continue
            if node.get("component") != "U1":
                continue
            pf = node.get("pinfunction")
            pn = node.get("pin")
            key = norm(pf) if pf else f"?pin={pn}"
            entry = used.setdefault(
                key,
                {"pinfunction": pf, "pin": pn, "nets": []},
            )
            entry["nets"].append(net_name)
        # при повторной встрече того же ключа сохраняем первый
        # непустой pinfunction/pin
    return used


def main():
    if len(sys.argv) > 1 and sys.argv[1].endswith(".xml"):
        xml_path = sys.argv[1]
        yaml_path = sys.argv[2] if len(sys.argv) > 2 else "sheets/climate_control_niva_travel.yaml"
    else:
        xml_path = find_xml()
        yaml_path = sys.argv[1] if len(sys.argv) > 1 else "sheets/main.yaml"

    if not xml_path or not os.path.exists(xml_path):
        print("XML не найден. Скачайте, например:")
        print("  curl -O 'https://raw.githubusercontent.com/"
              "STMicroelectronics/STM32_open_pin_data/master/mcu/"
              "STM32G071R(6-8-B)Tx.xml'")
        return 2

    print(f"XML:  {xml_path}")
    print(f"YAML: {yaml_path}")

    by_pos, by_name, type_by_pos, package, refname = parse_xml(xml_path)
    print(f"  RefName: {refname or '—'}")
    print(f"  Package: {package or '—'}")
    print(f"  пинов в LQFP64: {len(by_pos)}")

    if refname and not refname.startswith("STM32G0"):
        print(f"  !!! RefName={refname!r} — это не STM32G0.")
        print("      Для STM32G071RBT6 нужен STM32G071R(6-8-B)Tx.xml")
        return 2

    if by_pos:
        sample = ", ".join(
            f"{k}={by_pos[k]}" for k in sorted(by_pos)[:8]
        )
        print(f"  пример: {sample}")

    with open(yaml_path, encoding="utf-8") as f:
        doc = yaml.safe_load(f) or {}
    root = doc.get("root_page") or {}

    if "mcu_pin_map" in root:
        print("  ~ Внимание: mcu_pin_map в YAML присутствует, "
              "но больше не используется.")

    nets = root.get("nets") or {}
    used = collect_u1_nodes(nets)

    problems = []
    warnings = []
    infos = []

    # ─── Проверки по каждому узлу U1 ─────────────────────────────────
    for key in sorted(used):
        entry = used[key]
        label = entry["pinfunction"] or f"(pin={entry['pin']})"

        # A. pinfunction отсутствует
        if key.startswith("?pin="):
            problems.append(
                f"U1: узел без pinfunction (pin={entry['pin']}) "
                f"в цепях {entry['nets']}"
            )
            continue

        # B. Имени нет в XML
        if key not in by_name:
            problems.append(
                f"U1 pinfunction='{label}': нет такого пина в XML "
                f"(цепи {entry['nets']})"
            )
            continue

        positions = by_name[key]

        # C. Имя неоднозначно в XML
        if len(positions) > 1:
            warnings.append(
                f"U1 pinfunction='{label}': имя неоднозначно в XML, "
                f"позиции {positions} — сверка по pin пропущена"
            )
            xml_pos = positions[0]
        else:
            xml_pos = positions[0]

        # D. Если указан pin (номер) — должен совпадать с позицией
        if entry["pin"] is not None and len(positions) == 1:
            try:
                pn_int = int(entry["pin"])
            except (ValueError, TypeError):
                pn_int = None
            if pn_int is not None and pn_int != xml_pos:
                problems.append(
                    f"U1 pinfunction='{label}': указан pin="
                    f"{entry['pin']}, но в XML это позиция {xml_pos}"
                )
                continue

        # E. Пин в нескольких цепях
        if len(entry["nets"]) > 1:
            problems.append(
                f"U1 pinfunction='{label}': в нескольких цепях: "
                f"{entry['nets']}"
            )

        # F. Информация по спецпинам
        xml_name = by_pos[xml_pos]
        up = xml_name.upper()
        if any(t in up for t in ("OSC", "TAMPER")):
            infos.append(
                f"U1 pinfunction='{label}' ({xml_name}): спецпин "
                f"(OSC/TAMPER), ограничения при использовании как GPIO"
            )
        if "NRST" in up:
            infos.append(
                f"U1 pinfunction='{label}' ({xml_name}): NRST, "
                f"проверьте RC-цепь"
            )
        if "BOOT" in up:
            infos.append(
                f"U1 pinfunction='{label}' ({xml_name}): BOOT0, "
                f"подтяжка 10k к GND"
            )

    # ─── G. INFO: неиспользуемые GPIO из XML ─────────────────────────
    used_pos = set()
    for key in used:
        if key in by_name and len(by_name[key]) == 1:
            used_pos.add(by_name[key][0])

    unused = []
    for pos in sorted(by_pos):
        if pos in used_pos:
            continue
        nm = by_pos[pos]
        up = nm.upper()
        if any(up.startswith(p) for p in
               ("VDD", "VSS", "VBAT", "VREF", "VDDA", "VSSA")):
            continue
        if "NRST" in up or "BOOT" in up:
            continue
        unused.append(f"{pos}({norm(nm) or nm})")

    if unused:
        infos.append(
            "не используются в nets (GPIO из XML): " + ", ".join(unused)
        )

    # ─── Отчёт ───────────────────────────────────────────────────────
    print("=" * 76)
    if problems:
        print(f"  ПРОБЛЕМЫ ({len(problems)}):")
        for p in problems:
            print(f"  ! {p}")
    else:
        print("  ✓ проблем не найдено")
    if warnings:
        print(f"\n  ПРЕДУПРЕЖДЕНИЯ ({len(warnings)}):")
        for w in warnings:
            print(f"  ~ {w}")
    if infos:
        print(f"\n  ИНФО ({len(infos)}):")
        for i in infos:
            print(f"  i {i}")
    print("=" * 76)
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())