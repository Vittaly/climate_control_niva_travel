import os
import sys
import yaml

# ============================================================
#  ШАГ 1. НАХОДИМ БИБЛИОТЕКИ KICAD И ВЫСТАВЛЯЕМ ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ
#  Это должно произойти ДО импорта skidl!
# ============================================================
def find_kicad_libraries():
    """Автоматически находит пути к символам и посадочным местам KiCad."""
    base_paths = [
        "/usr/share/kicad",
        "/usr/local/share/kicad",
        os.path.expanduser("~/.var/app/org.kicad.KiCad/data/kicad"),
        "/var/lib/flatpak/app/org.kicad.KiCad/current/active/files/share/kicad",
        "/snap/kicad/current/usr/share/kicad",
    ]

    symbol_path = None
    footprint_path = None

    for base in base_paths:
        if not os.path.isdir(base):
            continue

        # --- Символы ---
        sym_dir = os.path.join(base, "symbols")
        if os.path.isdir(sym_dir) and symbol_path is None:
            if os.path.exists(os.path.join(sym_dir, "Device.kicad_sym")):
                symbol_path = sym_dir
            else:
                for root, dirs, files in os.walk(sym_dir):
                    if "Device.kicad_sym" in files:
                        symbol_path = root
                        break

        # --- Посадочные места ---
        fp_dir = os.path.join(base, "footprints")
        if os.path.isdir(fp_dir) and footprint_path is None:
            for item in os.listdir(fp_dir):
                if item.endswith(".pretty"):
                    footprint_path = fp_dir
                    break

        if symbol_path and footprint_path:
            break

    return symbol_path, footprint_path


symbol_path, footprint_path = find_kicad_libraries()

if symbol_path:
    # Выставляем переменные для ВСЕХ версий KiCad, которые проверяет SKiDL
    os.environ["KICAD_SYMBOL_DIR"] = symbol_path
    os.environ["KICAD6_SYMBOL_DIR"] = symbol_path
    os.environ["KICAD7_SYMBOL_DIR"] = symbol_path
    os.environ["KICAD8_SYMBOL_DIR"] = symbol_path
    os.environ["KICAD9_SYMBOL_DIR"] = symbol_path
    os.environ["KICAD10_SYMBOL_DIR"] = symbol_path
    print(f"[BOOTSTRAP] Библиотеки символов найдены: {symbol_path}")
else:
    print("[BOOTSTRAP] ВНИМАНИЕ: библиотеки символов KiCad не найдены.")

if footprint_path:
    os.environ["KICAD6_FOOTPRINT_DIR"] = footprint_path
    os.environ["KICAD7_FOOTPRINT_DIR"] = footprint_path
    os.environ["KICAD8_FOOTPRINT_DIR"] = footprint_path
    os.environ["KICAD9_FOOTPRINT_DIR"] = footprint_path
    os.environ["KICAD10_FOOTPRINT_DIR"] = footprint_path
    print(f"[BOOTSTRAP] Посадочные места найдены: {footprint_path}")
else:
    print("[BOOTSTRAP] ВНИМАНИЕ: посадочные места KiCad не найдены.")


# ============================================================
#  ШАГ 2. ТОЛЬКО ТЕПЕРЬ ИМПОРТИРУЕМ SKIDL
#  К этому моменту переменные окружения уже заданы, поэтому SKiDL
#  сам подхватит нужные пути и не будет ругаться на их отсутствие.
# ============================================================
from skidl import KICAD10, lib_search_paths, footprint_search_paths
from skidl import *

# Включаем компиляцию под стандарты KiCad 10.0
set_default_tool(KICAD10)

# Дополнительно подстрахуемся и продублируем пути в словари SKiDL
if symbol_path and symbol_path not in lib_search_paths[KICAD10]:
    lib_search_paths[KICAD10].append(symbol_path)
if footprint_path and footprint_path not in footprint_search_paths[KICAD10]:
    footprint_search_paths[KICAD10].append(footprint_path)


# ============================================================
#  ШАГ 3. ДАЛЬШЕ — ОБЫЧНАЯ ЛОГИКА ГЕНЕРАЦИИ ПРОЕКТА
# ============================================================

def load_yaml(file_path):
    if not os.path.exists(file_path):
        return None
    with open(file_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f) or {}


def split_symbol(symbol_str, default_lib='Device', default_part='R'):
    if not symbol_str:
        return default_lib, default_part
    if ':' in symbol_str:
        lib_name, part_name = symbol_str.split(':', 1)
    else:
        lib_name, part_name = default_lib, symbol_str
    return lib_name, part_name


def find_pin(comp_obj, pin_id):
    """Ищет пин по точному совпадению имени или номера."""
    try:
        return comp_obj[pin_id]
    except Exception:
        pass
    try:
        for p in comp_obj.pins:
            if str(p.name) == str(pin_id) or str(p.num) == str(pin_id):
                return p
    except Exception:
        pass
    return None


def safe_connect(net_obj, comp_obj, pin_id, comp_ref, net_name):
    pin = find_pin(comp_obj, pin_id)
    if pin is None:
        available = []
        try:
            available = [f"{p.name}({p.num})" for p in comp_obj.pins]
        except Exception:
            pass
        print(f"[ОШИБКА ПИНА] {comp_ref}: пин '{pin_id}' не найден "
              f"(цепь '{net_name}'). Доступные пины: {available}")
        return False

    existing_net = getattr(pin, "net", None)
    if existing_net is not None and getattr(existing_net, "name", ""):
        if existing_net.name != net_name and not existing_net.is_implicit():
            print(f"[КОНФЛИКТ] Пин {comp_ref}[{pin_id}] уже принадлежит "
                  f"цепи '{existing_net.name}'.")
            return False

    net_obj += pin
    return True


def build_kicad10_project(main_yaml_path):
    main_data = load_yaml(main_yaml_path)
    if not main_data:
        print(f"[ОШИБКА] Файл {main_yaml_path} не найден")
        return

    root = main_data.get('root_page', {})
    components = root.get('components', {})
    comp_types = root.get('component_types', {})
    nets_data = root.get('nets', {})

    print(f"=== [SKIDL API] Сборка проекта на базе символов KiCad 10.0 ===")

    hardware_pool = {}

    # ===== ШАГ 1: Компоненты главного листа =====
    for ref, comp_info in components.items():
        if ref.startswith('X_'):
            continue
        c_type = comp_info.get('type')
        type_data = comp_types.get(c_type, {})
        symbol_str = type_data.get('symbol', 'Device:R')
        lib_name, part_name = split_symbol(symbol_str)
        val = str(type_data.get('value', 'Value'))

        try:
            comp_obj = Part(lib_name, part_name, value=val)
        except Exception as e:
            print(f"[КРИТИЧЕСКАЯ ОШИБКА] Не удалось загрузить "
                  f"{lib_name}:{part_name}: {e}")
            sys.exit(1)

        if type_data.get('footprint'):
            comp_obj.footprint = type_data.get('footprint')
        hardware_pool[ref] = comp_obj

    # ===== ШАГ 2: Иерархические подстраницы =====
    for ref, comp_info in components.items():
        if not ref.startswith('X_'):
            continue
        yaml_spec = comp_info.get(
            'value', f"sheets/{ref.lower().replace('x_', '')}.yaml")
        yaml_path = (yaml_spec if os.path.exists(yaml_spec)
                     else os.path.join("sheets", os.path.basename(yaml_spec)))

        child_data = load_yaml(yaml_path)
        if not child_data:
            continue

        child_page = (child_data.get('page_info', child_data)
                      if 'page_info' in child_data else child_data)
        c_components = child_page.get('components', {})
        c_types = child_page.get('component_types', {})

        for c_ref, c_info in c_components.items():
            ct = c_info.get('type')
            td = c_types.get(ct, {})
            c_symbol_str = td.get('symbol', 'Device:R')
            clib, cpart = split_symbol(c_symbol_str)

            try:
                comp_obj = Part(clib, cpart,
                                value=str(td.get('value', 'Value')))
            except Exception as e:
                print(f"[КРИТИЧЕСКАЯ ОШИБКА] {clib}:{cpart}: {e}")
                sys.exit(1)

            if td.get('footprint'):
                comp_obj.footprint = td.get('footprint')

            hardware_pool[f"{ref}_{c_ref}"] = comp_obj

    # ===== ШАГ 3: Линковка цепей =====
    sheet_children = {}
    for key in hardware_pool.keys():
        if key.startswith("X_") and "_" in key:
            parts = key.split("_")
            if len(parts) >= 3:
                sheet_children.setdefault(parts[0] + "_" + parts[1],
                                          []).append(key)

    for net_name, net_info in nets_data.items():
        net_obj = Net(net_name)
        for node in (net_info.get('nodes', []) or []):
            comp_ref = node.get('component')
            raw_pin = node.get('pin')
            if not comp_ref:
                continue
            if raw_pin is None:
                continue
            pin_id = str(raw_pin)

            if comp_ref.startswith('X_'):
                for ck in sheet_children.get(comp_ref, []):
                    child = hardware_pool[ck]
                    if find_pin(child, pin_id) is None:
                        continue
                    if safe_connect(net_obj, child, pin_id, ck, net_name):
                        break
                continue

            if comp_ref in hardware_pool:
                safe_connect(net_obj, hardware_pool[comp_ref], pin_id,
                             comp_ref, net_name)

    # ===== ШАГ 4: Экспорт =====
    output_sch_file = root.get('file',
                               'climate_control_niva_travel.kicad_sch')
    generate_schematic(filepath=output_sch_file)
    print(f"-> Схема сохранена: {output_sch_file}")

    os.makedirs(".netlist_tmp", exist_ok=True)
    generate_netlist(filename=".netlist_tmp/MAIN_ROOT.xml")
    print(f"-> Нетлист сохранён: .netlist_tmp/MAIN_ROOT.xml")


if __name__ == "__main__":
    build_kicad10_project("main.yaml")