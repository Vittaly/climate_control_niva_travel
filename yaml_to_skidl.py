#!/usr/bin/env python3
"""
Компилятор YAML → SKiDL с настоящей иерархией.

Каждая подстраница → @SubCircuit с параметрами-портами, взятыми
из секции `ports:` YAML. Локальные цепи (is_hierarchical_port:
false) создаются внутри модуля, иерархические (true) приходят
снаружи как аргументы.

Префикс X_ в именах листов YAML используется только для
идентификации иерархической ссылки. В Python-коде от него
избавляемся: X_ACT → module_ACT, tag_prefix = 'ACT_'.

Метаданные (описания, purpose, атрибуты цепей, карты пинов) — в
docstring'ах и комментариях.
"""
import os
import yaml


# ============================================================
#  УТИЛИТЫ
# ============================================================

def load_yaml(path):
    if not os.path.exists(path):
        return None
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f) or {}


def split_symbol(s, default_lib='Device', default_part='R'):
    if not s:
        return default_lib, default_part
    if ':' in s:
        return s.split(':', 1)
    return default_lib, s


def py_str(s):
    return "'" + str(s).replace("\\", "\\\\").replace("'", "\\'") + "'"


def clean_name(ref):
    """X_ACT → ACT, U1 → U1."""
    return ref[2:] if ref.startswith('X_') else ref


def cell(s, width):
    s = str(s) if s is not None else ''
    if len(s) > width - 1:
        s = s[:width - 2] + '…'
    return s.ljust(width)


def port_var(name):
    return f"p_{name}"


def net_var(name, is_port):
    return port_var(name) if is_port else f"net_{name}"


def get_sheet_ports(page):
    """Возвращает список имён портов листа в порядке из YAML."""
    return [p.get('net_label', '') for p in (page.get('ports') or [])]


# ============================================================
#  ШАПКА МОДУЛЯ
# ============================================================

def build_module_header(main_data, sheets_by_ref, page_by_ref):
    root = main_data.get('root_page', {})
    L = []
    L.append('"""')
    L.append('Climate Control Project — сгенерировано из main.yaml.')
    L.append('')
    L.append('=' * 78)
    L.append('ОБЩАЯ ИНФОРМАЦИЯ')
    L.append('=' * 78)
    L.append(f"project:   {root.get('project', '')}")
    L.append(f"version:   {root.get('version', '')}")
    L.append(f"root file: {root.get('file', '')}")
    L.append('')

    if sheets_by_ref:
        L.append('=' * 78)
        L.append('ИЕРАРХИЧЕСКИЕ ЛИСТЫ И ИХ ПОРТЫ')
        L.append('=' * 78)
        for ref, info in sheets_by_ref.items():
            desc = info.get('description', '')
            file_name = info.get('value_sch') or info.get('value', '')
            L.append(f"  {ref}:")
            L.append(f"    module:  module_{clean_name(ref)}()")
            L.append(f"    purpose: {desc}")
            L.append(f"    file:    {file_name}")
            page = page_by_ref.get(ref) or {}
            ports = page.get('ports') or []
            if ports:
                L.append(f"    ports ({len(ports)}):")
                for p in ports:
                    label = p.get('net_label', '')
                    ptype = p.get('type', '')
                    pdesc = p.get('description', '')
                    L.append(f"      - {label:<22} [{ptype:<8}] {pdesc}")
            L.append('')

    mcu = root.get('mcu_pin_map')
    if mcu:
        L.append('=' * 78)
        L.append('КАРТА ПИНОВ МИКРОКОНТРОЛЛЕРА (STM32F103RCT6, LQFP-64)')
        L.append('=' * 78)
        L.append(cell('Pin', 5) + cell('Signal', 10) + cell('Net', 22) +
                 cell('Function', 14) + 'Comment')
        L.append('-' * 78)
        for pin in sorted(mcu.keys(), key=lambda x: int(x)):
            info = mcu[pin]
            L.append(
                cell(pin, 5) +
                cell(info.get('signal', ''), 10) +
                cell(info.get('net') or '—', 22) +
                cell(info.get('function', ''), 14) +
                str(info.get('comment', '') or '')
            )
        L.append('')

    j1 = root.get('j1_pinout')
    if j1:
        L.append('=' * 78)
        L.append('РАЗЪЁМ J1 (автомобильный жгут)')
        L.append('=' * 78)
        for pin in sorted(j1.keys(), key=lambda x: int(x)):
            L.append(f"  {str(pin).rjust(2)}: {j1[pin]}")
        L.append('')

    spm = root.get('symbol_pin_map')
    if spm:
        L.append('=' * 78)
        L.append('КАРТА ПИНОВ СИМВОЛОВ (symbol_pin_map)')
        L.append('=' * 78)
        for k, v in spm.items():
            L.append(f"  {k}: {v}")
        L.append('')

    L.append('"""')
    return '\n'.join(L)


# ============================================================
#  КОМПОНЕНТ
# ============================================================

def emit_part(ref, info, type_data, indent='    ', tag_prefix=''):
    out = []
    type_name = info.get('type', '')
    desc = info.get('description', '')

    if type_name:
        out.append(f"{indent}# type:        {type_name}")
    if desc:
        out.append(f"{indent}# description: {desc}")

    lib, part = split_symbol(type_data.get('symbol', 'Device:R'))
    value = type_data.get('value', '')
    fp = type_data.get('footprint', '')

    tag = f"{tag_prefix}{ref}" if tag_prefix else ref
    out.append(f"{indent}# tag:         {tag}")

    args = [py_str(lib), py_str(part),
            f"ref={py_str(ref)}",
            f"tag={py_str(tag)}"]
    if value:
        args.append(f"value={py_str(value)}")
    if fp:
        args.append(f"footprint={py_str(fp)}")
    out.append(f"{indent}comp_{ref} = Part({', '.join(args)})")

    fields = type_data.get('fields') or {}
    for k, v in fields.items():
        out.append(
            f"{indent}comp_{ref}.fields[{py_str(k)}] = {py_str(v)}")
    if desc:
        out.append(
            f"{indent}comp_{ref}.fields['Description'] = {py_str(desc)}")

    return out


# ============================================================
#  ЦЕПЬ
# ============================================================

def emit_net_decl(net_name, net_info, is_port, indent='    '):
    out = []
    desc = net_info.get('description', '')
    if desc:
        out.append(f"{indent}# Цепь {net_name}: {desc}")
    attrs = net_info.get('attributes') or {}
    if attrs:
        parts = [f"{k}={v}" for k, v in attrs.items()]
        out.append(f"{indent}# attributes: {', '.join(parts)}")
    if is_port:
        out.append(f"{indent}# Порт листа (см. docstring выше).")
    else:
        out.append(f"{indent}net_{net_name} = "
                   f"Net({py_str(net_name)})")
    return out


# ============================================================
#  ПОДСТРАНИЦА
# ============================================================

def compile_sheet(sheet_ref, info, page):
    out = []
    file_name = info.get('value_sch') or info.get('value', '')
    purpose = info.get('description', '') or page.get('functional_purpose', '')
    page_desc = page.get('description', '')

    ports = page.get('ports') or []
    port_names = [p.get('net_label', '') for p in ports]
    port_set = set(port_names)

    module_name = clean_name(sheet_ref)
    tag_prefix = f"{module_name}_"

    sig_args = ", ".join(port_var(n) for n in port_names)
    out.append('@SubCircuit')

    out.append(f'def module_{module_name}({sig_args}):')
    out.append('    """')
    out.append(f"    Подстраница: {sheet_ref}")
    out.append(f"    file: {file_name}")
    if purpose:
        out.append(f"    purpose: {purpose}")
    if page_desc and page_desc != purpose:
        out.append(f"    description: {page_desc}")
    if ports:
        out.append('')
        out.append('    Порты листа:')
        for p in ports:
            label = p.get('net_label', '')
            ptype = p.get('type', '')
            pdesc = p.get('description', '')
            out.append(f"      {label:<22} [{ptype:<8}] {pdesc}")
    out.append('    """')

    components = page.get('components', {})
    comp_types = page.get('component_types', {})
    nets = page.get('nets', {})

    if components:
        out.append('')
        out.append('    # ' + '=' * 70)
        out.append('    # Компоненты')
        out.append('    # ' + '=' * 70)
        for ref, cinfo in components.items():
            td = comp_types.get(cinfo.get('type'), {})
            if not td:
                out.append(f"    # ПРОПУЩЕН {ref}: тип "
                           f"'{cinfo.get('type')}' не найден")
                continue
            out.extend(emit_part(ref, cinfo, td, tag_prefix=tag_prefix))
            out.append('')

    if nets:
        out.append('    # ' + '=' * 70)
        out.append('    # Цепи и соединения')
        out.append('    # ' + '=' * 70)
        for net_name, net_info in nets.items():
            is_port = (net_name in port_set) or \
                      bool(net_info.get('is_hierarchical_port', False))

            out.extend(emit_net_decl(net_name, net_info, is_port))
            var = net_var(net_name, is_port)
            for node in (net_info.get('nodes', []) or []):
                comp = node.get('component')
                pin = node.get('pin')
                if not comp or pin is None:
                    continue
                if comp.startswith('X_'):
                    out.append(f"    # TODO: вложенный лист {comp} "
                               f"порт {pin} (цепь {net_name})")
                    continue
                out.append(f"    {var} += comp_{comp}[{py_str(pin)}]")
            out.append('')

    if not components and not nets:
        out.append('    pass')

    
    # Установка tag после определения (обход ограничения @SubCircuit)
    out.append('')
    out.append(f"module_{module_name}.tag = {py_str('SHEET_' + module_name)}")

    return out


# ============================================================
#  КОРНЕВОЙ ЛИСТ
# ============================================================

def compile_root(root, page_by_ref):
    out = []
    components = root.get('components', {})
    comp_types = root.get('component_types', {})
    nets = root.get('nets', {})

    out.append("@SubCircuit")


    out.append('def build_root():')
    out.append('    """')
    out.append('    Корневой лист проекта.')
    out.append(f"    project: {root.get('project', '')}")
    out.append(f"    version: {root.get('version', '')}")
    out.append('    """')

    # --- Корневые компоненты ---
    out.append('')
    out.append('    # ' + '=' * 70)
    out.append('    # Корневые компоненты')
    out.append('    # ' + '=' * 70)
    for ref, cinfo in components.items():
        if ref.startswith('X_'):
            continue
        td = comp_types.get(cinfo.get('type'), {})
        if not td:
            continue
        out.extend(emit_part(ref, cinfo, td))
        out.append('')

    # --- Цепи корневого листа ---
    out.append('    # ' + '=' * 70)
    out.append('    # Цепи корневого листа')
    out.append('    # ' + '=' * 70)
    for net_name, net_info in nets.items():
        desc = net_info.get('description', '')
        if desc:
            out.append(f"    # Цепь {net_name}: {desc}")
        attrs = net_info.get('attributes') or {}
        if attrs:
            parts = [f"{k}={v}" for k, v in attrs.items()]
            out.append(f"    # attributes: {', '.join(parts)}")
        out.append(f"    net_{net_name} = Net({py_str(net_name)})")
        for node in (net_info.get('nodes', []) or []):
            comp = node.get('component')
            pin = node.get('pin')
            if not comp or pin is None:
                continue
            if comp.startswith('X_'):
                continue
            out.append(f"    net_{net_name} += "
                       f"comp_{comp}[{py_str(pin)}]")
        out.append('')

    # --- Автосозданные цепи ---
    # Порты подстраниц, которых нет в root.nets, объявляем пустыми
    # цепями, чтобы не падать с NameError.
    root_net_names = set(nets.keys())
    all_sheet_ports = {}
    for ref, page in page_by_ref.items():
        for p in (page.get('ports') or []):
            n = p.get('net_label', '')
            if not n:
                continue
            all_sheet_ports.setdefault(n, []).append(ref)

    auto_nets = sorted(set(all_sheet_ports.keys()) - root_net_names)

    if auto_nets:
        out.append('    # ' + '=' * 70)
        out.append('    # ВНИМАНИЕ: автосозданные цепи')
        out.append('    # Эти имена объявлены как порты подстраниц, но')
        out.append('    # отсутствуют в main.yaml->root_page->nets.')
        out.append('    # Вероятно, забыли объявить цепь. Проверьте YAML.')
        out.append('    # ' + '=' * 70)
        for n in auto_nets:
            sheets = ', '.join(all_sheet_ports[n])
            out.append(f"    # '{n}' экспонируют листы: {sheets}")
            out.append(f"    net_{n} = Net({py_str(n)})")
        out.append('')

    # --- Вызовы подстраниц ---
    out.append('    # ' + '=' * 70)
    out.append('    # Иерархические подстраницы (с передачей портов)')
    out.append('    # ' + '=' * 70)
    for ref, cinfo in components.items():
        if not ref.startswith('X_'):
            continue
        desc = cinfo.get('description', '')
        file_name = cinfo.get('value_sch') or cinfo.get('value', '')
        page = page_by_ref.get(ref) or {}
        port_names = get_sheet_ports(page)
        module_name = clean_name(ref)

        out.append(f"    # {ref}: {desc}")
        out.append(f"    #     file: {file_name}")
        if not port_names:
            out.append(f"    #     (порты не объявлены)")
            out.append(f"    module_{module_name}()")
        else:
            out.append(f"    module_{module_name}(")
            for n in port_names:
                out.append(f"        net_{n},")
            out.append('    )')
        out.append('')

    # Установка tag для корневого SubCircuit
    out.append('')
    out.append("build_root.tag = 'ROOT'")

    return out

def build_bootstrap_lines():
    L = []
    L.append('# ' + '=' * 74)
    L.append('# BOOTSTRAP: настройка путей к библиотекам KiCad')
    L.append('# ' + '=' * 74)
    L.append('import os')
    L.append('import sys')
    L.append('')
    L.append('')
    L.append('def _find_kicad_libraries():')
    L.append('    base_paths = [')
    L.append("        '/usr/share/kicad',")
    L.append("        '/usr/local/share/kicad',")
    L.append("        os.path.expanduser("
             "'~/.var/app/org.kicad.KiCad/data/kicad'),")
    L.append("        '/var/lib/flatpak/app/org.kicad.KiCad/current/active/"
             "files/share/kicad',")
    L.append("        '/snap/kicad/current/usr/share/kicad',")
    L.append('    ]')
    L.append('    sym = None')
    L.append('    fp = None')
    L.append('    for base in base_paths:')
    L.append('        if not os.path.isdir(base):')
    L.append('            continue')
    L.append("        sd = os.path.join(base, 'symbols')")
    L.append('        if os.path.isdir(sd) and sym is None:')
    L.append("            if os.path.exists(os.path.join(sd, "
             "'Device.kicad_sym')):")
    L.append('                sym = sd')
    L.append('            else:')
    L.append('                for r, _d, f in os.walk(sd):')
    L.append("                    if 'Device.kicad_sym' in f:")
    L.append('                        sym = r')
    L.append('                        break')
    L.append("        fd = os.path.join(base, 'footprints')")
    L.append('        if os.path.isdir(fd) and fp is None:')
    L.append('            for item in os.listdir(fd):')
    L.append("                if item.endswith('.pretty'):")
    L.append('                    fp = fd')
    L.append('                    break')
    L.append('        if sym and fp:')
    L.append('            break')
    L.append('    return sym, fp')
    L.append('')
    L.append('')
    L.append('_sym, _fp = _find_kicad_libraries()')
    L.append('if _sym:')
    L.append("    for _v in ('KICAD_SYMBOL_DIR', 'KICAD6_SYMBOL_DIR',")
    L.append("               'KICAD7_SYMBOL_DIR', 'KICAD8_SYMBOL_DIR',")
    L.append("               'KICAD9_SYMBOL_DIR', 'KICAD10_SYMBOL_DIR'):")
    L.append('        os.environ[_v] = _sym')
    L.append("    print(f'[BOOTSTRAP] Символы: {_sym}', flush=True)")
    L.append('if _fp:')
    L.append("    for _v in ('KICAD6_FOOTPRINT_DIR', "
             "'KICAD7_FOOTPRINT_DIR',")
    L.append("               'KICAD8_FOOTPRINT_DIR', "
             "'KICAD9_FOOTPRINT_DIR',")
    L.append("               'KICAD10_FOOTPRINT_DIR'):")
    L.append('        os.environ[_v] = _fp')
    L.append("    print(f'[BOOTSTRAP] Footprints: {_fp}', flush=True)")
    L.append('')
    L.append('# Автопоиск fp-lib-table для устранения WARNING')
    L.append('_fp_table_candidates = [')
    L.append("    os.path.expanduser('~/.config/kicad/9.0/fp-lib-table'),")
    L.append("    os.path.expanduser('~/.config/kicad/8.0/fp-lib-table'),")
    L.append("    os.path.expanduser('~/.config/kicad/10.0/fp-lib-table'),")
    L.append("    os.path.expanduser('~/.config/kicad/fp-lib-table'),")
    L.append("    '/usr/share/kicad/template/fp-lib-table',")
    L.append(']')
    L.append('for _tbl in _fp_table_candidates:')
    L.append('    if os.path.exists(_tbl):')
    L.append("        os.environ['KICAD10_FP_LIB_TABLE'] = _tbl")
    L.append("        os.environ['KICAD9_FP_LIB_TABLE'] = _tbl")
    L.append("        os.environ['KICAD8_FP_LIB_TABLE'] = _tbl")
    L.append("        print(f'[BOOTSTRAP] fp-lib-table: {_tbl}', flush=True)")
    L.append('        break')
    L.append('')
    L.append('')
    L.append('from skidl import KICAD10, lib_search_paths, '
             'footprint_search_paths')
    L.append('from skidl import *')
    L.append('from skidl import SubCircuit')
    L.append('')
    L.append('set_default_tool(KICAD10)')
    L.append('')
    L.append('if _sym and _sym not in lib_search_paths[KICAD10]:')
    L.append('    lib_search_paths[KICAD10].append(_sym)')
    L.append('if _fp and _fp not in footprint_search_paths[KICAD10]:')
    L.append('    footprint_search_paths[KICAD10].append(_fp)')
    L.append('')
    L.append('')
    return L


# ============================================================
#  main
# ============================================================

def main():
    main_data = load_yaml('main.yaml')
    if not main_data:
        print('[ОШИБКА] main.yaml не найден')
        return

    root = main_data.get('root_page', {})
    components = root.get('components', {})

    # --- Первый проход: загружаем все подстраницы ---
    sheets_by_ref = {}
    page_by_ref = {}
    yaml_path_by_ref = {}

    for ref, info in components.items():
        if not ref.startswith('X_'):
            continue
        yaml_spec = info.get('value',
                             f"sheets/{ref.lower().replace('x_', '')}.yaml")
        yaml_path = (yaml_spec if os.path.exists(yaml_spec)
                     else os.path.join('sheets',
                                       os.path.basename(yaml_spec)))
        child = load_yaml(yaml_path)
        if not child:
            print(f"[WARN] {ref}: YAML '{yaml_path}' не найден")
            continue
        page = (child.get('page_info', child)
                if 'page_info' in child else child)
        sheets_by_ref[ref] = info
        page_by_ref[ref] = page
        yaml_path_by_ref[ref] = yaml_path

    # --- Сборка выходного файла ---
    lines = [build_module_header(main_data, sheets_by_ref, page_by_ref), '']
    lines.extend(build_bootstrap_lines())

    # --- Подстраницы ---
    for ref, info in sheets_by_ref.items():
        lines.append('# ' + '=' * 74)
        lines.append(f'# Лист {ref}  ({yaml_path_by_ref[ref]})')
        lines.append('# ' + '=' * 74)
        lines.extend(compile_sheet(ref, info, page_by_ref[ref]))
        lines.append('')
        lines.append('')

    # --- Корень ---
    lines.append('# ' + '=' * 74)
    lines.append('# Корневой лист')
    lines.append('# ' + '=' * 74)
    lines.extend(compile_root(root, page_by_ref))
    lines.append('')
    lines.append('')

    # --- Точка входа ---
    lines.append('# ' + '=' * 74)
    lines.append('# Точка входа')
    lines.append('# ' + '=' * 74)
    lines.append("if __name__ == '__main__':")
    lines.append('    import shutil')
    lines.append('    from pathlib import Path')
    lines.append('')
    lines.append('    BASE_DIR = Path(__file__).resolve().parent')
    lines.append('    SCHEMATIC_DIR = BASE_DIR')
    lines.append("    NETLIST_DIR = BASE_DIR / 'netlist_out'")
    lines.append(f"    ROOT_SCH = BASE_DIR / 'climate_control_niva_travel.kicad_sch'")
    lines.append('')
    lines.append('    # Очистка старых .kicad_sch в корне (не трогает исходники)')
    lines.append('    for _sch in SCHEMATIC_DIR.glob("*.kicad_sch"):')
    lines.append('        try:')
    lines.append('            _sch.unlink()')
    lines.append('        except OSError:')
    lines.append('            pass')
    lines.append('')
    lines.append('    if NETLIST_DIR.is_dir():')
    lines.append('        shutil.rmtree(NETLIST_DIR)')
    lines.append('    NETLIST_DIR.mkdir(parents=True, exist_ok=True)')
    lines.append('')
    lines.append('    build_root()')
    lines.append("    print('=== Схема собрана ===', flush=True)")
    lines.append('')
    lines.append('    _netlist = NETLIST_DIR / "MAIN_ROOT.xml"')
    lines.append('    generate_netlist(filename=str(_netlist))')
    lines.append("    print(f'-> Нетлист: {_netlist}', flush=True)")
    lines.append('')
    lines.append('    generate_schematic(')
    lines.append('        filepath=str(SCHEMATIC_DIR),')
    lines.append("        top_name='climate_control_niva_travel',")
    lines.append('        flatness=0.0,')
    lines.append('        auto_stub=True,')
    lines.append('    )')
    lines.append('')
    lines.append("    print(f'-> Все .kicad_sch в: {SCHEMATIC_DIR}', flush=True)")


    with open('circuit_generated.py', 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    # --- Диагностика рассинхрона YAML ---
    root_nets = set(root.get('nets', {}).keys())
    missing = {}
    for ref, page in page_by_ref.items():
        for p in (page.get('ports') or []):
            n = p.get('net_label', '')
            if n and n not in root_nets:
                missing.setdefault(n, []).append(ref)

    if missing:
        print('')
        print('[ВНИМАНИЕ] Порты, объявленные в подстраницах, но '
              'отсутствующие в main.yaml->root_page->nets:')
        for n, sheets in sorted(missing.items()):
            print(f"  - {n:<24} (экспонируют: {', '.join(sheets)})")
        print('')
        print('  Они автоматически созданы как пустые цепи, но '
              'проверьте YAML:')
        print('  скорее всего, вы забыли объявить их в main.yaml.')

    print('')
    print('[OK] Сгенерирован circuit_generated.py')
    print(f'     Подстраниц: {len(sheets_by_ref)}')
    print('     Запустить: python3 -u circuit_generated.py')


if __name__ == '__main__':
    main()