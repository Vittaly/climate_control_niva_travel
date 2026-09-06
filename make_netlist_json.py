#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Сборка circuit_model.json (модель электрической схемы климат-контроля Niva Travel).
Формат совместим с build_project.py: ключи metadata / lib_symbols / components / nets.
Генератор построен так, что каждое объявление (ref, pin) попадает ровно в одну сеть,
а после сборки выполняется самопроверка на дубликаты.
"""
import json
import os

NETS = {}          # name -> {"description":.., "nodes":[[ref,pin],...]}

def N(name, desc, *nodes):
    """Зарегистрировать цепь с узлами (ref, pin)."""
    assert name not in NETS, "сеть %s уже определена" % name
    NETS[name] = {"description": desc, "nodes": [[r, str(p)] for (r, p) in nodes]}

def add_nodes(name, *nodes):
    for (r, p) in nodes:
        NETS[name]["nodes"].append([r, str(p)])

# ============================================================================
#  ПИНЫ МК U1 = STM32F103C8T6 (LQFP-48). Имя пина -> номер вывода.
# ============================================================================
mp = {
 'VBAT':1,'PC13':2,'PC14':3,'PC15':4,'PD0':5,'PD1':6,'NRST':7,'VSSA':12,'VDDA':13,
 'PC0':8,'PC1':9,'PC2':10,'PC3':11,
 'PA0':14,'PA1':15,'PA2':16,'PA3':17,'PA4':20,'PA5':21,'PA6':22,'PA7':23,
 'PB0':26,'PB1':27,'PB2':28,'PB10':29,'PB11':30,
 'PB12':33,'PB13':34,'PB14':35,'PB15':36,
 'PA8':41,'PA9':42,'PA10':43,'PA11':44,'PA12':45,'PA13':46,'PA14':49,'PA15':50,
 'PB3':55,'PB4':56,'PB5':57,'PB6':58,'PB7':59,'PB8':61,'PB9':62,
 'PC6':37,'PC7':38,'PC8':39,'PC9':40,'PC10':51,'PC11':52,'PC12':53,
 'PD2':54,'BOOT0':60}

# ПИНЫ прочих символов (логические, задокументированы в metadata.symbol_pin_map)
# U2..U5 DRV8871 : 1 GND,2 IN2,3 IN1,4 ILIM,5 VM,6 OUT1,7 PGND,8 OUT2
# U6/U7  LDO     : 1 IN,2 GND,3 OUT
# MOSFET         : 1 G,2 D,3 S
# NPN/PNP        : 1 B,2 C,3 E
# LED / Diode    : 1 A(анод),2 K(катод)
# R/C/NTC        : 1,2
# Кнопка SW      : 1,2
# Подключения разъёмов приведены в metadata.

# ============================================================================
#  ССЫЛКИ-СОКРАЩЕНИЯ ДЛЯ ДРАЙВЕРОВ (4 мотора -> 4 H-моста DRV8871)
# ============================================================================
M1_DRV, M2_DRV, M3_DRV, M4_DRV = "U2", "U3", "U4", "U5"
MOT = {1: "V_MOTOR_1", 2: "V_MOTOR_2", 3: "V_MOTOR_3", 4: "V_MOTOR_4"}
DRV = {1: "U2", 2: "U3", 3: "U4", 4: "U5"}

# ============================================================================
#  ПИТАНИЕ И ЗАЩИТА
# ============================================================================
# Клеммы J1: 1,2 = +12В БАТ, 3,4 = GND. D1 - защита от переполюсовки (SS54),
# D2 - TVS от выбросов, D4 - развязка от обратного +12В на линии датчиков.
# Предохранители не применяются.
N("VBAT_IN",   "Входное бортовое питание +12В, выводы 1-2 разъёма J1",
  ("J1","1"), ("J1","2"), ("D1","1"))
N("VCC_12V",   "Силовая шина +12В после защиты от переполюсовки (D1), с фильтрацией и защитой от выбросов",
  ("D1","2"), ("D2","2"), ("C1","1"), ("C2","1"), ("C3","1"),
  ("U6","1"),
  ("U2","5"), ("U3","5"), ("U4","5"), ("U5","5"),
  ("C11","1"), ("C12","1"), ("C13","1"), ("C14","1"), ("C15","1"),
  ("J_SENS_FAN","1"), ("D3","2"),
  ("Q_AC_P","3"), ("R_AC_PU","2"), ("R_FAN_PU","2"))
N("VCC_5V",    "Внутреннее стабилизированное питание +5В (логика/питание стабилизатора 3,3В)",
  ("U6","3"), ("C4","1"), ("U7","1"), ("D4","1"), ("U8","3"), ("U8","5"))
N("V5_SENS",   "Общий выход +5В/опора на датчики и края потенциометров ОС (J1:17). Диод D4 исключает обратную подачу +12В снаружи",
  ("D4","2"), ("C16","1"), ("C17","1"), ("C18","1"), ("C19","1"),
  ("J1","17"),
  ("SOLAR_SNS","1"), ("COND_SNS","1"))
N("VCC_3V3",  "Логическое питание +3,3В микроконтроллера и фронт-панели",
  ("U7","3"), ("C5","1"), ("C6","1"), ("C7","1"), ("C8","1"), ("C9","1"),
  ("U1","19"), ("U1","32"), ("U1","48"), ("U1","64"), ("U1","1"),
  ("FB1","1"),
  ("R_NRST","1"), ("J_DBG","1"),
  ("R_TEMP_UP","1"), ("R_FAN_UP","1"),
  ("R_CABIN_UP","1"), ("R_OZH_UP","1"),
  ("R_LED1","1"), ("R_LED2","1"), ("R_LED3","1"), ("R_LED4","1"), ("R_LED5","1"), ("R_LED6","1"))
N("VDDA_3V3", "Аналоговое питание АЦП (через феррит FB1 от VCC_3V3)",
  ("FB1","2"), ("C10","1"), ("U1","13"))
N("GND",      "Общий провод (кузов автомобиля)",
  ("J1","3"), ("J1","4"), ("J1","18"),
  ("U1","18"), ("U1","31"), ("U1","47"), ("U1","63"), ("U1","12"),
  ("U2","1"), ("U2","7"), ("U3","1"), ("U3","7"), ("U4","1"), ("U4","7"), ("U5","1"), ("U5","7"),
  ("U6","2"), ("U7","2"), ("U8","2"), ("U8","8"),
  ("D2","1"),
  ("C1","2"), ("C2","2"), ("C3","2"), ("C4","2"), ("C5","2"), ("C6","2"),
  ("C7","2"), ("C8","2"), ("C9","2"), ("C10","2"),
  ("C11","2"), ("C12","2"), ("C13","2"), ("C14","2"), ("C15","2"),
  ("C16","2"), ("C17","2"), ("C18","2"), ("C19","2"),
  ("R_ILIM1","2"), ("R_ILIM2","2"), ("R_ILIM3","2"), ("R_ILIM4","2"),
  ("C_NRST","2"), ("R_BOOT","2"), ("J_DBG","4"),
  ("Q_FAN","3"), ("Q_MFAN","3"), ("Q_AC_N","3"),
  ("SW1","2"), ("SW2","2"), ("SW3","2"), ("SW4","2"), ("SW5","2"), ("SW6","2"),
  ("J_POT","2"), ("J_SW","2"),
  ("RT1","2"), ("C_TEMP","2"), ("C_FAN","2"), ("C_CABIN","2"), ("C_OZH","2"),
  ("R_FB1_B","2"), ("R_FB2_B","2"), ("R_FB3_B","2"), ("R_FB4_B","2"),
  ("C_FB1","2"), ("C_FB2","2"), ("C_FB3","2"), ("C_FB4","2"),
  ("R_SOL_B","2"), ("C_SOL","2"), ("R_CND_B","2"), ("C_CND","2"),
  ("R_ILL_B","2"), ("C_ILL","2"),
  ("R_MFAN_GD","2"), ("R_AC_GD","2"),
  # внешние устройства (виртуальные)
  ("RT_OZH","2"), ("SOLAR_SNS","3"), ("COND_SNS","3"),
  ("TEMP_KNOB","2"), ("FAN_KNOB","2"))

# ============================================================================
#  СБРОС / ЗАПУСК / ОТЛАДКА МК
# ============================================================================
N("NRST",   "Сброс МК (RC-цепь)",
  ("U1","7"), ("R_NRST","2"), ("C_NRST","1"))
N("BOOT0",  "Выбор режима загрузки: подтяжка к GND (загрузка из основной Flash)",
  ("U1","60"), ("R_BOOT","1"))
N("SWDIO",  "Отладочный интерфейс SWD: данные",
  ("U1","46"), ("J_DBG","2"))
N("SWCLK",  "Отладочный интерфейс SWD: тактирование",
  ("U1","49"), ("J_DBG","3"))

# ============================================================================
#  КНОПКИ (6 шт., без фиксации; вторая нога на GND, подтяжка внутренняя в МК)
# ============================================================================
BTN_LABEL = {
 "SW1": ("BTN_DEFROST_GLASS", "Кнопка: воздух на стекло"),
 "SW2": ("BTN_FACE",          "Кнопка: воздух в лицо"),
 "SW3": ("BTN_FEET",          "Кнопка: воздух в ноги"),
 "SW4": ("BTN_DRY_GLASS",     "Кнопка: сушка стекла"),
 "SW5": ("BTN_AC",            "Кнопка: кондиционер"),
 "SW6": ("BTN_RECIRC",        "Кнопка: рециркуляция"),
}
MCU_BTN_PIN = {"SW1": mp["PB12"], "SW2": mp["PB13"], "SW3": mp["PB14"],
               "SW4": mp["PB15"], "SW5": mp["PC10"], "SW6": mp["PC11"]}
for sw, (nm, ds) in BTN_LABEL.items():
    N(nm, ds, (sw, "1"), ("U1", MCU_BTN_PIN[sw]))

# ============================================================================
#  СВЕТОДИОДЫ-ИНДИКАТОРЫ (6 шт.) - включаются АКТИВНЫМ НУЛЁМ (нога МК к катоду)
# ============================================================================
LED_LABEL = {
 "LED1": ("LED_DEFROST_GLASS", "Индикатор кнопки: воздух на стекло"),
 "LED2": ("LED_FACE",          "Индикатор кнопки: воздух в лицо"),
 "LED3": ("LED_FEET",          "Индикатор кнопки: воздух в ноги"),
 "LED4": ("LED_DRY_GLASS",     "Индикатор кнопки: сушка стекла"),
 "LED5": ("LED_AC",            "Индикатор кнопки: кондиционер"),
 "LED6": ("LED_RECIRC",        "Индикатор кнопки: рециркуляция"),
}
MCU_LED_PIN = {"LED1": mp["PC6"], "LED2": mp["PC7"], "LED3": mp["PC8"],
               "LED4": mp["PC9"], "LED5": mp["PC12"], "LED6": mp["PD2"]}
RLED = {"LED1": "R_LED1", "LED2": "R_LED2", "LED3": "R_LED3",
        "LED4": "R_LED4", "LED5": "R_LED5", "LED6": "R_LED6"}
for ld, (nm, ds) in LED_LABEL.items():
    N(nm + "_A",   ds + " (анодная шина)", (RLED[ld], "2"), (ld, "1"))
    N(nm + "_DRV", ds + " (управление, активный низкий уровень)",
      (ld, "2"), ("U1", MCU_LED_PIN[ld]))

# ============================================================================
#  ПАНЕЛЬНЫЕ ОРГАНЫ УПРАВЛЕНИЯ (подключены внутренними 2-пин коннекторами)
# ============================================================================
# Задание температуры: внешний переменный резистор включён реостатом (2 провода:
# SIG+GND). Подтяжка R_TEMP_UP к 3,3В образует делитель; сигнал на АЦП PA0.
N("TEMP_SET_ADC", "АЦП задания температуры (потенциометр, 2-проводное включение, внутренний коннектор J_POT)",
  ("J_POT","1"), ("R_TEMP_UP","2"), ("C_TEMP","1"), ("TEMP_KNOB","1"), ("U1", mp["PA0"]))
# Галлетник вентилятора AUTO/0/1/2/3/4: резисторный код внутри фронт-модуля (2 провода)
N("FAN_SEL_ADC", "АЦП выбора режима/скорости вентилятора (галлетник AUTO,0..4, резисторный код)",
  ("J_SW","1"), ("R_FAN_UP","2"), ("C_FAN","1"), ("FAN_KNOB","1"), ("U1", mp["PA1"]))

# ============================================================================
#  ДАТЧИК ТЕМПЕРАТУРЫ В САЛОНЕ (на плате, длинные ножки в трубе продувки)
# ============================================================================
N("NTC_CABIN", "Температура воздуха в салоне (NTC на плате в трубе продувки)",
  ("RT1","1"), ("R_CABIN_UP","2"), ("C_CABIN","1"), ("U1", mp["PA2"]))

# ============================================================================
# ДАТЧИК ТЕМПЕРАТУРЫ ОЖ (двигатель, 2 провода через J1:25).
# Узел J1 отделён от входа МК защитным резистором R_OZH_PROT:
# при замыкании линии на +12В ток во вход МК ограничен.
N("NTC_HEAT_W", "Датчик патрубка отопителя: узел линии на разъёме",
  ("J1","19"), ("RT_OZH","1"), ("R_OZH_UP","2"), ("C_OZH","1"), ("R_OZH_PROT","1"))
N("NTC_HEAT", "Датчик патрубка отопителя: сигнал на АЦП (после защитного резистора)",
  ("R_OZH_PROT","2"), ("U1", mp["PA3"]))

# ============================================================================
#  ДАТЧИК СОЛНЕЧНОЙ РАДИАЦИИ (0..5В, питание +5В, J1:26/27/29)
# ============================================================================
N("SOLAR_RAW", "Выход датчика солнечной радиации (0..5В)",
  ("J1","20"), ("SOLAR_SNS","2"), ("R_SOL_A","1"))
N("SOLAR_ADC", "Сигнал солнечной радиации после делителя 5В->3,3В на АЦП",
  ("R_SOL_A","2"), ("R_SOL_B","1"), ("C_SOL","1"), ("U1", mp["PA4"]))

# ============================================================================
#  ДАТЧИК КОНДЕНСАТА НА СТЕКЛЕ (0..5В, питание +5В, J1:28/29)
# ============================================================================
N("COND_RAW", "Выход датчика конденсата на стекле (0..5В)",
  ("J1","21"), ("COND_SNS","2"), ("R_CND_A","1"))
N("COND_ADC", "Сигнал конденсата после делителя 5В->3,3В на АЦП",
  ("R_CND_A","2"), ("R_CND_B","1"), ("C_CND","1"), ("U1", mp["PA5"]))

# ============================================================================
#  МОТОРЕДУКТОРЫ ЗАСЛОНОК (4 шт.) и их потенциометры обратной связи
# ============================================================================
# J1: M1 5..7 ; M2 8..10 ; M3 11..13 ; M4 14..16  (A=3k+2, B=3k+3, FB=3k+4)
for k in (1,2,3,4):
    # Токовые провода мотора
    N(f"MOTOR_{k}_A", f"Заслонка {k}: выход А мостового драйвера к моторедуктору",
      (DRV[k], "6"), ("J1", 3*k+2), (MOT[k], "1"))
    N(f"MOTOR_{k}_B", f"Заслонка {k}: выход B мостового драйвера к моторедуктору",
      (DRV[k], "8"), ("J1", 3*k+3), (MOT[k], "2"))
    # Потенциометр обратной связи: питание (5В, VCC_5V), выход, общий
    N(f"FB_M{k}_RAW", f"Заслонка {k}: выход потенциометра положения (0..5В)",
      ("J1", 3*k+4), (MOT[k], "3"), (f"R_FB{k}_A", "1"))
    N(f"FB_M{k}", f"Заслонка {k}: сигнал ОС после делителя 5В->3,3В на АЦП",
      (f"R_FB{k}_A", "2"), (f"R_FB{k}_B", "1"), (f"C_FB{k}", "1"),
      ("U1", {"1": mp["PA6"], "2": mp["PA7"], "3": mp["PB0"], "4": mp["PB1"]}[str(k)]))
    # Управляющие входы H-моста
    N(f"M{k}_IN1", f"Заслонка {k}: вход IN1 драйвера",
      (DRV[k], "3"), ("U1", {"1": mp["PB5"], "2": mp["PA9"], "3": mp["PA11"], "4": mp["PB7"]}[str(k)]))
    N(f"M{k}_IN2", f"Заслонка {k}: вход IN2 драйвера",
      (DRV[k], "2"), ("U1", {"1": mp["PB6"], "2": mp["PA10"], "3": mp["PA12"], "4": mp["PC13"]}[str(k)]))
    # Установка токоограничения H-моста
    N(f"ILIM_{k}", f"Заслонка {k}: установка токоограничения драйвера",
      (DRV[k], "4"), (f"R_ILIM{k}", "1"))

# ============================================================================
#  ОСНОВНОЙ ВЕНТИЛЯТОР ПЕЧКИ (ШИМ-команда на внешний силовой модуль)
# ============================================================================
N("FAN_PWM_CTL", "ШИМ управления основным вентилятором (TIM1_CH1)",
  ("U1", mp["PA8"]), ("R_FAN_GATE", "1"))
N("FAN_GATE",    "Затвор буферного MOSFET",
  ("R_FAN_GATE", "2"), ("Q_FAN", "1"))
N("FAN_PWM_NODE", "Выход ШИМ 12В на внешний силовой модуль вентилятора (открытый сток, инверсный)",
  ("Q_FAN", "2"), ("R_FAN_PU", "1"), ("R_FAN_SER", "1"))
N("FAN_PWM_OUT", "ШИМ-линия к разъёму J1:30 (через защитный резистор R_FAN_SER)",
  ("R_FAN_SER", "2"), ("J1", "23"))

# ============================================================================
#  МИНИ-ВЕНТИЛЯТОР ПРОДУВКИ ДАТЧИКА (внутренний коннектор 2п)
# ============================================================================
N("M_FAN_CTL",   "Управление мини-вентилятором продувки датчика",
  ("U1", mp["PA15"]), ("R_MFAN_G", "1"))
N("M_FAN_GATE",  "Затвор MOSFET мини-вентилятора",
  ("R_MFAN_G", "2"), ("Q_MFAN", "1"), ("R_MFAN_GD", "1"))
N("SENS_FAN_SW", "Коммутируемая линия питания мини-вентилятора",
  ("Q_MFAN", "2"), ("J_SENS_FAN", "2"), ("D3", "1"))

# ============================================================================
#  ВЫХОД ЗАПРОСА КОНДИЦИОНЕРА (12В на вход ЭБУ двигателя)
# ============================================================================
N("AC_CTL",      "Управление транзистором запроса кондиционера",
  ("U1", mp["PB2"]), ("R_AC_1", "1"))
N("AC_BASE",     "База NPN-драйвера запроса кондиционера",
  ("R_AC_1", "2"), ("Q_AC_N", "1"), ("R_AC_GD", "1"))
N("AC_PNP_BASE", "База высокостороннего PNP-ключа 12В",
  ("Q_AC_N", "2"), ("Q_AC_P", "1"), ("R_AC_PU", "1"))
N("AC_REQ",      "Выход запроса кондиционера (через защитный резистор R_AC_SER)",
  ("Q_AC_P", "2"), ("R_AC_SER", "1"))
N("AC_REQ_OUT",  "Линия запроса кондиционера +12В к J1:31 (вход ЭБУ двигателя)",
  ("R_AC_SER", "2"), ("J1", "24"))

# ============================================================================
#  ПОДСВЕТКА ПРИБОРА (внешний провод, вход уровня бортовой сети)
# ============================================================================
N("ILLUM_IN_RAW", "Вход внешней подсветки прибора (+12В габаритов)",
  ("J1", "22"), ("R_ILL_A", "1"))
N("ILLUM_SENSE",  "Сигнал подсветки после делителя на вход МК",
  ("R_ILL_A", "2"), ("R_ILL_B", "1"), ("C_ILL", "1"), ("U1", mp["PD0"]))


# ============================================================================
#  ШИНА CAN (MCP2562; STM32F103RCT6 bxCAN: TX=PB9(62), RX=PB8(61))
# ============================================================================
N("CAN_TX", "CAN: передача от МК к трансиверу",
  ("U1", mp["PB9"]), ("U8","1"))
N("CAN_RX", "CAN: приём от трансивера к МК",
  ("U1", mp["PB8"]), ("U8","4"))
N("CANH",   "CAN: шина High (J1:25)",
  ("U8","7"), ("J1","25"))
N("CANL",   "CAN: шина Low (J1:26)",
  ("U8","6"), ("J1","26"))

# ============================================================================
#  ПРОВЕРКА: каждый (ref, pin) встречается ровно в одной сети
# ============================================================================
seen = {}
for nm, inf in NETS.items():
    for (r, p) in inf["nodes"]:
        key = (r, p)
        if key in seen:
            raise SystemExit("Дубликат узла %s:%s в сетях %s и %s" % (r, p, seen[key], nm))
        seen[key] = nm

# ============================================================================
#  ПЕРЕЧЕНЬ РАДИОКОМПОНЕНТОВ (BOM)
# ============================================================================
def comp(ref, value, library, sym, footprint, ctype, virtual=False):
    return {ref: {"value": value, "library": library, "sym_name": sym,
                  "footprint": footprint, "type": ctype, "virtual": virtual}}

C = {}
# --- Силовые / защита ---
C.update(comp("D1",  "SS54 (5A, 40В) защита от переполюсовки", "Device", "D_Schottky",
              "Diode_SMD:D_SMA", "Power_Protection"))
C.update(comp("D2",  "SMBJ15A TVS защита от выбросов", "Device", "D_Zener",
              "Diode_SMD:D_SMB", "Power_Protection"))
C.update(comp("D4",  "SS14 диодная развязка от обратного +12В на линии датчиков", "Device", "D_Schottky",
              "Diode_SMD:D_SMA", "Power_Protection"))
C.update(comp("C1",  "470uF 25В электролит по питанию", "Device", "C",
              "Capacitor_SMD:CP_Elec_10x10.5", "Filter_Power"))
C.update(comp("C2",  "100nF керамика по питанию 12В", "Device", "C",
              "Capacitor_SMD:C_0603_1608Metric", "Filter_Power"))
C.update(comp("C3",  "10uF 35В вход стабилизатора 5В", "Device", "C",
              "Capacitor_SMD:C_0805_2012Metric", "Filter_Power"))
C.update(comp("C4",  "10uF 10В выход стабилизатора 5В", "Device", "C",
              "Capacitor_SMD:C_0805_2012Metric", "Filter_Power"))
C.update(comp("C5",  "10uF 6,3В выход стабилизатора 3,3В", "Device", "C",
              "Capacitor_SMD:C_0805_2012Metric", "Filter_Power"))
C.update(comp("C6",  "10uF 6,3В шина 3,3В (общий накопитель)", "Device", "C",
              "Capacitor_SMD:C_0805_2012Metric", "Filter_Power"))
C.update(comp("C7",  "100nF развязка VDD_1", "Device", "C",
              "Capacitor_SMD:C_0603_1608Metric", "Filter_Decoupling"))
C.update(comp("C8",  "100nF развязка VDD_2", "Device", "C",
              "Capacitor_SMD:C_0603_1608Metric", "Filter_Decoupling"))
C.update(comp("C9",  "100nF развязка VDD_3", "Device", "C",
              "Capacitor_SMD:C_0603_1608Metric", "Filter_Decoupling"))
C.update(comp("C10", "100nF фильтр VDDA", "Device", "C",
              "Capacitor_SMD:C_0603_1608Metric", "Filter_Decoupling"))
C.update(comp("C11", "100uF 25В силовая шина моторов", "Device", "C",
              "Capacitor_SMD:CP_Elec_8x10.5", "Filter_Power"))
C.update(comp("C12", "100nF питание драйвера U2", "Device", "C",
              "Capacitor_SMD:C_0603_1608Metric", "Filter_Decoupling"))
C.update(comp("C13", "100nF питание драйвера U3", "Device", "C",
              "Capacitor_SMD:C_0603_1608Metric", "Filter_Decoupling"))
C.update(comp("C14", "100nF питание драйвера U4", "Device", "C",
              "Capacitor_SMD:C_0603_1608Metric", "Filter_Decoupling"))
C.update(comp("C15", "100nF питание драйвера U5", "Device", "C",
              "Capacitor_SMD:C_0603_1608Metric", "Filter_Decoupling"))
C.update(comp("C16", "100nF фильтр опоры потенциометра M1", "Device", "C",
              "Capacitor_SMD:C_0603_1608Metric", "Filter_Analog"))
C.update(comp("C17", "100nF фильтр опоры потенциометра M2", "Device", "C",
              "Capacitor_SMD:C_0603_1608Metric", "Filter_Analog"))
C.update(comp("C18", "100nF фильтр опоры потенциометра M3", "Device", "C",
              "Capacitor_SMD:C_0603_1608Metric", "Filter_Analog"))
C.update(comp("C19", "100nF фильтр опоры потенциометра M4", "Device", "C",
              "Capacitor_SMD:C_0603_1608Metric", "Filter_Analog"))
C.update(comp("FB1", "Феррит 600Ом@100МГц по питанию VDDA", "Device", "L",
              "Inductor_SMD:L_0805_2012Metric", "Filter_Analog"))
# --- Стабилизаторы ---
C.update(comp("U6", "MC78M05CDTG (5В, 500мА, TO-252)", "Regulator_Linear", "LM78M05_TO252",
              "Package_TO_SOT_SMD:TO-252-3_TabPin2", "Regulator_5V"))
C.update(comp("U7", "AMS1117-3.3 (3,3В, SOT-223)", "Regulator_Linear", "AP1117-15",
              "Package_TO_SOT_SMD:SOT-223-3_TabPin2", "Regulator_3V3"))
# --- CAN-трансивер ---
# --- CAN-трансивер ---
C.update(comp("U8", "MCP2562-E-SN (CAN transceiver, SOIC-8)", "Interface_CAN_LIN", "MCP2562-E-SN",
              "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm", "CAN_Transceiver"))
# --- Микроконтроллер ---
C.update(comp("U1", "STM32F103RCT6 (LQFP-64)", "MCU_ST_STM32F1", "STM32F103R_C-D-E_Tx",
              "Package_QFP:LQFP-64_10x10mm_P0.5mm", "MCU"))
C.update(comp("J_DBG", "SWD-отладка 1x04", "Connector_Generic", "Conn_01x04",
              "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical", "Debug_Connector"))
C.update(comp("R_NRST", "10k сброс МК", "Device", "R",
              "Resistor_SMD:R_0603_1608Metric", "RC_Reset"))
C.update(comp("C_NRST", "100nF сброс МК", "Device", "C",
              "Capacitor_SMD:C_0603_1608Metric", "RC_Reset"))
C.update(comp("R_BOOT", "10k BOOT0 к GND", "Device", "R",
              "Resistor_SMD:R_0603_1608Metric", "RC_Reset"))
# --- Мостовые драйверы моторов ---
for k, drv in DRV.items():
    C.update(comp(drv, "DRV8871 H-мост заслонки %d" % k, "Driver_Motor", "DRV8871DDA",
                  "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm", "Motor_Driver"))
    C.update(comp(f"R_ILIM{k}", "33k токоограничение драйвера (подобрать)", "Device", "R",
                  "Resistor_SMD:R_0603_1608Metric", "Motor_Driver"))
# --- Разъёмы ---
C.update(comp("J1", "Разъём к автомобилю 2x16 (32 конт.)", "Connector_Generic", "Conn_02x16_Odd_Even",
              "Connector_PinHeader_2.54mm:PinHeader_2x16_P2.54mm_Horizontal", "Connector_Main"))
C.update(comp("J_POT", "Внутр. коннектор потенциометра (2п, XH)", "Connector_Generic", "Conn_01x02",
              "Connector_JST:JST_XH_B2B-XH-A_1x02_P2.50mm_Vertical", "Connector_UI"))
C.update(comp("J_SW", "Внутр. коннектор галлетника (2п, XH)", "Connector_Generic", "Conn_01x02",
              "Connector_JST:JST_XH_B2B-XH-A_1x02_P2.50mm_Vertical", "Connector_UI"))
C.update(comp("J_SENS_FAN", "Внутр. коннектор вентилятора продувки (2п, XH)", "Connector_Generic", "Conn_01x02",
              "Connector_JST:JST_XH_B2B-XH-A_1x02_P2.50mm_Vertical", "Connector_UI"))
# --- Кнопки и светодиоды панели ---
for i, sw in enumerate(["SW1","SW2","SW3","SW4","SW5","SW6"]):
    C.update(comp(sw, "Кнопка тактовая 6x6 без фиксации", "Switch", "SW_Push",
                  "Button_Switch_THT:SW_Push_1P1T_NO_6x6mm_H7.0mm", "UI_Button"))
C.update(comp("LED1", "Индикатор зелёный 1206", "Device", "LED",
              "LED_SMD:LED_1206_3216Metric", "UI_LED"))
C.update(comp("LED2", "Индикатор зелёный 1206", "Device", "LED",
              "LED_SMD:LED_1206_3216Metric", "UI_LED"))
C.update(comp("LED3", "Индикатор зелёный 1206", "Device", "LED",
              "LED_SMD:LED_1206_3216Metric", "UI_LED"))
C.update(comp("LED4", "Индикатор янтарный 1206", "Device", "LED",
              "LED_SMD:LED_1206_3216Metric", "UI_LED"))
C.update(comp("LED5", "Индикатор зелёный 1206", "Device", "LED",
              "LED_SMD:LED_1206_3216Metric", "UI_LED"))
C.update(comp("LED6", "Индикатор зелёный 1206", "Device", "LED",
              "LED_SMD:LED_1206_3216Metric", "UI_LED"))
for i in range(1, 7):
    C.update(comp(f"R_LED{i}", "1k токоограничение индикатора", "Device", "R",
                  "Resistor_SMD:R_0603_1608Metric", "UI_LED"))
# --- Транзисторы вывода ---
C.update(comp("Q_FAN",  "BSS138 буфер ШИМ вентилятора", "Device", "Q_NMOS",
              "Package_TO_SOT_SMD:SOT-23", "Switch_OpenDrain"))
C.update(comp("R_FAN_GATE", "1k затвор Q_FAN", "Device", "R",
              "Resistor_SMD:R_0603_1608Metric", "Switch_OpenDrain"))
C.update(comp("R_FAN_PU", "4.7k подтяжка выхода ШИМ к 12В", "Device", "R",
              "Resistor_SMD:R_0603_1608Metric", "Switch_OpenDrain"))
C.update(comp("R_FAN_SER", "1k защитный резистор в линии ШИМ вентилятора (к J1:30)", "Device", "R",
              "Resistor_SMD:R_0603_1608Metric", "Switch_OpenDrain"))
C.update(comp("Q_MFAN", "AO3400 ключ мини-вентилятора (логич. уровень, 5,7А)", "Device", "Q_NMOS",
              "Package_TO_SOT_SMD:SOT-23", "Switch_Load"))
C.update(comp("R_MFAN_G",  "1k затвор Q_MFAN", "Device", "R",
              "Resistor_SMD:R_0603_1608Metric", "Switch_Load"))
C.update(comp("R_MFAN_GD", "10k подтяжка затвора Q_MFAN к GND", "Device", "R",
              "Resistor_SMD:R_0603_1608Metric", "Switch_Load"))
C.update(comp("D3", "1N4148W обратный диод вентилятора", "Device", "D",
              "Diode_SMD:D_SOD-123", "Switch_Load"))
C.update(comp("Q_AC_N", "MMBT3904 драйвер запроса кондиционера", "Device", "Q_NPN",
              "Package_TO_SOT_SMD:SOT-23", "Switch_12V"))
C.update(comp("Q_AC_P", "MMBT3906 высокосторонний ключ 12В", "Device", "Q_PNP",
              "Package_TO_SOT_SMD:SOT-23", "Switch_12V"))
C.update(comp("R_AC_1",  "10k база Q_AC_N", "Device", "R",
              "Resistor_SMD:R_0603_1608Metric", "Switch_12V"))
C.update(comp("R_AC_GD", "100k подтяжка базы Q_AC_N к GND", "Device", "R",
              "Resistor_SMD:R_0603_1608Metric", "Switch_12V"))
C.update(comp("R_AC_PU", "10k подтяжка базы PNP к +12В", "Device", "R",
              "Resistor_SMD:R_0603_1608Metric", "Switch_12V"))
C.update(comp("R_AC_SER", "1k защитный резистор линии запроса кондиционера (к J1:31)", "Device", "R",
              "Resistor_SMD:R_0603_1608Metric", "Switch_12V"))
# --- Датчики и цепи согласования ---
C.update(comp("RT1", "NTC 10k B3435, длинные ножки, в трубе продувки", "Device", "Thermistor_NTC",
              "Resistor_THT:R_Axial_DIN0204_L3.6mm_D1.6mm_P7.62mm_Horizontal", "Sensor_Cabin"))
C.update(comp("R_TEMP_UP", "10k подтяжка потенциометра температуры", "Device", "R",
              "Resistor_SMD:R_0603_1608Metric", "Analog_Condition"))
C.update(comp("C_TEMP", "100nF фильтр АЦП температуры", "Device", "C",
              "Capacitor_SMD:C_0603_1608Metric", "Analog_Condition"))
C.update(comp("R_FAN_UP", "10k подтяжка галлетника", "Device", "R",
              "Resistor_SMD:R_0603_1608Metric", "Analog_Condition"))
C.update(comp("C_FAN", "100nF фильтр АЦП галлетника", "Device", "C",
              "Capacitor_SMD:C_0603_1608Metric", "Analog_Condition"))
C.update(comp("R_CABIN_UP", "10k подтяжка NTC салона", "Device", "R",
              "Resistor_SMD:R_0603_1608Metric", "Analog_Condition"))
C.update(comp("C_CABIN", "100nF фильтр АЦП салона", "Device", "C",
              "Capacitor_SMD:C_0603_1608Metric", "Analog_Condition"))
C.update(comp("R_OZH_UP", "10k подтяжка NTC патрубка отопителя", "Device", "R",
              "Resistor_SMD:R_0603_1608Metric", "Analog_Condition"))
C.update(comp("R_OZH_PROT", "10k защитный резистор линии NTC патрубка перед АЦП (J1:25)", "Device", "R",
              "Resistor_SMD:R_0603_1608Metric", "Analog_Condition"))
C.update(comp("C_OZH", "100nF фильтр АЦП ОЖ", "Device", "C",
              "Capacitor_SMD:C_0603_1608Metric", "Analog_Condition"))
C.update(comp("R_SOL_A", "10k делитель сигнала солнечной радиации (верх)", "Device", "R",
              "Resistor_SMD:R_0603_1608Metric", "Analog_Condition"))
C.update(comp("R_SOL_B", "20k делитель сигнала солнечной радиации (низ)", "Device", "R",
              "Resistor_SMD:R_0603_1608Metric", "Analog_Condition"))
C.update(comp("C_SOL", "100nF фильтр АЦП солнечной радиации", "Device", "C",
              "Capacitor_SMD:C_0603_1608Metric", "Analog_Condition"))
C.update(comp("R_CND_A", "10k делитель сигнала конденсата (верх)", "Device", "R",
              "Resistor_SMD:R_0603_1608Metric", "Analog_Condition"))
C.update(comp("R_CND_B", "20k делитель сигнала конденсата (низ)", "Device", "R",
              "Resistor_SMD:R_0603_1608Metric", "Analog_Condition"))
C.update(comp("C_CND", "100nF фильтр АЦП конденсата", "Device", "C",
              "Capacitor_SMD:C_0603_1608Metric", "Analog_Condition"))
for k in (1,2,3,4):
    C.update(comp(f"R_FB{k}_A", f"10k делитель ОС заслонки {k} (верх)", "Device", "R",
                  "Resistor_SMD:R_0603_1608Metric", "Analog_Condition"))
    C.update(comp(f"R_FB{k}_B", f"20k делитель ОС заслонки {k} (низ)", "Device", "R",
                  "Resistor_SMD:R_0603_1608Metric", "Analog_Condition"))
    C.update(comp(f"C_FB{k}", f"100nF фильтр АЦП ОС заслонки {k}", "Device", "C",
                  "Capacitor_SMD:C_0603_1608Metric", "Analog_Condition"))
C.update(comp("R_ILL_A", "47k делитель входа подсветки (верх)", "Device", "R",
              "Resistor_SMD:R_0603_1608Metric", "Analog_Condition"))
C.update(comp("R_ILL_B", "10k делитель входа подсветки (низ)", "Device", "R",
              "Resistor_SMD:R_0603_1608Metric", "Analog_Condition"))
C.update(comp("C_ILL", "100nF фильтр входа подсветки", "Device", "C",
              "Capacitor_SMD:C_0603_1608Metric", "Analog_Condition"))
# --- Внешние устройства (не устанавливаются на плату; виртуальные символы) ---
for k, vm in MOT.items():
    C.update(comp(vm, "Моторедуктор заслонки с потенциометром (внешний)", "Virtual", "EXT_MOTOR_FB",
                  "VIRTUAL_NO_PCB", "External_Actuator", virtual=True))
C.update(comp("RT_OZH", "NTC 10k B3435 на выходном патрубке отопителя (внешний)", "Virtual", "EXT_NTC",
              "VIRTUAL_NO_PCB", "External_Sensor", virtual=True))
C.update(comp("SOLAR_SNS", "Датчик солнечной радиации 0..5В (внешний)", "Virtual", "EXT_SOLAR",
              "VIRTUAL_NO_PCB", "External_Sensor", virtual=True))
C.update(comp("COND_SNS", "Датчик конденсата на стекле 0..5В (внешний)", "Virtual", "EXT_COND",
              "VIRTUAL_NO_PCB", "External_Sensor", virtual=True))
C.update(comp("TEMP_KNOB", "Потенциометр задания температуры (внешний, 2п)", "Virtual", "EXT_KNOB_TEMP",
              "VIRTUAL_NO_PCB", "External_Control", virtual=True))
C.update(comp("FAN_KNOB", "Галлетник AUTO,0..4 резисторный код (внешний, 2п)", "Virtual", "EXT_KNOB_FAN",
              "VIRTUAL_NO_PCB", "External_Control", virtual=True))


# ============================================================================
#  РАЗДЕЛЕНИЕ "value" (номинал) И "description" (описание/роль) ДЛЯ КОМПОНЕНТОВ
# ============================================================================
def _nominal_of(value):
    tokens = str(value).split()
    if not tokens:
        return ""
    acc = []
    for t in tokens:
        c0 = t[0]
        cyr = '\u0400' <= c0 <= '\u04FF'
        if not acc and cyr:
            return str(value)
        if acc and (cyr or c0 in '(№'):
            break
        if not acc and c0 in '(№':
            return str(value)
        acc.append(t)
    return ' '.join(acc) if acc else str(value)

for ref, info in C.items():
    full = str(info.get("value", ""))
    nom = _nominal_of(full)
    if nom == full:
        desc = full
    else:
        desc = full[len(nom):].strip(" ,()")
    info["value"] = nom
    info["description"] = desc

# ============================================================================
#  МЕТАДАННЫЕ
# ============================================================================
metadata = {
    "project": "Climate Control Niva Travel",
    "version": "2.2",
    "specification": "Модель электрической схемы: перечень компонентов и цепей для генерации схемы KiCad",
    "mcu": "STM32F103C8T6 (LQFP-48), тактирование от внутреннего HSI 8МГц (PD0/PD1 свободны)",
    "architecture": {
        "mcu": "U1 STM32F103C8T6",
        "motor_drivers": "4 x DRV8871 (H-мост, токоограничение, SOIC-8) - по одному на заслонку",
        "power": "12В -> защита от переполюсовки (D1/SS54) + TVS (D2) -> 5В (MC78M05) -> 3,3В (AMS1117)",
        "fan_main": "ШИМ-команда на внешний силовой модуль вентилятора через J1:30",
        "fan_sensor": "мини-вентилятор продувки датчика через внутренний коннектор J_SENS_FAN (AO3400)",
        "protection": {
            "scope": "Защита от ошибок подключения предусмотрена ТОЛЬКО на внешних линиях разъёма J1 (32-пин). Внутренние линии (кнопки, светодиоды, вентилятор продувки, ручки J_POT/J_SW) не защищаются. Предохранители не применяются.",
            "power_in": "D1 (переполюсовка) + D2 (TVS выбросы) + C1/C11 - защита входа и силовой шины",
            "sens_5v": "линии +5В датчиков и опор ОС (J1:7/12/17/22/26): диод D4 (SS14) исключает подачу обратного +12В снаружи",
            "ozh": "NTC ОЖ (J1:25): последовательный R_OZH_PROT 10k ограничивает ток при КЗ линии на +12В",
            "fb_pots": "сигналы потенциометров ОС (J1:8/13/18/23): делитель R_FB_A 10k ограничивает ток в АЦП",
            "solar_cond": "солнце (J1:27)/конденсат (J1:28): R_SOL_A / R_CND_A 10k ограничивают ток в АЦП",
            "illum": "подсветка (J1:32): R_ILL_A 47k (рассчитан на приход +12В штатно)",
            "fan_pwm": "ШИМ вентилятора (J1:30): R_FAN_SER 1k ограничивает ток при КЗ линии",
            "ac": "запрос кондиционера (J1:31): R_AC_SER 1k ограничивает ток при КЗ на GND",
            "motors": "выходы моторов (J1:5-24): внутреннее токоограничение DRV8871 (R_ILIM)",
            "ground": "ВНИМАНИЕ: силовые/датчиковые земли (J1:3/4/9/14/19/24/29) перепутывать с +12В нельзя - это КЗ кузова через плату; контролировать косой."
        },
        "sensors": {
            "cabin_air": "NTC на плате, длинные ножки в трубе продувки (RT1)",
            "heat_pipe": "NTC на выходном патрубке радиатора печки, J1:25",
            "solar": "датчик солнечной радиации 0..5В, J1:26/27/29",
            "condensate": "датчик конденсата на стекле 0..5В, J1:26/28/29",
            "illumination": "вход подсветки прибора J1:32"
        },
        "controls": {
            "buttons": "6 кнопок без фиксации (стекло/лицо/ноги/сушка стекла/кондиционер/рециркуляция), каждая со светодиодом-индикатором",
            "temp_knob": "потенциометр задания температуры, подключается внутренним 2-пин коннектором J_POT (реостатное включение)",
            "fan_switch": "галетник AUTO,0,1,2,3,4, подключается внутренним 2-пин коннектором J_SW (резисторный код)"
        },
        "actuators_mapping": {
            "M1 (U2)": "заслонка ТЕПЛО/ХОЛОД (смеситель/клапан отопителя)",
            "M2 (U3)": "заслонка режима: СТЕКЛО или (ЛИЦО+НОГИ)",
            "M3 (U4)": "заслонка режима: ЛИЦО или НОГИ",
            "M4 (U5)": "заслонка РЕЦИРКУЛЯЦИИ",
            "note": "Комбинация M2/M3 формирует режимы подачи воздуха; M1 управляется заданием температуры с потенциометра."
        }
    },
    "j1_pinout": {
        "1": "+12В_БАТ вход питания",
        "2": "+12В_БАТ вход питания (дубль, снижение нагрузки)",
        "3": "GND_PWR",
        "4": "GND_PWR (дубль)",
        "5": "M1_A",
        "6": "M1_B",
        "7": "M1_FB (выход потенциометра ОС)",
        "8": "M2_A",
        "9": "M2_B",
        "10": "M2_FB",
        "11": "M3_A",
        "12": "M3_B",
        "13": "M3_FB",
        "14": "M4_A",
        "15": "M4_B",
        "16": "M4_FB",
        "17": "+5В_SENS/REF (края потенциометров заслонок и питание датчиков)",
        "18": "DGND (общая цифровая земля датчиков/потенциометров)",
        "19": "NTC_HEAT (датчик на патрубке радиатора печки)",
        "20": "SOLAR_OUT (0..5В)",
        "21": "COND_OUT (0..5В)",
        "22": "ILLUM_IN (подсветка прибора)",
        "23": "FAN_PWM_OUT (ШИМ на внешний силовой модуль)",
        "24": "AC_REQ_OUT (+12В запрос кондиционера на вход ЭБУ)",
        "25": "CANH",
        "26": "CANL",
        "27": "резерв",
        "28": "резерв",
        "29": "резерв",
        "30": "резерв",
        "31": "резерв",
        "32": "резерв"
    },
    "symbol_pin_map": {
        "MCU_ST_STM32F1:STM32F103C8Tx": "номера выводов = физические номера LQFP-48 (см. mcu_pin_map)",
        "Driver_Motor:DRV8871DDA": {"1": "GND", "2": "IN2", "3": "IN1", "4": "ILIM", "5": "VM", "6": "OUT1", "7": "PGND", "8": "OUT2"},
        "Regulator_Linear:L78M05": {"1": "IN", "2": "GND", "3": "OUT"},
        "Regulator_Linear:AMS1117-3.3": {"1": "IN", "2": "GND", "3": "OUT"},
        "Device:Q_NMOS_GSD": {"1": "G", "2": "D", "3": "S"},
        "Device:Q_NPN_ECB": {"1": "B", "2": "C", "3": "E"},
        "Device:Q_PNP_ECB": {"1": "B", "2": "C", "3": "E"},
        "Device:LED": {"1": "A(анод)", "2": "K(катод)"},
        "Device:D": {"1": "A(анод)", "2": "K(катод)"},
        "Device:D_Zener": {"1": "A(анод)", "2": "K(катод)"},
        "Device:D_Schottky": {"1": "A(анод)", "2": "K(катод)"}
    },
    "mcu_pin_map": {
        "1": "VBAT -> VCC_3V3", "2": "PC13 -> M4_IN2 (драйвер U5)",
        "3": "PC14 -> LED4_DRV", "4": "PC15 -> LED5_DRV", "5": "PD0 -> ILLUM_SENSE",
        "7": "NRST", "8": "VSSA -> GND", "9": "VDDA -> VDDA_3V3",
        "10": "PA0 -> TEMP_SET_ADC", "11": "PA1 -> FAN_SEL_ADC", "12": "PA2 -> NTC_CABIN",
        "13": "PA3 -> NTC_OZH", "14": "PA4 -> SOLAR_ADC", "15": "PA5 -> COND_ADC",
        "16": "PA6 -> FB_M1", "17": "PA7 -> FB_M2", "18": "PB0 -> FB_M3", "19": "PB1 -> FB_M4",
        "20": "PB2 -> AC_CTL (запрос кондиционера)",
        "21": "PB10 -> BTN_DEFROST_GLASS", "22": "PB11 -> BTN_FACE",
        "23": "VSS_1", "24": "VDD_1",
        "25": "PB12 -> BTN_FEET", "26": "PB13 -> BTN_DRY_GLASS",
        "27": "PB14 -> BTN_AC", "28": "PB15 -> BTN_RECIRC",
        "29": "PA8 -> FAN_PWM_CTL (TIM1_CH1)", "30": "PA9 -> M1_IN1",
        "31": "PA10 -> M1_IN2", "32": "PA11 -> M2_IN1", "33": "PA12 -> M2_IN2",
        "34": "PA13/SWDIO", "35": "VSS_2", "36": "VDD_2", "37": "PA14/SWCLK",
        "38": "PA15 -> LED1_DRV", "39": "PB3 -> LED2_DRV", "40": "PB4 -> LED3_DRV",
        "41": "PB5 -> M3_IN1", "42": "PB6 -> M3_IN2", "43": "PB7 -> M4_IN1",
        "44": "BOOT0 (через 10k к GND)", "45": "PB8 -> LED6_DRV", "46": "PB9 -> M_FAN_CTL",
        "47": "VSS_3", "48": "VDD_3"
    },
    "notes": [
        "MCU выбран STM32F103C8T6 как бюджетный; при необходимости заменяется без изменения топологии цепей (сменить символ и номера выводов в mcu_pin_map).",
        "Светодиоды-индикаторы включаются АКТИВНЫМ НУЛЁМ (МК притягивает катод к GND).",
        "Потенциометр температуры и галлетник подключены 2-проводными линиями; на фронт-модуле они образуют сопротивление на GND, плата опрашивает делитель с подтяжкой к 3,3В.",
        "Выход ШИМ основного вентилятора - открытый сток, активный низкий уровень (ШИМ инвертируется в ПО).",
        "Питание мини-вентилятора продувки +12В снимается с VCC_12V через J_SENS_FAN.",
        "Полярность проводов моторов к драйверам задаётся при настройке (направление 'открыть/закрыть' настраивается в ПО или перестановкой Mx_A/Mx_B).",
        "Потенциометры ОС заслонок питаются от +5В; сигнал масштабируется делителем 10k/20k до диапазона АЦП 0..3,3В.",
        "Подтяжки кнопок - внутренние у МК; на плату выведены только кнопка+индикатор.",
        "Разъём J1 на 32 контакта описан в j1_pinout; фактический тип (автомобильный герметичный) уточняется под косу."
    ]
}

# ============================================================================
#  ЗАГЛУШКИ ГРАФИКИ СИМВОЛОВ (используются генератором build_project.py)
#  Реальные символы KiCad берутся из библиотек по lib_id при импорте.
# ============================================================================
lib_symbols = {}
def rect_for(libid, w, h):
    lib_symbols[libid] = [
        "(rectangle (start -%s %s) (end %s -%s) (stroke (width 0.254)) (fill (type background)))" % (w, h, w, h)
    ]

rect_for("MCU_ST_STM32F1:STM32F103C8Tx", "17.78", "17.78")
rect_for("Driver_Motor:DRV8871DDA", "8.0", "8.0")
rect_for("Regulator_Linear:L78M05", "5.0", "6.0")
rect_for("Regulator_Linear:AMS1117-3.3", "5.0", "6.0")
rect_for("Device:LED", "2.54", "2.54")
rect_for("Switch:SW_Push", "2.54", "1.27")
rect_for("Device:R", "3.0", "1.2")
rect_for("Device:C", "3.0", "1.5")
rect_for("Device:R_NTC", "3.0", "1.2")
rect_for("Device:L", "3.0", "2.0")
rect_for("Device:Q_NMOS_GSD", "5.0", "5.0")
rect_for("Device:Q_NPN_ECB", "5.0", "5.0")
rect_for("Device:Q_PNP_ECB", "5.0", "5.0")
rect_for("Device:D", "3.0", "2.0")
rect_for("Device:D_Zener", "3.0", "2.0")
rect_for("Device:D_Schottky", "3.0", "2.0")
rect_for("Connector_Generic:Conn_02x16_Odd_Even", "5.0", "20.0")
rect_for("Connector_Generic:Conn_01x02", "3.0", "2.0")
rect_for("Connector_Generic:Conn_01x04", "3.0", "4.0")

# ============================================================================
#  ПЛОСКИЙ СПИСОК СТРАНИЦ (все одного уровня; 1-я MAIN - разъём J1 + питание)
# ============================================================================
_default_sheet = {
    "Power_Protection": "MAIN", "Regulator_5V": "MAIN", "Regulator_3V3": "MAIN",
    "Filter_Power": "MAIN", "Connector_Main": "MAIN",
    "Filter_Decoupling": "MCU", "Filter_Analog": "ACT", "RC_Reset": "MCU", "MCU": "MCU",
    "Debug_Connector": "MCU",
    "Motor_Driver": "ACT",
    "Switch_OpenDrain": "OUT", "Switch_12V": "OUT",
    "Switch_Load": "SEN_CABIN", "Sensor_Cabin": "SEN_CABIN",
    "Connector_UI": "UI", "UI_Button": "UI", "UI_LED": "UI",
    "Analog_Condition": "UI",
}
_overrides = {
    "C5": "MCU", "C6": "MCU", "C10": "MCU", "FB1": "MCU", "C7": "MCU", "C8": "MCU", "C9": "MCU",
    "C12": "ACT", "C13": "ACT", "C14": "ACT", "C15": "ACT",
    "C16": "ACT", "C17": "ACT", "C18": "ACT", "C19": "ACT",
    "J_SENS_FAN": "SEN_CABIN", "D3": "SEN_CABIN",
    "R_OZH_UP": "SEN_HEAT", "R_OZH_PROT": "SEN_HEAT", "C_OZH": "SEN_HEAT",
    "R_SOL_A": "SEN_SOLAR", "R_SOL_B": "SEN_SOLAR", "C_SOL": "SEN_SOLAR",
    "R_CND_A": "SEN_COND", "R_CND_B": "SEN_COND", "C_CND": "SEN_COND",
    "R_FB1_A": "ACT", "R_FB1_B": "ACT", "C_FB1": "ACT",
    "R_FB2_A": "ACT", "R_FB2_B": "ACT", "C_FB2": "ACT",
    "R_FB3_A": "ACT", "R_FB3_B": "ACT", "C_FB3": "ACT",
    "R_FB4_A": "ACT", "R_FB4_B": "ACT", "C_FB4": "ACT",
    "R_ILL_A": "UI", "R_ILL_B": "UI", "C_ILL": "UI",
    "R_TEMP_UP": "UI", "C_TEMP": "UI", "R_FAN_UP": "UI", "C_FAN": "UI",
}
_sheet_order = ["MAIN", "MCU", "UI", "SEN_CABIN", "SEN_HEAT", "SEN_SOLAR", "SEN_COND", "OUT", "ACT"]
_by_sheet = {name: [] for name in _sheet_order}
for _ref, _info in C.items():
    if _info.get("virtual"):
        continue
    _sh = _overrides.get(_ref) or _default_sheet.get(_info.get("type", ""), "MAIN")
    _by_sheet[_sh].append(_ref)
_sheets = []
for _i, _name in enumerate(_sheet_order, start=1):
    _sheets.append({"order": _i, "name": _name,
                    "file": "cc_%02d_%s.kicad_sch" % (_i, _name.lower()) if _i != 1 else "climate_control_niva_travel.kicad_sch",
                    "components": sorted(_by_sheet[_name])})
_covered = sorted(r for r in C if not C[r].get("virtual"))
_flat = sorted(r for sh in _sheets for r in sh["components"])
if _flat != _covered:
    raise SystemExit("Ошибка разбиения на страницы: лишние %s, пропущены %s" % (sorted(set(_flat) - set(_covered)), sorted(set(_covered) - set(_flat))))

# ============================================================================
#  СБОРКА И ЗАПИСЬ
# ============================================================================
model = {
    "metadata": metadata,
    "sheets": _sheets,
    "lib_symbols": lib_symbols,
    "components": dict(sorted(C.items())),
    "nets": NETS,
}

path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "circuit_model.json")
with open(path, "w", encoding="utf-8") as f:
    json.dump(model, f, ensure_ascii=False, indent=2)

# самопроверка
n_comp = len(C); n_nets = len(NETS); n_nodes = len(seen)
print("OK. компонентов: %d, цепей: %d, узлов: %d" % (n_comp, n_nets, n_nodes))
