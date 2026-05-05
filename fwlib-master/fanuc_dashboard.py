# -*- coding: utf-8 -*-
import ctypes
import os
import socket
import sys
import time
from datetime import datetime

sys.stdout.reconfigure(encoding='utf-8')

# =========================
# CONFIG
# =========================
IP           = b"172.16.4.89"
PORT         = 8193
MACHINE_NAME = "FANUC CNC - MC2469"
MACHINE_ID   = "MC-001"
LOCATION     = "Shop Floor - Line 1"
MAX_SPINDLE  = 6000
MAX_FEED     = 50000

PART_MAP = {
    87164210: {"part_name": "Bracket-A", "operation": "OP-20"}
}

# =========================
# LOAD DLL
# =========================
dll_path = os.path.join(os.getcwd(), "Fwlib32.dll")
if not os.path.exists(dll_path):
    dll_path = os.path.join(os.getcwd(), "fwlib32.dll")

fwlib = ctypes.cdll.LoadLibrary(dll_path)
fwlib.cnc_allclibhndl3.argtypes = [
    ctypes.c_char_p, ctypes.c_ushort,
    ctypes.c_long, ctypes.POINTER(ctypes.c_ushort),
]
fwlib.cnc_allclibhndl3.restype = ctypes.c_short
fwlib.cnc_freelibhndl.argtypes = [ctypes.c_ushort]
fwlib.cnc_freelibhndl.restype  = ctypes.c_short

# =========================
# TCP CHECK
# =========================
def tcp_port_open(ip, port, timeout=3):
    try:
        with socket.create_connection((ip.decode(), port), timeout=timeout):
            return True
    except OSError:
        return False

if not tcp_port_open(IP, PORT):
    print(f"[ERROR] Cannot reach {IP.decode()}:{PORT}")
    exit()

handle = ctypes.c_ushort()
ret = fwlib.cnc_allclibhndl3(IP, PORT, 10, ctypes.byref(handle))
if ret != 0:
    print(f"[ERROR] Connection Failed! Code: {ret}")
    exit()

print(f"[OK] Connected to {MACHINE_NAME}")

# =========================
# STRUCTURES
# =========================
class ODBST(ctypes.Structure):
    _fields_ = [
        ("dummy",     ctypes.c_short * 2),
        ("aut",       ctypes.c_short),
        ("run",       ctypes.c_short),
        ("motion",    ctypes.c_short),
        ("mstb",      ctypes.c_short),
        ("emergency", ctypes.c_short),
        ("alarm",     ctypes.c_short),
        ("edit",      ctypes.c_short),
    ]

class ODBSPEED(ctypes.Structure):
    _fields_ = [
        ("datano", ctypes.c_short),
        ("type",   ctypes.c_short),
        ("data",   ctypes.c_long),
    ]

class ODBPRO(ctypes.Structure):
    _fields_ = [
        ("dummy", ctypes.c_short),
        ("data",  ctypes.c_long),
    ]

class ODBALMMSG(ctypes.Structure):
    _fields_ = [
        ("alm_no", ctypes.c_short),
        ("type",   ctypes.c_short),
        ("axis",   ctypes.c_short),
        ("msg",    ctypes.c_char * 64),
    ]

class ODBSEQ(ctypes.Structure):
    _fields_ = [
        ("dummy", ctypes.c_short),
        ("data",  ctypes.c_long),
    ]

class IODBPSD(ctypes.Structure):
    _fields_ = [
        ("datano", ctypes.c_short),
        ("type",   ctypes.c_short),
        ("data",   ctypes.c_long),
    ]

class IODBOVR(ctypes.Structure):
    _fields_ = [
        ("datano", ctypes.c_short),
        ("type",   ctypes.c_short),
        ("data",   ctypes.c_short * 8),
    ]

# ── Axis - same structure jo pehle kaam kar raha tha ──
class ODBAXIS(ctypes.Structure):
    _fields_ = [
        ("dummy", ctypes.c_short),
        ("type",  ctypes.c_short),
        ("data",  ctypes.c_long * 8),
    ]

# =========================
# MAPS
# =========================
status_map = {0: "STOP", 1: "HOLD", 2: "START", 3: "RUNNING"}
mode_map   = {
    0: "MDI", 1: "AUTO", 2: "AUTO",
    3: "EDIT", 4: "JOG", 5: "JOG",
    6: "HANDLE", 7: "HANDLE"
}
axis_names = ["X", "Y", "Z", "B"]

# =========================
# STATE TRACKING
# =========================
cycle_start      = None
cycle_running    = False
cycle_start_str  = ""
cycle_end_str    = ""
last_cycle_time  = 0
part_count_local = 0
runtime          = 0
downtime         = 0

def clear():
    os.system('cls' if os.name == 'nt' else 'clear')

# =========================
# GET AXIS - pehle wala method
# =========================
def get_axis_positions():
    positions = {"X": 0.0, "Y": 0.0, "Z": 0.0, "B": 0.0}

    ax  = ODBAXIS()
    ret = fwlib.cnc_machine(handle, ctypes.byref(ax))
    if ret == 0:
        for i in range(4):
            positions[axis_names[i]] = ax.data[i] / 1000.0
        return positions

    ax2  = ODBAXIS()
    ret2 = fwlib.cnc_absolute(
        handle,
        ctypes.c_short(-1),
        ctypes.c_short(ctypes.sizeof(ax2)),
        ctypes.byref(ax2)
    )
    if ret2 == 0:
        for i in range(4):
            positions[axis_names[i]] = ax2.data[i] / 1000.0

    return positions

# =========================
# HELPERS
# =========================
def get_sequence_number():
    seq = ODBSEQ()
    ret = fwlib.cnc_rdseqnum(handle, ctypes.byref(seq))
    return seq.data if ret == 0 else 0

def get_parts_count():
    psd = IODBPSD()
    ret = fwlib.cnc_rdparam(handle, 6711, 0, ctypes.sizeof(psd), ctypes.byref(psd))
    return psd.data if ret == 0 else "N/A"

def get_cycle_time():
    psd = IODBPSD()
    ret = fwlib.cnc_rdparam(handle, 6757, 0, ctypes.sizeof(psd), ctypes.byref(psd))
    return psd.data if ret == 0 else 0

def get_run_time():
    psd = IODBPSD()
    ret = fwlib.cnc_rdparam(handle, 6750, 0, ctypes.sizeof(psd), ctypes.byref(psd))
    return psd.data if ret == 0 else 0

def get_feed_override():
    try:
        ovr = IODBOVR()
        ret = fwlib.cnc_rdopnlsgnl(handle, 4, ctypes.byref(ovr))
        return ovr.data[0] if ret == 0 else "N/A"
    except:
        return "N/A"

def get_spindle_override():
    try:
        ovr = IODBOVR()
        ret = fwlib.cnc_rdopnlsgnl(handle, 8, ctypes.byref(ovr))
        return ovr.data[0] if ret == 0 else "N/A"
    except:
        return "N/A"

def format_time(seconds):
    try:
        seconds = int(seconds)
        h = seconds // 3600
        m = (seconds % 3600) // 60
        s = seconds % 60
        return f"{h}h {m}m {s}s"
    except:
        return "N/A"

# =========================
# MAIN LOOP
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

        positions   = get_axis_positions()
        seq_no      = get_sequence_number()
        parts_count = get_parts_count()
        cycle_time  = get_cycle_time()
        run_time    = get_run_time()
        feed_ovr    = get_feed_override()
        spindle_ovr = get_spindle_override()

        current_status = status_map.get(status.run, "UNKNOWN")
        mode           = mode_map.get(status.aut, "UNKNOWN")
        now            = time.time()

        # Cycle Logic
        if current_status == "RUNNING" and spindle.data > 0:
            runtime += 2
            if not cycle_running:
                cycle_start     = now
                cycle_start_str = datetime.now().strftime("%H:%M:%S")
                cycle_running   = True
        else:
            downtime += 2
            if cycle_running:
                cycle_end_str    = datetime.now().strftime("%H:%M:%S")
                last_cycle_time  = round(now - cycle_start, 2)
                part_count_local += 1
                cycle_running    = False

        # Alarm
        alarm_msg  = ODBALMMSG()
        alarm_text = "NO ALARM"
        alarm_no   = 0
        try:
            ret = fwlib.cnc_rdalmmsg(handle, 1, ctypes.byref(alarm_msg))
            if ret == 0:
                alarm_no   = alarm_msg.alm_no
                alarm_text = alarm_msg.msg.decode(errors="ignore").strip() or "NO ALARM"
        except:
            alarm_text = "Not Supported"

        # Part Info
        part_info   = PART_MAP.get(prog.data, {})
        part_name   = part_info.get("part_name", "UNKNOWN")
        operation   = part_info.get("operation", "UNKNOWN")

        # Calculations
        spindle_pct = min((spindle.data / MAX_SPINDLE) * 100, 100) if spindle.data else 0
        feed_pct    = min((feed.data / MAX_FEED) * 100, 100) if feed.data else 0
        utilization = (runtime / (runtime + downtime) * 100) if (runtime + downtime) else 0

        # Machine State
        if status.emergency:
            machine_state = "EMERGENCY [!!!]"
        elif status.alarm:
            machine_state = "ALARM [!]"
        elif current_status == "RUNNING":
            machine_state = "RUNNING [ON]"
        elif current_status == "HOLD":
            machine_state = "HOLD [~]"
        else:
            machine_state = "IDLE [--]"

        # =========================
        # DISPLAY
        # =========================
        clear()
        print("=======================================================")
        print("          FANUC PRODUCTION DASHBOARD")
        print("=======================================================")
        print(f"  Machine Name   : {MACHINE_NAME}")
        print(f"  Machine ID     : {MACHINE_ID}")
        print(f"  Location       : {LOCATION}")
        print(f"  IP Address     : {IP.decode()}")
        print(f"  Updated At     : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=======================================================")
        print(f"  Machine State  : {machine_state}")
        print(f"  Mode           : {mode}")
        print(f"  Program No     : O{prog.data}")
        print(f"  Sequence No    : N{seq_no:05d}")
        print("-------------------------------------------------------")
        print("  AXIS POSITIONS (Absolute mm)")
        for ax, val in positions.items():
            print(f"    {ax}            : {val:.3f}")
        print("-------------------------------------------------------")
        print(f"  Spindle        : {spindle.data} RPM  ({spindle_pct:.1f}%)  Ovr: {spindle_ovr}%")
        print(f"  Feed           : {feed.data} mm/min  ({feed_pct:.1f}%)  Ovr: {feed_ovr}%")
        print("-------------------------------------------------------")
        print(f"  Part Name      : {part_name}")
        print(f"  Operation      : {operation}")
        print("-------------------------------------------------------")
        print(f"  Parts Count    : {parts_count}  (Machine)")
        print(f"  Cycle Time     : {cycle_time} sec")
        print(f"  Run Time       : {format_time(run_time)}")
        print("-------------------------------------------------------")
        print(f"  Cycle Running  : {'YES' if cycle_running else 'NO'}")
        print(f"  Cycle Start    : {cycle_start_str}")
        print(f"  Cycle End      : {cycle_end_str}")
        print(f"  Last Cycle     : {last_cycle_time} sec")
        print(f"  Local Count    : {part_count_local}")
        print("-------------------------------------------------------")
        print(f"  Runtime        : {runtime} sec")
        print(f"  Downtime       : {downtime} sec")
        print(f"  Utilization    : {utilization:.2f}%")
        print("-------------------------------------------------------")
        print(f"  Alarm          : {'YES' if status.alarm else 'NO'}")
        print(f"  Alarm No       : {alarm_no}")
        print(f"  Alarm Msg      : {alarm_text}")
        print(f"  Emergency      : {'YES' if status.emergency else 'NO'}")
        print("=======================================================")

        time.sleep(2)

except KeyboardInterrupt:
    print("\n[STOP] Stopped by User")

finally:
    fwlib.cnc_freelibhndl(handle)
    print("[OFF] Disconnected from Machine")