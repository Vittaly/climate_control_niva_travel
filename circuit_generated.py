"""
Climate Control Project — сгенерировано из main.yaml.

==============================================================================
ОБЩАЯ ИНФОРМАЦИЯ
==============================================================================
project:   Climate Control Niva Travel
version:   2.2
root file: climate_control_niva_travel.kicad_sch

==============================================================================
ИЕРАРХИЧЕСКИЕ ЛИСТЫ И ИХ ПОРТЫ
==============================================================================
  X_CAN:
    module:  module_CAN()
    purpose: Модуль CAN
    file:    sheets/can_bus.kicad_sch
    ports (6):
      - VCC_5V                 [POWER   ] Внутреннее стабилизированное питание +5В (логика/питание стабилизатора 3,3В)
      - GND                    [POWER   ] Общий провод (кузов автомобиля)
      - CAN_TX                 [OUTPUT  ] CAN: передача от МК к трансиверу
      - CAN_RX                 [OUTPUT  ] CAN: приём от трансивера к МК
      - CANH                   [OUTPUT  ] CAN: шина High (J1:25)
      - CANL                   [OUTPUT  ] CAN: шина Low (J1:26)

  X_PWR:
    module:  module_PWR()
    purpose: Модуль PWR
    file:    sheets/power_supply.kicad_sch
    ports (24):
      - VCC_12V                [POWER   ] Силовая шина +12В после фильтра помех L1, с TVS D2 и конденсаторами
      - VCC_5V                 [POWER   ] Внутреннее стабилизированное питание +5В (логика/питание стабилизатора 3,3В)
      - VCC_3V3                [POWER   ] Логическое питание +3,3В микроконтроллера и фронт-панели
      - GND                    [POWER   ] Общий провод (кузов автомобиля)
      - NTC_HEAT_W             [OUTPUT  ] Датчик патрубка отопителя: узел линии на разъёме
      - SOLAR_RAW              [INPUT   ] Выход датчика солнечной радиации (0..5В)
      - COND_RAW               [INPUT   ] Выход датчика конденсата на стекле (0..5В)
      - MOTOR_1_A              [OUTPUT  ] Заслонка 1: выход А мостового драйвера к моторедуктору
      - MOTOR_1_B              [OUTPUT  ] Заслонка 1: выход B мостового драйвера к моторедуктору
      - MOTOR_2_A              [OUTPUT  ] Заслонка 2: выход А мостового драйвера к моторедуктору
      - MOTOR_2_B              [OUTPUT  ] Заслонка 2: выход B мостового драйвера к моторедуктору
      - FB_M2_RAW              [INPUT   ] Заслонка 2: выход потенциометра положения (0..5В)
      - MOTOR_3_A              [OUTPUT  ] Заслонка 3: выход А мостового драйвера к моторедуктору
      - MOTOR_3_B              [OUTPUT  ] Заслонка 3: выход B мостового драйвера к моторедуктору
      - FB_M3_RAW              [INPUT   ] Заслонка 3: выход потенциометра положения (0..5В)
      - MOTOR_4_A              [OUTPUT  ] Заслонка 4: выход А мостового драйвера к моторедуктору
      - MOTOR_4_B              [OUTPUT  ] Заслонка 4: выход B мостового драйвера к моторедуктору
      - FB_M4_RAW              [INPUT   ] Заслонка 4: выход потенциометра положения (0..5В)
      - AC_REQ_OUT             [INPUT   ] Линия запроса кондиционера +12В к J1:31 (вход ЭБУ двигателя)
      - ILLUM_IN_RAW           [INPUT   ] Вход внешней подсветки прибора (+12В габаритов)
      - CANH                   [OUTPUT  ] CAN: шина High (J1:25)
      - CANL                   [OUTPUT  ] CAN: шина Low (J1:26)
      - HEAT_FAN_PWM_CTL       [OUTPUT  ] Автоматически синхронизированный иерархический порт FAN_PWM_OUT
      - FB_M1_RAW              [INPUT   ] Заслонка 1: выход потенциометра положения (0..5В)

  X_UI:
    module:  module_UI()
    purpose: Модуль UI
    file:    sheets/user_interface.kicad_sch
    ports (19):
      - VCC_3V3                [POWER   ] Логическое питание +3,3В микроконтроллера и фронт-панели
      - GND                    [POWER   ] Общий провод (кузов автомобиля)
      - BTN_DEFROST_GLASS      [OUTPUT  ] Кнопка: воздух на стекло
      - BTN_FACE               [OUTPUT  ] Кнопка: воздух в лицо
      - BTN_FEET               [OUTPUT  ] Кнопка: воздух в ноги
      - BTN_DRY_GLASS          [OUTPUT  ] Кнопка: сушка стекла
      - BTN_AC                 [OUTPUT  ] Кнопка: кондиционер
      - BTN_RECIRC             [OUTPUT  ] Кнопка: рециркуляция
      - LED_DEFROST_GLASS_DRV  [OUTPUT  ] Индикатор кнопки: воздух на стекло (управление, активный низкий уровень)
      - LED_FACE_DRV           [OUTPUT  ] Индикатор кнопки: воздух в лицо (управление, активный низкий уровень)
      - LED_FEET_DRV           [OUTPUT  ] Индикатор кнопки: воздух в ноги (управление, активный низкий уровень)
      - LED_DRY_GLASS_DRV      [OUTPUT  ] Индикатор кнопки: сушка стекла (управление, активный низкий уровень)
      - LED_AC_DRV             [OUTPUT  ] Индикатор кнопки: кондиционер (управление, активный низкий уровень)
      - LED_RECIRC_DRV         [OUTPUT  ] Индикатор кнопки: рециркуляция (управление, активный низкий уровень)
      - TEMP_SET_ADC           [OUTPUT  ] АЦП задания температуры (потенциометр, 2-проводное включение, внутренний коннектор J_POT)
      - FAN_SEL_ADC            [OUTPUT  ] АЦП выбора режима/скорости вентилятора (галлетник AUTO,0..4, резисторный код)
      - NTC_CABIN              [INPUT   ] Температура воздуха в салоне (NTC на плате в трубе продувки)
      - ILLUM_IN_RAW           [INPUT   ] Вход внешней подсветки прибора (+12В габаритов)
      - ILLUM_SENSE            [POWER   ] Сигнал подсветки после делителя на вход МК

  X_SEN_CABIN:
    module:  module_SEN_CABIN()
    purpose: Модуль SEN_CABIN
    file:    sheets/cabin_sensor.kicad_sch
    ports (4):
      - VCC_12V                [POWER   ] Силовая шина +12В после фильтра помех L1, с TVS D2 и конденсаторами
      - GND                    [POWER   ] Общий провод (кузов автомобиля)
      - NTC_CABIN              [INPUT   ] Температура воздуха в салоне (NTC на плате в трубе продувки)
      - M_FAN_CTL              [INPUT   ] Управление мини-вентилятором продувки датчика

  X_SEN_HEAT:
    module:  module_SEN_HEAT()
    purpose: Модуль SEN_HEAT
    file:    sheets/heating_sensor.kicad_sch
    ports (4):
      - VCC_3V3                [POWER   ] Логическое питание +3,3В микроконтроллера и фронт-панели
      - GND                    [POWER   ] Общий провод (кузов автомобиля)
      - NTC_HEAT_W             [OUTPUT  ] Датчик патрубка отопителя: узел линии на разъёме
      - NTC_HEAT               [OUTPUT  ] Датчик патрубка отопителя: сигнал на АЦП (после защитного резистора)

  X_SEN_SOLAR:
    module:  module_SEN_SOLAR()
    purpose: Модуль SEN_SOLAR
    file:    sheets/solar_sensor.kicad_sch
    ports (3):
      - GND                    [POWER   ] Общий провод (кузов автомобиля)
      - SOLAR_RAW              [INPUT   ] Выход датчика солнечной радиации (0..5В)
      - SOLAR_ADC              [OUTPUT  ] Сигнал солнечной радиации после делителя 5В->3,3В на АЦП

  X_SEN_COND:
    module:  module_SEN_COND()
    purpose: Модуль SEN_COND
    file:    sheets/condensate_sensor.kicad_sch
    ports (3):
      - GND                    [POWER   ] Общий провод (кузов автомобиля)
      - COND_RAW               [INPUT   ] Выход датчика конденсата на стекле (0..5В)
      - COND_ADC               [OUTPUT  ] Сигнал конденсата после делителя 5В->3,3В на АЦП

  X_OUT:
    module:  module_OUT()
    purpose: Модуль OUT
    file:    sheets/power_outputs.kicad_sch
    ports (6):
      - VCC_12V                [POWER   ] Силовая шина +12В после фильтра помех L1, с TVS D2 и конденсаторами
      - GND                    [POWER   ] Общий провод (кузов автомобиля)
      - FAN_PWM_CTL            [INPUT   ] ШИМ управления основным вентилятором (TIM1_CH1)
      - AC_CTL                 [INPUT   ] Управление транзистором запроса кондиционера
      - AC_REQ_OUT             [INPUT   ] Линия запроса кондиционера +12В к J1:31 (вход ЭБУ двигателя)
      - HEAT_FAN_PWM_CTL       [OUTPUT  ] ШИМ вентилятора печки на J1:23 (после буфера Q1 и защитного R15)

  X_ACT:
    module:  module_ACT()
    purpose: Модуль ACT
    file:    sheets/actuators.kicad_sch
    ports (25):
      - VCC_12V                [POWER   ] Силовая шина +12В после фильтра помех L1, с TVS D2 и конденсаторами
      - GND                    [POWER   ] Общий провод (кузов автомобиля)
      - MOTOR_1_A              [OUTPUT  ] Заслонка 1: выход А мостового драйвера к моторедуктору
      - MOTOR_1_B              [OUTPUT  ] Заслонка 1: выход B мостового драйвера к моторедуктору
      - FB_M1                  [OUTPUT  ] Заслонка 1: сигнал ОС после делителя 5В->3,3В на АЦП
      - M1_IN1                 [INPUT   ] Заслонка 1: вход IN1 драйвера
      - M1_IN2                 [INPUT   ] Заслонка 1: вход IN2 драйвера
      - MOTOR_2_A              [OUTPUT  ] Заслонка 2: выход А мостового драйвера к моторедуктору
      - MOTOR_2_B              [OUTPUT  ] Заслонка 2: выход B мостового драйвера к моторедуктору
      - FB_M2_RAW              [INPUT   ] Заслонка 2: выход потенциометра положения (0..5В)
      - FB_M2                  [OUTPUT  ] Заслонка 2: сигнал ОС после делителя 5В->3,3В на АЦП
      - M2_IN1                 [INPUT   ] Заслонка 2: вход IN1 драйвера
      - M2_IN2                 [INPUT   ] Заслонка 2: вход IN2 драйвера
      - MOTOR_3_A              [OUTPUT  ] Заслонка 3: выход А мостового драйвера к моторедуктору
      - MOTOR_3_B              [OUTPUT  ] Заслонка 3: выход B мостового драйвера к моторедуктору
      - FB_M3_RAW              [INPUT   ] Заслонка 3: выход потенциометра положения (0..5В)
      - FB_M3                  [OUTPUT  ] Заслонка 3: сигнал ОС после делителя 5В->3,3В на АЦП
      - M3_IN1                 [INPUT   ] Заслонка 3: вход IN1 драйвера
      - M3_IN2                 [INPUT   ] Заслонка 3: вход IN2 драйвера
      - MOTOR_4_A              [OUTPUT  ] Заслонка 4: выход А мостового драйвера к моторедуктору
      - MOTOR_4_B              [OUTPUT  ] Заслонка 4: выход B мостового драйвера к моторедуктору
      - FB_M4_RAW              [INPUT   ] Заслонка 4: выход потенциометра положения (0..5В)
      - FB_M4                  [OUTPUT  ] Заслонка 4: сигнал ОС после делителя 5В->3,3В на АЦП
      - M4_IN1                 [INPUT   ] Заслонка 4: вход IN1 драйвера
      - M4_IN2                 [INPUT   ] Заслонка 4: вход IN2 драйвера

  X_BACKLIGHT:
    module:  module_BACKLIGHT()
    purpose: Модуль радиальной фоновой подсветки шкал ручек управления
    file:    sheets/backlight.kicad_sch
    ports (2):
      - ILLUM_IN_RAW           [POWER   ] Вход внешней подсветки прибора (+12В габаритов автомобиля)
      - GND                    [POWER   ] Общая силовая земля схемы

==============================================================================
КАРТА ПИНОВ МИКРОКОНТРОЛЛЕРА (STM32F103RCT6, LQFP-64)
==============================================================================
Pin  Signal    Net                   Function      Comment
------------------------------------------------------------------------------
1    VBAT      VCC_3V3               power_in      
2    PC13      M4_IN2                              драйвер U5
3    PC14      LED_DRY_GLASS_DRV                   
4    PC15      LED_AC_DRV                          
5    PD0       —                     OSC_IN        
6    PD1       —                     OSC_OUT       
7    NRST      NRST                  reset         
8    PC0       ILLUM_SENSE                         
9    PC1       —                                   
10   PC2       LED_RECIRC_DRV                      
11   PC3       M_FAN_CTL                           
12   VSSA      GND                   power_in      
13   VDDA      VDDA_3V3              power_in      
14   PA0       TEMP_SET_ADC                        
15   PA1       FAN_SEL_ADC                         
16   PA2       NTC_CABIN                           
17   PA3       NTC_HEAT                            
18   VSS_1     GND                   power_in      
19   VDD_1     VCC_3V3               power_in      
20   PA4       SOLAR_ADC                           
21   PA5       COND_ADC                            
22   PA6       FB_M1                               
23   PA7       FB_M2                               
24   PC4       —                                   
25   PC5       —                                   
26   PB0       FB_M3                               
27   PB1       FB_M4                               
28   PB2       AC_CTL                              запрос кондиционера
29   PB10      BTN_DEFROST_GLASS                   
30   PB11      BTN_FACE                            
31   VSS_2     GND                   power_in      
32   VDD_2     VCC_3V3               power_in      
33   PB12      BTN_FEET                            
34   PB13      BTN_DRY_GLASS                       
35   PB14      BTN_AC                              
36   PB15      BTN_RECIRC                          
37   PC6       —                                   
38   PC7       —                                   
39   PC8       —                                   
40   PC9       —                                   
41   PA8       FAN_PWM_CTL                         TIM1_CH1
42   PA9       M1_IN1                              
43   PA10      M1_IN2                              
44   PA11      M2_IN1                              
45   PA12      M2_IN2                              
46   PA13      SWDIO                 SWDIO         
47   VSS_3     GND                   power_in      
48   VDD_3     VCC_3V3               power_in      
49   PA14      SWCLK                 SWCLK         
50   PA15      LED_DEFROST_GLASS_DRV               
51   PC10      —                                   
52   PC11      —                                   
53   PC12      —                                   
54   PD2       —                                   
55   PB3       LED_FACE_DRV                        
56   PB4       LED_FEET_DRV                        
57   PB5       M3_IN1                              
58   PB6       M3_IN2                              
59   PB7       M4_IN1                              
60   BOOT0     BOOT0                 boot          через 10k к GND
61   PB8       CAN_RX                              
62   PB9       CAN_TX                              
63   VSS_4     GND                   power_in      
64   VDD_4     VCC_3V3               power_in      

==============================================================================
РАЗЪЁМ J1 (автомобильный жгут)
==============================================================================
   1: +12В_БАТ вход питания
   2: +12В_БАТ вход питания (дубль, снижение нагрузки)
   3: GND_PWR
   4: GND_PWR (дубль)
   5: M1_A
   6: M1_B
   7: M1_FB (выход потенциометра ОС)
   8: M2_A
   9: M2_B
  10: M2_FB
  11: M3_A
  12: M3_B
  13: M3_FB
  14: M4_A
  15: M4_B
  16: M4_FB
  17: +5В_SENS/REF (края потенциометров заслонок и питание датчиков)
  18: DGND (общая цифровая земля датчиков/потенциометров)
  19: NTC_HEAT (датчик на патрубке радиатора печки)
  20: SOLAR_OUT (0..5В)
  21: COND_OUT (0..5В)
  22: ILLUM_IN (подсветка прибора)
  23: FAN_PWM_OUT (ШИМ на внешний силовой модуль)
  24: AC_REQ_OUT (+12В запрос кондиционера на вход ЭБУ)
  25: CANH
  26: CANL
  27: резерв
  28: резерв
  29: резерв
  30: резерв
  31: резерв
  32: резерв

"""

# ==========================================================================
# BOOTSTRAP: настройка путей к библиотекам KiCad
# ==========================================================================
import os
import sys


def _find_kicad_libraries():
    base_paths = [
        '/usr/share/kicad',
        '/usr/local/share/kicad',
        os.path.expanduser('~/.var/app/org.kicad.KiCad/data/kicad'),
        '/var/lib/flatpak/app/org.kicad.KiCad/current/active/files/share/kicad',
        '/snap/kicad/current/usr/share/kicad',
    ]
    sym = None
    fp = None
    for base in base_paths:
        if not os.path.isdir(base):
            continue
        sd = os.path.join(base, 'symbols')
        if os.path.isdir(sd) and sym is None:
            if os.path.exists(os.path.join(sd, 'Device.kicad_sym')):
                sym = sd
            else:
                for r, _d, f in os.walk(sd):
                    if 'Device.kicad_sym' in f:
                        sym = r
                        break
        fd = os.path.join(base, 'footprints')
        if os.path.isdir(fd) and fp is None:
            for item in os.listdir(fd):
                if item.endswith('.pretty'):
                    fp = fd
                    break
        if sym and fp:
            break
    return sym, fp


_sym, _fp = _find_kicad_libraries()
if _sym:
    for _v in ('KICAD_SYMBOL_DIR', 'KICAD6_SYMBOL_DIR',
               'KICAD7_SYMBOL_DIR', 'KICAD8_SYMBOL_DIR',
               'KICAD9_SYMBOL_DIR', 'KICAD10_SYMBOL_DIR'):
        os.environ[_v] = _sym
    print(f'[BOOTSTRAP] Символы: {_sym}', flush=True)
if _fp:
    for _v in ('KICAD6_FOOTPRINT_DIR', 'KICAD7_FOOTPRINT_DIR',
               'KICAD8_FOOTPRINT_DIR', 'KICAD9_FOOTPRINT_DIR',
               'KICAD10_FOOTPRINT_DIR'):
        os.environ[_v] = _fp
    print(f'[BOOTSTRAP] Footprints: {_fp}', flush=True)

# Автопоиск fp-lib-table для устранения WARNING
_fp_table_candidates = [
    os.path.expanduser('~/.config/kicad/9.0/fp-lib-table'),
    os.path.expanduser('~/.config/kicad/8.0/fp-lib-table'),
    os.path.expanduser('~/.config/kicad/10.0/fp-lib-table'),
    os.path.expanduser('~/.config/kicad/fp-lib-table'),
    '/usr/share/kicad/template/fp-lib-table',
]
for _tbl in _fp_table_candidates:
    if os.path.exists(_tbl):
        os.environ['KICAD10_FP_LIB_TABLE'] = _tbl
        os.environ['KICAD9_FP_LIB_TABLE'] = _tbl
        os.environ['KICAD8_FP_LIB_TABLE'] = _tbl
        print(f'[BOOTSTRAP] fp-lib-table: {_tbl}', flush=True)
        break


from skidl import KICAD10, lib_search_paths, footprint_search_paths
from skidl import *
from skidl import SubCircuit

set_default_tool(KICAD10)

if _sym and _sym not in lib_search_paths[KICAD10]:
    lib_search_paths[KICAD10].append(_sym)
if _fp and _fp not in footprint_search_paths[KICAD10]:
    footprint_search_paths[KICAD10].append(_fp)


# ==========================================================================
# Лист X_CAN  (sheets/can_bus.yaml)
# ==========================================================================
@SubCircuit
def module_CAN(p_VCC_5V, p_GND, p_CAN_TX, p_CAN_RX, p_CANH, p_CANL):
    """
    Подстраница: X_CAN
    file: sheets/can_bus.kicad_sch
    purpose: Модуль CAN

    Порты листа:
      VCC_5V                 [POWER   ] Внутреннее стабилизированное питание +5В (логика/питание стабилизатора 3,3В)
      GND                    [POWER   ] Общий провод (кузов автомобиля)
      CAN_TX                 [OUTPUT  ] CAN: передача от МК к трансиверу
      CAN_RX                 [OUTPUT  ] CAN: приём от трансивера к МК
      CANH                   [OUTPUT  ] CAN: шина High (J1:25)
      CANL                   [OUTPUT  ] CAN: шина Low (J1:26)
    """

    # ======================================================================
    # Компоненты
    # ======================================================================
    # type:        TYPE_MCP2562-E-SN_MCP2562-E-SN
    # description: CAN transceiver, SOIC-8
    # tag:         CAN_U8
    comp_U8 = Part('Interface_CAN_LIN', 'MCP2562-E-SN', ref='U8', tag='CAN_U8', value='MCP2562-E-SN', footprint='Package_SO:SOIC-8_3.9x4.9mm_P1.27mm')
    comp_U8.fields['Description'] = 'CAN transceiver, SOIC-8'

    # ======================================================================
    # Цепи и соединения
    # ======================================================================
    # Цепь VCC_5V: Внутреннее стабилизированное питание +5В (логика/питание стабилизатора 3,3В)
    # attributes: type=POWER, voltage_level=5.0V, current_max=0.5A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_VCC_5V += comp_U8['3']
    p_VCC_5V += comp_U8['5']

    # Цепь GND: Общий провод (кузов автомобиля)
    # attributes: type=GND, voltage_level=0V, current_max=15A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_GND += comp_U8['2']
    p_GND += comp_U8['8']

    # Цепь CAN_TX: CAN: передача от МК к трансиверу
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_CAN_TX += comp_U8['1']

    # Цепь CAN_RX: CAN: приём от трансивера к МК
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_CAN_RX += comp_U8['4']

    # Цепь CANH: CAN: шина High (J1:25)
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_CANH += comp_U8['7']

    # Цепь CANL: CAN: шина Low (J1:26)
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_CANL += comp_U8['6']


module_CAN.tag = 'SHEET_CAN'


# ==========================================================================
# Лист X_PWR  (sheets/power_supply.yaml)
# ==========================================================================
@SubCircuit
def module_PWR(p_VCC_12V, p_VCC_5V, p_VCC_3V3, p_GND, p_NTC_HEAT_W, p_SOLAR_RAW, p_COND_RAW, p_MOTOR_1_A, p_MOTOR_1_B, p_MOTOR_2_A, p_MOTOR_2_B, p_FB_M2_RAW, p_MOTOR_3_A, p_MOTOR_3_B, p_FB_M3_RAW, p_MOTOR_4_A, p_MOTOR_4_B, p_FB_M4_RAW, p_AC_REQ_OUT, p_ILLUM_IN_RAW, p_CANH, p_CANL, p_HEAT_FAN_PWM_CTL, p_FB_M1_RAW):
    """
    Подстраница: X_PWR
    file: sheets/power_supply.kicad_sch
    purpose: Модуль PWR

    Порты листа:
      VCC_12V                [POWER   ] Силовая шина +12В после фильтра помех L1, с TVS D2 и конденсаторами
      VCC_5V                 [POWER   ] Внутреннее стабилизированное питание +5В (логика/питание стабилизатора 3,3В)
      VCC_3V3                [POWER   ] Логическое питание +3,3В микроконтроллера и фронт-панели
      GND                    [POWER   ] Общий провод (кузов автомобиля)
      NTC_HEAT_W             [OUTPUT  ] Датчик патрубка отопителя: узел линии на разъёме
      SOLAR_RAW              [INPUT   ] Выход датчика солнечной радиации (0..5В)
      COND_RAW               [INPUT   ] Выход датчика конденсата на стекле (0..5В)
      MOTOR_1_A              [OUTPUT  ] Заслонка 1: выход А мостового драйвера к моторедуктору
      MOTOR_1_B              [OUTPUT  ] Заслонка 1: выход B мостового драйвера к моторедуктору
      MOTOR_2_A              [OUTPUT  ] Заслонка 2: выход А мостового драйвера к моторедуктору
      MOTOR_2_B              [OUTPUT  ] Заслонка 2: выход B мостового драйвера к моторедуктору
      FB_M2_RAW              [INPUT   ] Заслонка 2: выход потенциометра положения (0..5В)
      MOTOR_3_A              [OUTPUT  ] Заслонка 3: выход А мостового драйвера к моторедуктору
      MOTOR_3_B              [OUTPUT  ] Заслонка 3: выход B мостового драйвера к моторедуктору
      FB_M3_RAW              [INPUT   ] Заслонка 3: выход потенциометра положения (0..5В)
      MOTOR_4_A              [OUTPUT  ] Заслонка 4: выход А мостового драйвера к моторедуктору
      MOTOR_4_B              [OUTPUT  ] Заслонка 4: выход B мостового драйвера к моторедуктору
      FB_M4_RAW              [INPUT   ] Заслонка 4: выход потенциометра положения (0..5В)
      AC_REQ_OUT             [INPUT   ] Линия запроса кондиционера +12В к J1:31 (вход ЭБУ двигателя)
      ILLUM_IN_RAW           [INPUT   ] Вход внешней подсветки прибора (+12В габаритов)
      CANH                   [OUTPUT  ] CAN: шина High (J1:25)
      CANL                   [OUTPUT  ] CAN: шина Low (J1:26)
      HEAT_FAN_PWM_CTL       [OUTPUT  ] Автоматически синхронизированный иерархический порт FAN_PWM_OUT
      FB_M1_RAW              [INPUT   ] Заслонка 1: выход потенциометра положения (0..5В)
    """

    # ======================================================================
    # Компоненты
    # ======================================================================
    # type:        TYPE_C_470UF_25V
    # description: электролит по питанию
    # tag:         PWR_C1
    comp_C1 = Part('Device', 'C', ref='C1', tag='PWR_C1', value='470uF', footprint='Capacitor_SMD:CP_Elec_10x10.5')
    comp_C1.fields['Voltage'] = '25V'
    comp_C1.fields['Type'] = 'Aluminum Electrolytic'
    comp_C1.fields['Description'] = 'электролит по питанию'

    # type:        TYPE_C_100UF_25V
    # description: силовая шина моторов
    # tag:         PWR_C11
    comp_C11 = Part('Device', 'C', ref='C11', tag='PWR_C11', value='100uF', footprint='Capacitor_SMD:CP_Elec_8x10.5')
    comp_C11.fields['Voltage'] = '25V'
    comp_C11.fields['Type'] = 'Ceramic'
    comp_C11.fields['Dielectric'] = 'X7R'
    comp_C11.fields['Description'] = 'силовая шина моторов'

    # type:        TYPE_C_100NF
    # description: фильтр опоры потенциометра M1
    # tag:         PWR_C16
    comp_C16 = Part('Device', 'C', ref='C16', tag='PWR_C16', value='100nF', footprint='Capacitor_SMD:C_0603_1608Metric')
    comp_C16.fields['Type'] = 'Ceramic'
    comp_C16.fields['Dielectric'] = 'X7R'
    comp_C16.fields['Description'] = 'фильтр опоры потенциометра M1'

    # type:        TYPE_C_100NF
    # description: фильтр опоры потенциометра M2
    # tag:         PWR_C17
    comp_C17 = Part('Device', 'C', ref='C17', tag='PWR_C17', value='100nF', footprint='Capacitor_SMD:C_0603_1608Metric')
    comp_C17.fields['Type'] = 'Ceramic'
    comp_C17.fields['Dielectric'] = 'X7R'
    comp_C17.fields['Description'] = 'фильтр опоры потенциометра M2'

    # type:        TYPE_C_100NF
    # description: фильтр опоры потенциометра M3
    # tag:         PWR_C18
    comp_C18 = Part('Device', 'C', ref='C18', tag='PWR_C18', value='100nF', footprint='Capacitor_SMD:C_0603_1608Metric')
    comp_C18.fields['Type'] = 'Ceramic'
    comp_C18.fields['Dielectric'] = 'X7R'
    comp_C18.fields['Description'] = 'фильтр опоры потенциометра M3'

    # type:        TYPE_C_100NF
    # description: фильтр опоры потенциометра M4
    # tag:         PWR_C19
    comp_C19 = Part('Device', 'C', ref='C19', tag='PWR_C19', value='100nF', footprint='Capacitor_SMD:C_0603_1608Metric')
    comp_C19.fields['Type'] = 'Ceramic'
    comp_C19.fields['Dielectric'] = 'X7R'
    comp_C19.fields['Description'] = 'фильтр опоры потенциометра M4'

    # type:        TYPE_C_100NF_12V
    # description: керамика по питанию 12В
    # tag:         PWR_C2
    comp_C2 = Part('Device', 'C', ref='C2', tag='PWR_C2', value='100nF', footprint='Capacitor_SMD:C_0603_1608Metric')
    comp_C2.fields['Voltage'] = '12V'
    comp_C2.fields['Type'] = 'Ceramic'
    comp_C2.fields['Dielectric'] = 'X7R'
    comp_C2.fields['Description'] = 'керамика по питанию 12В'

    # type:        TYPE_C_1UF_25V
    # description: керамика по входу +12В (ВЧ-фильтр
    # tag:         PWR_C20
    comp_C20 = Part('Device', 'C', ref='C20', tag='PWR_C20', value='1uF', footprint='Capacitor_SMD:C_0805_2012Metric')
    comp_C20.fields['Voltage'] = '25V'
    comp_C20.fields['Type'] = 'Ceramic'
    comp_C20.fields['Dielectric'] = 'X7R'
    comp_C20.fields['Description'] = 'керамика по входу +12В (ВЧ-фильтр'

    # type:        TYPE_C_10UF_35V
    # description: вход стабилизатора 5В
    # tag:         PWR_C3
    comp_C3 = Part('Device', 'C', ref='C3', tag='PWR_C3', value='10uF', footprint='Capacitor_SMD:C_0805_2012Metric')
    comp_C3.fields['Voltage'] = '35V'
    comp_C3.fields['Type'] = 'Ceramic'
    comp_C3.fields['Dielectric'] = 'X7R'
    comp_C3.fields['Description'] = 'вход стабилизатора 5В'

    # type:        TYPE_C_10UF_10V
    # description: выход стабилизатора 5В
    # tag:         PWR_C4
    comp_C4 = Part('Device', 'C', ref='C4', tag='PWR_C4', value='10uF', footprint='Capacitor_SMD:C_0805_2012Metric')
    comp_C4.fields['Voltage'] = '10V'
    comp_C4.fields['Type'] = 'Ceramic'
    comp_C4.fields['Dielectric'] = 'X7R'
    comp_C4.fields['Description'] = 'выход стабилизатора 5В'

    # type:        TYPE_DSCHOTTKY_SS54_40V
    # description: 5A, 40В) защита от переполюсовки
    # tag:         PWR_D1
    comp_D1 = Part('Device', 'D_Schottky', ref='D1', tag='PWR_D1', value='SS54', footprint='Diode_SMD:D_SMA')
    comp_D1.fields['Voltage'] = '40V'
    comp_D1.fields['Description'] = '5A, 40В) защита от переполюсовки'

    # type:        TYPE_DZENER_SMBJ15ATVS
    # description: защита от выбросов
    # tag:         PWR_D2
    comp_D2 = Part('Device', 'D_Zener', ref='D2', tag='PWR_D2', value='SMBJ15A TVS', footprint='Diode_SMD:D_SMB')
    comp_D2.fields['Description'] = 'защита от выбросов'

    # type:        TYPE_DSCHOTTKY_SS14_12V
    # description: диодная развязка от обратного +12В на линии датчиков
    # tag:         PWR_D4
    comp_D4 = Part('Device', 'D_Schottky', ref='D4', tag='PWR_D4', value='SS14', footprint='Diode_SMD:D_SMA')
    comp_D4.fields['Voltage'] = '12V'
    comp_D4.fields['Description'] = 'диодная развязка от обратного +12В на линии датчиков'

    # type:        TYPE_DZENER_SMBJ5P0A/5,6В_5.6V
    # description: защита линии +5В датчиков
    # tag:         PWR_D5
    comp_D5 = Part('Device', 'D_Zener', ref='D5', tag='PWR_D5', value='SMBJ5.0A / 5,6В', footprint='Diode_SMD:D_SMB')
    comp_D5.fields['Voltage'] = '5.6V'
    comp_D5.fields['Description'] = 'защита линии +5В датчиков'

    # type:        TYPE_CONN02X16ODDEVEN_РАЗЪЁМКАВТОМОБИЛЮ2X16(32КОНТP)
    # description: Разъём к автомобилю 2x16 (32 конт.)
    # tag:         PWR_J1
    comp_J1 = Part('Connector_Generic', 'Conn_02x16_Odd_Even', ref='J1', tag='PWR_J1', value='Разъём к автомобилю 2x16 (32 конт.)', footprint='Connector_PinHeader_2.54mm:PinHeader_2x16_P2.54mm_Horizontal')
    comp_J1.fields['Description'] = 'Разъём к автомобилю 2x16 (32 конт.)'

    # type:        TYPE_L_ФЕРРИТ/ДРОССЕЛЬПОВХОДУ+12В(ПОМЕХИ)_12V
    # description: Феррит/дроссель по входу +12В (помехи)
    # tag:         PWR_L1
    comp_L1 = Part('Device', 'L', ref='L1', tag='PWR_L1', value='Феррит/дроссель по входу +12В (помехи)', footprint='Inductor_SMD:L_1210_3225Metric')
    comp_L1.fields['Voltage'] = '12V'
    comp_L1.fields['Description'] = 'Феррит/дроссель по входу +12В (помехи)'

    # type:        TYPE_LM78M05TO252_MC78M05CDTG_5V
    # description: 5В, 500мА, TO-252
    # tag:         PWR_U6
    comp_U6 = Part('Regulator_Linear', 'LM78M05_TO252', ref='U6', tag='PWR_U6', value='MC78M05CDTG', footprint='Package_TO_SOT_SMD:TO-252-3_TabPin2')
    comp_U6.fields['Voltage'] = '5V'
    comp_U6.fields['Description'] = '5В, 500мА, TO-252'

    # type:        TYPE_AP1117-15_AMS1117-3P3_3.3V
    # description: 3,3В, SOT-223
    # tag:         PWR_U7
    comp_U7 = Part('Regulator_Linear', 'AP1117-15', ref='U7', tag='PWR_U7', value='AMS1117-3.3', footprint='Package_TO_SOT_SMD:SOT-223-3_TabPin2')
    comp_U7.fields['Voltage'] = '3.3V'
    comp_U7.fields['Description'] = '3,3В, SOT-223'

    # ======================================================================
    # Цепи и соединения
    # ======================================================================
    # Цепь VBAT_IN: Входное бортовое питание +12В, выводы 1-2 разъёма J1
    # attributes: type=POWER, voltage_level=12.0V, current_max=15A, spice_simulation={'model_stimulus': 'DC 12.0', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_VBAT_IN = Net('VBAT_IN')
    net_VBAT_IN += comp_J1['1']
    net_VBAT_IN += comp_J1['2']
    net_VBAT_IN += comp_D1['1']

    # Цепь VBAT_PROT: После защиты от переполюсовки (D1), перед входным фильтром L1
    # attributes: type=POWER, voltage_level=12.0V, current_max=15A, spice_simulation={'model_stimulus': 'DC 12.0', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_VBAT_PROT = Net('VBAT_PROT')
    net_VBAT_PROT += comp_D1['2']
    net_VBAT_PROT += comp_L1['1']

    # Цепь VCC_12V: Силовая шина +12В после фильтра помех L1, с TVS D2 и конденсаторами
    # attributes: type=POWER, voltage_level=12.0V, current_max=15A, spice_simulation={'model_stimulus': 'DC 12.0', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_VCC_12V += comp_L1['2']
    p_VCC_12V += comp_D2['2']
    p_VCC_12V += comp_C1['1']
    p_VCC_12V += comp_C2['1']
    p_VCC_12V += comp_C20['1']
    p_VCC_12V += comp_C3['1']
    p_VCC_12V += comp_U6['1']
    p_VCC_12V += comp_C11['1']

    # Цепь VCC_5V: Внутреннее стабилизированное питание +5В (логика/питание стабилизатора 3,3В)
    # attributes: type=POWER, voltage_level=5.0V, current_max=0.5A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_VCC_5V += comp_U6['3']
    p_VCC_5V += comp_C4['1']
    p_VCC_5V += comp_U7['1']
    p_VCC_5V += comp_D4['1']

    # Цепь V5_SENS: Общий выход +5В/опора на датчики и края потенциометров ОС (J1:17). Диод D4 исключает обратную подачу +12В снаружи
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_V5_SENS = Net('V5_SENS')
    net_V5_SENS += comp_D4['2']
    net_V5_SENS += comp_D5['2']
    net_V5_SENS += comp_C16['1']
    net_V5_SENS += comp_C17['1']
    net_V5_SENS += comp_C18['1']
    net_V5_SENS += comp_C19['1']
    net_V5_SENS += comp_J1['17']

    # Цепь VCC_3V3: Логическое питание +3,3В микроконтроллера и фронт-панели
    # attributes: type=POWER, voltage_level=3.3V, current_max=0.3A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_VCC_3V3 += comp_U7['3']

    # Цепь GND: Общий провод (кузов автомобиля)
    # attributes: type=GND, voltage_level=0V, current_max=15A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_GND += comp_J1['3']
    p_GND += comp_J1['4']
    p_GND += comp_J1['18']
    p_GND += comp_U6['2']
    p_GND += comp_U7['2']
    p_GND += comp_C20['2']
    p_GND += comp_D5['1']
    p_GND += comp_D2['1']
    p_GND += comp_C1['2']
    p_GND += comp_C2['2']
    p_GND += comp_C3['2']
    p_GND += comp_C4['2']
    p_GND += comp_C11['2']
    p_GND += comp_C16['2']
    p_GND += comp_C17['2']
    p_GND += comp_C18['2']
    p_GND += comp_C19['2']

    # Цепь NTC_HEAT_W: Датчик патрубка отопителя: узел линии на разъёме
    # attributes: type=ANALOG_SIGNAL, voltage_level=0..3.3V, current_max=0.005A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_NTC_HEAT_W += comp_J1['19']

    # Цепь SOLAR_RAW: Выход датчика солнечной радиации (0..5В)
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_SOLAR_RAW += comp_J1['20']

    # Цепь COND_RAW: Выход датчика конденсата на стекле (0..5В)
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_COND_RAW += comp_J1['21']

    # Цепь MOTOR_1_A: Заслонка 1: выход А мостового драйвера к моторедуктору
    # attributes: type=PWM_POWER, voltage_level=0..12.0V, current_max=5.0A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_MOTOR_1_A += comp_J1['5']

    # Цепь MOTOR_1_B: Заслонка 1: выход B мостового драйвера к моторедуктору
    # attributes: type=PWM_POWER, voltage_level=0..12.0V, current_max=5.0A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_MOTOR_1_B += comp_J1['6']

    # Цепь FB_M1_RAW: Заслонка 1: выход потенциометра положения (0..5В)
    # attributes: type=ANALOG_SIGNAL, voltage_level=0..3.3V, current_max=0.005A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_FB_M1_RAW += comp_J1['7']

    # Цепь MOTOR_2_A: Заслонка 2: выход А мостового драйвера к моторедуктору
    # attributes: type=PWM_POWER, voltage_level=0..12.0V, current_max=5.0A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_MOTOR_2_A += comp_J1['8']

    # Цепь MOTOR_2_B: Заслонка 2: выход B мостового драйвера к моторедуктору
    # attributes: type=PWM_POWER, voltage_level=0..12.0V, current_max=5.0A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_MOTOR_2_B += comp_J1['9']

    # Цепь FB_M2_RAW: Заслонка 2: выход потенциометра положения (0..5В)
    # attributes: type=ANALOG_SIGNAL, voltage_level=0..3.3V, current_max=0.005A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_FB_M2_RAW += comp_J1['10']

    # Цепь MOTOR_3_A: Заслонка 3: выход А мостового драйвера к моторедуктору
    # attributes: type=PWM_POWER, voltage_level=0..12.0V, current_max=5.0A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_MOTOR_3_A += comp_J1['11']

    # Цепь MOTOR_3_B: Заслонка 3: выход B мостового драйвера к моторедуктору
    # attributes: type=PWM_POWER, voltage_level=0..12.0V, current_max=5.0A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_MOTOR_3_B += comp_J1['12']

    # Цепь FB_M3_RAW: Заслонка 3: выход потенциометра положения (0..5В)
    # attributes: type=ANALOG_SIGNAL, voltage_level=0..3.3V, current_max=0.005A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_FB_M3_RAW += comp_J1['13']

    # Цепь MOTOR_4_A: Заслонка 4: выход А мостового драйвера к моторедуктору
    # attributes: type=PWM_POWER, voltage_level=0..12.0V, current_max=5.0A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_MOTOR_4_A += comp_J1['14']

    # Цепь MOTOR_4_B: Заслонка 4: выход B мостового драйвера к моторедуктору
    # attributes: type=PWM_POWER, voltage_level=0..12.0V, current_max=5.0A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_MOTOR_4_B += comp_J1['15']

    # Цепь FB_M4_RAW: Заслонка 4: выход потенциометра положения (0..5В)
    # attributes: type=ANALOG_SIGNAL, voltage_level=0..3.3V, current_max=0.005A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_FB_M4_RAW += comp_J1['16']

    # Цепь AC_REQ_OUT: Линия запроса кондиционера +12В к J1:31 (вход ЭБУ двигателя)
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_AC_REQ_OUT += comp_J1['24']

    # Цепь ILLUM_IN_RAW: Вход внешней подсветки прибора (+12В габаритов)
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_ILLUM_IN_RAW += comp_J1['22']

    # Цепь CANH: CAN: шина High (J1:25)
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_CANH += comp_J1['25']

    # Цепь CANL: CAN: шина Low (J1:26)
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_CANL += comp_J1['26']

    # Порт листа (см. docstring выше).
    p_HEAT_FAN_PWM_CTL += comp_J1['23']


module_PWR.tag = 'SHEET_PWR'


# ==========================================================================
# Лист X_UI  (sheets/user_interface.yaml)
# ==========================================================================
@SubCircuit
def module_UI(p_VCC_3V3, p_GND, p_BTN_DEFROST_GLASS, p_BTN_FACE, p_BTN_FEET, p_BTN_DRY_GLASS, p_BTN_AC, p_BTN_RECIRC, p_LED_DEFROST_GLASS_DRV, p_LED_FACE_DRV, p_LED_FEET_DRV, p_LED_DRY_GLASS_DRV, p_LED_AC_DRV, p_LED_RECIRC_DRV, p_TEMP_SET_ADC, p_FAN_SEL_ADC, p_NTC_CABIN, p_ILLUM_IN_RAW, p_ILLUM_SENSE):
    """
    Подстраница: X_UI
    file: sheets/user_interface.kicad_sch
    purpose: Модуль UI

    Порты листа:
      VCC_3V3                [POWER   ] Логическое питание +3,3В микроконтроллера и фронт-панели
      GND                    [POWER   ] Общий провод (кузов автомобиля)
      BTN_DEFROST_GLASS      [OUTPUT  ] Кнопка: воздух на стекло
      BTN_FACE               [OUTPUT  ] Кнопка: воздух в лицо
      BTN_FEET               [OUTPUT  ] Кнопка: воздух в ноги
      BTN_DRY_GLASS          [OUTPUT  ] Кнопка: сушка стекла
      BTN_AC                 [OUTPUT  ] Кнопка: кондиционер
      BTN_RECIRC             [OUTPUT  ] Кнопка: рециркуляция
      LED_DEFROST_GLASS_DRV  [OUTPUT  ] Индикатор кнопки: воздух на стекло (управление, активный низкий уровень)
      LED_FACE_DRV           [OUTPUT  ] Индикатор кнопки: воздух в лицо (управление, активный низкий уровень)
      LED_FEET_DRV           [OUTPUT  ] Индикатор кнопки: воздух в ноги (управление, активный низкий уровень)
      LED_DRY_GLASS_DRV      [OUTPUT  ] Индикатор кнопки: сушка стекла (управление, активный низкий уровень)
      LED_AC_DRV             [OUTPUT  ] Индикатор кнопки: кондиционер (управление, активный низкий уровень)
      LED_RECIRC_DRV         [OUTPUT  ] Индикатор кнопки: рециркуляция (управление, активный низкий уровень)
      TEMP_SET_ADC           [OUTPUT  ] АЦП задания температуры (потенциометр, 2-проводное включение, внутренний коннектор J_POT)
      FAN_SEL_ADC            [OUTPUT  ] АЦП выбора режима/скорости вентилятора (галлетник AUTO,0..4, резисторный код)
      NTC_CABIN              [INPUT   ] Температура воздуха в салоне (NTC на плате в трубе продувки)
      ILLUM_IN_RAW           [INPUT   ] Вход внешней подсветки прибора (+12В габаритов)
      ILLUM_SENSE            [POWER   ] Сигнал подсветки после делителя на вход МК
    """

    # ======================================================================
    # Компоненты
    # ======================================================================
    # type:        TYPE_C_100NF
    # description: фильтр АЦП температуры
    # tag:         UI_C22
    comp_C22 = Part('Device', 'C', ref='C22', tag='UI_C22', value='100nF', footprint='Capacitor_SMD:C_0603_1608Metric')
    comp_C22.fields['Type'] = 'Ceramic'
    comp_C22.fields['Dielectric'] = 'X7R'
    comp_C22.fields['Description'] = 'фильтр АЦП температуры'

    # type:        TYPE_C_100NF
    # description: фильтр АЦП галлетника
    # tag:         UI_C23
    comp_C23 = Part('Device', 'C', ref='C23', tag='UI_C23', value='100nF', footprint='Capacitor_SMD:C_0603_1608Metric')
    comp_C23.fields['Type'] = 'Ceramic'
    comp_C23.fields['Dielectric'] = 'X7R'
    comp_C23.fields['Description'] = 'фильтр АЦП галлетника'

    # type:        TYPE_C_100NF
    # description: фильтр АЦП салона
    # tag:         UI_C24
    comp_C24 = Part('Device', 'C', ref='C24', tag='UI_C24', value='100nF', footprint='Capacitor_SMD:C_0603_1608Metric')
    comp_C24.fields['Type'] = 'Ceramic'
    comp_C24.fields['Dielectric'] = 'X7R'
    comp_C24.fields['Description'] = 'фильтр АЦП салона'

    # type:        TYPE_C_100NF
    # description: фильтр входа подсветки
    # tag:         UI_C32
    comp_C32 = Part('Device', 'C', ref='C32', tag='UI_C32', value='100nF', footprint='Capacitor_SMD:C_0603_1608Metric')
    comp_C32.fields['Type'] = 'Ceramic'
    comp_C32.fields['Dielectric'] = 'X7R'
    comp_C32.fields['Description'] = 'фильтр входа подсветки'

    # type:        TYPE_CONN01X02_ВНУТРPКОННЕКТОРПОТЕНЦИОМЕТРА(2П,XH)
    # description: Внутр. коннектор потенциометра (2п, XH)
    # tag:         UI_J3
    comp_J3 = Part('Connector_Generic', 'Conn_01x02', ref='J3', tag='UI_J3', value='Внутр. коннектор потенциометра (2п, XH)', footprint='Connector_JST:JST_XH_B2B-XH-A_1x02_P2.50mm_Vertical')
    comp_J3.fields['Description'] = 'Внутр. коннектор потенциометра (2п, XH)'

    # type:        TYPE_CONN01X02_ВНУТРPКОННЕКТОРГАЛЛЕТНИКА(2П,XH)
    # description: Внутр. коннектор галлетника (2п, XH)
    # tag:         UI_J4
    comp_J4 = Part('Connector_Generic', 'Conn_01x02', ref='J4', tag='UI_J4', value='Внутр. коннектор галлетника (2п, XH)', footprint='Connector_JST:JST_XH_B2B-XH-A_1x02_P2.50mm_Vertical')
    comp_J4.fields['Description'] = 'Внутр. коннектор галлетника (2п, XH)'

    # type:        TYPE_LED_ИНДИКАТОРЗЕЛЁНЫЙ1206
    # description: Индикатор зелёный 1206
    # tag:         UI_LED1
    comp_LED1 = Part('Device', 'LED', ref='LED1', tag='UI_LED1', value='Индикатор зелёный 1206', footprint='LED_SMD:LED_1206_3216Metric')
    comp_LED1.fields['Description'] = 'Индикатор зелёный 1206'

    # type:        TYPE_LED_ИНДИКАТОРЗЕЛЁНЫЙ1206
    # description: Индикатор зелёный 1206
    # tag:         UI_LED2
    comp_LED2 = Part('Device', 'LED', ref='LED2', tag='UI_LED2', value='Индикатор зелёный 1206', footprint='LED_SMD:LED_1206_3216Metric')
    comp_LED2.fields['Description'] = 'Индикатор зелёный 1206'

    # type:        TYPE_LED_ИНДИКАТОРЗЕЛЁНЫЙ1206
    # description: Индикатор зелёный 1206
    # tag:         UI_LED3
    comp_LED3 = Part('Device', 'LED', ref='LED3', tag='UI_LED3', value='Индикатор зелёный 1206', footprint='LED_SMD:LED_1206_3216Metric')
    comp_LED3.fields['Description'] = 'Индикатор зелёный 1206'

    # type:        TYPE_LED_ИНДИКАТОРЯНТАРНЫЙ1206
    # description: Индикатор янтарный 1206
    # tag:         UI_LED4
    comp_LED4 = Part('Device', 'LED', ref='LED4', tag='UI_LED4', value='Индикатор янтарный 1206', footprint='LED_SMD:LED_1206_3216Metric')
    comp_LED4.fields['Description'] = 'Индикатор янтарный 1206'

    # type:        TYPE_LED_ИНДИКАТОРЗЕЛЁНЫЙ1206
    # description: Индикатор зелёный 1206
    # tag:         UI_LED5
    comp_LED5 = Part('Device', 'LED', ref='LED5', tag='UI_LED5', value='Индикатор зелёный 1206', footprint='LED_SMD:LED_1206_3216Metric')
    comp_LED5.fields['Description'] = 'Индикатор зелёный 1206'

    # type:        TYPE_LED_ИНДИКАТОРЗЕЛЁНЫЙ1206
    # description: Индикатор зелёный 1206
    # tag:         UI_LED6
    comp_LED6 = Part('Device', 'LED', ref='LED6', tag='UI_LED6', value='Индикатор зелёный 1206', footprint='LED_SMD:LED_1206_3216Metric')
    comp_LED6.fields['Description'] = 'Индикатор зелёный 1206'

    # type:        TYPE_R_1K
    # description: токоограничение индикатора
    # tag:         UI_R10
    comp_R10 = Part('Device', 'R', ref='R10', tag='UI_R10', value='1k', footprint='Resistor_SMD:R_0603_1608Metric')
    comp_R10.fields['Power'] = '0.1W'
    comp_R10.fields['Tolerance'] = '1%'
    comp_R10.fields['Description'] = 'токоограничение индикатора'

    # type:        TYPE_R_1K
    # description: токоограничение индикатора
    # tag:         UI_R11
    comp_R11 = Part('Device', 'R', ref='R11', tag='UI_R11', value='1k', footprint='Resistor_SMD:R_0603_1608Metric')
    comp_R11.fields['Power'] = '0.1W'
    comp_R11.fields['Tolerance'] = '1%'
    comp_R11.fields['Description'] = 'токоограничение индикатора'

    # type:        TYPE_R_1K
    # description: токоограничение индикатора
    # tag:         UI_R12
    comp_R12 = Part('Device', 'R', ref='R12', tag='UI_R12', value='1k', footprint='Resistor_SMD:R_0603_1608Metric')
    comp_R12.fields['Power'] = '0.1W'
    comp_R12.fields['Tolerance'] = '1%'
    comp_R12.fields['Description'] = 'токоограничение индикатора'

    # type:        TYPE_R_10K
    # description: подтяжка потенциометра температуры
    # tag:         UI_R22
    comp_R22 = Part('Device', 'R', ref='R22', tag='UI_R22', value='10k', footprint='Resistor_SMD:R_0603_1608Metric')
    comp_R22.fields['Power'] = '0.1W'
    comp_R22.fields['Tolerance'] = '1%'
    comp_R22.fields['Description'] = 'подтяжка потенциометра температуры'

    # type:        TYPE_R_10K
    # description: подтяжка галлетника
    # tag:         UI_R23
    comp_R23 = Part('Device', 'R', ref='R23', tag='UI_R23', value='10k', footprint='Resistor_SMD:R_0603_1608Metric')
    comp_R23.fields['Power'] = '0.1W'
    comp_R23.fields['Tolerance'] = '1%'
    comp_R23.fields['Description'] = 'подтяжка галлетника'

    # type:        TYPE_R_10K
    # description: подтяжка NTC салона
    # tag:         UI_R24
    comp_R24 = Part('Device', 'R', ref='R24', tag='UI_R24', value='10k', footprint='Resistor_SMD:R_0603_1608Metric')
    comp_R24.fields['Power'] = '0.1W'
    comp_R24.fields['Tolerance'] = '1%'
    comp_R24.fields['Description'] = 'подтяжка NTC салона'

    # type:        TYPE_R_47K
    # description: делитель входа подсветки (верх
    # tag:         UI_R39
    comp_R39 = Part('Device', 'R', ref='R39', tag='UI_R39', value='47k', footprint='Resistor_SMD:R_0603_1608Metric')
    comp_R39.fields['Power'] = '0.1W'
    comp_R39.fields['Tolerance'] = '1%'
    comp_R39.fields['Description'] = 'делитель входа подсветки (верх'

    # type:        TYPE_R_10K
    # description: делитель входа подсветки (низ
    # tag:         UI_R40
    comp_R40 = Part('Device', 'R', ref='R40', tag='UI_R40', value='10k', footprint='Resistor_SMD:R_0603_1608Metric')
    comp_R40.fields['Power'] = '0.1W'
    comp_R40.fields['Tolerance'] = '1%'
    comp_R40.fields['Description'] = 'делитель входа подсветки (низ'

    # type:        TYPE_R_1K
    # description: токоограничение индикатора
    # tag:         UI_R7
    comp_R7 = Part('Device', 'R', ref='R7', tag='UI_R7', value='1k', footprint='Resistor_SMD:R_0603_1608Metric')
    comp_R7.fields['Power'] = '0.1W'
    comp_R7.fields['Tolerance'] = '1%'
    comp_R7.fields['Description'] = 'токоограничение индикатора'

    # type:        TYPE_R_1K
    # description: токоограничение индикатора
    # tag:         UI_R8
    comp_R8 = Part('Device', 'R', ref='R8', tag='UI_R8', value='1k', footprint='Resistor_SMD:R_0603_1608Metric')
    comp_R8.fields['Power'] = '0.1W'
    comp_R8.fields['Tolerance'] = '1%'
    comp_R8.fields['Description'] = 'токоограничение индикатора'

    # type:        TYPE_R_1K
    # description: токоограничение индикатора
    # tag:         UI_R9
    comp_R9 = Part('Device', 'R', ref='R9', tag='UI_R9', value='1k', footprint='Resistor_SMD:R_0603_1608Metric')
    comp_R9.fields['Power'] = '0.1W'
    comp_R9.fields['Tolerance'] = '1%'
    comp_R9.fields['Description'] = 'токоограничение индикатора'

    # type:        TYPE_SWPUSH_КНОПКАТАКТОВАЯ6X6БЕЗФИКСАЦИИ
    # description: Кнопка тактовая 6x6 без фиксации
    # tag:         UI_SW1
    comp_SW1 = Part('Switch', 'SW_Push', ref='SW1', tag='UI_SW1', value='Кнопка тактовая 6x6 без фиксации', footprint='Button_Switch_THT:SW_Push_1P1T_NO_6x6mm_H7.0mm')
    comp_SW1.fields['Description'] = 'Кнопка тактовая 6x6 без фиксации'

    # type:        TYPE_SWPUSH_КНОПКАТАКТОВАЯ6X6БЕЗФИКСАЦИИ
    # description: Кнопка тактовая 6x6 без фиксации
    # tag:         UI_SW2
    comp_SW2 = Part('Switch', 'SW_Push', ref='SW2', tag='UI_SW2', value='Кнопка тактовая 6x6 без фиксации', footprint='Button_Switch_THT:SW_Push_1P1T_NO_6x6mm_H7.0mm')
    comp_SW2.fields['Description'] = 'Кнопка тактовая 6x6 без фиксации'

    # type:        TYPE_SWPUSH_КНОПКАТАКТОВАЯ6X6БЕЗФИКСАЦИИ
    # description: Кнопка тактовая 6x6 без фиксации
    # tag:         UI_SW3
    comp_SW3 = Part('Switch', 'SW_Push', ref='SW3', tag='UI_SW3', value='Кнопка тактовая 6x6 без фиксации', footprint='Button_Switch_THT:SW_Push_1P1T_NO_6x6mm_H7.0mm')
    comp_SW3.fields['Description'] = 'Кнопка тактовая 6x6 без фиксации'

    # type:        TYPE_SWPUSH_КНОПКАТАКТОВАЯ6X6БЕЗФИКСАЦИИ
    # description: Кнопка тактовая 6x6 без фиксации
    # tag:         UI_SW4
    comp_SW4 = Part('Switch', 'SW_Push', ref='SW4', tag='UI_SW4', value='Кнопка тактовая 6x6 без фиксации', footprint='Button_Switch_THT:SW_Push_1P1T_NO_6x6mm_H7.0mm')
    comp_SW4.fields['Description'] = 'Кнопка тактовая 6x6 без фиксации'

    # type:        TYPE_SWPUSH_КНОПКАТАКТОВАЯ6X6БЕЗФИКСАЦИИ
    # description: Кнопка тактовая 6x6 без фиксации
    # tag:         UI_SW5
    comp_SW5 = Part('Switch', 'SW_Push', ref='SW5', tag='UI_SW5', value='Кнопка тактовая 6x6 без фиксации', footprint='Button_Switch_THT:SW_Push_1P1T_NO_6x6mm_H7.0mm')
    comp_SW5.fields['Description'] = 'Кнопка тактовая 6x6 без фиксации'

    # type:        TYPE_SWPUSH_КНОПКАТАКТОВАЯ6X6БЕЗФИКСАЦИИ
    # description: Кнопка тактовая 6x6 без фиксации
    # tag:         UI_SW6
    comp_SW6 = Part('Switch', 'SW_Push', ref='SW6', tag='UI_SW6', value='Кнопка тактовая 6x6 без фиксации', footprint='Button_Switch_THT:SW_Push_1P1T_NO_6x6mm_H7.0mm')
    comp_SW6.fields['Description'] = 'Кнопка тактовая 6x6 без фиксации'

    # ======================================================================
    # Цепи и соединения
    # ======================================================================
    # Цепь VCC_3V3: Логическое питание +3,3В микроконтроллера и фронт-панели
    # attributes: type=POWER, voltage_level=3.3V, current_max=0.3A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_VCC_3V3 += comp_R22['1']
    p_VCC_3V3 += comp_R23['1']
    p_VCC_3V3 += comp_R24['1']
    p_VCC_3V3 += comp_R7['1']
    p_VCC_3V3 += comp_R8['1']
    p_VCC_3V3 += comp_R9['1']
    p_VCC_3V3 += comp_R10['1']
    p_VCC_3V3 += comp_R11['1']
    p_VCC_3V3 += comp_R12['1']

    # Цепь GND: Общий провод (кузов автомобиля)
    # attributes: type=GND, voltage_level=0V, current_max=15A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_GND += comp_SW1['2']
    p_GND += comp_SW2['2']
    p_GND += comp_SW3['2']
    p_GND += comp_SW4['2']
    p_GND += comp_SW5['2']
    p_GND += comp_SW6['2']
    p_GND += comp_J3['2']
    p_GND += comp_J4['2']
    p_GND += comp_C22['2']
    p_GND += comp_C23['2']
    p_GND += comp_C24['2']
    p_GND += comp_R40['2']
    p_GND += comp_C32['2']

    # Цепь BTN_DEFROST_GLASS: Кнопка: воздух на стекло
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_BTN_DEFROST_GLASS += comp_SW1['1']

    # Цепь BTN_FACE: Кнопка: воздух в лицо
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_BTN_FACE += comp_SW2['1']

    # Цепь BTN_FEET: Кнопка: воздух в ноги
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_BTN_FEET += comp_SW3['1']

    # Цепь BTN_DRY_GLASS: Кнопка: сушка стекла
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_BTN_DRY_GLASS += comp_SW4['1']

    # Цепь BTN_AC: Кнопка: кондиционер
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_BTN_AC += comp_SW5['1']

    # Цепь BTN_RECIRC: Кнопка: рециркуляция
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_BTN_RECIRC += comp_SW6['1']

    # Цепь LED_DEFROST_GLASS_A: Индикатор кнопки: воздух на стекло (анодная шина)
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_LED_DEFROST_GLASS_A = Net('LED_DEFROST_GLASS_A')
    net_LED_DEFROST_GLASS_A += comp_R7['2']
    net_LED_DEFROST_GLASS_A += comp_LED1['1']

    # Цепь LED_DEFROST_GLASS_DRV: Индикатор кнопки: воздух на стекло (управление, активный низкий уровень)
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_LED_DEFROST_GLASS_DRV += comp_LED1['2']

    # Цепь LED_FACE_A: Индикатор кнопки: воздух в лицо (анодная шина)
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_LED_FACE_A = Net('LED_FACE_A')
    net_LED_FACE_A += comp_R8['2']
    net_LED_FACE_A += comp_LED2['1']

    # Цепь LED_FACE_DRV: Индикатор кнопки: воздух в лицо (управление, активный низкий уровень)
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_LED_FACE_DRV += comp_LED2['2']

    # Цепь LED_FEET_A: Индикатор кнопки: воздух в ноги (анодная шина)
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_LED_FEET_A = Net('LED_FEET_A')
    net_LED_FEET_A += comp_R9['2']
    net_LED_FEET_A += comp_LED3['1']

    # Цепь LED_FEET_DRV: Индикатор кнопки: воздух в ноги (управление, активный низкий уровень)
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_LED_FEET_DRV += comp_LED3['2']

    # Цепь LED_DRY_GLASS_A: Индикатор кнопки: сушка стекла (анодная шина)
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_LED_DRY_GLASS_A = Net('LED_DRY_GLASS_A')
    net_LED_DRY_GLASS_A += comp_R10['2']
    net_LED_DRY_GLASS_A += comp_LED4['1']

    # Цепь LED_DRY_GLASS_DRV: Индикатор кнопки: сушка стекла (управление, активный низкий уровень)
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_LED_DRY_GLASS_DRV += comp_LED4['2']

    # Цепь LED_AC_A: Индикатор кнопки: кондиционер (анодная шина)
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_LED_AC_A = Net('LED_AC_A')
    net_LED_AC_A += comp_R11['2']
    net_LED_AC_A += comp_LED5['1']

    # Цепь LED_AC_DRV: Индикатор кнопки: кондиционер (управление, активный низкий уровень)
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_LED_AC_DRV += comp_LED5['2']

    # Цепь LED_RECIRC_A: Индикатор кнопки: рециркуляция (анодная шина)
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_LED_RECIRC_A = Net('LED_RECIRC_A')
    net_LED_RECIRC_A += comp_R12['2']
    net_LED_RECIRC_A += comp_LED6['1']

    # Цепь LED_RECIRC_DRV: Индикатор кнопки: рециркуляция (управление, активный низкий уровень)
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_LED_RECIRC_DRV += comp_LED6['2']

    # Цепь TEMP_SET_ADC: АЦП задания температуры (потенциометр, 2-проводное включение, внутренний коннектор J_POT)
    # attributes: type=ANALOG_SIGNAL, voltage_level=0..3.3V, current_max=0.005A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_TEMP_SET_ADC += comp_J3['1']
    p_TEMP_SET_ADC += comp_R22['2']
    p_TEMP_SET_ADC += comp_C22['1']

    # Цепь FAN_SEL_ADC: АЦП выбора режима/скорости вентилятора (галлетник AUTO,0..4, резисторный код)
    # attributes: type=ANALOG_SIGNAL, voltage_level=0..3.3V, current_max=0.005A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_FAN_SEL_ADC += comp_J4['1']
    p_FAN_SEL_ADC += comp_R23['2']
    p_FAN_SEL_ADC += comp_C23['1']

    # Цепь NTC_CABIN: Температура воздуха в салоне (NTC на плате в трубе продувки)
    # attributes: type=ANALOG_SIGNAL, voltage_level=0..3.3V, current_max=0.005A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_NTC_CABIN += comp_R24['2']
    p_NTC_CABIN += comp_C24['1']

    # Цепь ILLUM_IN_RAW: Вход внешней подсветки прибора (+12В габаритов)
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_ILLUM_IN_RAW += comp_R39['1']

    # Цепь ILLUM_SENSE: Сигнал подсветки после делителя на вход МК
    # attributes: type=ANALOG_SIGNAL, voltage_level=0..3.3V, current_max=0.005A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_ILLUM_SENSE += comp_R39['2']
    p_ILLUM_SENSE += comp_R40['1']
    p_ILLUM_SENSE += comp_C32['1']


module_UI.tag = 'SHEET_UI'


# ==========================================================================
# Лист X_SEN_CABIN  (sheets/cabin_sensor.yaml)
# ==========================================================================
@SubCircuit
def module_SEN_CABIN(p_VCC_12V, p_GND, p_NTC_CABIN, p_M_FAN_CTL):
    """
    Подстраница: X_SEN_CABIN
    file: sheets/cabin_sensor.kicad_sch
    purpose: Модуль SEN_CABIN

    Порты листа:
      VCC_12V                [POWER   ] Силовая шина +12В после фильтра помех L1, с TVS D2 и конденсаторами
      GND                    [POWER   ] Общий провод (кузов автомобиля)
      NTC_CABIN              [INPUT   ] Температура воздуха в салоне (NTC на плате в трубе продувки)
      M_FAN_CTL              [INPUT   ] Управление мини-вентилятором продувки датчика
    """

    # ======================================================================
    # Компоненты
    # ======================================================================
    # type:        TYPE_D_1N4148W
    # description: обратный диод вентилятора
    # tag:         SEN_CABIN_D3
    comp_D3 = Part('Device', 'D', ref='D3', tag='SEN_CABIN_D3', value='1N4148W', footprint='Diode_SMD:D_SOD-123')
    comp_D3.fields['Description'] = 'обратный диод вентилятора'

    # type:        TYPE_CONN01X02_ВНУТРPКОННЕКТОРВЕНТИЛЯТОРАПРОДУВКИ(2П,XH)
    # description: Внутр. коннектор вентилятора продувки (2п, XH)
    # tag:         SEN_CABIN_J5
    comp_J5 = Part('Connector_Generic', 'Conn_01x02', ref='J5', tag='SEN_CABIN_J5', value='Внутр. коннектор вентилятора продувки (2п, XH)', footprint='Connector_JST:JST_XH_B2B-XH-A_1x02_P2.50mm_Vertical')
    comp_J5.fields['Description'] = 'Внутр. коннектор вентилятора продувки (2п, XH)'

    # type:        TYPE_QNMOS_AO3400
    # description: ключ мини-вентилятора (логич. уровень, 5,7А
    # tag:         SEN_CABIN_Q2
    comp_Q2 = Part('Transistor_FET', 'AO3400A', ref='Q2', tag='SEN_CABIN_Q2', value='AO3400', footprint='Package_TO_SOT_SMD:SOT-23')
    comp_Q2.fields['Description'] = 'ключ мини-вентилятора (логич. уровень, 5,7А'

    # type:        TYPE_R_1K
    # description: затвор Q_MFAN
    # tag:         SEN_CABIN_R16
    comp_R16 = Part('Device', 'R', ref='R16', tag='SEN_CABIN_R16', value='1k', footprint='Resistor_SMD:R_0603_1608Metric')
    comp_R16.fields['Power'] = '0.1W'
    comp_R16.fields['Tolerance'] = '1%'
    comp_R16.fields['Description'] = 'затвор Q_MFAN'

    # type:        TYPE_R_10K
    # description: подтяжка затвора Q_MFAN к GND
    # tag:         SEN_CABIN_R17
    comp_R17 = Part('Device', 'R', ref='R17', tag='SEN_CABIN_R17', value='10k', footprint='Resistor_SMD:R_0603_1608Metric')
    comp_R17.fields['Power'] = '0.1W'
    comp_R17.fields['Tolerance'] = '1%'
    comp_R17.fields['Description'] = 'подтяжка затвора Q_MFAN к GND'

    # type:        TYPE_THERMISTORNTC_10K
    # description: длинные ножки, в трубе продувки
    # tag:         SEN_CABIN_RT1
    comp_RT1 = Part('Device', 'Thermistor_NTC', ref='RT1', tag='SEN_CABIN_RT1', value='10k', footprint='Resistor_THT:R_Axial_DIN0204_L3.6mm_D1.6mm_P7.62mm_Horizontal')
    comp_RT1.fields['Power'] = '0.1W'
    comp_RT1.fields['Tolerance'] = '1%'
    comp_RT1.fields['Description'] = 'длинные ножки, в трубе продувки'

    # ======================================================================
    # Цепи и соединения
    # ======================================================================
    # Цепь VCC_12V: Силовая шина +12В после фильтра помех L1, с TVS D2 и конденсаторами
    # attributes: type=POWER, voltage_level=12.0V, current_max=15A, spice_simulation={'model_stimulus': 'DC 12.0', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_VCC_12V += comp_J5['1']
    p_VCC_12V += comp_D3['2']

    # Цепь GND: Общий провод (кузов автомобиля)
    # attributes: type=GND, voltage_level=0V, current_max=15A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_GND += comp_Q2['3']
    p_GND += comp_RT1['2']
    p_GND += comp_R17['2']

    # Цепь NTC_CABIN: Температура воздуха в салоне (NTC на плате в трубе продувки)
    # attributes: type=ANALOG_SIGNAL, voltage_level=0..3.3V, current_max=0.005A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_NTC_CABIN += comp_RT1['1']

    # Цепь M_FAN_CTL: Управление мини-вентилятором продувки датчика
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_M_FAN_CTL += comp_R16['1']

    # Цепь M_FAN_GATE: Затвор MOSFET мини-вентилятора
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_M_FAN_GATE = Net('M_FAN_GATE')
    net_M_FAN_GATE += comp_R16['2']
    net_M_FAN_GATE += comp_Q2['1']
    net_M_FAN_GATE += comp_R17['1']

    # Цепь SENS_FAN_SW: Коммутируемая линия питания мини-вентилятора
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_SENS_FAN_SW = Net('SENS_FAN_SW')
    net_SENS_FAN_SW += comp_Q2['2']
    net_SENS_FAN_SW += comp_J5['2']
    net_SENS_FAN_SW += comp_D3['1']


module_SEN_CABIN.tag = 'SHEET_SEN_CABIN'


# ==========================================================================
# Лист X_SEN_HEAT  (sheets/heating_sensor.yaml)
# ==========================================================================
@SubCircuit
def module_SEN_HEAT(p_VCC_3V3, p_GND, p_NTC_HEAT_W, p_NTC_HEAT):
    """
    Подстраница: X_SEN_HEAT
    file: sheets/heating_sensor.kicad_sch
    purpose: Модуль SEN_HEAT

    Порты листа:
      VCC_3V3                [POWER   ] Логическое питание +3,3В микроконтроллера и фронт-панели
      GND                    [POWER   ] Общий провод (кузов автомобиля)
      NTC_HEAT_W             [OUTPUT  ] Датчик патрубка отопителя: узел линии на разъёме
      NTC_HEAT               [OUTPUT  ] Датчик патрубка отопителя: сигнал на АЦП (после защитного резистора)
    """

    # ======================================================================
    # Компоненты
    # ======================================================================
    # type:        TYPE_C_100NF
    # description: фильтр АЦП ОЖ
    # tag:         SEN_HEAT_C25
    comp_C25 = Part('Device', 'C', ref='C25', tag='SEN_HEAT_C25', value='100nF', footprint='Capacitor_SMD:C_0603_1608Metric')
    comp_C25.fields['Type'] = 'Ceramic'
    comp_C25.fields['Dielectric'] = 'X7R'
    comp_C25.fields['Description'] = 'фильтр АЦП ОЖ'

    # type:        TYPE_R_10K
    # description: подтяжка NTC патрубка отопителя
    # tag:         SEN_HEAT_R25
    comp_R25 = Part('Device', 'R', ref='R25', tag='SEN_HEAT_R25', value='10k', footprint='Resistor_SMD:R_0603_1608Metric')
    comp_R25.fields['Power'] = '0.1W'
    comp_R25.fields['Tolerance'] = '1%'
    comp_R25.fields['Description'] = 'подтяжка NTC патрубка отопителя'

    # type:        TYPE_R_10K
    # description: защитный резистор линии NTC патрубка перед АЦП (J1:25
    # tag:         SEN_HEAT_R26
    comp_R26 = Part('Device', 'R', ref='R26', tag='SEN_HEAT_R26', value='10k', footprint='Resistor_SMD:R_0603_1608Metric')
    comp_R26.fields['Power'] = '0.1W'
    comp_R26.fields['Tolerance'] = '1%'
    comp_R26.fields['Description'] = 'защитный резистор линии NTC патрубка перед АЦП (J1:25'

    # ======================================================================
    # Цепи и соединения
    # ======================================================================
    # Цепь VCC_3V3: Логическое питание +3,3В микроконтроллера и фронт-панели
    # attributes: type=POWER, voltage_level=3.3V, current_max=0.3A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_VCC_3V3 += comp_R25['1']

    # Цепь GND: Общий провод (кузов автомобиля)
    # attributes: type=GND, voltage_level=0V, current_max=15A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_GND += comp_C25['2']

    # Цепь NTC_HEAT_W: Датчик патрубка отопителя: узел линии на разъёме
    # attributes: type=ANALOG_SIGNAL, voltage_level=0..3.3V, current_max=0.005A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_NTC_HEAT_W += comp_R25['2']
    p_NTC_HEAT_W += comp_C25['1']
    p_NTC_HEAT_W += comp_R26['1']

    # Цепь NTC_HEAT: Датчик патрубка отопителя: сигнал на АЦП (после защитного резистора)
    # attributes: type=ANALOG_SIGNAL, voltage_level=0..3.3V, current_max=0.005A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_NTC_HEAT += comp_R26['2']


module_SEN_HEAT.tag = 'SHEET_SEN_HEAT'


# ==========================================================================
# Лист X_SEN_SOLAR  (sheets/solar_sensor.yaml)
# ==========================================================================
@SubCircuit
def module_SEN_SOLAR(p_GND, p_SOLAR_RAW, p_SOLAR_ADC):
    """
    Подстраница: X_SEN_SOLAR
    file: sheets/solar_sensor.kicad_sch
    purpose: Модуль SEN_SOLAR

    Порты листа:
      GND                    [POWER   ] Общий провод (кузов автомобиля)
      SOLAR_RAW              [INPUT   ] Выход датчика солнечной радиации (0..5В)
      SOLAR_ADC              [OUTPUT  ] Сигнал солнечной радиации после делителя 5В->3,3В на АЦП
    """

    # ======================================================================
    # Компоненты
    # ======================================================================
    # type:        TYPE_C_100NF
    # description: фильтр АЦП солнечной радиации
    # tag:         SEN_SOLAR_C26
    comp_C26 = Part('Device', 'C', ref='C26', tag='SEN_SOLAR_C26', value='100nF', footprint='Capacitor_SMD:C_0603_1608Metric')
    comp_C26.fields['Type'] = 'Ceramic'
    comp_C26.fields['Dielectric'] = 'X7R'
    comp_C26.fields['Description'] = 'фильтр АЦП солнечной радиации'

    # type:        TYPE_R_10K
    # description: делитель сигнала солнечной радиации (верх
    # tag:         SEN_SOLAR_R27
    comp_R27 = Part('Device', 'R', ref='R27', tag='SEN_SOLAR_R27', value='10k', footprint='Resistor_SMD:R_0603_1608Metric')
    comp_R27.fields['Power'] = '0.1W'
    comp_R27.fields['Tolerance'] = '1%'
    comp_R27.fields['Description'] = 'делитель сигнала солнечной радиации (верх'

    # type:        TYPE_R_20K
    # description: делитель сигнала солнечной радиации (низ
    # tag:         SEN_SOLAR_R28
    comp_R28 = Part('Device', 'R', ref='R28', tag='SEN_SOLAR_R28', value='20k', footprint='Resistor_SMD:R_0603_1608Metric')
    comp_R28.fields['Power'] = '0.1W'
    comp_R28.fields['Tolerance'] = '1%'
    comp_R28.fields['Description'] = 'делитель сигнала солнечной радиации (низ'

    # ======================================================================
    # Цепи и соединения
    # ======================================================================
    # Цепь GND: Общий провод (кузов автомобиля)
    # attributes: type=GND, voltage_level=0V, current_max=15A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_GND += comp_R28['2']
    p_GND += comp_C26['2']

    # Цепь SOLAR_RAW: Выход датчика солнечной радиации (0..5В)
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_SOLAR_RAW += comp_R27['1']

    # Цепь SOLAR_ADC: Сигнал солнечной радиации после делителя 5В->3,3В на АЦП
    # attributes: type=ANALOG_SIGNAL, voltage_level=0..3.3V, current_max=0.005A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_SOLAR_ADC += comp_R27['2']
    p_SOLAR_ADC += comp_R28['1']
    p_SOLAR_ADC += comp_C26['1']


module_SEN_SOLAR.tag = 'SHEET_SEN_SOLAR'


# ==========================================================================
# Лист X_SEN_COND  (sheets/condensate_sensor.yaml)
# ==========================================================================
@SubCircuit
def module_SEN_COND(p_GND, p_COND_RAW, p_COND_ADC):
    """
    Подстраница: X_SEN_COND
    file: sheets/condensate_sensor.kicad_sch
    purpose: Модуль SEN_COND

    Порты листа:
      GND                    [POWER   ] Общий провод (кузов автомобиля)
      COND_RAW               [INPUT   ] Выход датчика конденсата на стекле (0..5В)
      COND_ADC               [OUTPUT  ] Сигнал конденсата после делителя 5В->3,3В на АЦП
    """

    # ======================================================================
    # Компоненты
    # ======================================================================
    # type:        TYPE_C_100NF
    # description: фильтр АЦП конденсата
    # tag:         SEN_COND_C27
    comp_C27 = Part('Device', 'C', ref='C27', tag='SEN_COND_C27', value='100nF', footprint='Capacitor_SMD:C_0603_1608Metric')
    comp_C27.fields['Type'] = 'Ceramic'
    comp_C27.fields['Dielectric'] = 'X7R'
    comp_C27.fields['Description'] = 'фильтр АЦП конденсата'

    # type:        TYPE_R_10K
    # description: делитель сигнала конденсата (верх
    # tag:         SEN_COND_R29
    comp_R29 = Part('Device', 'R', ref='R29', tag='SEN_COND_R29', value='10k', footprint='Resistor_SMD:R_0603_1608Metric')
    comp_R29.fields['Power'] = '0.1W'
    comp_R29.fields['Tolerance'] = '1%'
    comp_R29.fields['Description'] = 'делитель сигнала конденсата (верх'

    # type:        TYPE_R_20K
    # description: делитель сигнала конденсата (низ
    # tag:         SEN_COND_R30
    comp_R30 = Part('Device', 'R', ref='R30', tag='SEN_COND_R30', value='20k', footprint='Resistor_SMD:R_0603_1608Metric')
    comp_R30.fields['Power'] = '0.1W'
    comp_R30.fields['Tolerance'] = '1%'
    comp_R30.fields['Description'] = 'делитель сигнала конденсата (низ'

    # ======================================================================
    # Цепи и соединения
    # ======================================================================
    # Цепь GND: Общий провод (кузов автомобиля)
    # attributes: type=GND, voltage_level=0V, current_max=15A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_GND += comp_R30['2']
    p_GND += comp_C27['2']

    # Цепь COND_RAW: Выход датчика конденсата на стекле (0..5В)
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_COND_RAW += comp_R29['1']

    # Цепь COND_ADC: Сигнал конденсата после делителя 5В->3,3В на АЦП
    # attributes: type=ANALOG_SIGNAL, voltage_level=0..3.3V, current_max=0.005A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_COND_ADC += comp_R29['2']
    p_COND_ADC += comp_R30['1']
    p_COND_ADC += comp_C27['1']


module_SEN_COND.tag = 'SHEET_SEN_COND'


# ==========================================================================
# Лист X_OUT  (sheets/power_outputs.yaml)
# ==========================================================================
@SubCircuit
def module_OUT(p_VCC_12V, p_GND, p_FAN_PWM_CTL, p_AC_CTL, p_AC_REQ_OUT, p_HEAT_FAN_PWM_CTL):
    """
    Подстраница: X_OUT
    file: sheets/power_outputs.kicad_sch
    purpose: Модуль OUT

    Порты листа:
      VCC_12V                [POWER   ] Силовая шина +12В после фильтра помех L1, с TVS D2 и конденсаторами
      GND                    [POWER   ] Общий провод (кузов автомобиля)
      FAN_PWM_CTL            [INPUT   ] ШИМ управления основным вентилятором (TIM1_CH1)
      AC_CTL                 [INPUT   ] Управление транзистором запроса кондиционера
      AC_REQ_OUT             [INPUT   ] Линия запроса кондиционера +12В к J1:31 (вход ЭБУ двигателя)
      HEAT_FAN_PWM_CTL       [OUTPUT  ] ШИМ вентилятора печки на J1:23 (после буфера Q1 и защитного R15)
    """

    # ======================================================================
    # Компоненты
    # ======================================================================
    # type:        TYPE_QNMOS_BSS138
    # description: буфер ШИМ вентилятора
    # tag:         OUT_Q1
    comp_Q1 = Part('Transistor_FET', 'BSS138', ref='Q1', tag='OUT_Q1', value='BSS138', footprint='Package_TO_SOT_SMD:SOT-23')
    comp_Q1.fields['Description'] = 'буфер ШИМ вентилятора'

    # type:        TYPE_QNPN_MMBT3904
    # description: драйвер запроса кондиционера
    # tag:         OUT_Q3
    comp_Q3 = Part('Transistor_BJT', 'MMBT3904', ref='Q3', tag='OUT_Q3', value='MMBT3904', footprint='Package_TO_SOT_SMD:SOT-23')
    comp_Q3.fields['Description'] = 'драйвер запроса кондиционера'

    # type:        TYPE_QPNP_MMBT3906_3906V
    # description: высокосторонний ключ 12В
    # tag:         OUT_Q4
    comp_Q4 = Part('Transistor_BJT', 'MMBT3906', ref='Q4', tag='OUT_Q4', value='MMBT3906', footprint='Package_TO_SOT_SMD:SOT-23')
    comp_Q4.fields['Voltage'] = '3906V'
    comp_Q4.fields['Description'] = 'высокосторонний ключ 12В'

    # type:        TYPE_R_1K
    # description: затвор Q_FAN
    # tag:         OUT_R13
    comp_R13 = Part('Device', 'R', ref='R13', tag='OUT_R13', value='1k', footprint='Resistor_SMD:R_0603_1608Metric')
    comp_R13.fields['Power'] = '0.1W'
    comp_R13.fields['Tolerance'] = '1%'
    comp_R13.fields['Description'] = 'затвор Q_FAN'

    # type:        TYPE_R_4_12V
    # description: подтяжка выхода ШИМ к 12В
    # tag:         OUT_R14
    comp_R14 = Part('Device', 'R', ref='R14', tag='OUT_R14', value='4', footprint='Resistor_SMD:R_0603_1608Metric')
    comp_R14.fields['Voltage'] = '12V'
    comp_R14.fields['Power'] = '0.1W'
    comp_R14.fields['Tolerance'] = '1%'
    comp_R14.fields['Description'] = 'подтяжка выхода ШИМ к 12В'

    # type:        TYPE_R_1K
    # description: защитный резистор в линии ШИМ вентилятора (к J1:30
    # tag:         OUT_R15
    comp_R15 = Part('Device', 'R', ref='R15', tag='OUT_R15', value='1k', footprint='Resistor_SMD:R_0603_1608Metric')
    comp_R15.fields['Power'] = '0.1W'
    comp_R15.fields['Tolerance'] = '1%'
    comp_R15.fields['Description'] = 'защитный резистор в линии ШИМ вентилятора (к J1:30'

    # type:        TYPE_R_10K
    # description: база Q_AC_N
    # tag:         OUT_R18
    comp_R18 = Part('Device', 'R', ref='R18', tag='OUT_R18', value='10k', footprint='Resistor_SMD:R_0603_1608Metric')
    comp_R18.fields['Power'] = '0.1W'
    comp_R18.fields['Tolerance'] = '1%'
    comp_R18.fields['Description'] = 'база Q_AC_N'

    # type:        TYPE_R_100K
    # description: подтяжка базы Q_AC_N к GND
    # tag:         OUT_R19
    comp_R19 = Part('Device', 'R', ref='R19', tag='OUT_R19', value='100k', footprint='Resistor_SMD:R_0603_1608Metric')
    comp_R19.fields['Power'] = '0.1W'
    comp_R19.fields['Tolerance'] = '1%'
    comp_R19.fields['Description'] = 'подтяжка базы Q_AC_N к GND'

    # type:        TYPE_R_10K_12V
    # description: подтяжка базы PNP к +12В
    # tag:         OUT_R20
    comp_R20 = Part('Device', 'R', ref='R20', tag='OUT_R20', value='10k', footprint='Resistor_SMD:R_0603_1608Metric')
    comp_R20.fields['Voltage'] = '12V'
    comp_R20.fields['Power'] = '0.1W'
    comp_R20.fields['Tolerance'] = '1%'
    comp_R20.fields['Description'] = 'подтяжка базы PNP к +12В'

    # type:        TYPE_R_1K
    # description: защитный резистор линии запроса кондиционера (к J1:31
    # tag:         OUT_R21
    comp_R21 = Part('Device', 'R', ref='R21', tag='OUT_R21', value='1k', footprint='Resistor_SMD:R_0603_1608Metric')
    comp_R21.fields['Power'] = '0.1W'
    comp_R21.fields['Tolerance'] = '1%'
    comp_R21.fields['Description'] = 'защитный резистор линии запроса кондиционера (к J1:31'

    # ======================================================================
    # Цепи и соединения
    # ======================================================================
    # Цепь VCC_12V: Силовая шина +12В после фильтра помех L1, с TVS D2 и конденсаторами
    # attributes: type=POWER, voltage_level=12.0V, current_max=15A, spice_simulation={'model_stimulus': 'DC 12.0', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_VCC_12V += comp_Q4['2']
    p_VCC_12V += comp_R20['2']
    p_VCC_12V += comp_R14['2']

    # Цепь GND: Общий провод (кузов автомобиля)
    # attributes: type=GND, voltage_level=0V, current_max=15A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_GND += comp_Q1['2']
    p_GND += comp_Q3['2']
    p_GND += comp_R19['2']

    # Цепь FAN_PWM_CTL: ШИМ управления основным вентилятором (TIM1_CH1)
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_FAN_PWM_CTL += comp_R13['1']

    # Цепь FAN_GATE: Затвор буферного MOSFET
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_FAN_GATE = Net('FAN_GATE')
    net_FAN_GATE += comp_R13['2']
    net_FAN_GATE += comp_Q1['1']

    # Цепь FAN_PWM_NODE: Выход ШИМ 12В на внешний силовой модуль вентилятора (открытый сток, инверсный)
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_FAN_PWM_NODE = Net('FAN_PWM_NODE')
    net_FAN_PWM_NODE += comp_Q1['3']
    net_FAN_PWM_NODE += comp_R14['1']
    net_FAN_PWM_NODE += comp_R15['1']

    # Цепь AC_CTL: Управление транзистором запроса кондиционера
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_AC_CTL += comp_R18['1']

    # Цепь AC_BASE: База NPN-драйвера запроса кондиционера
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_AC_BASE = Net('AC_BASE')
    net_AC_BASE += comp_R18['2']
    net_AC_BASE += comp_Q3['1']
    net_AC_BASE += comp_R19['1']

    # Цепь AC_PNP_BASE: База высокостороннего PNP-ключа 12В
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_AC_PNP_BASE = Net('AC_PNP_BASE')
    net_AC_PNP_BASE += comp_Q3['3']
    net_AC_PNP_BASE += comp_Q4['1']
    net_AC_PNP_BASE += comp_R20['1']

    # Цепь AC_REQ: Выход запроса кондиционера (через защитный резистор R_AC_SER)
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_AC_REQ = Net('AC_REQ')
    net_AC_REQ += comp_Q4['3']
    net_AC_REQ += comp_R21['1']

    # Цепь AC_REQ_OUT: Линия запроса кондиционера +12В к J1:31 (вход ЭБУ двигателя)
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_AC_REQ_OUT += comp_R21['2']

    # Цепь HEAT_FAN_PWM_CTL: Внешний ШИМ-выход вентилятора печки на J1:23 через защитный резистор R15
    # attributes: type=PWM_POWER, voltage_level=0..12.0V, current_max=0.5A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_HEAT_FAN_PWM_CTL += comp_R15['2']


module_OUT.tag = 'SHEET_OUT'


# ==========================================================================
# Лист X_ACT  (sheets/actuators.yaml)
# ==========================================================================
@SubCircuit
def module_ACT(p_VCC_12V, p_GND, p_MOTOR_1_A, p_MOTOR_1_B, p_FB_M1, p_M1_IN1, p_M1_IN2, p_MOTOR_2_A, p_MOTOR_2_B, p_FB_M2_RAW, p_FB_M2, p_M2_IN1, p_M2_IN2, p_MOTOR_3_A, p_MOTOR_3_B, p_FB_M3_RAW, p_FB_M3, p_M3_IN1, p_M3_IN2, p_MOTOR_4_A, p_MOTOR_4_B, p_FB_M4_RAW, p_FB_M4, p_M4_IN1, p_M4_IN2):
    """
    Подстраница: X_ACT
    file: sheets/actuators.kicad_sch
    purpose: Модуль ACT

    Порты листа:
      VCC_12V                [POWER   ] Силовая шина +12В после фильтра помех L1, с TVS D2 и конденсаторами
      GND                    [POWER   ] Общий провод (кузов автомобиля)
      MOTOR_1_A              [OUTPUT  ] Заслонка 1: выход А мостового драйвера к моторедуктору
      MOTOR_1_B              [OUTPUT  ] Заслонка 1: выход B мостового драйвера к моторедуктору
      FB_M1                  [OUTPUT  ] Заслонка 1: сигнал ОС после делителя 5В->3,3В на АЦП
      M1_IN1                 [INPUT   ] Заслонка 1: вход IN1 драйвера
      M1_IN2                 [INPUT   ] Заслонка 1: вход IN2 драйвера
      MOTOR_2_A              [OUTPUT  ] Заслонка 2: выход А мостового драйвера к моторедуктору
      MOTOR_2_B              [OUTPUT  ] Заслонка 2: выход B мостового драйвера к моторедуктору
      FB_M2_RAW              [INPUT   ] Заслонка 2: выход потенциометра положения (0..5В)
      FB_M2                  [OUTPUT  ] Заслонка 2: сигнал ОС после делителя 5В->3,3В на АЦП
      M2_IN1                 [INPUT   ] Заслонка 2: вход IN1 драйвера
      M2_IN2                 [INPUT   ] Заслонка 2: вход IN2 драйвера
      MOTOR_3_A              [OUTPUT  ] Заслонка 3: выход А мостового драйвера к моторедуктору
      MOTOR_3_B              [OUTPUT  ] Заслонка 3: выход B мостового драйвера к моторедуктору
      FB_M3_RAW              [INPUT   ] Заслонка 3: выход потенциометра положения (0..5В)
      FB_M3                  [OUTPUT  ] Заслонка 3: сигнал ОС после делителя 5В->3,3В на АЦП
      M3_IN1                 [INPUT   ] Заслонка 3: вход IN1 драйвера
      M3_IN2                 [INPUT   ] Заслонка 3: вход IN2 драйвера
      MOTOR_4_A              [OUTPUT  ] Заслонка 4: выход А мостового драйвера к моторедуктору
      MOTOR_4_B              [OUTPUT  ] Заслонка 4: выход B мостового драйвера к моторедуктору
      FB_M4_RAW              [INPUT   ] Заслонка 4: выход потенциометра положения (0..5В)
      FB_M4                  [OUTPUT  ] Заслонка 4: сигнал ОС после делителя 5В->3,3В на АЦП
      M4_IN1                 [INPUT   ] Заслонка 4: вход IN1 драйвера
      M4_IN2                 [INPUT   ] Заслонка 4: вход IN2 драйвера
    """

    # ======================================================================
    # Компоненты
    # ======================================================================
    # type:        TYPE_C_100NF
    # description: питание драйвера U2
    # tag:         ACT_C12
    comp_C12 = Part('Device', 'C', ref='C12', tag='ACT_C12', value='100nF', footprint='Capacitor_SMD:C_0603_1608Metric')
    comp_C12.fields['Type'] = 'Ceramic'
    comp_C12.fields['Dielectric'] = 'X7R'
    comp_C12.fields['Description'] = 'питание драйвера U2'

    # type:        TYPE_C_100NF
    # description: питание драйвера U3
    # tag:         ACT_C13
    comp_C13 = Part('Device', 'C', ref='C13', tag='ACT_C13', value='100nF', footprint='Capacitor_SMD:C_0603_1608Metric')
    comp_C13.fields['Type'] = 'Ceramic'
    comp_C13.fields['Dielectric'] = 'X7R'
    comp_C13.fields['Description'] = 'питание драйвера U3'

    # type:        TYPE_C_100NF
    # description: питание драйвера U4
    # tag:         ACT_C14
    comp_C14 = Part('Device', 'C', ref='C14', tag='ACT_C14', value='100nF', footprint='Capacitor_SMD:C_0603_1608Metric')
    comp_C14.fields['Type'] = 'Ceramic'
    comp_C14.fields['Dielectric'] = 'X7R'
    comp_C14.fields['Description'] = 'питание драйвера U4'

    # type:        TYPE_C_100NF
    # description: питание драйвера U5
    # tag:         ACT_C15
    comp_C15 = Part('Device', 'C', ref='C15', tag='ACT_C15', value='100nF', footprint='Capacitor_SMD:C_0603_1608Metric')
    comp_C15.fields['Type'] = 'Ceramic'
    comp_C15.fields['Dielectric'] = 'X7R'
    comp_C15.fields['Description'] = 'питание драйвера U5'

    # type:        TYPE_C_100NF
    # description: фильтр АЦП ОС заслонки 1
    # tag:         ACT_C28
    comp_C28 = Part('Device', 'C', ref='C28', tag='ACT_C28', value='100nF', footprint='Capacitor_SMD:C_0603_1608Metric')
    comp_C28.fields['Type'] = 'Ceramic'
    comp_C28.fields['Dielectric'] = 'X7R'
    comp_C28.fields['Description'] = 'фильтр АЦП ОС заслонки 1'

    # type:        TYPE_C_100NF
    # description: фильтр АЦП ОС заслонки 2
    # tag:         ACT_C29
    comp_C29 = Part('Device', 'C', ref='C29', tag='ACT_C29', value='100nF', footprint='Capacitor_SMD:C_0603_1608Metric')
    comp_C29.fields['Type'] = 'Ceramic'
    comp_C29.fields['Dielectric'] = 'X7R'
    comp_C29.fields['Description'] = 'фильтр АЦП ОС заслонки 2'

    # type:        TYPE_C_100NF
    # description: фильтр АЦП ОС заслонки 3
    # tag:         ACT_C30
    comp_C30 = Part('Device', 'C', ref='C30', tag='ACT_C30', value='100nF', footprint='Capacitor_SMD:C_0603_1608Metric')
    comp_C30.fields['Type'] = 'Ceramic'
    comp_C30.fields['Dielectric'] = 'X7R'
    comp_C30.fields['Description'] = 'фильтр АЦП ОС заслонки 3'

    # type:        TYPE_C_100NF
    # description: фильтр АЦП ОС заслонки 4
    # tag:         ACT_C31
    comp_C31 = Part('Device', 'C', ref='C31', tag='ACT_C31', value='100nF', footprint='Capacitor_SMD:C_0603_1608Metric')
    comp_C31.fields['Type'] = 'Ceramic'
    comp_C31.fields['Dielectric'] = 'X7R'
    comp_C31.fields['Description'] = 'фильтр АЦП ОС заслонки 4'

    # type:        TYPE_R_33K
    # description: токоограничение драйвера (подобрать
    # tag:         ACT_R3
    comp_R3 = Part('Device', 'R', ref='R3', tag='ACT_R3', value='33k', footprint='Resistor_SMD:R_0603_1608Metric')
    comp_R3.fields['Power'] = '0.1W'
    comp_R3.fields['Tolerance'] = '1%'
    comp_R3.fields['Description'] = 'токоограничение драйвера (подобрать'

    # type:        TYPE_R_20K
    # description: делитель ОС заслонки 1 (низ
    # tag:         ACT_R32
    comp_R32 = Part('Device', 'R', ref='R32', tag='ACT_R32', value='20k', footprint='Resistor_SMD:R_0603_1608Metric')
    comp_R32.fields['Power'] = '0.1W'
    comp_R32.fields['Tolerance'] = '1%'
    comp_R32.fields['Description'] = 'делитель ОС заслонки 1 (низ'

    # type:        TYPE_R_10K
    # description: делитель ОС заслонки 2 (верх
    # tag:         ACT_R33
    comp_R33 = Part('Device', 'R', ref='R33', tag='ACT_R33', value='10k', footprint='Resistor_SMD:R_0603_1608Metric')
    comp_R33.fields['Power'] = '0.1W'
    comp_R33.fields['Tolerance'] = '1%'
    comp_R33.fields['Description'] = 'делитель ОС заслонки 2 (верх'

    # type:        TYPE_R_20K
    # description: делитель ОС заслонки 2 (низ
    # tag:         ACT_R34
    comp_R34 = Part('Device', 'R', ref='R34', tag='ACT_R34', value='20k', footprint='Resistor_SMD:R_0603_1608Metric')
    comp_R34.fields['Power'] = '0.1W'
    comp_R34.fields['Tolerance'] = '1%'
    comp_R34.fields['Description'] = 'делитель ОС заслонки 2 (низ'

    # type:        TYPE_R_10K
    # description: делитель ОС заслонки 3 (верх
    # tag:         ACT_R35
    comp_R35 = Part('Device', 'R', ref='R35', tag='ACT_R35', value='10k', footprint='Resistor_SMD:R_0603_1608Metric')
    comp_R35.fields['Power'] = '0.1W'
    comp_R35.fields['Tolerance'] = '1%'
    comp_R35.fields['Description'] = 'делитель ОС заслонки 3 (верх'

    # type:        TYPE_R_20K
    # description: делитель ОС заслонки 3 (низ
    # tag:         ACT_R36
    comp_R36 = Part('Device', 'R', ref='R36', tag='ACT_R36', value='20k', footprint='Resistor_SMD:R_0603_1608Metric')
    comp_R36.fields['Power'] = '0.1W'
    comp_R36.fields['Tolerance'] = '1%'
    comp_R36.fields['Description'] = 'делитель ОС заслонки 3 (низ'

    # type:        TYPE_R_10K
    # description: делитель ОС заслонки 4 (верх
    # tag:         ACT_R37
    comp_R37 = Part('Device', 'R', ref='R37', tag='ACT_R37', value='10k', footprint='Resistor_SMD:R_0603_1608Metric')
    comp_R37.fields['Power'] = '0.1W'
    comp_R37.fields['Tolerance'] = '1%'
    comp_R37.fields['Description'] = 'делитель ОС заслонки 4 (верх'

    # type:        TYPE_R_20K
    # description: делитель ОС заслонки 4 (низ
    # tag:         ACT_R38
    comp_R38 = Part('Device', 'R', ref='R38', tag='ACT_R38', value='20k', footprint='Resistor_SMD:R_0603_1608Metric')
    comp_R38.fields['Power'] = '0.1W'
    comp_R38.fields['Tolerance'] = '1%'
    comp_R38.fields['Description'] = 'делитель ОС заслонки 4 (низ'

    # type:        TYPE_R_33K
    # description: токоограничение драйвера (подобрать
    # tag:         ACT_R4
    comp_R4 = Part('Device', 'R', ref='R4', tag='ACT_R4', value='33k', footprint='Resistor_SMD:R_0603_1608Metric')
    comp_R4.fields['Power'] = '0.1W'
    comp_R4.fields['Tolerance'] = '1%'
    comp_R4.fields['Description'] = 'токоограничение драйвера (подобрать'

    # type:        TYPE_R_33K
    # description: токоограничение драйвера (подобрать
    # tag:         ACT_R5
    comp_R5 = Part('Device', 'R', ref='R5', tag='ACT_R5', value='33k', footprint='Resistor_SMD:R_0603_1608Metric')
    comp_R5.fields['Power'] = '0.1W'
    comp_R5.fields['Tolerance'] = '1%'
    comp_R5.fields['Description'] = 'токоограничение драйвера (подобрать'

    # type:        TYPE_R_33K
    # description: токоограничение драйвера (подобрать
    # tag:         ACT_R6
    comp_R6 = Part('Device', 'R', ref='R6', tag='ACT_R6', value='33k', footprint='Resistor_SMD:R_0603_1608Metric')
    comp_R6.fields['Power'] = '0.1W'
    comp_R6.fields['Tolerance'] = '1%'
    comp_R6.fields['Description'] = 'токоограничение драйвера (подобрать'

    # type:        TYPE_DRV8871DDA_DRV8871H-МОСТ
    # description: заслонки 1
    # tag:         ACT_U2
    comp_U2 = Part('Driver_Motor', 'DRV8871DDA', ref='U2', tag='ACT_U2', value='DRV8871 H-мост', footprint='Package_SO:SOIC-8_3.9x4.9mm_P1.27mm')
    comp_U2.fields['Description'] = 'заслонки 1'

    # type:        TYPE_DRV8871DDA_DRV8871H-МОСТ
    # description: заслонки 2
    # tag:         ACT_U3
    comp_U3 = Part('Driver_Motor', 'DRV8871DDA', ref='U3', tag='ACT_U3', value='DRV8871 H-мост', footprint='Package_SO:SOIC-8_3.9x4.9mm_P1.27mm')
    comp_U3.fields['Description'] = 'заслонки 2'

    # type:        TYPE_DRV8871DDA_DRV8871H-МОСТ
    # description: заслонки 3
    # tag:         ACT_U4
    comp_U4 = Part('Driver_Motor', 'DRV8871DDA', ref='U4', tag='ACT_U4', value='DRV8871 H-мост', footprint='Package_SO:SOIC-8_3.9x4.9mm_P1.27mm')
    comp_U4.fields['Description'] = 'заслонки 3'

    # type:        TYPE_DRV8871DDA_DRV8871H-МОСТ
    # description: заслонки 4
    # tag:         ACT_U5
    comp_U5 = Part('Driver_Motor', 'DRV8871DDA', ref='U5', tag='ACT_U5', value='DRV8871 H-мост', footprint='Package_SO:SOIC-8_3.9x4.9mm_P1.27mm')
    comp_U5.fields['Description'] = 'заслонки 4'

    # ======================================================================
    # Цепи и соединения
    # ======================================================================
    # Цепь VCC_12V: Силовая шина +12В после фильтра помех L1, с TVS D2 и конденсаторами
    # attributes: type=POWER, voltage_level=12.0V, current_max=15A, spice_simulation={'model_stimulus': 'DC 12.0', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_VCC_12V += comp_U2['5']
    p_VCC_12V += comp_U3['5']
    p_VCC_12V += comp_U4['5']
    p_VCC_12V += comp_U5['5']
    p_VCC_12V += comp_C12['1']
    p_VCC_12V += comp_C13['1']
    p_VCC_12V += comp_C14['1']
    p_VCC_12V += comp_C15['1']

    # Цепь GND: Общий провод (кузов автомобиля)
    # attributes: type=GND, voltage_level=0V, current_max=15A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_GND += comp_U2['1']
    p_GND += comp_U2['7']
    p_GND += comp_U3['1']
    p_GND += comp_U3['7']
    p_GND += comp_U4['1']
    p_GND += comp_U4['7']
    p_GND += comp_U5['1']
    p_GND += comp_U5['7']
    p_GND += comp_C12['2']
    p_GND += comp_C13['2']
    p_GND += comp_C14['2']
    p_GND += comp_C15['2']
    p_GND += comp_R3['2']
    p_GND += comp_R4['2']
    p_GND += comp_R5['2']
    p_GND += comp_R6['2']
    p_GND += comp_R32['2']
    p_GND += comp_R34['2']
    p_GND += comp_R36['2']
    p_GND += comp_R38['2']
    p_GND += comp_C28['2']
    p_GND += comp_C29['2']
    p_GND += comp_C30['2']
    p_GND += comp_C31['2']

    # Цепь MOTOR_1_A: Заслонка 1: выход А мостового драйвера к моторедуктору
    # attributes: type=PWM_POWER, voltage_level=0..12.0V, current_max=5.0A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_MOTOR_1_A += comp_U2['6']

    # Цепь MOTOR_1_B: Заслонка 1: выход B мостового драйвера к моторедуктору
    # attributes: type=PWM_POWER, voltage_level=0..12.0V, current_max=5.0A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_MOTOR_1_B += comp_U2['8']

    # Цепь FB_M1: Заслонка 1: сигнал ОС после делителя 5В->3,3В на АЦП
    # attributes: type=ANALOG_SIGNAL, voltage_level=0..3.3V, current_max=0.005A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_FB_M1 += comp_R32['1']
    p_FB_M1 += comp_C28['1']

    # Цепь M1_IN1: Заслонка 1: вход IN1 драйвера
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_M1_IN1 += comp_U2['3']

    # Цепь M1_IN2: Заслонка 1: вход IN2 драйвера
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_M1_IN2 += comp_U2['2']

    # Цепь ILIM_1: Заслонка 1: установка токоограничения драйвера
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_ILIM_1 = Net('ILIM_1')
    net_ILIM_1 += comp_U2['4']
    net_ILIM_1 += comp_R3['1']

    # Цепь MOTOR_2_A: Заслонка 2: выход А мостового драйвера к моторедуктору
    # attributes: type=PWM_POWER, voltage_level=0..12.0V, current_max=5.0A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_MOTOR_2_A += comp_U3['6']

    # Цепь MOTOR_2_B: Заслонка 2: выход B мостового драйвера к моторедуктору
    # attributes: type=PWM_POWER, voltage_level=0..12.0V, current_max=5.0A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_MOTOR_2_B += comp_U3['8']

    # Цепь FB_M2_RAW: Заслонка 2: выход потенциометра положения (0..5В)
    # attributes: type=ANALOG_SIGNAL, voltage_level=0..3.3V, current_max=0.005A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_FB_M2_RAW += comp_R33['1']

    # Цепь FB_M2: Заслонка 2: сигнал ОС после делителя 5В->3,3В на АЦП
    # attributes: type=ANALOG_SIGNAL, voltage_level=0..3.3V, current_max=0.005A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_FB_M2 += comp_R33['2']
    p_FB_M2 += comp_R34['1']
    p_FB_M2 += comp_C29['1']

    # Цепь M2_IN1: Заслонка 2: вход IN1 драйвера
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_M2_IN1 += comp_U3['3']

    # Цепь M2_IN2: Заслонка 2: вход IN2 драйвера
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_M2_IN2 += comp_U3['2']

    # Цепь ILIM_2: Заслонка 2: установка токоограничения драйвера
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_ILIM_2 = Net('ILIM_2')
    net_ILIM_2 += comp_U3['4']
    net_ILIM_2 += comp_R4['1']

    # Цепь MOTOR_3_A: Заслонка 3: выход А мостового драйвера к моторедуктору
    # attributes: type=PWM_POWER, voltage_level=0..12.0V, current_max=5.0A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_MOTOR_3_A += comp_U4['6']

    # Цепь MOTOR_3_B: Заслонка 3: выход B мостового драйвера к моторедуктору
    # attributes: type=PWM_POWER, voltage_level=0..12.0V, current_max=5.0A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_MOTOR_3_B += comp_U4['8']

    # Цепь FB_M3_RAW: Заслонка 3: выход потенциометра положения (0..5В)
    # attributes: type=ANALOG_SIGNAL, voltage_level=0..3.3V, current_max=0.005A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_FB_M3_RAW += comp_R35['1']

    # Цепь FB_M3: Заслонка 3: сигнал ОС после делителя 5В->3,3В на АЦП
    # attributes: type=ANALOG_SIGNAL, voltage_level=0..3.3V, current_max=0.005A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_FB_M3 += comp_R35['2']
    p_FB_M3 += comp_R36['1']
    p_FB_M3 += comp_C30['1']

    # Цепь M3_IN1: Заслонка 3: вход IN1 драйвера
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_M3_IN1 += comp_U4['3']

    # Цепь M3_IN2: Заслонка 3: вход IN2 драйвера
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_M3_IN2 += comp_U4['2']

    # Цепь ILIM_3: Заслонка 3: установка токоограничения драйвера
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_ILIM_3 = Net('ILIM_3')
    net_ILIM_3 += comp_U4['4']
    net_ILIM_3 += comp_R5['1']

    # Цепь MOTOR_4_A: Заслонка 4: выход А мостового драйвера к моторедуктору
    # attributes: type=PWM_POWER, voltage_level=0..12.0V, current_max=5.0A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_MOTOR_4_A += comp_U5['6']

    # Цепь MOTOR_4_B: Заслонка 4: выход B мостового драйвера к моторедуктору
    # attributes: type=PWM_POWER, voltage_level=0..12.0V, current_max=5.0A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_MOTOR_4_B += comp_U5['8']

    # Цепь FB_M4_RAW: Заслонка 4: выход потенциометра положения (0..5В)
    # attributes: type=ANALOG_SIGNAL, voltage_level=0..3.3V, current_max=0.005A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_FB_M4_RAW += comp_R37['1']

    # Цепь FB_M4: Заслонка 4: сигнал ОС после делителя 5В->3,3В на АЦП
    # attributes: type=ANALOG_SIGNAL, voltage_level=0..3.3V, current_max=0.005A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_FB_M4 += comp_R37['2']
    p_FB_M4 += comp_R38['1']
    p_FB_M4 += comp_C31['1']

    # Цепь M4_IN1: Заслонка 4: вход IN1 драйвера
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_M4_IN1 += comp_U5['3']

    # Цепь M4_IN2: Заслонка 4: вход IN2 драйвера
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    # Порт листа (см. docstring выше).
    p_M4_IN2 += comp_U5['2']

    # Цепь ILIM_4: Заслонка 4: установка токоограничения драйвера
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_ILIM_4 = Net('ILIM_4')
    net_ILIM_4 += comp_U5['4']
    net_ILIM_4 += comp_R6['1']


module_ACT.tag = 'SHEET_ACT'


# ==========================================================================
# Лист X_BACKLIGHT  (sheets/backlight.yaml)
# ==========================================================================
@SubCircuit
def module_BACKLIGHT(p_ILLUM_IN_RAW, p_GND):
    """
    Подстраница: X_BACKLIGHT
    file: sheets/backlight.kicad_sch
    purpose: Модуль радиальной фоновой подсветки шкал ручек управления

    Порты листа:
      ILLUM_IN_RAW           [POWER   ] Вход внешней подсветки прибора (+12В габаритов автомобиля)
      GND                    [POWER   ] Общая силовая земля схемы
    """

    # ======================================================================
    # Компоненты
    # ======================================================================
    # type:        TYPE_R_0603_130R
    # description: Резистор шкал 1
    # tag:         BACKLIGHT_R1
    comp_R1 = Part('Device', 'R', ref='R1', tag='BACKLIGHT_R1', value='130R', footprint='Resistor_SMD:R_0603_1608Metric')
    comp_R1.fields['Power'] = '0.1W'
    comp_R1.fields['Tolerance'] = '1%'
    comp_R1.fields['Description'] = 'Резистор шкал 1'

    # type:        TYPE_R_0603_130R
    # description: Резистор шкал 2
    # tag:         BACKLIGHT_R2
    comp_R2 = Part('Device', 'R', ref='R2', tag='BACKLIGHT_R2', value='130R', footprint='Resistor_SMD:R_0603_1608Metric')
    comp_R2.fields['Power'] = '0.1W'
    comp_R2.fields['Tolerance'] = '1%'
    comp_R2.fields['Description'] = 'Резистор шкал 2'

    # type:        TYPE_R_0603_130R
    # description: Резистор шкал 3
    # tag:         BACKLIGHT_R3
    comp_R3 = Part('Device', 'R', ref='R3', tag='BACKLIGHT_R3', value='130R', footprint='Resistor_SMD:R_0603_1608Metric')
    comp_R3.fields['Power'] = '0.1W'
    comp_R3.fields['Tolerance'] = '1%'
    comp_R3.fields['Description'] = 'Резистор шкал 3'

    # type:        TYPE_R_0603_130R
    # description: Резистор шкал 4
    # tag:         BACKLIGHT_R4
    comp_R4 = Part('Device', 'R', ref='R4', tag='BACKLIGHT_R4', value='130R', footprint='Resistor_SMD:R_0603_1608Metric')
    comp_R4.fields['Power'] = '0.1W'
    comp_R4.fields['Tolerance'] = '1%'
    comp_R4.fields['Description'] = 'Резистор шкал 4'

    # type:        TYPE_R_0603_130R
    # description: Резистор шкал 5
    # tag:         BACKLIGHT_R5
    comp_R5 = Part('Device', 'R', ref='R5', tag='BACKLIGHT_R5', value='130R', footprint='Resistor_SMD:R_0603_1608Metric')
    comp_R5.fields['Power'] = '0.1W'
    comp_R5.fields['Tolerance'] = '1%'
    comp_R5.fields['Description'] = 'Резистор шкал 5'

    # type:        TYPE_R_0603_130R
    # description: Резистор шкал 6
    # tag:         BACKLIGHT_R6
    comp_R6 = Part('Device', 'R', ref='R6', tag='BACKLIGHT_R6', value='130R', footprint='Resistor_SMD:R_0603_1608Metric')
    comp_R6.fields['Power'] = '0.1W'
    comp_R6.fields['Tolerance'] = '1%'
    comp_R6.fields['Description'] = 'Резистор шкал 6'

    # type:        TYPE_R_0603_130R
    # description: Резистор шкал 7
    # tag:         BACKLIGHT_R7
    comp_R7 = Part('Device', 'R', ref='R7', tag='BACKLIGHT_R7', value='130R', footprint='Resistor_SMD:R_0603_1608Metric')
    comp_R7.fields['Power'] = '0.1W'
    comp_R7.fields['Tolerance'] = '1%'
    comp_R7.fields['Description'] = 'Резистор шкал 7'

    # type:        TYPE_R_0603_130R
    # description: Резистор шкал 8
    # tag:         BACKLIGHT_R8
    comp_R8 = Part('Device', 'R', ref='R8', tag='BACKLIGHT_R8', value='130R', footprint='Resistor_SMD:R_0603_1608Metric')
    comp_R8.fields['Power'] = '0.1W'
    comp_R8.fields['Tolerance'] = '1%'
    comp_R8.fields['Description'] = 'Резистор шкал 8'

    # type:        TYPE_LED_0805_WHITE
    # description: Шкала Ручки 1: Диод 1
    # tag:         BACKLIGHT_LED11
    comp_LED11 = Part('Device', 'LED', ref='LED11', tag='BACKLIGHT_LED11', value='Белый SMD 0805', footprint='LED_SMD:LED_0805_2012Metric')
    comp_LED11.fields['Color'] = 'White'
    comp_LED11.fields['Description'] = 'Шкала Ручки 1: Диод 1'

    # type:        TYPE_LED_0805_WHITE
    # description: Шкала Ручки 1: Диод 2
    # tag:         BACKLIGHT_LED12
    comp_LED12 = Part('Device', 'LED', ref='LED12', tag='BACKLIGHT_LED12', value='Белый SMD 0805', footprint='LED_SMD:LED_0805_2012Metric')
    comp_LED12.fields['Color'] = 'White'
    comp_LED12.fields['Description'] = 'Шкала Ручки 1: Диод 2'

    # type:        TYPE_LED_0805_WHITE
    # description: Шкала Ручки 1: Диод 3
    # tag:         BACKLIGHT_LED13
    comp_LED13 = Part('Device', 'LED', ref='LED13', tag='BACKLIGHT_LED13', value='Белый SMD 0805', footprint='LED_SMD:LED_0805_2012Metric')
    comp_LED13.fields['Color'] = 'White'
    comp_LED13.fields['Description'] = 'Шкала Ручки 1: Диод 3'

    # type:        TYPE_LED_0805_WHITE
    # description: Шкала Ручки 1: Диод 4
    # tag:         BACKLIGHT_LED21
    comp_LED21 = Part('Device', 'LED', ref='LED21', tag='BACKLIGHT_LED21', value='Белый SMD 0805', footprint='LED_SMD:LED_0805_2012Metric')
    comp_LED21.fields['Color'] = 'White'
    comp_LED21.fields['Description'] = 'Шкала Ручки 1: Диод 4'

    # type:        TYPE_LED_0805_WHITE
    # description: Шкала Ручки 1: Диод 5
    # tag:         BACKLIGHT_LED22
    comp_LED22 = Part('Device', 'LED', ref='LED22', tag='BACKLIGHT_LED22', value='Белый SMD 0805', footprint='LED_SMD:LED_0805_2012Metric')
    comp_LED22.fields['Color'] = 'White'
    comp_LED22.fields['Description'] = 'Шкала Ручки 1: Диод 5'

    # type:        TYPE_LED_0805_WHITE
    # description: Шкала Ручки 1: Диод 6
    # tag:         BACKLIGHT_LED23
    comp_LED23 = Part('Device', 'LED', ref='LED23', tag='BACKLIGHT_LED23', value='Белый SMD 0805', footprint='LED_SMD:LED_0805_2012Metric')
    comp_LED23.fields['Color'] = 'White'
    comp_LED23.fields['Description'] = 'Шкала Ручки 1: Диод 6'

    # type:        TYPE_LED_0805_WHITE
    # description: Шкала Ручки 1: Диод 7
    # tag:         BACKLIGHT_LED31
    comp_LED31 = Part('Device', 'LED', ref='LED31', tag='BACKLIGHT_LED31', value='Белый SMD 0805', footprint='LED_SMD:LED_0805_2012Metric')
    comp_LED31.fields['Color'] = 'White'
    comp_LED31.fields['Description'] = 'Шкала Ручки 1: Диод 7'

    # type:        TYPE_LED_0805_WHITE
    # description: Шкала Ручки 1: Диод 8
    # tag:         BACKLIGHT_LED32
    comp_LED32 = Part('Device', 'LED', ref='LED32', tag='BACKLIGHT_LED32', value='Белый SMD 0805', footprint='LED_SMD:LED_0805_2012Metric')
    comp_LED32.fields['Color'] = 'White'
    comp_LED32.fields['Description'] = 'Шкала Ручки 1: Диод 8'

    # type:        TYPE_LED_0805_WHITE
    # description: Шкала Ручки 1: Диод 9
    # tag:         BACKLIGHT_LED33
    comp_LED33 = Part('Device', 'LED', ref='LED33', tag='BACKLIGHT_LED33', value='Белый SMD 0805', footprint='LED_SMD:LED_0805_2012Metric')
    comp_LED33.fields['Color'] = 'White'
    comp_LED33.fields['Description'] = 'Шкала Ручки 1: Диод 9'

    # type:        TYPE_LED_0805_WHITE
    # description: Шкала Ручки 1: Диод 10
    # tag:         BACKLIGHT_LED41
    comp_LED41 = Part('Device', 'LED', ref='LED41', tag='BACKLIGHT_LED41', value='Белый SMD 0805', footprint='LED_SMD:LED_0805_2012Metric')
    comp_LED41.fields['Color'] = 'White'
    comp_LED41.fields['Description'] = 'Шкала Ручки 1: Диод 10'

    # type:        TYPE_LED_0805_WHITE
    # description: Шкала Ручки 1: Диод 11
    # tag:         BACKLIGHT_LED42
    comp_LED42 = Part('Device', 'LED', ref='LED42', tag='BACKLIGHT_LED42', value='Белый SMD 0805', footprint='LED_SMD:LED_0805_2012Metric')
    comp_LED42.fields['Color'] = 'White'
    comp_LED42.fields['Description'] = 'Шкала Ручки 1: Диод 11'

    # type:        TYPE_LED_0805_WHITE
    # description: Шкала Ручки 1: Диод 12
    # tag:         BACKLIGHT_LED43
    comp_LED43 = Part('Device', 'LED', ref='LED43', tag='BACKLIGHT_LED43', value='Белый SMD 0805', footprint='LED_SMD:LED_0805_2012Metric')
    comp_LED43.fields['Color'] = 'White'
    comp_LED43.fields['Description'] = 'Шкала Ручки 1: Диод 12'

    # type:        TYPE_LED_0805_WHITE
    # description: Шкала Ручки 2: Диод 1
    # tag:         BACKLIGHT_LED51
    comp_LED51 = Part('Device', 'LED', ref='LED51', tag='BACKLIGHT_LED51', value='Белый SMD 0805', footprint='LED_SMD:LED_0805_2012Metric')
    comp_LED51.fields['Color'] = 'White'
    comp_LED51.fields['Description'] = 'Шкала Ручки 2: Диод 1'

    # type:        TYPE_LED_0805_WHITE
    # description: Шкала Ручки 2: Диод 2
    # tag:         BACKLIGHT_LED52
    comp_LED52 = Part('Device', 'LED', ref='LED52', tag='BACKLIGHT_LED52', value='Белый SMD 0805', footprint='LED_SMD:LED_0805_2012Metric')
    comp_LED52.fields['Color'] = 'White'
    comp_LED52.fields['Description'] = 'Шкала Ручки 2: Диод 2'

    # type:        TYPE_LED_0805_WHITE
    # description: Шкала Ручки 2: Диод 3
    # tag:         BACKLIGHT_LED53
    comp_LED53 = Part('Device', 'LED', ref='LED53', tag='BACKLIGHT_LED53', value='Белый SMD 0805', footprint='LED_SMD:LED_0805_2012Metric')
    comp_LED53.fields['Color'] = 'White'
    comp_LED53.fields['Description'] = 'Шкала Ручки 2: Диод 3'

    # type:        TYPE_LED_0805_WHITE
    # description: Шкала Ручки 2: Диод 4
    # tag:         BACKLIGHT_LED61
    comp_LED61 = Part('Device', 'LED', ref='LED61', tag='BACKLIGHT_LED61', value='Белый SMD 0805', footprint='LED_SMD:LED_0805_2012Metric')
    comp_LED61.fields['Color'] = 'White'
    comp_LED61.fields['Description'] = 'Шкала Ручки 2: Диод 4'

    # type:        TYPE_LED_0805_WHITE
    # description: Шкала Ручки 2: Диод 5
    # tag:         BACKLIGHT_LED62
    comp_LED62 = Part('Device', 'LED', ref='LED62', tag='BACKLIGHT_LED62', value='Белый SMD 0805', footprint='LED_SMD:LED_0805_2012Metric')
    comp_LED62.fields['Color'] = 'White'
    comp_LED62.fields['Description'] = 'Шкала Ручки 2: Диод 5'

    # type:        TYPE_LED_0805_WHITE
    # description: Шкала Ручки 2: Диод 6
    # tag:         BACKLIGHT_LED63
    comp_LED63 = Part('Device', 'LED', ref='LED63', tag='BACKLIGHT_LED63', value='Белый SMD 0805', footprint='LED_SMD:LED_0805_2012Metric')
    comp_LED63.fields['Color'] = 'White'
    comp_LED63.fields['Description'] = 'Шкала Ручки 2: Диод 6'

    # type:        TYPE_LED_0805_WHITE
    # description: Шкала Ручки 2: Диод 7
    # tag:         BACKLIGHT_LED71
    comp_LED71 = Part('Device', 'LED', ref='LED71', tag='BACKLIGHT_LED71', value='Белый SMD 0805', footprint='LED_SMD:LED_0805_2012Metric')
    comp_LED71.fields['Color'] = 'White'
    comp_LED71.fields['Description'] = 'Шкала Ручки 2: Диод 7'

    # type:        TYPE_LED_0805_WHITE
    # description: Шкала Ручки 2: Диод 8
    # tag:         BACKLIGHT_LED72
    comp_LED72 = Part('Device', 'LED', ref='LED72', tag='BACKLIGHT_LED72', value='Белый SMD 0805', footprint='LED_SMD:LED_0805_2012Metric')
    comp_LED72.fields['Color'] = 'White'
    comp_LED72.fields['Description'] = 'Шкала Ручки 2: Диод 8'

    # type:        TYPE_LED_0805_WHITE
    # description: Шкала Ручки 2: Диод 9
    # tag:         BACKLIGHT_LED73
    comp_LED73 = Part('Device', 'LED', ref='LED73', tag='BACKLIGHT_LED73', value='Белый SMD 0805', footprint='LED_SMD:LED_0805_2012Metric')
    comp_LED73.fields['Color'] = 'White'
    comp_LED73.fields['Description'] = 'Шкала Ручки 2: Диод 9'

    # type:        TYPE_LED_0805_WHITE
    # description: Шкала Ручки 2: Диод 10
    # tag:         BACKLIGHT_LED81
    comp_LED81 = Part('Device', 'LED', ref='LED81', tag='BACKLIGHT_LED81', value='Белый SMD 0805', footprint='LED_SMD:LED_0805_2012Metric')
    comp_LED81.fields['Color'] = 'White'
    comp_LED81.fields['Description'] = 'Шкала Ручки 2: Диод 10'

    # type:        TYPE_LED_0805_WHITE
    # description: Шкала Ручки 2: Диод 11
    # tag:         BACKLIGHT_LED82
    comp_LED82 = Part('Device', 'LED', ref='LED82', tag='BACKLIGHT_LED82', value='Белый SMD 0805', footprint='LED_SMD:LED_0805_2012Metric')
    comp_LED82.fields['Color'] = 'White'
    comp_LED82.fields['Description'] = 'Шкала Ручки 2: Диод 11'

    # type:        TYPE_LED_0805_WHITE
    # description: Шкала Ручки 2: Диод 12
    # tag:         BACKLIGHT_LED83
    comp_LED83 = Part('Device', 'LED', ref='LED83', tag='BACKLIGHT_LED83', value='Белый SMD 0805', footprint='LED_SMD:LED_0805_2012Metric')
    comp_LED83.fields['Color'] = 'White'
    comp_LED83.fields['Description'] = 'Шкала Ручки 2: Диод 12'

    # ======================================================================
    # Цепи и соединения
    # ======================================================================
    # Цепь ILLUM_IN_RAW: Вход внешней подсветки прибора (+12В габаритов)
    # attributes: type=POWER
    # Порт листа (см. docstring выше).
    p_ILLUM_IN_RAW += comp_R1['1']
    p_ILLUM_IN_RAW += comp_R2['1']
    p_ILLUM_IN_RAW += comp_R3['1']
    p_ILLUM_IN_RAW += comp_R4['1']
    p_ILLUM_IN_RAW += comp_R5['1']
    p_ILLUM_IN_RAW += comp_R6['1']
    p_ILLUM_IN_RAW += comp_R7['1']
    p_ILLUM_IN_RAW += comp_R8['1']

    net_NET_SCALE_CH1_A = Net('NET_SCALE_CH1_A')
    net_NET_SCALE_CH1_A += comp_R1['2']
    net_NET_SCALE_CH1_A += comp_LED11['1']

    net_NET_SCALE_CH1_B = Net('NET_SCALE_CH1_B')
    net_NET_SCALE_CH1_B += comp_LED11['2']
    net_NET_SCALE_CH1_B += comp_LED12['1']

    net_NET_SCALE_CH1_C = Net('NET_SCALE_CH1_C')
    net_NET_SCALE_CH1_C += comp_LED12['2']
    net_NET_SCALE_CH1_C += comp_LED13['1']

    net_NET_SCALE_CH2_A = Net('NET_SCALE_CH2_A')
    net_NET_SCALE_CH2_A += comp_R2['2']
    net_NET_SCALE_CH2_A += comp_LED21['1']

    net_NET_SCALE_CH2_B = Net('NET_SCALE_CH2_B')
    net_NET_SCALE_CH2_B += comp_LED21['2']
    net_NET_SCALE_CH2_B += comp_LED22['1']

    net_NET_SCALE_CH2_C = Net('NET_SCALE_CH2_C')
    net_NET_SCALE_CH2_C += comp_LED22['2']
    net_NET_SCALE_CH2_C += comp_LED23['1']

    net_NET_SCALE_CH3_A = Net('NET_SCALE_CH3_A')
    net_NET_SCALE_CH3_A += comp_R3['2']
    net_NET_SCALE_CH3_A += comp_LED31['1']

    net_NET_SCALE_CH3_B = Net('NET_SCALE_CH3_B')
    net_NET_SCALE_CH3_B += comp_LED31['2']
    net_NET_SCALE_CH3_B += comp_LED32['1']

    net_NET_SCALE_CH3_C = Net('NET_SCALE_CH3_C')
    net_NET_SCALE_CH3_C += comp_LED32['2']
    net_NET_SCALE_CH3_C += comp_LED33['1']

    net_NET_SCALE_CH4_A = Net('NET_SCALE_CH4_A')
    net_NET_SCALE_CH4_A += comp_R4['2']
    net_NET_SCALE_CH4_A += comp_LED41['1']

    net_NET_SCALE_CH4_B = Net('NET_SCALE_CH4_B')
    net_NET_SCALE_CH4_B += comp_LED41['2']
    net_NET_SCALE_CH4_B += comp_LED42['1']

    net_NET_SCALE_CH4_C = Net('NET_SCALE_CH4_C')
    net_NET_SCALE_CH4_C += comp_LED42['2']
    net_NET_SCALE_CH4_C += comp_LED43['1']

    net_NET_SCALE_CH5_A = Net('NET_SCALE_CH5_A')
    net_NET_SCALE_CH5_A += comp_R5['2']
    net_NET_SCALE_CH5_A += comp_LED51['1']

    net_NET_SCALE_CH5_B = Net('NET_SCALE_CH5_B')
    net_NET_SCALE_CH5_B += comp_LED51['2']
    net_NET_SCALE_CH5_B += comp_LED52['1']

    net_NET_SCALE_CH5_C = Net('NET_SCALE_CH5_C')
    net_NET_SCALE_CH5_C += comp_LED52['2']
    net_NET_SCALE_CH5_C += comp_LED53['1']

    net_NET_SCALE_CH6_A = Net('NET_SCALE_CH6_A')
    net_NET_SCALE_CH6_A += comp_R6['2']
    net_NET_SCALE_CH6_A += comp_LED61['1']

    net_NET_SCALE_CH6_B = Net('NET_SCALE_CH6_B')
    net_NET_SCALE_CH6_B += comp_LED61['2']
    net_NET_SCALE_CH6_B += comp_LED62['1']

    net_NET_SCALE_CH6_C = Net('NET_SCALE_CH6_C')
    net_NET_SCALE_CH6_C += comp_LED62['2']
    net_NET_SCALE_CH6_C += comp_LED63['1']

    net_NET_SCALE_CH7_A = Net('NET_SCALE_CH7_A')
    net_NET_SCALE_CH7_A += comp_R7['2']
    net_NET_SCALE_CH7_A += comp_LED71['1']

    net_NET_SCALE_CH7_B = Net('NET_SCALE_CH7_B')
    net_NET_SCALE_CH7_B += comp_LED71['2']
    net_NET_SCALE_CH7_B += comp_LED72['1']

    net_NET_SCALE_CH7_C = Net('NET_SCALE_CH7_C')
    net_NET_SCALE_CH7_C += comp_LED72['2']
    net_NET_SCALE_CH7_C += comp_LED73['1']

    net_NET_SCALE_CH8_A = Net('NET_SCALE_CH8_A')
    net_NET_SCALE_CH8_A += comp_R8['2']
    net_NET_SCALE_CH8_A += comp_LED81['1']

    net_NET_SCALE_CH8_B = Net('NET_SCALE_CH8_B')
    net_NET_SCALE_CH8_B += comp_LED81['2']
    net_NET_SCALE_CH8_B += comp_LED82['1']

    net_NET_SCALE_CH8_C = Net('NET_SCALE_CH8_C')
    net_NET_SCALE_CH8_C += comp_LED82['2']
    net_NET_SCALE_CH8_C += comp_LED83['1']

    # Цепь GND: Общая силовая земля схемы
    # attributes: type=GND
    # Порт листа (см. docstring выше).
    p_GND += comp_LED13['2']
    p_GND += comp_LED23['2']
    p_GND += comp_LED33['2']
    p_GND += comp_LED43['2']
    p_GND += comp_LED53['2']
    p_GND += comp_LED63['2']
    p_GND += comp_LED73['2']
    p_GND += comp_LED83['2']


module_BACKLIGHT.tag = 'SHEET_BACKLIGHT'


# ==========================================================================
# Корневой лист
# ==========================================================================
@SubCircuit
def build_root():
    """
    Корневой лист проекта.
    project: Climate Control Niva Travel
    version: 2.2
    """

    # ======================================================================
    # Корневые компоненты
    # ======================================================================
    # type:        TYPE_C_100NF
    # description: фильтр VDDA
    # tag:         C10
    comp_C10 = Part('Device', 'C', ref='C10', tag='C10', value='100nF', footprint='Capacitor_SMD:C_0603_1608Metric')
    comp_C10.fields['Type'] = 'Ceramic'
    comp_C10.fields['Dielectric'] = 'X7R'
    comp_C10.fields['Description'] = 'фильтр VDDA'

    # type:        TYPE_C_100NF
    # description: сброс МК
    # tag:         C21
    comp_C21 = Part('Device', 'C', ref='C21', tag='C21', value='100nF', footprint='Capacitor_SMD:C_0603_1608Metric')
    comp_C21.fields['Type'] = 'Ceramic'
    comp_C21.fields['Dielectric'] = 'X7R'
    comp_C21.fields['Description'] = 'сброс МК'

    # type:        TYPE_C_10UF_6.3V
    # description: выход стабилизатора 3,3В
    # tag:         C5
    comp_C5 = Part('Device', 'C', ref='C5', tag='C5', value='10uF', footprint='Capacitor_SMD:C_0805_2012Metric')
    comp_C5.fields['Voltage'] = '6.3V'
    comp_C5.fields['Type'] = 'Ceramic'
    comp_C5.fields['Dielectric'] = 'X7R'
    comp_C5.fields['Description'] = 'выход стабилизатора 3,3В'

    # type:        TYPE_C_10UF_6.3V
    # description: шина 3,3В (общий накопитель
    # tag:         C6
    comp_C6 = Part('Device', 'C', ref='C6', tag='C6', value='10uF', footprint='Capacitor_SMD:C_0805_2012Metric')
    comp_C6.fields['Voltage'] = '6.3V'
    comp_C6.fields['Type'] = 'Ceramic'
    comp_C6.fields['Dielectric'] = 'X7R'
    comp_C6.fields['Description'] = 'шина 3,3В (общий накопитель'

    # type:        TYPE_C_100NF
    # description: развязка VDD_1
    # tag:         C7
    comp_C7 = Part('Device', 'C', ref='C7', tag='C7', value='100nF', footprint='Capacitor_SMD:C_0603_1608Metric')
    comp_C7.fields['Type'] = 'Ceramic'
    comp_C7.fields['Dielectric'] = 'X7R'
    comp_C7.fields['Description'] = 'развязка VDD_1'

    # type:        TYPE_C_100NF
    # description: развязка VDD_2
    # tag:         C8
    comp_C8 = Part('Device', 'C', ref='C8', tag='C8', value='100nF', footprint='Capacitor_SMD:C_0603_1608Metric')
    comp_C8.fields['Type'] = 'Ceramic'
    comp_C8.fields['Dielectric'] = 'X7R'
    comp_C8.fields['Description'] = 'развязка VDD_2'

    # type:        TYPE_C_100NF
    # description: развязка VDD_3
    # tag:         C9
    comp_C9 = Part('Device', 'C', ref='C9', tag='C9', value='100nF', footprint='Capacitor_SMD:C_0603_1608Metric')
    comp_C9.fields['Type'] = 'Ceramic'
    comp_C9.fields['Dielectric'] = 'X7R'
    comp_C9.fields['Description'] = 'развязка VDD_3'

    # type:        TYPE_L_ФЕРРИТ600ОМ@100МГЦПОПИТАНИЮVDDA
    # description: Феррит 600Ом@100МГц по питанию VDDA
    # tag:         FB1
    comp_FB1 = Part('Device', 'L', ref='FB1', tag='FB1', value='Феррит 600Ом@100МГц по питанию VDDA', footprint='Inductor_SMD:L_0805_2012Metric')
    comp_FB1.fields['Description'] = 'Феррит 600Ом@100МГц по питанию VDDA'

    # type:        TYPE_CONN01X04_SWD-ОТЛАДКА1X04
    # description: SWD-отладка 1x04
    # tag:         J2
    comp_J2 = Part('Connector_Generic', 'Conn_01x04', ref='J2', tag='J2', value='SWD-отладка 1x04', footprint='Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical')
    comp_J2.fields['Description'] = 'SWD-отладка 1x04'

    # type:        TYPE_R_10K
    # description: сброс МК
    # tag:         R1
    comp_R1 = Part('Device', 'R', ref='R1', tag='R1', value='10k', footprint='Resistor_SMD:R_0603_1608Metric')
    comp_R1.fields['Power'] = '0.1W'
    comp_R1.fields['Tolerance'] = '1%'
    comp_R1.fields['Description'] = 'сброс МК'

    # type:        TYPE_R_10K
    # description: к GND
    # tag:         R2
    comp_R2 = Part('Device', 'R', ref='R2', tag='R2', value='10k', footprint='Resistor_SMD:R_0603_1608Metric')
    comp_R2.fields['Power'] = '0.1W'
    comp_R2.fields['Tolerance'] = '1%'
    comp_R2.fields['Description'] = 'к GND'

    # type:        TYPE_STM32F103RC-D-ETX_STM32F103RCT6
    # description: LQFP-64
    # tag:         U1
    comp_U1 = Part('MCU_ST_STM32F1', 'STM32F103R_C-D-E_Tx', ref='U1', tag='U1', value='STM32F103RCT6', footprint='Package_QFP:LQFP-64_10x10mm_P0.5mm')
    comp_U1.fields['Description'] = 'LQFP-64'

    # ======================================================================
    # Цепи корневого листа
    # ======================================================================
    # Цепь VCC_12V: Силовая шина +12В после фильтра помех L1, с TVS D2 и конденсаторами
    # attributes: type=POWER, voltage_level=12.0V, current_max=15A, spice_simulation={'model_stimulus': 'DC 12.0', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_VCC_12V = Net('VCC_12V')

    # Цепь VCC_5V: Внутреннее стабилизированное питание +5В (логика/питание стабилизатора 3,3В)
    # attributes: type=POWER, voltage_level=5.0V, current_max=0.5A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_VCC_5V = Net('VCC_5V')

    # Цепь VCC_3V3: Логическое питание +3,3В микроконтроллера и фронт-панели
    # attributes: type=POWER, voltage_level=3.3V, current_max=0.3A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_VCC_3V3 = Net('VCC_3V3')
    net_VCC_3V3 += comp_C5['1']
    net_VCC_3V3 += comp_C6['1']
    net_VCC_3V3 += comp_C7['1']
    net_VCC_3V3 += comp_C8['1']
    net_VCC_3V3 += comp_C9['1']
    net_VCC_3V3 += comp_U1['48']
    net_VCC_3V3 += comp_U1['64']
    net_VCC_3V3 += comp_U1['1']
    net_VCC_3V3 += comp_FB1['1']
    net_VCC_3V3 += comp_R1['1']
    net_VCC_3V3 += comp_J2['1']
    net_VCC_3V3 += comp_U1['19']
    net_VCC_3V3 += comp_U1['32']

    # Цепь VDDA_3V3: Аналоговое питание АЦП (через феррит FB1 от VCC_3V3)
    # attributes: type=POWER, voltage_level=3.3V, current_max=0.3A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_VDDA_3V3 = Net('VDDA_3V3')
    net_VDDA_3V3 += comp_FB1['2']
    net_VDDA_3V3 += comp_C10['1']
    net_VDDA_3V3 += comp_U1['13']

    # Цепь GND: Общий провод (кузов автомобиля)
    # attributes: type=GND, voltage_level=0V, current_max=15A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_GND = Net('GND')
    net_GND += comp_U1['47']
    net_GND += comp_U1['63']
    net_GND += comp_C5['2']
    net_GND += comp_C6['2']
    net_GND += comp_C7['2']
    net_GND += comp_C8['2']
    net_GND += comp_C9['2']
    net_GND += comp_C10['2']
    net_GND += comp_C21['2']
    net_GND += comp_R2['2']
    net_GND += comp_J2['4']
    net_GND += comp_U1['12']
    net_GND += comp_U1['18']
    net_GND += comp_U1['31']

    # Цепь NRST: Сброс МК (RC-цепь)
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_NRST = Net('NRST')
    net_NRST += comp_U1['7']
    net_NRST += comp_R1['2']
    net_NRST += comp_C21['1']

    # Цепь BOOT0: Выбор режима загрузки: подтяжка к GND (загрузка из основной Flash)
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_BOOT0 = Net('BOOT0')
    net_BOOT0 += comp_R2['1']
    net_BOOT0 += comp_U1['60']

    # Цепь SWDIO: Отладочный интерфейс SWD: данные
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_SWDIO = Net('SWDIO')
    net_SWDIO += comp_J2['2']
    net_SWDIO += comp_U1['46']

    # Цепь SWCLK: Отладочный интерфейс SWD: тактирование
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_SWCLK = Net('SWCLK')
    net_SWCLK += comp_J2['3']
    net_SWCLK += comp_U1['49']

    # Цепь BTN_DEFROST_GLASS: Кнопка: воздух на стекло
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_BTN_DEFROST_GLASS = Net('BTN_DEFROST_GLASS')
    net_BTN_DEFROST_GLASS += comp_U1['29']

    # Цепь BTN_FACE: Кнопка: воздух в лицо
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_BTN_FACE = Net('BTN_FACE')
    net_BTN_FACE += comp_U1['30']

    # Цепь BTN_FEET: Кнопка: воздух в ноги
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_BTN_FEET = Net('BTN_FEET')
    net_BTN_FEET += comp_U1['33']

    # Цепь BTN_DRY_GLASS: Кнопка: сушка стекла
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_BTN_DRY_GLASS = Net('BTN_DRY_GLASS')
    net_BTN_DRY_GLASS += comp_U1['34']

    # Цепь BTN_AC: Кнопка: кондиционер
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_BTN_AC = Net('BTN_AC')
    net_BTN_AC += comp_U1['35']

    # Цепь BTN_RECIRC: Кнопка: рециркуляция
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_BTN_RECIRC = Net('BTN_RECIRC')
    net_BTN_RECIRC += comp_U1['36']

    # Цепь LED_DEFROST_GLASS_DRV: Индикатор кнопки: воздух на стекло (управление, активный низкий уровень)
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_LED_DEFROST_GLASS_DRV = Net('LED_DEFROST_GLASS_DRV')
    net_LED_DEFROST_GLASS_DRV += comp_U1['50']

    # Цепь LED_FACE_DRV: Индикатор кнопки: воздух в лицо (управление, активный низкий уровень)
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_LED_FACE_DRV = Net('LED_FACE_DRV')
    net_LED_FACE_DRV += comp_U1['55']

    # Цепь LED_FEET_DRV: Индикатор кнопки: воздух в ноги (управление, активный низкий уровень)
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_LED_FEET_DRV = Net('LED_FEET_DRV')
    net_LED_FEET_DRV += comp_U1['56']

    # Цепь LED_DRY_GLASS_DRV: Индикатор кнопки: сушка стекла (управление, активный низкий уровень)
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_LED_DRY_GLASS_DRV = Net('LED_DRY_GLASS_DRV')
    net_LED_DRY_GLASS_DRV += comp_U1['3']

    # Цепь LED_AC_DRV: Индикатор кнопки: кондиционер (управление, активный низкий уровень)
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_LED_AC_DRV = Net('LED_AC_DRV')
    net_LED_AC_DRV += comp_U1['4']

    # Цепь LED_RECIRC_DRV: Индикатор кнопки: рециркуляция (управление, активный низкий уровень)
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_LED_RECIRC_DRV = Net('LED_RECIRC_DRV')
    net_LED_RECIRC_DRV += comp_U1['10']

    # Цепь TEMP_SET_ADC: АЦП задания температуры (потенциометр, 2-проводное включение, внутренний коннектор J_POT)
    # attributes: type=ANALOG_SIGNAL, voltage_level=0..3.3V, current_max=0.005A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_TEMP_SET_ADC = Net('TEMP_SET_ADC')
    net_TEMP_SET_ADC += comp_U1['14']

    # Цепь FAN_SEL_ADC: АЦП выбора режима/скорости вентилятора (галлетник AUTO,0..4, резисторный код)
    # attributes: type=ANALOG_SIGNAL, voltage_level=0..3.3V, current_max=0.005A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_FAN_SEL_ADC = Net('FAN_SEL_ADC')
    net_FAN_SEL_ADC += comp_U1['15']

    # Цепь NTC_CABIN: Температура воздуха в салоне (NTC на плате в трубе продувки)
    # attributes: type=ANALOG_SIGNAL, voltage_level=0..3.3V, current_max=0.005A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_NTC_CABIN = Net('NTC_CABIN')
    net_NTC_CABIN += comp_U1['16']

    # Цепь NTC_HEAT_W: Датчик патрубка отопителя: узел линии на разъёме
    # attributes: type=ANALOG_SIGNAL, voltage_level=0..3.3V, current_max=0.005A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_NTC_HEAT_W = Net('NTC_HEAT_W')

    # Цепь NTC_HEAT: Датчик патрубка отопителя: сигнал на АЦП (после защитного резистора)
    # attributes: type=ANALOG_SIGNAL, voltage_level=0..3.3V, current_max=0.005A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_NTC_HEAT = Net('NTC_HEAT')
    net_NTC_HEAT += comp_U1['17']

    # Цепь SOLAR_RAW: Выход датчика солнечной радиации (0..5В)
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_SOLAR_RAW = Net('SOLAR_RAW')

    # Цепь SOLAR_ADC: Сигнал солнечной радиации после делителя 5В->3,3В на АЦП
    # attributes: type=ANALOG_SIGNAL, voltage_level=0..3.3V, current_max=0.005A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_SOLAR_ADC = Net('SOLAR_ADC')
    net_SOLAR_ADC += comp_U1['20']

    # Цепь COND_RAW: Выход датчика конденсата на стекле (0..5В)
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_COND_RAW = Net('COND_RAW')

    # Цепь COND_ADC: Сигнал конденсата после делителя 5В->3,3В на АЦП
    # attributes: type=ANALOG_SIGNAL, voltage_level=0..3.3V, current_max=0.005A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_COND_ADC = Net('COND_ADC')
    net_COND_ADC += comp_U1['21']

    # Цепь MOTOR_1_A: Заслонка 1: выход А мостового драйвера к моторедуктору
    # attributes: type=PWM_POWER, voltage_level=0..12.0V, current_max=5.0A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_MOTOR_1_A = Net('MOTOR_1_A')

    # Цепь MOTOR_1_B: Заслонка 1: выход B мостового драйвера к моторедуктору
    # attributes: type=PWM_POWER, voltage_level=0..12.0V, current_max=5.0A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_MOTOR_1_B = Net('MOTOR_1_B')

    # Цепь FB_M1: Заслонка 1: сигнал ОС после делителя 5В->3,3В на АЦП
    # attributes: type=ANALOG_SIGNAL, voltage_level=0..3.3V, current_max=0.005A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_FB_M1 = Net('FB_M1')
    net_FB_M1 += comp_U1['22']

    # Цепь M1_IN1: Заслонка 1: вход IN1 драйвера
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_M1_IN1 = Net('M1_IN1')
    net_M1_IN1 += comp_U1['42']

    # Цепь M1_IN2: Заслонка 1: вход IN2 драйвера
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_M1_IN2 = Net('M1_IN2')
    net_M1_IN2 += comp_U1['43']

    # Цепь MOTOR_2_A: Заслонка 2: выход А мостового драйвера к моторедуктору
    # attributes: type=PWM_POWER, voltage_level=0..12.0V, current_max=5.0A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_MOTOR_2_A = Net('MOTOR_2_A')

    # Цепь MOTOR_2_B: Заслонка 2: выход B мостового драйвера к моторедуктору
    # attributes: type=PWM_POWER, voltage_level=0..12.0V, current_max=5.0A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_MOTOR_2_B = Net('MOTOR_2_B')

    # Цепь FB_M2_RAW: Заслонка 2: выход потенциометра положения (0..5В)
    # attributes: type=ANALOG_SIGNAL, voltage_level=0..3.3V, current_max=0.005A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_FB_M2_RAW = Net('FB_M2_RAW')

    # Цепь FB_M2: Заслонка 2: сигнал ОС после делителя 5В->3,3В на АЦП
    # attributes: type=ANALOG_SIGNAL, voltage_level=0..3.3V, current_max=0.005A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_FB_M2 = Net('FB_M2')
    net_FB_M2 += comp_U1['23']

    # Цепь M2_IN1: Заслонка 2: вход IN1 драйвера
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_M2_IN1 = Net('M2_IN1')
    net_M2_IN1 += comp_U1['44']

    # Цепь M2_IN2: Заслонка 2: вход IN2 драйвера
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_M2_IN2 = Net('M2_IN2')
    net_M2_IN2 += comp_U1['45']

    # Цепь MOTOR_3_A: Заслонка 3: выход А мостового драйвера к моторедуктору
    # attributes: type=PWM_POWER, voltage_level=0..12.0V, current_max=5.0A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_MOTOR_3_A = Net('MOTOR_3_A')

    # Цепь MOTOR_3_B: Заслонка 3: выход B мостового драйвера к моторедуктору
    # attributes: type=PWM_POWER, voltage_level=0..12.0V, current_max=5.0A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_MOTOR_3_B = Net('MOTOR_3_B')

    # Цепь FB_M3_RAW: Заслонка 3: выход потенциометра положения (0..5В)
    # attributes: type=ANALOG_SIGNAL, voltage_level=0..3.3V, current_max=0.005A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_FB_M3_RAW = Net('FB_M3_RAW')

    # Цепь FB_M3: Заслонка 3: сигнал ОС после делителя 5В->3,3В на АЦП
    # attributes: type=ANALOG_SIGNAL, voltage_level=0..3.3V, current_max=0.005A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_FB_M3 = Net('FB_M3')
    net_FB_M3 += comp_U1['26']

    # Цепь M3_IN1: Заслонка 3: вход IN1 драйвера
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_M3_IN1 = Net('M3_IN1')
    net_M3_IN1 += comp_U1['57']

    # Цепь M3_IN2: Заслонка 3: вход IN2 драйвера
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_M3_IN2 = Net('M3_IN2')
    net_M3_IN2 += comp_U1['58']

    # Цепь MOTOR_4_A: Заслонка 4: выход А мостового драйвера к моторедуктору
    # attributes: type=PWM_POWER, voltage_level=0..12.0V, current_max=5.0A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_MOTOR_4_A = Net('MOTOR_4_A')

    # Цепь MOTOR_4_B: Заслонка 4: выход B мостового драйвера к моторедуктору
    # attributes: type=PWM_POWER, voltage_level=0..12.0V, current_max=5.0A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_MOTOR_4_B = Net('MOTOR_4_B')

    # Цепь FB_M4_RAW: Заслонка 4: выход потенциометра положения (0..5В)
    # attributes: type=ANALOG_SIGNAL, voltage_level=0..3.3V, current_max=0.005A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_FB_M4_RAW = Net('FB_M4_RAW')

    # Цепь FB_M4: Заслонка 4: сигнал ОС после делителя 5В->3,3В на АЦП
    # attributes: type=ANALOG_SIGNAL, voltage_level=0..3.3V, current_max=0.005A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_FB_M4 = Net('FB_M4')
    net_FB_M4 += comp_U1['27']

    # Цепь M4_IN1: Заслонка 4: вход IN1 драйвера
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_M4_IN1 = Net('M4_IN1')
    net_M4_IN1 += comp_U1['59']

    # Цепь M4_IN2: Заслонка 4: вход IN2 драйвера
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_M4_IN2 = Net('M4_IN2')
    net_M4_IN2 += comp_U1['2']

    # Цепь FAN_PWM_CTL: Внутренний ШИМ-сигнал управления основным вентилятором с МК
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_FAN_PWM_CTL = Net('FAN_PWM_CTL')
    net_FAN_PWM_CTL += comp_U1['41']

    # Цепь HEAT_FAN_PWM_CTL: Внешний ШИМ-выход на автомобильный разъем к штатному силовому модулю вентилятора
    # attributes: type=PWM_POWER, voltage_level=0..12.0V, current_max=0.5A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_HEAT_FAN_PWM_CTL = Net('HEAT_FAN_PWM_CTL')

    # Цепь M_FAN_CTL: Управление мини-вентилятором продувки датчика
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_M_FAN_CTL = Net('M_FAN_CTL')
    net_M_FAN_CTL += comp_U1['11']

    # Цепь AC_CTL: Управление транзистором запроса кондиционера
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_AC_CTL = Net('AC_CTL')
    net_AC_CTL += comp_U1['28']

    # Цепь AC_REQ_OUT: Линия запроса кондиционера +12В к J1:31 (вход ЭБУ двигателя)
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_AC_REQ_OUT = Net('AC_REQ_OUT')

    # Цепь ILLUM_IN_RAW: Вход внешней подсветки прибора (+12В габаритов)
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_ILLUM_IN_RAW = Net('ILLUM_IN_RAW')

    # Цепь ILLUM_SENSE: Сигнал подсветки после делителя на вход МК
    # attributes: type=ANALOG_SIGNAL, voltage_level=0..3.3V, current_max=0.005A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_ILLUM_SENSE = Net('ILLUM_SENSE')
    net_ILLUM_SENSE += comp_U1['8']

    # Цепь CAN_TX: CAN: передача от МК к трансиверу
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_CAN_TX = Net('CAN_TX')
    net_CAN_TX += comp_U1['62']

    # Цепь CAN_RX: CAN: приём от трансивера к МК
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_CAN_RX = Net('CAN_RX')
    net_CAN_RX += comp_U1['61']

    # Цепь CANH: CAN: шина High (J1:25)
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_CANH = Net('CANH')

    # Цепь CANL: CAN: шина Low (J1:26)
    # attributes: type=DIGITAL_SIGNAL, voltage_level=3.3V, current_max=0.02A, spice_simulation={'model_stimulus': '', 'parasitic_r_ohm': 0.05, 'parasitic_l_h': '10n'}
    net_CANL = Net('CANL')

    # ======================================================================
    # ВНИМАНИЕ: автосозданные цепи
    # Эти имена объявлены как порты подстраниц, но
    # отсутствуют в main.yaml->root_page->nets.
    # Вероятно, забыли объявить цепь. Проверьте YAML.
    # ======================================================================
    # 'FB_M1_RAW' экспонируют листы: X_PWR
    net_FB_M1_RAW = Net('FB_M1_RAW')

    # ======================================================================
    # Иерархические подстраницы (с передачей портов)
    # ======================================================================
    # X_CAN: Модуль CAN
    #     file: sheets/can_bus.kicad_sch
    module_CAN(
        net_VCC_5V,
        net_GND,
        net_CAN_TX,
        net_CAN_RX,
        net_CANH,
        net_CANL,
    )

    # X_PWR: Модуль PWR
    #     file: sheets/power_supply.kicad_sch
    module_PWR(
        net_VCC_12V,
        net_VCC_5V,
        net_VCC_3V3,
        net_GND,
        net_NTC_HEAT_W,
        net_SOLAR_RAW,
        net_COND_RAW,
        net_MOTOR_1_A,
        net_MOTOR_1_B,
        net_MOTOR_2_A,
        net_MOTOR_2_B,
        net_FB_M2_RAW,
        net_MOTOR_3_A,
        net_MOTOR_3_B,
        net_FB_M3_RAW,
        net_MOTOR_4_A,
        net_MOTOR_4_B,
        net_FB_M4_RAW,
        net_AC_REQ_OUT,
        net_ILLUM_IN_RAW,
        net_CANH,
        net_CANL,
        net_HEAT_FAN_PWM_CTL,
        net_FB_M1_RAW,
    )

    # X_UI: Модуль UI
    #     file: sheets/user_interface.kicad_sch
    module_UI(
        net_VCC_3V3,
        net_GND,
        net_BTN_DEFROST_GLASS,
        net_BTN_FACE,
        net_BTN_FEET,
        net_BTN_DRY_GLASS,
        net_BTN_AC,
        net_BTN_RECIRC,
        net_LED_DEFROST_GLASS_DRV,
        net_LED_FACE_DRV,
        net_LED_FEET_DRV,
        net_LED_DRY_GLASS_DRV,
        net_LED_AC_DRV,
        net_LED_RECIRC_DRV,
        net_TEMP_SET_ADC,
        net_FAN_SEL_ADC,
        net_NTC_CABIN,
        net_ILLUM_IN_RAW,
        net_ILLUM_SENSE,
    )

    # X_SEN_CABIN: Модуль SEN_CABIN
    #     file: sheets/cabin_sensor.kicad_sch
    module_SEN_CABIN(
        net_VCC_12V,
        net_GND,
        net_NTC_CABIN,
        net_M_FAN_CTL,
    )

    # X_SEN_HEAT: Модуль SEN_HEAT
    #     file: sheets/heating_sensor.kicad_sch
    module_SEN_HEAT(
        net_VCC_3V3,
        net_GND,
        net_NTC_HEAT_W,
        net_NTC_HEAT,
    )

    # X_SEN_SOLAR: Модуль SEN_SOLAR
    #     file: sheets/solar_sensor.kicad_sch
    module_SEN_SOLAR(
        net_GND,
        net_SOLAR_RAW,
        net_SOLAR_ADC,
    )

    # X_SEN_COND: Модуль SEN_COND
    #     file: sheets/condensate_sensor.kicad_sch
    module_SEN_COND(
        net_GND,
        net_COND_RAW,
        net_COND_ADC,
    )

    # X_OUT: Модуль OUT
    #     file: sheets/power_outputs.kicad_sch
    module_OUT(
        net_VCC_12V,
        net_GND,
        net_FAN_PWM_CTL,
        net_AC_CTL,
        net_AC_REQ_OUT,
        net_HEAT_FAN_PWM_CTL,
    )

    # X_ACT: Модуль ACT
    #     file: sheets/actuators.kicad_sch
    module_ACT(
        net_VCC_12V,
        net_GND,
        net_MOTOR_1_A,
        net_MOTOR_1_B,
        net_FB_M1,
        net_M1_IN1,
        net_M1_IN2,
        net_MOTOR_2_A,
        net_MOTOR_2_B,
        net_FB_M2_RAW,
        net_FB_M2,
        net_M2_IN1,
        net_M2_IN2,
        net_MOTOR_3_A,
        net_MOTOR_3_B,
        net_FB_M3_RAW,
        net_FB_M3,
        net_M3_IN1,
        net_M3_IN2,
        net_MOTOR_4_A,
        net_MOTOR_4_B,
        net_FB_M4_RAW,
        net_FB_M4,
        net_M4_IN1,
        net_M4_IN2,
    )

    # X_BACKLIGHT: Модуль радиальной фоновой подсветки шкал ручек управления
    #     file: sheets/backlight.kicad_sch
    module_BACKLIGHT(
        net_ILLUM_IN_RAW,
        net_GND,
    )


build_root.tag = 'ROOT'


# ==========================================================================
# Точка входа
# ==========================================================================
if __name__ == '__main__':
    import shutil
    from pathlib import Path

    BASE_DIR = Path(__file__).resolve().parent
    SCHEMATIC_DIR = BASE_DIR
    NETLIST_DIR = BASE_DIR / '.netlist_tmp'
    ROOT_SCH = BASE_DIR / 'climate_control_niva_travel.kicad_sch'

    # Очистка старых .kicad_sch в корне (не трогает исходники)
    for _sch in SCHEMATIC_DIR.glob("*.kicad_sch"):
        try:
            _sch.unlink()
        except OSError:
            pass

    if NETLIST_DIR.is_dir():
        shutil.rmtree(NETLIST_DIR)
    NETLIST_DIR.mkdir(parents=True, exist_ok=True)

    build_root()
    print('=== Схема собрана ===', flush=True)

    _netlist = NETLIST_DIR / "MAIN_ROOT.net"
    generate_netlist(file=str(_netlist))
    print(f'-> Нетлист: {_netlist}', flush=True)

   # generate_schematic(
   #     filepath=str(SCHEMATIC_DIR),
   #     top_name='climate_control_niva_travel',
   #     flatness=0.0,
   #     auto_stub=True,
   # )

    print(f'-> Все .kicad_sch в: {SCHEMATIC_DIR}', flush=True)