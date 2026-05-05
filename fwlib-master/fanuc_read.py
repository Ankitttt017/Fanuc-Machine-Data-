import ctypes
import os
import time
import sys
from datetime import datetime

# =========================
# CONFIG
# =========================
IP = b"172.16.4.89"
PORT = 8193

MAX_SPINDLE = 6000
MAX_FEED = 50000

PART_MAP = {
    87164210: {"part_name": "Bracket-A", "operation": "OP-20"}
}

# =========================
# LOAD DLL
# =========================
fwlib = ctypes.cdll.LoadLibrary(os.path.join(os.getcwd(), "fwlib32.dll"))

handle = ctypes.c_ushort()
fwlib.cnc_allclibhndl3(IP, PORT, 10, ctypes.byref(handle))

# =========================
# STRUCTURES
# =========================
class ODBST(ctypes.Structure):
    _fields_ = [
        ("dummy", ctypes.c_short * 2),
        ("aut", ctypes.c_short),
        ("run", ctypes.c_short),
        ("motion", ctypes.c_short),
        ("mstb", ctypes.c_short),
        ("emergency", ctypes.c_short),
        ("alarm", ctypes.c_short),
        ("edit", ctypes.c_short)
    ]

class ODBSPEED(ctypes.Structure):
    _fields_ = [
        ("datano", ctypes.c_short),
        ("type", ctypes.c_short),
        ("data", ctypes.c_long)
    ]

class ODBPRO(ctypes.Structure):
    _fields_ = [
        ("dummy", ctypes.c_short),
        ("data", ctypes.c_long)
    ]

# 🔥 ALARM STRUCTURE
class ODBALMMSG(ctypes.Structure):
    _fields_ = [
        ("alm_no", ctypes.c_short),
        ("type", ctypes.c_short),
        ("axis", ctypes.c_short),
        ("msg", ctypes.c_char * 64)
    ]

# =========================
# MAPS
# =========================
status_map = {0: "STOP", 1: "HOLD", 2: "START", 3: "RUNNING"}
mode_map = {0: "MDI", 1: "AUTO", 3: "EDIT"}

# =========================
# STATE TRACKING
# =========================
cycle_start = None
cycle_running = False
cycle_start_str = ""
cycle_end_str = ""
last_cycle_time = 0
part_count = 0

runtime = 0
downtime = 0

# =========================
# CLEAR SCREEN
# =========================
def clear():
    os.system('cls' if os.name == 'nt' else 'clear')

# =========================
# LOOP
# =========================
try:
    while True:

        status = ODBST()
        fwlib.cnc_statinfo(handle, ctypes.byref(status))

        spindle = ODBSPEED()
        fwlib.cnc_acts(handle, ctypes.byref(spindle))

        feed = ODBSPEED()
        fwlib.cnc_actf(handle, ctypes.byref(feed))

        prog = ODBPRO()
        fwlib.cnc_rdprgnum(handle, ctypes.byref(prog))

        current_status = status_map.get(status.run, "UNKNOWN")
        mode = mode_map.get(status.aut, "UNKNOWN")

        now = time.time()

        # =========================
        # 🔥 CYCLE LOGIC
        # =========================
        if current_status == "RUNNING" and spindle.data > 0:

            runtime += 2

            if not cycle_running:
                cycle_start = now
                cycle_start_str = datetime.now().strftime("%H:%M:%S")
                cycle_running = True

        else:
            downtime += 2

            if cycle_running:
                cycle_end_str = datetime.now().strftime("%H:%M:%S")
                last_cycle_time = round(now - cycle_start, 2)
                part_count += 1
                cycle_running = False

        # =========================
        # 🔥 ALARM FETCH
        # =========================
        alarm_msg = ODBALMMSG()
        alarm_text = "NO ALARM"
        alarm_no = 0

        try:
            ret = fwlib.cnc_rdalmmsg(handle, 1, ctypes.byref(alarm_msg))
            if ret == 0:
                alarm_no = alarm_msg.alm_no
                alarm_text = alarm_msg.msg.decode(errors="ignore").strip()
        except:
            alarm_text = "Not Supported"

        # =========================
        # PART INFO
        # =========================
        part_info = PART_MAP.get(prog.data, {})
        part_name = part_info.get("part_name", "UNKNOWN")
        operation = part_info.get("operation", "UNKNOWN")

        # =========================
        # CALCULATIONS
        # =========================
        spindle_pct = (spindle.data / MAX_SPINDLE) * 100
        feed_pct = (feed.data / MAX_FEED) * 100

        utilization = (runtime / (runtime + downtime) * 100) if (runtime + downtime) else 0

        # =========================
        # MACHINE STATE
        # =========================
        if status.emergency:
            machine_state = "EMERGENCY 🔴"
        elif status.alarm:
            machine_state = "ALARM ⚠"
        elif current_status == "RUNNING":
            machine_state = "RUNNING 🟢"
        else:
            machine_state = "IDLE 🟡"

        # =========================
        # DISPLAY
        # =========================
        clear()

        print("🚀 FANUC PRODUCTION DASHBOARD")
        print("========================================")
        print(f"Machine State : {machine_state}")
        print(f"Mode          : {mode}")
        print("----------------------------------------")
        print(f"Part Name     : {part_name}")
        print(f"Operation     : {operation}")
        print(f"Program       : {prog.data}")
        print("----------------------------------------")
        print(f"Spindle       : {spindle.data} RPM ({spindle_pct:.2f}%)")
        print(f"Feed          : {feed.data} ({feed_pct:.2f}%)")
        print("----------------------------------------")

        print(f"Cycle Running : {'YES' if cycle_running else 'NO'}")
        print(f"Cycle Start   : {cycle_start_str}")
        print(f"Cycle End     : {cycle_end_str}")
        print(f"Cycle Time    : {last_cycle_time} sec")
        print(f"Production    : {part_count}")

        print("----------------------------------------")
        print(f"Runtime       : {runtime} sec")
        print(f"Downtime      : {downtime} sec")
        print(f"Utilization   : {utilization:.2f}%")

        print("----------------------------------------")
        print(f"Alarm Status  : {'YES' if status.alarm else 'NO'}")
        print(f"Alarm No      : {alarm_no}")
        print(f"Alarm Msg     : {alarm_text}")

        print("----------------------------------------")
        print(f"Emergency     : {'YES' if status.emergency else 'NO'}")
        print("========================================")

        time.sleep(2)

except KeyboardInterrupt:
    print("\n🛑 Stopped")

finally:
    fwlib.cnc_freelibhndl(handle)
    print("🔌 Disconnected")


    #cd C:\Users\IOT1\Desktop\fanuc\fwlib-master
#& "C:\Users\IOT1\AppData\Local\Programs\Python\Python313-32\python.exe" fanuc_read.py