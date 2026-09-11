* Поведенческая модель CAN-трансивера MCP2562 для ngspice
* Выводы: TXD RXD CANH CANL STBY VDD VIO GND
.subckt MCP2562 TXD RXD CANH CANL STBY VDD VIO GND

* --- Параметры ключей и источников ---
.model SW_DIG SW(Ron=10 Roff=1Meg Vt=1.4 Vh=0.2)
.model SW_CAN SW(Ron=45 Roff=100k Vt=1.4 Vh=0.2)

* --- Логика STBY (Режим ожидания) ---
* Если STBY = HIGH, трансивер засыпает (ключи CAN-передатчика отключаются)
* Формируем внутренний узел управления передатчиком (TX_EN)
* TX_EN активен (HIGH), только если STBY = LOW
S_STBY_INV VIO TX_EN GND STBY SW_DIG

* --- Передатчик (TXD -> CANH/CANL) ---
* В нормальном режиме CAN-шина подтягивается к VDD/2 (рецессивное состояние ~2.5V)
R_SPLIT1 CANH SPLIT 30k
R_SPLIT2 SPLIT CANL 30k
V_REF    SPLIT GND  {5.0/2.0}

* Идеальные диоды для защиты от обратного тока в ключах CAN
D_CAN1 CANH_DRV CANH D_IDEAL
D_CAN2 CANL CANL_DRV D_IDEAL
.model D_IDEAL D(IS=1e-12 N=0.01)

* Ключи доминантного состояния (когда TXD = LOW и TX_EN = HIGH)
* Для ngspice реализуем логику: ключ замыкается, если разность (TX_EN - TXD) > Vt
S_DOH VM_DRV CANH_DRV TX_EN TXD SW_CAN
S_DOL CANL_DRV GND    TX_EN TXD SW_CAN

* Ограничение напряжения для CANH (подтяжка к VDD при доминантном состоянии)
V_VDD_REG VM_DRV GND 4.0

* --- Приемник (CANH/CANL -> RXD) ---
* Дифференциальный усилитель на источнике, управляемом напряжением (E-source)
* Измеряет V(CANH) - V(CANL). Порог доминантного состояния ~0.9V
E_DIFF V_DIFF GND CANH CANL 1.0

* Компаратор для RXD: если V_DIFF > 0.9V, то RXD прижимается к GND (LOW).
* Если V_DIFF < 0.5V (рецессивное состояние), RXD подтягивается к VIO (HIGH).
S_RXD RXD GND V_DIFF GND SW_DIG
R_RXD_PULL VIO RXD 10k

.ends MCP2562
