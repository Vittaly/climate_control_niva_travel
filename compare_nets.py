#!/usr/bin/env python3
"""
Автоматическое сравнение цепей:
  1. Нетлист SKiDL (netlist_out/MAIN_ROOT.xml)
  2. Нетлист KiCad (экспорт через kicad-cli sch export netlist)

Никакого ручного экспорта не требуется.
"""
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
SKIDL_NETLIST = BASE_DIR / '.netlist_out' / 'MAIN_ROOT.xml'
KICAD_SCH = BASE_DIR / 'climate_control_niva_travel.kicad_sch'
KICAD_NETLIST = BASE_DIR / 'netlist_out' / 'kicad_export.net'


# ============================================================
#  ЭКСПОРТ НЕТЛИСТА ИЗ KICAD
# ============================================================

def export_kicad_netlist(sch_path, out_path):
    """Экспорт нетлиста через kicad-cli."""
    if not sch_path.exists():
        print(f'[ОШИБКА] Схема не найдена: {sch_path}')
        return False

    # kicad-cli может быть под разными именами в зависимости от версии
    candidates = ['kicad-cli', 'kicad-cli-10', 'kicad-cli-9']
    cli = None
    for c in candidates:
        if subprocess.run(['which', c], capture_output=True).returncode == 0:
            cli = c
            break

    if not cli:
        print('[ОШИБКА] kicad-cli не найден в PATH.')
        print('         Установите KiCad или добавьте его bin/ в PATH.')
        return False

    out_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [cli, 'sch', 'export', 'netlist',
           '--format', 'kicadxml',
           '--output', str(out_path),
           str(sch_path)]

    print(f'[kicad-cli] {cli} sch export netlist ...')
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f'[ОШИБКА] kicad-cli вернул код {result.returncode}')
        print(f'  stdout: {result.stdout}')
        print(f'  stderr: {result.stderr}')
        return False

    if not out_path.exists():
        print(f'[ОШИБКА] kicad-cli завершился успешно, но {out_path} не создан.')
        return False

    print(f'[OK] Экспортирован нетлист KiCad: {out_path}')
    return True


# ============================================================
#  ПАРСЕРЫ НЕТЛИСТОВ
# ============================================================

def parse_kicadxml(path):
    """Читает нетлист KiCad XML: {net_name: set('REF.PIN')}."""
    tree = ET.parse(path)
    root = tree.getroot()
    nets = {}
    for net in root.iter('net'):
        name = net.get('name') or net.get('code') or '?'
        pins = set()
        for node in net.iter('node'):
            ref = node.get('ref')
            pin = node.get('pin')
            if ref and pin:
                pins.add(f'{ref}.{pin}')
        if pins:
            nets[name] = pins
    return nets


def parse_skidl_xml(path):
    """SKiDL генерирует KiCad-совместимый XML, парсер тот же."""
    return parse_kicadxml(path)


# ============================================================
#  СРАВНЕНИЕ
# ============================================================

def compare(skidl, kicad):
    skidl_keys = set(skidl)
    kicad_keys = set(kicad)
    only_skidl = skidl_keys - kicad_keys
    only_kicad = kicad_keys - skidl_keys
    common = skidl_keys & kicad_keys

    print()
    print('=' * 78)
    print('ЦЕПИ ТОЛЬКО В SKIDL')
    print('=' * 78)
    if only_skidl:
        for n in sorted(only_skidl):
            print(f'  {n}  ({len(skidl[n])} пинов)')
    else:
        print('  (нет)')

    print()
    print('=' * 78)
    print('ЦЕПИ ТОЛЬКО В KICAD')
    print('=' * 78)
    if only_kicad:
        for n in sorted(only_kicad):
            print(f'  {n}  ({len(kicad[n])} пинов)')
    else:
        print('  (нет)')

    print()
    print('=' * 78)
    print('РАСХОЖДЕНИЯ В ОБЩИХ ЦЕПЯХ')
    print('=' * 78)
    mismatches = 0
    for n in sorted(common):
        s = skidl[n]
        k = kicad[n]
        if s == k:
            continue
        mismatches += 1
        print(f'  Цепь {n}:')
        missing = s - k
        extra = k - s
        if missing:
            print(f'    в SKiDL, но нет в KiCad: {sorted(missing)}')
        if extra:
            print(f'    в KiCad, но нет в SKiDL: {sorted(extra)}')
    if mismatches == 0:
        print('  (нет — все общие цепи совпадают по пинам)')

    print()
    print('=' * 78)
    print('ИТОГО')
    print('=' * 78)
    print(f'  Цепей в SKiDL:  {len(skidl)}')
    print(f'  Цепей в KiCad:  {len(kicad)}')
    print(f'  Совпадают:      {len(common) - mismatches}')
    print(f'  Расхождений:    {mismatches}')
    print(f'  Только SKiDL:   {len(only_skidl)}')
    print(f'  Только KiCad:   {len(only_kicad)}')

    return (len(only_skidl) == 0 and len(only_kicad) == 0 and mismatches == 0)


# ============================================================
#  MAIN
# ============================================================

def main():
    if not SKIDL_NETLIST.exists():
        print(f'[ОШИБКА] Нетлист SKiDL не найден: {SKIDL_NETLIST}')
        print('         Сначала запустите circuit_generated.py.')
        sys.exit(1)

    if not export_kicad_netlist(KICAD_SCH, KICAD_NETLIST):
        sys.exit(1)

    print()
    print(f'[1] Читаю нетлист SKiDL: {SKIDL_NETLIST}')
    skidl_nets = parse_skidl_xml(SKIDL_NETLIST)
    print(f'    Цепей: {len(skidl_nets)}')

    print(f'[2] Читаю нетлист KiCad: {KICAD_NETLIST}')
    kicad_nets = parse_kicadxml(KICAD_NETLIST)
    print(f'    Цепей: {len(kicad_nets)}')

    ok = compare(skidl_nets, kicad_nets)

    print()
    if ok:
        print('✅ ВСЁ СОВПАЛО. Цепи в SKiDL и KiCad идентичны.')
    else:
        print('❌ ЕСТЬ РАСХОЖДЕНИЯ. Смотрите отчёт выше.')
        sys.exit(2)


if __name__ == '__main__':
    main()
