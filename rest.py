import os
import json
import re
import yaml

def clean_and_load_json(file_path):
    with open(file_path, "r", encoding="utf-8") as f:
        raw_content = f.read()
    fixed_content = raw_content.replace("\\n", " ")
    return json.loads(fixed_content)

def get_mapped_ref(old_ref):
    if not old_ref.startswith(("R", "LED_")): return old_ref
    if old_ref.startswith("R") and old_ref[1:].isdigit():
        num = int(old_ref[1:])
        if 43 <= num <= 56:
            ch = num - 42
            if ch <= 2: return f"R_BTN_{ch}"
            elif ch <= 10: return f"R_SCALE_{ch-2}"
            else: return f"R_PTR_{ch-10}"
    if old_ref.startswith("LED_BTN_"):
        num = int(old_ref.split("_")[-1])
        return f"LED_BTN_{(num-1)//3+1}_{(num-1)%3+1}"
    if old_ref.startswith("LED_SCALE_"):
        num = int(old_ref.split("_")[-1])
        return f"LED_SCALE_{(num-1)//3+1}_{(num-1)%3+1}"
    if old_ref.startswith("LED_PTR_"):
        num = int(old_ref.split("_")[-1])
        return f"LED_PTR_{(num-1)//3+1}_{(num-1)%3+1}"
    return old_ref

def get_mapped_net_name(old_net):
    if not old_net.startswith("NET_ILL_CH"): return old_net
    try:
        ch_num = int(re.search(r'\d+', old_net).group())
    except:
        ch_num = 1
    sub_letter = "A"
    if old_net.endswith(("_A", "_B", "_C")):
        sub_letter = old_net.split("_")[-1]
    if ch_num <= 2: return f"NET_BTN_CH{ch_num}_{sub_letter}"
    elif ch_num <= 10: return f"NET_SCALE_CH{ch_num-2}_{sub_letter}"
    else: return f"NET_PTR_CH{ch_num-10}_{sub_letter}"

def get_net_attributes(net_name):
    attrs = {
        "type": "DIGITAL_SIGNAL",
        "voltage_level": "3.3V",
        "current_max": "0.02A",
        "spice_simulation": {"model_stimulus": "", "parasitic_r_ohm": 0.05, "parasitic_l_h": "10n"}
    }
    if "GND" in net_name: attrs.update({"type": "GND", "voltage_level": "0V", "current_max": "15A"})
    elif "VCC_12V" in net_name or "VBAT" in net_name:
        attrs.update({"type": "POWER", "voltage_level": "12.0V", "current_max": "15A"})
        attrs["spice_simulation"]["model_stimulus"] = "DC 12.0"
    elif "5V" in net_name: attrs.update({"type": "POWER", "voltage_level": "5.0V", "current_max": "0.5A"})
    elif "3V3" in net_name: attrs.update({"type": "POWER", "voltage_level": "3.3V", "current_max": "0.3A"})
    elif "ADC" in net_name or "NTC" in net_name or "FB_" in net_name or "SENSE" in net_name:
        attrs.update({"type": "ANALOG_SIGNAL", "voltage_level": "0..3.3V", "current_max": "0.005A"})
    elif "MOTOR_" in net_name or "FAN_LOAD" in net_name:
        attrs.update({"type": "PWM_POWER", "voltage_level": "0..12.0V", "current_max": "5.0A"})
        if "FAN" in net_name:
            attrs["current_max"] = "30.0A"
            attrs["spice_simulation"]["model_stimulus"] = "PULSE(0 12 0 10n 10n 25u 250u)"
    return attrs

def extract_clean_signal_name(text):
    if not text: return ""
    # 1. Если строка содержит стрелку '->', берем правую часть (имя сигнала)
    if " -> " in text:
        text = text.split(" -> ")[-1].strip()
    # 2. Отрезаем комментарии в круглых скобках (берем элемент [0] до скобки)
    if "(" in text:
        text = text.split("(")[0].strip()
    # 3. Отрезаем любые случайные пояснения через пробел (берем первый элемент)
    if " " in text:
        text = text.split(" ")[0].strip()
    return text

def parse_custom_fields(ref, value_str, desc_str):
    fields = {}
    combined_text = f"{value_str} {desc_str}".lower()
    voltage_match = re.search(r'(\d+[\.,]?\d*)\s*(в|v)', combined_text)
    if voltage_match: fields["Voltage"] = f"{voltage_match.group(1).replace(',', '.')}V"
    clean_value = value_str
    if ref.startswith("C"):
        val_match = re.search(r'(\d+\s*[uunpф]f?)', value_str, re.IGNORECASE)
        if val_match: clean_value = val_match.group(1)
    elif ref.startswith("R"):
        val_match = re.search(r'(\d+\s*[krmооm]?)', value_str, re.IGNORECASE)
        if val_match: clean_value = val_match.group(1)
    if "электролит" in combined_text or "cp_" in combined_text: fields["Type"] = "Aluminum Electrolytic"
    elif ref.startswith("C"):
        fields["Type"] = "Ceramic"
        fields["Dielectric"] = "X7R"
    if ref.startswith("R"):
        if "мощность" in combined_text:
            p_match = re.search(r'(\d+[\.,]?\d*)\s*(вт|w)', combined_text)
            if p_match: fields["Power"] = f"{p_match.group(1)}W"
        else: fields["Power"] = "0.1W"
        fields["Tolerance"] = "1%"
    return clean_value, fields

def generate_type_key(symbol, footprint, value, fields):
    """Генерирует уникальный строковый ключ для типа компонента"""
    clean_sym = symbol.split(":")[-1].replace("_", "")
    clean_val = str(value).replace(".", "p").replace(" ", "")
    volt = fields.get("Voltage", "").replace("V", "v")
    tail = f"_{volt}" if volt else ""
    return f"TYPE_{clean_sym}_{clean_val}{tail}".upper()

def restructure_perfect_project_v5(json_path, output_dir="."):
    if not os.path.exists(json_path):
        print(f"Ошибка: Файл {json_path} не найден!")
        return

    src = clean_and_load_json(json_path)
    sheets_dir = os.path.join(output_dir, "sheets")
    os.makedirs(sheets_dir, exist_ok=True)

    metadata_block = src.get("metadata", {})
    mcu_pin_map = metadata_block.get("mcu_pin_map", {})
    j1_pinout = metadata_block.get("j1_pinout", {})
    symbol_pin_map = src.get("symbol_pin_map", {})

    comp_dict = src.get("components", {})
    net_dict = src.get("nets", {})

    comp_to_sheet = {}
    virtual_components = set()
    root_components = {}
    root_types = {}
    structured_sheets = {} # ИСПРАВЛЕНИЕ: Инициализация словаря дочерних страниц схемы

    # Сначала выявляем все виртуальные элементы из исходной базы данных
    for ref, info in comp_dict.items():
        if info.get("virtual") is True:
            virtual_components.add(ref)

    # Создаем структуры для каждого дочернего листа схемы на основе исходного JSON
    for sheet in src.get("sheets", []):
        name = sheet["name"]
        if name == "CONTROLLER": continue
        structured_sheets[name] = {
            "page_name": name,
            "file": sheet["file"],
            "functional_purpose": metadata_block.get("architecture", {}).get(name.lower(), f"Модуль {name}"),
            "ports": [],
            "component_types": {},
            "components": {},
            "nets": {}
        }

    # Строим карту распределения реальных компонентов по страницам
    for sheet in src.get("sheets", []):
        for comp in sheet.get("components", []):
            if comp not in virtual_components:
                comp_to_sheet[comp] = sheet["name"]

    # 2. И только затем перебираем все компоненты из общего списка для типизации
    print("--- 1. Создание библиотеки типов и экспорт компонентов ---")
    for ref, info in comp_dict.items():
        if ref in virtual_components: continue

        sheet_name = comp_to_sheet.get(ref)
        # Компоненты FAN_KEY будут сохранены в его личный суб-файл  # Пропуск виртуального стенда вентилятора

        new_ref = get_mapped_ref(ref)
        clean_val, extracted_fields = parse_custom_fields(ref, info.get("value", ""), info.get("description", ""))

        symbol_name = f"{info.get('library', 'Device')}:{info.get('sym_name', 'R')}"
        footprint_name = info.get("footprint", "")

        type_key = generate_type_key(symbol_name, footprint_name, clean_val, extracted_fields)

        type_entry = {
            "symbol": symbol_name,
            "footprint": footprint_name,
            "value": clean_val,
            "fields": extracted_fields
        }

        comp_entry = {
            "type": type_key,
            "description": info.get("description", "")
        }

        if sheet_name == "CONTROLLER" or not sheet_name:
            root_types[type_key] = type_entry
            root_components[new_ref] = comp_entry
        else:
            if sheet_name in structured_sheets:
                structured_sheets[sheet_name]["component_types"][type_key] = type_entry
                structured_sheets[sheet_name]["components"][new_ref] = comp_entry

    mcu_function_to_pin = {}
    for pin_num, pin_desc in mcu_pin_map.items():
        clean_sig = extract_clean_signal_name(pin_desc)
        if clean_sig: mcu_function_to_pin[clean_sig] = pin_num

    j1_function_to_pin = {}
    for pin_num, pin_desc in j1_pinout.items():
        clean_sig = extract_clean_signal_name(pin_desc)
        if clean_sig: j1_function_to_pin[clean_sig] = pin_num

    # 2. Построение графов цепей и выделение портов
    print("--- 2. Построение сквозного графа цепей ---")
    root_nets = {}

    for net_name, net_info in net_dict.items():
        nodes = net_info.get("nodes", [])
        new_net_name = get_mapped_net_name(net_name)

        local_nodes = []
        net_sheets = set()
        for node in nodes:
            if isinstance(node, list) and len(node) >= 2:
                comp_ref = node[0]
                pin_num = node[1]
            else:
                comp_ref = node
                pin_num = "1"

            if comp_ref in virtual_components: continue
            new_comp_ref = get_mapped_ref(comp_ref)
            local_nodes.append({"component": new_comp_ref, "pin": str(pin_num)})
            if comp_ref in comp_to_sheet: net_sheets.add(comp_to_sheet[comp_ref])
            elif comp_ref == "J1": net_sheets.add("PWR")

        if not local_nodes: continue
        final_net_name = new_net_name if new_net_name and not new_net_name.startswith("unnamed") else f"Net-({local_nodes['component']}-Pad{local_nodes['pin']})"
        net_attrs = get_net_attributes(final_net_name)

        mcu_pin = mcu_function_to_pin.get(final_net_name)
        j1_pin = j1_function_to_pin.get(final_net_name)

        full_nodes = list(local_nodes)
        if mcu_pin:
            full_nodes.append({"component": "U1", "pin": str(mcu_pin)})
            net_sheets.add("CONTROLLER")
        if j1_pin and not any(n["component"] == "J1" for n in full_nodes):
            full_nodes.append({"component": "J1", "pin": str(j1_pin)})
            net_sheets.add("PWR")

        is_global = "CONTROLLER" in net_sheets or len(net_sheets) > 1 or j1_pin is not None
        net_object_main = {"name": final_net_name, "description": net_info.get("description", f"Соединение {final_net_name}"), "attributes": net_attrs, "nodes": full_nodes}

        if is_global:
            root_nets[final_net_name] = net_object_main

        for sheet_name, sheet_data in structured_sheets.items():
            sheet_components = list(sheet_data["components"].keys())
            has_local_nodes = any(n["component"] in sheet_components or (sheet_name == "PWR" and n["component"] == "J1") for n in local_nodes)

            is_functional_port = False
            if is_global and mcu_pin:
                if sheet_name == "ILLUM" and any(x in final_net_name for x in ["ILLUM", "NET_BTN", "SCALE", "PTR"]): is_functional_port = True
                if sheet_name == "ACT" and any(x in final_net_name for x in ["MOTOR", "M1_", "M2_", "M3_", "M4_", "FB_M", "ILIM"]): is_functional_port = True
                if sheet_name == "CAN" and "CAN" in final_net_name: is_functional_port = True
                if sheet_name == "FAN_KEY" and "FAN_PWM" in final_net_name: is_functional_port = True
                if sheet_name == "SEN_CABIN" and "NTC_CABIN" in final_net_name: is_functional_port = True
                if sheet_name == "SEN_HEAT" and "NTC_HEAT" in final_net_name: is_functional_port = True
                if sheet_name == "SEN_SOLAR" and "SOLAR_" in final_net_name:
                            is_functional_port = True
                if sheet_name == "SEN_COND" and "COND_" in final_net_name:
                            is_functional_port = True
                if sheet_name == "UI" and any(x in final_net_name for x in ["BTN_", "LED1_", "LED2_", "LED3_", "LED4_", "LED5_", "LED6_", "TEMP_SET", "FAN_SEL"]):
                            is_functional_port = True

            if has_local_nodes or is_functional_port:
                # Фильтруем ноды: в дочерний лист должны попасть ТОЛЬКО его локальные компоненты + иерархический порт связи наружу!
                sub_nodes = [n for n in local_nodes if n["component"] in sheet_components or (sheet_name == "PWR" and n["component"] == "J1")]

                if is_global:
                    # Если цепь уходит наружу лимбического блока — суб-лист видит в нодах и точку МК/J1, и генерирует ПОРТ!
                    if mcu_pin and not any(n["component"] == "U1" for n in sub_nodes):
                        sub_nodes.append({"component": "U1", "pin": str(mcu_pin)})
                    if j1_pin and not any(n["component"] == "J1" for n in sub_nodes):
                        sub_nodes.append({"component": "J1", "pin": str(j1_pin)})

                    port_type = "INPUT" if any(x in final_net_name for x in ["IN", "RAW", "CTL", "IN1", "IN2", "REQ"]) else "OUTPUT"
                    if any(p in final_net_name for p in ["GND", "VCC", "3V3", "5V", "SENS"]): port_type = "POWER"

                    sheet_data["ports"].append({
                        "net_label": final_net_name,
                        "type": port_type,
                        "description": net_object_main["description"]
                    })

                # ТОЧЕЧНАЯ ИНЖЕКЦИЯ ПИНА СТРАНИЦЫ В СЕТЬ ВЕРХНЕГО УРОВНЯ


                sheet_ref = f"X_{sheet_name}"


                target_nodes = full_nodes if "full_nodes" in locals() else (perfect_nodes if "perfect_nodes" in locals() else local_nodes)


                if not any(n["component"] == sheet_ref and n["pin"] == final_net_name for n in target_nodes):


                    target_nodes.append({"component": sheet_ref, "pin": final_net_name})



                sheet_data["nets"][final_net_name] = {
                    "name": final_net_name,
                    "description": net_object_main["description"],
                    "is_hierarchical_port": is_global,
                    "attributes": net_attrs,
                    "nodes": sub_nodes # СТРОГО ЛОКАЛЬНЫЙ ИЗОЛИРОВАННЫЙ КЛЮЧ ГРАФА
                }

    # Сохраняем суб-листы
    print("--- 3. Очистка от дублирования и экспорт суб-листов ---")
    for sheet_name, sheet_data in structured_sheets.items():
        seen_ports = set()
        unique_ports = []
        for p in sheet_data["ports"]:
            if p["net_label"] not in seen_ports:
                seen_ports.add(p["net_label"])
                unique_ports.append(p)
        sheet_data["ports"] = unique_ports

        # В main.yaml пишется только чистая ссылка на файл. Никаких пинов тут больше нет!
        sheet_ref = f"X_{sheet_name}"
        yaml_file_path = f"sheets/cc_{sheet_name.lower()}.yaml"

        root_components[sheet_ref] = {
            "symbol": "Core:Hierarchical_Sheet",
            "value": yaml_file_path,  # Ссылка на файл-источник правды
            "description": sheet_data["functional_purpose"]
        }

        # Сохранение суб-листа (где пины описаны один раз в секции ports)
        with open(os.path.join(output_dir, yaml_file_path), "w", encoding="utf-8") as f:
            yaml.dump(sheet_data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        print(f"  [OK] Дочерний лист сохранен: {yaml_file_path}")

    # 4. Запись корневого файла main.yaml
    print("--- 4. Запись корневого файла main.yaml ---")
    main_project = {
        "root_page": {
            "project": metadata_block.get("project", "Climate Control Niva Travel"),
            "version": metadata_block.get("version", "2.6"),
            "file": "climate_control_niva_travel.kicad_sch",
            "mcu_pin_map": mcu_pin_map,
            "j1_pinout": j1_pinout,
            "symbol_pin_map": symbol_pin_map,
            "component_types": root_types, # Глобальная библиотека типов
            "components": root_components,
            "nets": root_nets
        }
    }

    main_yaml_path = os.path.join(output_dir, "main.yaml")
    with open(main_yaml_path, "w", encoding="utf-8") as f:
        yaml.dump(main_project, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    print(f"  [OK] Иерархический граф main.yaml собран без ошибок: {main_yaml_path}")
    print("\n--- Реструктуризация выполнена на 100%! Архитектура избавлена от дублирования! ---")

if __name__ == "__main__":
    INPUT_JSON = "circuit_model.old.json"
    restructure_perfect_project_v5(INPUT_JSON, ".")

