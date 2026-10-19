#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hud_dynamic.py - Returnal dynamic HUD controller.

Automates ShaderToggler Group0 ("Toggle HUD") from live game state read
straight out of the process. Zero keyboard injection: the addon's per-group
toggle byte is written directly in memory.

    HUD visible while ANY trigger is live (hold windows in parentheses):
      combat          EnemyManager aggression states (see --exit-delay)
      health change   UHealthComponent hp float moved (3 s)
      ammo change     UWeaponClip ammo float moved (3 s)
      reloading       clip empty/reloading byte or ammo rising (2 s)
      focus aim       RMB held -> visible the whole time it is held
      alt-fire        alt-fire bytes changed (4 s)
      ui events       new tutorial/notification/subtitle object or screen
                      stack change (6 s; best effort - see PlayerTracker)
    HUD hidden once every trigger has been quiet for its hold window.

    An open menu DISABLES hiding completely: byte 0 is forced while the HUD
    menu counter (ATouristHUD+0x4BC) is non-zero or a UPauseMenu screen sits
    on the UTouristScreenManager stack. A screen-stack layer that is neither
    a pause menu nor the persistent tutorial-panel shell (e.g. a tutorial
    prompt banner) also forces byte 0, sustained while it is present - no
    hold-window expiry (--no-stack-layers disables that behaviour).
    --invert flips the direction of everything EXCEPT those forced states.

Combat detection chain (all offsets verified via IDA decompilation of the
shipping binaries on 2026-10-12):

    game DLL IAT 0x8A15B0        -> &GUObjectArray (Returnal-CoreUObject)
    GUObjectArray +0x10          -> FUObjectItem* chunk table (+0x24 = count)
    FUObjectItem                 -> 24 bytes; flags 0x20000000 = unreachable
    UObject +0x10                -> UClass*
    AEnemyManager class global   -> game DLL RVA 0xF5DC28 (qword_180F5DC28)
    AEnemyManager +0x838/+0x840  -> TArray<AEnemyBase*> {Data, Count}
    AEnemyManager +0xB70         -> audio threat level (display only)
    AEnemyBase +0x8F0            -> AEnemyControllerBase*  (GetEnemyController)
    AEnemyControllerBase +0x480  -> UEnemyAggressionComponent*
    UEnemyAggressionComponent +0x151 -> EAggressionState byte
    combat = state in {4 = EAS_InCombat_NoTicket, 5 = EAS_InCombat}
             (exactly AEnemyControllerBase::IsInCombat logic)

Player / HUD signal chain (offsets IDA-verified, re-verified live against
the running game on 2026-10-18):

    ATouristPlayerController  (class global RVA 0xF6F168)
      +0x330 -> pawn (AFirstPersonPlayerCharacter), +0x390 -> ATouristHUD
    pawn +0x668 -> UHealthComponent, +0xEB8 -> UFocusAimComponent,
      +0x1028/+0x1040 -> AGunBase slots;  gun +0x908 -> UWeaponClip,
      gun +0xC80 -> UAltFireComponent
    UHealthComponent +0x2AC       -> hp float (2.00 = 200/300 live)
    UWeaponClip +0x1A8            -> ammo in clip (float; 12 -> 0 observed)
    UWeaponClip +0x1B4            -> byte 1 while empty/reloading, 0 full
    UFocusAimComponent +0x198     -> 1 while RMB focus aim held
    ATouristHUD +0x514            -> same aim flag (byte)
    ATouristHUD +0x4BC            -> open-menu count (0 gameplay, N = N menus)
    UAltFireComponent +0x271/+0x272/+0x27C -> mode/firing/fuel bytes
      (change-based; alt-fire not unlocked in test save -> stay defensive)
    UTouristScreenManager +0x138 count / +0x130 data: 24-byte entries
      {u64 pad, u64 pad, u32 main index @16, u32 aux index @20}; indices
      resolve through the GUObjectArray to live screen objects and their
      class chains (UPauseMenu match; UTouristTutorialPanel = benign).
    Class chains: SuperStruct at +0x40 (this engine build).

ShaderToggler.addon64 internals (reversed via IDA):
    std::vector<Record> globals: begin RVA 0x23AF8, end RVA 0x23B00
    Record = 280 bytes: +0x00 id, +0x28 key VK, +0x29..0x2B modifiers,
    +0x50 vertex hash set, +0x90 pixel set, +0xD0 compute set,
    +0x110 toggled byte. Draw hook (sub_180009FA0) blocks the shader when
    toggled != 0; key handler (sub_18000A230) flips that byte.
    In other words: byte 1 = HUD hidden, byte 0 = HUD visible.

Usage:
    python hud_dynamic.py                 # fully automatic, reacts in ~0.2 s
    python hud_dynamic.py --dry-run       # detect only, never actuate
    python hud_dynamic.py --calibrate 30  # detailed dump for 30 s, no writes
    python hud_dynamic.py --invert        # flip (hidden while triggers live)
    python hud_dynamic.py --selftest      # offline logic tests, no game needed
"""

import argparse
import configparser
import ctypes
import math
import os
import struct
import sys
import time
from collections import Counter
from ctypes import wintypes

# ---------------------------------------------------------------------------
# Constants: process / modules
# ---------------------------------------------------------------------------

VERSION = "1.3.0"

GAME_EXE = "Returnal-Win64-Shipping.exe"
GAME_DLL = "Returnal-Returnal-Win64-Shipping.dll"
HMQ_DLL = "Returnal-HMQScreen-Win64-Shipping.dll"
ADDON_DLL = "ShaderToggler.addon64"
INI_FILE = "ShaderToggler.ini"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# Constants: game offsets (IDA-verified, see module docstring)
# ---------------------------------------------------------------------------

RVA_GUOBJECTARRAY_IAT = 0x8A15B0    # game DLL IAT slot -> &GUObjectArray
RVA_ENEMYMANAGER_CLASS = 0xF5DC28   # qword_180F5DC28: cached AEnemyManager UClass*

OFF_GUA_CHUNKTABLE = 0x10           # FUObjectArray +0x10: chunk table
OFF_GUA_COUNT = 0x24                # FUObjectArray +0x24: object count (int32)
OBJ_ITEM_SIZE = 24                  # FUObjectItem stride
OBJ_ITEM_FLAGS = 8                  # flags offset inside FUObjectItem
OBJ_ITEM_UNREACHABLE = 0x20000000   # skip item when this bit is set

UOBJECT_FLAGS = 0x08                # ObjectFlags (int32)
UOBJECT_INTERNAL_INDEX = 0x0C       # InternalIndex (int32)
UOBJECT_CLASS = 0x10                # UClass* (pointer)

EM_ENEMIES_DATA = 0x838             # AEnemyManager -> TArray<AEnemyBase*> Data
EM_ENEMIES_COUNT = 0x840            # ... Count (int32)
EM_AUDIO_THREAT = 0xB70             # ... GetCurrentAudioThreatLevel() (uint32)

ENEMY_CONTROLLER = 0x8F0            # AEnemyBase -> AEnemyControllerBase*
CTRL_AGGR_COMP = 0x480              # AEnemyControllerBase -> UEnemyAggressionComponent*
AGGR_STATE = 0x151                  # UEnemyAggressionComponent -> EAggressionState byte

COMBAT_STATES = frozenset({4, 5})   # EAS_InCombat_NoTicket, EAS_InCombat
MAX_SANE_ENEMIES = 4096
MAX_SANE_OBJECTS = 2_000_000

# ---------------------------------------------------------------------------
# Constants: player / HUD / screen objects (class globals in the module, then
# member offsets; all re-verified live against the running game on 2026-10-18,
# see PlayerTracker for the discovery/detection story)
# ---------------------------------------------------------------------------

RVA_CLASS_TOURISTPC = 0xF6F168      # ATouristPlayerController UClass*
RVA_CLASS_HEALTHCOMP = 0xF5FAF8     # UHealthComponent UClass*
RVA_CLASS_FOCUSCOMP = 0xF5EBE0      # UFocusAimComponent UClass*
RVA_CLASS_GUNBASE = 0xF5F330        # AGunBase UClass*
RVA_CLASS_WEAPONCLIP = 0xF679A8     # UWeaponClip UClass*
RVA_CLASS_ALTFIRECOMP = 0xF57B90    # UAltFireComponent UClass*
RVA_CLASS_TOURISTHUD = 0xF6EB10     # ATouristHUD UClass*
RVA_CLASS_SCREENMGR = 0xF6FED8      # UTouristScreenManager UClass*
RVA_CLASS_PAUSEMENU = 0xF64B88      # UPauseMenu UClass*
RVA_CLASS_TUTWIDGET = 0xF704A0      # UTouristTutorialWidget UClass* (watch)
RVA_CLASS_TUTPANEL = 0xF70460       # UTouristTutorialPanel UClass* (watch)
RVA_CLASS_NOTIFWIDGET = 0xF64280    # UNotificationWidget UClass* (watch)

# HMQ screen DLL class globals (subtitles; module may be absent -> watch off)
RVA_CLASS_SUBTITLEPLAYER = 0xA3370  # UHMQSubtitlePlayer UClass*
RVA_CLASS_SUBTITLEWIDGET = 0xA33A8  # UHMQSubtitlesWidget UClass*

UCLASS_SUPER = 0x40                 # UStruct::SuperStruct (empirically +0x40)

PC_PAWN = 0x330                     # ATouristPlayerController -> pawn
PC_HUD = 0x390                      # ... -> ATouristHUD
PAWN_HEALTH = 0x668                 # pawn -> UHealthComponent
PAWN_FOCUS = 0xEB8                  # pawn -> UFocusAimComponent
PAWN_GUN1 = 0x1028                  # pawn -> AGunBase slot 1
PAWN_GUN2 = 0x1040                  # pawn -> AGunBase slot 2
GUN_CLIP = 0x908                    # gun -> UWeaponClip
GUN_ALTFIRE = 0xC80                 # gun -> UAltFireComponent
HC_HP = 0x2AC                       # UHealthComponent -> hp float
CLIP_AMMO = 0x1A8                   # UWeaponClip -> ammo in clip (float)
CLIP_RELOAD = 0x1B4                 # ... -> empty/reloading byte (1 = reload)
HUD_MENU_COUNT = 0x4BC              # ATouristHUD -> open-menu count (0 = none)
HUD_AIM = 0x514                     # ... -> focus-aim byte (0/1)
FOCUS_AIM = 0x198                   # UFocusAimComponent -> aim dword (0/1)
ALT_BYTE1 = 0x271                   # UAltFireComponent -> mode/firing byte
ALT_BYTE2 = 0x272                   # ... second mode/firing byte
ALT_FUEL = 0x27C                    # ... alt-fire fuel byte
MGR_COUNT = 0x138                   # UTouristScreenManager -> stack count
MGR_DATA = 0x130                    # ... -> stack array (24-byte entries)
MGR_ENTRY_SIZE = 24
MGR_ENTRY_INDEX = 16                # entry+16: u32 object InternalIndex
MGR_ENTRY_AUX = 20                  # entry+20: u32 secondary object index
MGR_MAX_ENTRIES = 64

TAIL_SCAN_BUDGET = 6000             # new GUObjectArray items scanned per tick

# hold windows (seconds) for the trigger state machine
HOLD_HEALTH = 3.0
HOLD_AMMO = 3.0
HOLD_RELOAD = 2.0
HOLD_ALT = 4.0
HOLD_UI = 6.0

# ---------------------------------------------------------------------------
# Constants: ShaderToggler.addon64 internals (IDA-verified)
# ---------------------------------------------------------------------------

ADDON_RVA_GROUPVEC_BEGIN = 0x23AF8  # std::vector begin (qword_180023AF8)
ADDON_RVA_GROUPVEC_END = 0x23B00    # std::vector end   (qword_180023B00)
REC_SIZE = 280                      # group record stride
REC_ID = 0x00                       # dword group id
REC_KEY = 0x28                      # byte VK of the toggle key (F1 = 0x70)
REC_MOD_SHIFT = 0x29                # bool: requires Shift
REC_MOD_ALT = 0x2A                  # bool: requires Alt
REC_MOD_CTRL = 0x2B                 # bool: requires Ctrl
REC_TOGGLED = 0x110                 # byte: 1 = group ON = HUD hidden

# ---------------------------------------------------------------------------
# WinAPI setup
# ---------------------------------------------------------------------------

PROCESS_VM_OPERATION = 0x0008
PROCESS_VM_READ = 0x0010
PROCESS_VM_WRITE = 0x0020
PROCESS_QUERY_INFORMATION = 0x0400

TH32CS_SNAPPROCESS = 0x00000002
LIST_MODULES_ALL = 0x03
STILL_ACTIVE = 259

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
psapi = ctypes.WinDLL("psapi", use_last_error=True)

k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
k32.OpenProcess.restype = wintypes.HANDLE
k32.CloseHandle.argtypes = [wintypes.HANDLE]
k32.CloseHandle.restype = wintypes.BOOL
k32.ReadProcessMemory.argtypes = [
    wintypes.HANDLE, wintypes.LPCVOID, wintypes.LPVOID,
    ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t),
]
k32.ReadProcessMemory.restype = wintypes.BOOL
k32.WriteProcessMemory.argtypes = [
    wintypes.HANDLE, wintypes.LPVOID, wintypes.LPCVOID,
    ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t),
]
k32.WriteProcessMemory.restype = wintypes.BOOL
k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
k32.GetExitCodeProcess.restype = wintypes.BOOL
k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
psapi.EnumProcessModulesEx.argtypes = [
    wintypes.HANDLE, ctypes.POINTER(wintypes.HMODULE),
    wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.DWORD,
]
psapi.EnumProcessModulesEx.restype = wintypes.BOOL
psapi.GetModuleInformation.argtypes = [
    wintypes.HANDLE, wintypes.HMODULE, ctypes.c_void_p, wintypes.DWORD,
]
psapi.GetModuleInformation.restype = wintypes.BOOL
psapi.GetModuleBaseNameW.argtypes = [
    wintypes.HANDLE, wintypes.HMODULE, wintypes.LPWSTR, wintypes.DWORD,
]
psapi.GetModuleBaseNameW.restype = wintypes.DWORD


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


class MODULEINFO(ctypes.Structure):
    _fields_ = [
        ("lpBaseOfDll", wintypes.LPVOID),
        ("SizeOfImage", wintypes.DWORD),
        ("EntryPoint", wintypes.LPVOID),
    ]


k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE

INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


def log(msg):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), msg), flush=True)


def log_err(msg):
    print("[%s] ERROR: %s" % (time.strftime("%H:%M:%S"), msg), file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# Process helpers
# ---------------------------------------------------------------------------

def find_process_id(exe_name):
    """Return PID of first matching process, or None. Warns on multiple matches."""
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap is None or snap == INVALID_HANDLE_VALUE:
        return None
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        if not k32.Process32FirstW(snap, ctypes.byref(entry)):
            return None
        first = None
        matches = 0
        while True:
            if entry.szExeFile.lower() == exe_name.lower():
                matches += 1
                if first is None:
                    first = entry.th32ProcessID
            if not k32.Process32NextW(snap, ctypes.byref(entry)):
                break
        if matches > 1:
            log("multiple %s instances running (%d); using pid %d - pass --pid to pick another"
                % (exe_name, matches, first))
        return first
    finally:
        k32.CloseHandle(snap)


k32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
k32.Process32FirstW.restype = wintypes.BOOL
k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
k32.Process32NextW.restype = wintypes.BOOL


def wchar_str(buf):
    """String value of a WCHAR array.

    str() on a bare ctypes WCHAR array returns the object repr, not the text
    (unlike struct fields, which ctypes converts on access). Always use .value.
    """
    return buf.value or ""


def module_bases(pid, names_wanted):
    """Return {name_lower: base} for the wanted modules of a process."""
    hproc = k32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not hproc:
        return None
    try:
        needed = wintypes.DWORD(0)
        cap = 256
        while True:
            buf = (wintypes.HMODULE * cap)()
            if not psapi.EnumProcessModulesEx(
                    hproc, buf, ctypes.sizeof(buf), ctypes.byref(needed), LIST_MODULES_ALL):
                return None
            if needed.value <= ctypes.sizeof(buf):
                break
            cap = min(needed.value // ctypes.sizeof(wintypes.HMODULE) + 16, 8192)
        n_modules = min(needed.value // ctypes.sizeof(wintypes.HMODULE), cap)
        found = {}
        name_buf = wintypes.WCHAR * 260
        for i in range(n_modules):
            hmod = buf[i]
            name = name_buf()
            if psapi.GetModuleBaseNameW(hproc, hmod, name, 260) == 0:
                continue
            base_name = wchar_str(name).lower()
            if base_name not in found and base_name in names_wanted:
                mi = MODULEINFO()
                if psapi.GetModuleInformation(hproc, hmod, ctypes.byref(mi), ctypes.sizeof(mi)):
                    found[base_name] = mi.lpBaseOfDll
            if len(found) == len(names_wanted):
                break
        return found
    finally:
        k32.CloseHandle(hproc)


def _pid_alive(pid):
    h = k32.OpenProcess(PROCESS_QUERY_INFORMATION, False, pid)
    if not h:
        return False
    try:
        code = wintypes.DWORD()
        if not k32.GetExitCodeProcess(h, ctypes.byref(code)):
            return False
        return code.value == STILL_ACTIVE
    finally:
        k32.CloseHandle(h)


def wait_for_modules(pid, names_wanted, timeout_s=120.0):
    """Poll until all wanted modules are mapped. Returns dict, None on timeout
    or process death."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        found = module_bases(pid, names_wanted)
        if found is not None and len(found) == len(names_wanted):
            return found
        if not _pid_alive(pid):
            return None
        time.sleep(1.0)
    return None


# ---------------------------------------------------------------------------
# Memory reader / writer
# ---------------------------------------------------------------------------

class ProcessMem:
    def __init__(self, pid, read_only=False):
        access = PROCESS_VM_READ | PROCESS_QUERY_INFORMATION
        if not read_only:
            access |= PROCESS_VM_WRITE | PROCESS_VM_OPERATION
        self.pid = pid
        self.hproc = k32.OpenProcess(access, False, pid)
        if not self.hproc:
            raise OSError("OpenProcess failed for pid %d (err %d)" % (pid, ctypes.get_last_error()))

    def close(self):
        if self.hproc:
            k32.CloseHandle(self.hproc)
            self.hproc = None

    def alive(self):
        code = wintypes.DWORD()
        if not self.hproc or not k32.GetExitCodeProcess(self.hproc, ctypes.byref(code)):
            return False
        return code.value == STILL_ACTIVE

    def rpm(self, addr, size):
        """Read size bytes; raises OSError on failure or short read."""
        buf = (ctypes.c_ubyte * size)()
        n = ctypes.c_size_t(0)
        ok = k32.ReadProcessMemory(
            self.hproc, ctypes.c_void_p(addr), buf, size, ctypes.byref(n))
        if not ok or n.value != size:
            raise ctypes.WinError(ctypes.get_last_error() or 299)
        return bytes(buf)

    def wpm(self, addr, data):
        n = ctypes.c_size_t(0)
        buf = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
        ok = k32.WriteProcessMemory(
            self.hproc, ctypes.c_void_p(addr), buf, len(data), ctypes.byref(n))
        if not ok or n.value != len(data):
            raise ctypes.WinError(ctypes.get_last_error() or 299)

    def u8(self, addr):
        return self.rpm(addr, 1)[0]

    def u32(self, addr):
        return struct.unpack("<I", self.rpm(addr, 4))[0]

    def u64(self, addr):
        return struct.unpack("<Q", self.rpm(addr, 8))[0]


# ---------------------------------------------------------------------------
# Enemy manager discovery + combat sampling
# ---------------------------------------------------------------------------

class CombatDetector:
    """Finds the live AEnemyManager and samples per-enemy aggression states."""

    def __init__(self, mem, game_base):
        self.mem = mem
        self.game_base = game_base
        self.iat_gua = game_base + RVA_GUOBJECTARRAY_IAT
        self.class_slot = game_base + RVA_ENEMYMANAGER_CLASS
        self.em = None          # cached AEnemyBase* address of EnemyManager

    def _scan(self, em_class):
        """Full GUObjectArray scan for an AEnemyManager instance.

        Returns the address of the live instance or None. All transient read
        failures degrade to None (rescan next tick) instead of raising, so a
        glitch never tears down the session.
        """
        t0 = time.time()
        try:
            gua = self.mem.u64(self.iat_gua)      # IAT entry = &GUObjectArray
            if gua < 0x10000:
                return None
            chunk_table = self.mem.u64(gua + OFF_GUA_CHUNKTABLE)
            count = self.mem.u32(gua + OFF_GUA_COUNT)
            if not (0 < count < MAX_SANE_OBJECTS) or chunk_table < 0x10000:
                return None

            matches = []
            scanned = 0
            idx = 0
            chunk_cache = {}
            while idx < count:
                chunk_no = idx >> 16
                if chunk_no not in chunk_cache:
                    try:
                        chunk_cache[chunk_no] = self.mem.u64(chunk_table + 8 * chunk_no)
                    except OSError:
                        chunk_cache[chunk_no] = 0
                chunk_base = chunk_cache[chunk_no]
                items_here = min(0x10000, count - (chunk_no << 16))
                if chunk_base < 0x10000:
                    idx = (chunk_no + 1) << 16
                    continue        # unallocated chunk - skip, not fatal
                try:
                    raw = self.mem.rpm(chunk_base, items_here * OBJ_ITEM_SIZE)
                except OSError:
                    idx = (chunk_no + 1) << 16
                    continue
                for j in range(items_here):
                    off = j * OBJ_ITEM_SIZE
                    obj = struct.unpack_from("<Q", raw, off)[0]
                    if not obj:
                        continue
                    flags = struct.unpack_from("<I", raw, off + OBJ_ITEM_FLAGS)[0]
                    if flags & OBJ_ITEM_UNREACHABLE:
                        continue
                    scanned += 1
                    try:
                        if self.mem.u64(obj + UOBJECT_CLASS) == em_class:
                            matches.append(obj)
                    except OSError:
                        continue
                idx = (chunk_no + 1) << 16
        except OSError as e:
            log("GUObjectArray scan failed transiently (%s); will retry" % e)
            return None

        if not matches:
            return None
        if len(matches) > 1:
            log("EnemyManager class matched %d objects; picking the live one"
                % len(matches))

        # Validate each candidate's enemy array, then pick the newest valid
        # instance: InternalIndex grows with creation order, so a stale
        # instance from a previous level loses to the live one even if the
        # stale one still carries a non-null Data pointer.
        best = None
        best_key = (-1, -1)
        for obj in matches:
            try:
                if self.mem.u64(obj + UOBJECT_CLASS) != em_class:
                    continue                    # freed/reused meanwhile
                internal = self.mem.u32(obj + UOBJECT_INTERNAL_INDEX)
                ccount = self.mem.u32(obj + EM_ENEMIES_COUNT)
                cdata = self.mem.u64(obj + EM_ENEMIES_DATA)
            except OSError:
                continue
            if not (0 <= ccount <= MAX_SANE_ENEMIES):
                continue                        # tearing instance
            if ccount > 0 and not cdata:
                continue                        # half-destroyed TArray
            if ccount and cdata:
                try:
                    self.mem.rpm(cdata, 8)      # touch: is the buffer mapped?
                except OSError:
                    continue
            key = (internal,)
            if key > best_key:
                best_key, best = key, obj
        if best is not None:
            log("EnemyManager @ 0x%X (matches=%d, objects=%d, scan=%.2fs)"
                % (best, len(matches), scanned, time.time() - t0))
        return best

    def _valid_cached(self, em):
        try:
            return self.mem.u64(em + UOBJECT_CLASS) == self.mem.u64(self.class_slot) \
                and self.mem.u64(self.class_slot) != 0
        except OSError:
            return False

    def sample(self):
        """Return dict: ok, in_fight, count, states (Counter), threat, em."""
        out = {"ok": False, "in_fight": False, "count": 0,
               "states": Counter(), "threat": 0, "em": 0, "note": "",
               "details": []}
        try:
            em_class = self.mem.u64(self.class_slot)
        except OSError as e:
            out["note"] = "class slot unreadable: %s" % e
            return out
        if em_class == 0:
            out["note"] = "AEnemyManager class not initialized (boot/menu)"
            return out

        if self.em is None or not self._valid_cached(self.em):
            self.em = self._scan(em_class)
        if self.em is None:
            out["note"] = "no EnemyManager instance found"
            return out

        em = self.em
        out["em"] = em
        try:
            count = self.mem.u32(em + EM_ENEMIES_COUNT)
            if not (0 <= count <= MAX_SANE_ENEMIES):
                self.em = None          # stale/tearing instance -> rescan next tick
                out["note"] = "implausible enemy count %d -> rescan" % count
                return out
            data = self.mem.u64(em + EM_ENEMIES_DATA)
            if count > 0 and not data:
                self.em = None          # half-destroyed TArray
                out["note"] = "enemy array count/pointer mismatch -> rescan"
                return out
            raw = self.mem.rpm(data, count * 8) if count else b""
            # seqlock-lite: the engine resizes the array in place; if the count
            # changed under us the pointers we just read are suspect.
            if self.mem.u32(em + EM_ENEMIES_COUNT) != count:
                out["note"] = "enemy array resized mid-read; retry next tick"
                return out
            threat = self.mem.u32(em + EM_AUDIO_THREAT)
        except OSError as e:
            self.em = None
            out["note"] = "EnemyManager read failed (%s) -> rescan" % e
            return out

        states = Counter()
        in_fight = False
        details = []
        for off in range(0, len(raw), 8):
            enemy = struct.unpack_from("<Q", raw, off)[0]
            if not enemy:
                continue
            try:
                ctrl = self.mem.u64(enemy + ENEMY_CONTROLLER)
                if not ctrl:
                    states["no-ctrl"] += 1
                    details.append((enemy, 0, 0, -1))
                    continue
                comp = self.mem.u64(ctrl + CTRL_AGGR_COMP)
                if not comp:
                    states["no-comp"] += 1
                    details.append((enemy, ctrl, 0, -2))
                    continue
                st = self.mem.u8(comp + AGGR_STATE)
            except OSError:
                states["unreadable"] += 1
                details.append((enemy, 0, 0, -3))
                continue
            states[st] += 1
            details.append((enemy, ctrl, comp, st))
            if st in COMBAT_STATES:
                in_fight = True

        out.update(ok=True, in_fight=in_fight, count=count,
                   states=states, threat=threat, details=details)
        return out


# ---------------------------------------------------------------------------
# Live player/UI discovery + per-tick trigger signals
# ---------------------------------------------------------------------------

def classify_stack_chain(chain, pause_cls, benign_cls):
    """Flags for one resolved screen-stack object chain.

    is_pause  - chain contains the UPauseMenu class (menu rule)
    is_benign - chain contains UTouristTutorialPanel: a persistent layer
                that stays on the stack for whole tutorial zones while
                hiding is still expected to work
    """
    is_pause = bool(pause_cls) and pause_cls in chain
    is_benign = bool(benign_cls) and benign_cls in chain
    return (is_pause, is_benign)


class PlayerTracker:
    """Finds the live player/UI objects and samples the HUD trigger signals.

    Discovery (live-verified 2026-10-18; class chains walked via SuperStruct
    at +0x40, non-CDO objects only, newest InternalIndex wins):

        PC:    class chain contains ATouristPlayerController, pawn+health ok
        MGR:   class chain contains UTouristScreenManager, sane stack array

    Member chain: PC+0x330 pawn, +0x390 HUD; pawn+0x668 health, +0xEB8
    focus, +0x1028/+0x1040 gun slots; gun+0x908 clip, +0xC80 alt-fire.

    Signals per sample():
        menu_open  HUD+0x4BC count > 0, or a UPauseMenu object on the
                   screen stack (stack change also raises ui_event)
        stack_layer a screen-stack entry that is neither a pause menu nor
                   the persistent UTouristTutorialPanel shell (e.g. the
                   tutorial prompt banner) -> sustained HUD-on while present
        aim        FOCUS+0x198 != 0 or HUD+0x514 != 0 (RMB focus aim held)
        hp         HC+0x2AC float (None when unreadable)
        clip/clip2 CLIP+0x1A8 floats (None when that gun has no clip)
        reload     CLIP+0x1B4 == 1 on any gun (empty/reloading byte)
        altfire    packed ALT+0x271/0x272/0x27C bytes (change-based trigger)
        ui_event   new watched UI object in the GUObjectArray tail
                   (tutorial widget/panel, notification widget, subtitle
                   player/widget when the HMQ DLL is present)
    """

    def __init__(self, mem, game_base, hmq_base=0):
        self.mem = mem
        self.game_base = game_base
        self.hmq_base = hmq_base
        self.cls = {}                   # role -> UClass* (globals in module)
        self.watch = {}                 # UClass* -> label (tail scan)
        self.gua = 0
        self.pc = 0
        self.mgr = 0
        self.pawn = 0
        self.hc = 0
        self.focus = 0
        self.gun1 = 0
        self.gun2 = 0
        self.clip1 = 0
        self.clip2 = 0
        self.altfire = 0
        self.hud = 0
        self.tail_at = None
        self.stack_prev = None
        self.layer_prev = False
        self.next_scan = 0.0
        self.last_refresh = 0.0
        self.tail_every = 1             # ticks between ui tail scans
        self._tick = 0
        self._chain_cache = {}

    # -- small guarded readers ------------------------------------------------

    def _ru64(self, addr):
        try:
            return self.mem.u64(addr)
        except OSError:
            return 0

    def _ru8(self, addr):
        try:
            return self.mem.u8(addr)
        except OSError:
            return None

    def _ri32(self, addr):
        try:
            return struct.unpack("<i", self.mem.rpm(addr, 4))[0]
        except OSError:
            return None

    def _rf32(self, addr):
        try:
            return struct.unpack("<f", self.mem.rpm(addr, 4))[0]
        except OSError:
            return None

    def _chain(self, cls_ptr, cache=None, limit=24):
        """UClass chain via SuperStruct+0x40; cached per class pointer."""
        cache = self._chain_cache if cache is None else cache
        got = cache.get(cls_ptr)
        if got is not None:
            return got
        out = []
        seen = set()
        c = cls_ptr
        for _ in range(limit):
            if not c or c in seen:
                break
            seen.add(c)
            out.append(c)
            try:
                c = self.mem.u64(c + UCLASS_SUPER)
            except OSError:
                break
        out = tuple(out)
        cache[cls_ptr] = out
        return out

    def _member(self, ptr, key, cache):
        """Return ptr when its class chain contains the role's class, else 0."""
        if ptr < 0x10000:
            return 0
        base = self.cls.get(key, 0)
        if not base:
            return 0
        try:
            ch = self._chain(self.mem.u64(ptr + UOBJECT_CLASS), cache)
        except OSError:
            return 0
        return ptr if base in ch else 0

    def _scan_member(self, obj, key, span=0x2000):
        """Fallback: scan obj for the first pointer matching role `key`."""
        base = self.cls.get(key, 0)
        if not base:
            return 0
        try:
            blob = self.mem.rpm(obj, span)
        except OSError:
            return 0
        for off in range(0, len(blob) - 8, 8):
            p = struct.unpack_from("<Q", blob, off)[0]
            if p < 0x10000:
                continue
            if self._member(p, key, self._chain_cache):
                return p
        return 0

    # -- discovery ------------------------------------------------------------

    def _refresh_class_ptrs(self):
        want = {
            "pc": (self.game_base, RVA_CLASS_TOURISTPC),
            "hc": (self.game_base, RVA_CLASS_HEALTHCOMP),
            "focus": (self.game_base, RVA_CLASS_FOCUSCOMP),
            "gun": (self.game_base, RVA_CLASS_GUNBASE),
            "clip": (self.game_base, RVA_CLASS_WEAPONCLIP),
            "altfire": (self.game_base, RVA_CLASS_ALTFIRECOMP),
            "hud": (self.game_base, RVA_CLASS_TOURISTHUD),
            "mgr": (self.game_base, RVA_CLASS_SCREENMGR),
            "pause": (self.game_base, RVA_CLASS_PAUSEMENU),
            "tutwidget": (self.game_base, RVA_CLASS_TUTWIDGET),
            "tutpanel": (self.game_base, RVA_CLASS_TUTPANEL),
            "notifwidget": (self.game_base, RVA_CLASS_NOTIFWIDGET),
        }
        if self.hmq_base:
            want["sub_player"] = (self.hmq_base, RVA_CLASS_SUBTITLEPLAYER)
            want["sub_widget"] = (self.hmq_base, RVA_CLASS_SUBTITLEWIDGET)
        for k, (base, rva) in want.items():
            self.cls[k] = self._ru64(base + rva)
        watch = {}
        for k, label in (("tutwidget", "tutorial-widget"),
                         ("tutpanel", "tutorial-panel"),
                         ("notifwidget", "notification"),
                         ("sub_player", "subtitle-player"),
                         ("sub_widget", "subtitle-widget")):
            p = self.cls.get(k, 0)
            if p:
                watch[p] = label
        self.watch = watch

    def set_hmq_base(self, base):
        if base and base != self.hmq_base:
            self.hmq_base = base
            self.watch = {}             # rebuilt on next refresh
            self._refresh_class_ptrs()
            log("HMQ screen DLL @ 0x%X (subtitle watch on)" % base)

    def _full_scan(self):
        """Full GUObjectArray walk for PC + screen manager. Returns True if a
        PC was found. Degrades to False on transient read trouble."""
        t0 = time.time()
        self.pc = 0
        self.mgr = 0
        try:
            gua = self.mem.u64(self.game_base + RVA_GUOBJECTARRAY_IAT)
            if gua < 0x10000:
                return False
            self.gua = gua
            chunk_table = self.mem.u64(gua + OFF_GUA_CHUNKTABLE)
            count = self.mem.u32(gua + OFF_GUA_COUNT)
            if not (0 < count < MAX_SANE_OBJECTS) or chunk_table < 0x10000:
                return False
            self._refresh_class_ptrs()
            if not self.cls.get("pc"):
                return False

            cache = {}
            pcs = []
            mgrs = []
            idx = 0
            chunk_cache = {}
            while idx < count:
                chunk_no = idx >> 16
                if chunk_no not in chunk_cache:
                    try:
                        chunk_cache[chunk_no] = self.mem.u64(chunk_table + 8 * chunk_no)
                    except OSError:
                        chunk_cache[chunk_no] = 0
                chunk_base = chunk_cache[chunk_no]
                items_here = min(0x10000, count - (chunk_no << 16))
                if chunk_base < 0x10000:
                    idx = (chunk_no + 1) << 16
                    continue
                try:
                    raw = self.mem.rpm(chunk_base, items_here * OBJ_ITEM_SIZE)
                except OSError:
                    idx = (chunk_no + 1) << 16
                    continue
                for j in range(items_here):
                    off = j * OBJ_ITEM_SIZE
                    obj = struct.unpack_from("<Q", raw, off)[0]
                    if not obj:
                        continue
                    item_flags = struct.unpack_from("<I", raw, off + OBJ_ITEM_FLAGS)[0]
                    if item_flags & OBJ_ITEM_UNREACHABLE:
                        continue
                    try:
                        c = self.mem.u64(obj + UOBJECT_CLASS)
                    except OSError:
                        continue
                    if not c:
                        continue
                    ch = cache.get(c)
                    if ch is None:
                        ch = self._chain(c, cache)
                    if self.cls["pc"] in ch or (self.cls.get("mgr") and self.cls["mgr"] in ch):
                        try:
                            obj_flags = self.mem.u32(obj + UOBJECT_FLAGS)
                        except OSError:
                            continue
                        if obj_flags & 0x10:
                            continue        # class default object
                        if self.cls["pc"] in ch:
                            pcs.append(obj)
                        if self.cls.get("mgr") and self.cls["mgr"] in ch:
                            mgrs.append(obj)
                idx = (chunk_no + 1) << 16
        except OSError as e:
            log("player scan failed transiently (%s); will retry" % e)
            return False

        self._chain_cache = cache
        best, best_ii = 0, -1
        for obj in pcs:
            pawn = self._ru64(obj + PC_PAWN)
            if pawn < 0x10000:
                continue
            hc = self._ru64(pawn + PAWN_HEALTH)
            if hc < 0x10000:
                continue
            if self.cls["hc"] not in self._chain(self._ru64(hc + UOBJECT_CLASS), cache):
                continue
            ii = self._ru64(obj + UOBJECT_INTERNAL_INDEX) & 0xFFFFFFFF
            if ii > best_ii:
                best, best_ii = obj, ii
        self.pc = best

        best, best_key = 0, -1
        for obj in mgrs:
            data = self._ru64(obj + MGR_DATA)
            n = self._ri32(obj + MGR_COUNT)
            if n is None or n < 0 or n > MGR_MAX_ENTRIES:
                continue
            if n and not data:
                continue
            ii = self._ru64(obj + UOBJECT_INTERNAL_INDEX) & 0xFFFFFFFF
            if ii > best_key:
                best, best_key = obj, ii
        self.mgr = best

        self.tail_at = count
        if self.pc:
            self._resolve_members(cache)
        log("player scan: pc=0x%X pawn=0x%X hc=0x%X focus=0x%X gun1=0x%X gun2=0x%X "
            "clip1=0x%X clip2=0x%X alt=0x%X hud=0x%X mgr=0x%X (%.2fs, pc_matches=%d)"
            % (self.pc, self.pawn, self.hc, self.focus, self.gun1, self.gun2,
               self.clip1, self.clip2, self.altfire, self.hud, self.mgr,
               time.time() - t0, len(pcs)))
        return bool(self.pc)

    def _resolve_members(self, cache=None):
        prev = (self.gun1, self.gun2, self.clip1, self.clip2)
        self.pawn = self.hc = self.focus = 0
        self.gun1 = self.gun2 = self.clip1 = self.clip2 = self.altfire = 0
        self.hud = 0
        if not self.pc:
            return
        self.hud = self._member(self._ru64(self.pc + PC_HUD), "hud", cache)
        pawn = self._ru64(self.pc + PC_PAWN)
        if pawn < 0x10000:
            return
        self.pawn = pawn
        self.hc = self._member(self._ru64(pawn + PAWN_HEALTH), "hc", cache)
        self.focus = self._member(self._ru64(pawn + PAWN_FOCUS), "focus", cache)
        self.gun1 = self._member(self._ru64(pawn + PAWN_GUN1), "gun", cache)
        self.gun2 = self._member(self._ru64(pawn + PAWN_GUN2), "gun", cache)
        if self.gun1:
            self.clip1 = self._member(self._ru64(self.gun1 + GUN_CLIP), "clip", cache)
            self.altfire = self._member(self._ru64(self.gun1 + GUN_ALTFIRE), "altfire", cache)
            if not self.clip1:
                self.clip1 = self._scan_member(self.gun1, "clip")
        if self.gun2 and self.gun2 != self.gun1:
            self.clip2 = self._member(self._ru64(self.gun2 + GUN_CLIP), "clip", cache)
            if not self.clip2:
                self.clip2 = self._scan_member(self.gun2, "clip")
        if prev != (self.gun1, self.gun2, self.clip1, self.clip2) and prev[0]:
            log("weapon change: gun1=0x%X gun2=0x%X clip1=0x%X clip2=0x%X"
                % (self.gun1, self.gun2, self.clip1, self.clip2))

    # -- screen stack / UI tail watch -----------------------------------------

    def _gua_obj(self, idx):
        ct = self._ru64(self.gua + OFF_GUA_CHUNKTABLE)
        if ct < 0x10000:
            return 0
        cb = self._ru64(ct + 8 * (idx >> 16))
        if cb < 0x10000:
            return 0
        return self._ru64(cb + OBJ_ITEM_SIZE * (idx & 0xFFFF))

    def _stack(self):
        """(count, ((ii, obj, is_pause, is_benign, aux_ii), ...)) or None.

        Entry layout (live-verified 2026-10-18): 24 bytes, main object
        InternalIndex in the low u32 at +16, a secondary object index at
        +20. Chains classify each entry: pause menu vs the persistent
        tutorial-panel shell vs anything else ("layer").
        """
        if not self.mgr:
            return None
        n = self._ri32(self.mgr + MGR_COUNT)
        data = self._ru64(self.mgr + MGR_DATA)
        if n is None or n < 0 or n > MGR_MAX_ENTRIES:
            return None
        if n and data < 0x10000:
            return None
        pause_cls = self.cls.get("pause", 0)
        benign_cls = self.cls.get("tutpanel", 0)
        entries = []
        for k in range(n):
            try:
                b = self.mem.rpm(data + MGR_ENTRY_SIZE * k, MGR_ENTRY_SIZE)
            except OSError:
                entries.append((0, 0, False, False, 0))
                continue
            ii = struct.unpack_from("<I", b, MGR_ENTRY_INDEX)[0]
            aux = struct.unpack_from("<I", b, MGR_ENTRY_AUX)[0]
            o = self._gua_obj(ii)
            is_pause = is_benign = False
            if o and (pause_cls or benign_cls):
                try:
                    ch = self._chain(self.mem.u64(o + UOBJECT_CLASS))
                    is_pause, is_benign = classify_stack_chain(
                        ch, pause_cls, benign_cls)
                except OSError:
                    pass
            entries.append((ii, o, is_pause, is_benign, aux))
        return (n, tuple(entries))

    def _watch_ui(self):
        """Tail-scan new GUObjectArray items for watched UI classes."""
        if not self.gua:
            return False
        try:
            cnt = self.mem.u32(self.gua + OFF_GUA_COUNT)
        except OSError:
            return False
        if self.tail_at is None or cnt < self.tail_at:
            self.tail_at = cnt
            return False
        if cnt == self.tail_at:
            return False
        if not self.watch:
            self._refresh_class_ptrs()
            if not self.watch:
                self.tail_at = cnt
                return False
        start = max(self.tail_at, cnt - TAIL_SCAN_BUDGET)
        ev = False
        idx = start
        while idx < cnt:
            chunk_no = idx >> 16
            items_here = min(0x10000 - (idx & 0xFFFF), cnt - idx)
            ct = self._ru64(self.gua + OFF_GUA_CHUNKTABLE)
            cb = self._ru64(ct + 8 * chunk_no) if ct >= 0x10000 else 0
            if cb < 0x10000:
                idx += items_here
                continue
            try:
                b = self.mem.rpm(cb + OBJ_ITEM_SIZE * (idx & 0xFFFF),
                                 items_here * OBJ_ITEM_SIZE)
            except OSError:
                break
            for j in range(items_here):
                off = j * OBJ_ITEM_SIZE
                o = struct.unpack_from("<Q", b, off)[0]
                if not o:
                    continue
                f = struct.unpack_from("<I", b, off + OBJ_ITEM_FLAGS)[0]
                if f & OBJ_ITEM_UNREACHABLE:
                    continue
                c = self._ru64(o + UOBJECT_CLASS)
                if not c:
                    continue
                ch = set(self._chain(c))
                for w, label in self.watch.items():
                    if w in ch:
                        ev = True
                        log("ui watch: new %s ii=%d obj=0x%X" % (label, idx + j, o))
                        break
            idx += items_here
        self.tail_at = cnt
        return ev

    # -- per-tick sample ------------------------------------------------------

    def sample(self, now):
        out = {"ok": False, "note": "", "pc": self.pc, "pawn": self.pawn,
               "hp": None, "clip": None, "clip2": None, "reload": False,
               "aim": False, "altfire": None, "menu_open": False,
               "ui_event": False, "stack_layer": False}
        self._tick += 1
        if self._tick % self.tail_every == 0:
            out["ui_event"] = self._watch_ui()
        if not self.gua:
            self.gua = self._ru64(self.game_base + RVA_GUOBJECTARRAY_IAT)

        if self.pc:
            try:
                self.mem.u32(self.pc + UOBJECT_FLAGS)
            except OSError:
                log("player controller no longer readable; re-scanning")
                self.pc = 0
        if not self.pc and now >= self.next_scan:
            self.next_scan = now + 5.0
            self._full_scan()
        if not self.pc:
            out["note"] = "no player controller"
            return out

        out["pc"] = self.pc
        pawn_now = self._ru64(self.pc + PC_PAWN)
        if pawn_now != self.pawn:
            self._resolve_members()
        if now - self.last_refresh > 15.0:
            self.last_refresh = now
            self._resolve_members()
        out["pawn"] = self.pawn

        # HUD-driven signals work even without a pawn (menus during loads)
        menus = self._ri32(self.hud + HUD_MENU_COUNT) if self.hud else None
        if menus is not None and menus > 0:
            out["menu_open"] = True
            out["ok"] = True
            out["note"] = "menu open (%d)" % menus
        st = self._stack()
        if st is not None:
            if any(e[2] for e in st[1]):
                out["menu_open"] = True
            # a layer = any entry that is neither a pause menu nor the
            # persistent tutorial-panel shell (e.g. a tutorial prompt)
            out["stack_layer"] = any((not e[3]) and (not e[2]) for e in st[1])
            key = (st[0], tuple((e[0], e[4], e[2], e[3]) for e in st[1]))
            if self.stack_prev is not None and key != self.stack_prev:
                out["ui_event"] = True
                names = " ".join(
                    "ii=%d%s" % (e[0], "/pause" if e[2] else
                                 ("/tut" if e[3] else "/layer"))
                    for e in st[1])
                log("screen stack changed: n=%d [%s]" % (st[0], names))
            if out["stack_layer"] != self.layer_prev:
                log("screen layer %s" % ("present -> HUD held visible"
                                         if out["stack_layer"] else "gone"))
                self.layer_prev = out["stack_layer"]
            self.stack_prev = key

        if out["menu_open"] or out["stack_layer"]:
            out["ok"] = True
            if not out["note"]:
                out["note"] = ("menu open (stack)" if out["menu_open"]
                               else "screen layer")

        if not self.pawn:
            out["note"] = out["note"] or "player has no pawn yet"
            return out

        hp = self._rf32(self.hc + HC_HP) if self.hc else None
        if hp is not None and (not (0.0 <= hp <= 100000.0)):
            hp = None
        out["hp"] = hp

        for gun_i, clip in ((1, self.clip1), (2, self.clip2)):
            if not clip:
                continue
            ammo = self._rf32(clip + CLIP_AMMO)
            if ammo is not None and not (0.0 <= ammo <= 100000.0):
                ammo = None
            out["clip" if gun_i == 1 else "clip2"] = ammo
            if self._ru8(clip + CLIP_RELOAD) == 1:
                out["reload"] = True

        aim = False
        if self.focus and (self._ri32(self.focus + FOCUS_AIM) or 0) != 0:
            aim = True
        if not aim and self.hud and (self._ru8(self.hud + HUD_AIM) or 0) != 0:
            aim = True
        out["aim"] = aim

        if self.altfire:
            b1 = self._ru8(self.altfire + ALT_BYTE1)
            b2 = self._ru8(self.altfire + ALT_BYTE2)
            fuel = self._ru8(self.altfire + ALT_FUEL)
            if b1 is not None:
                out["altfire"] = (b1 | ((b2 or 0) << 8) | ((fuel or 0) << 16))

        out["ok"] = True
        return out


class TriggerLogic:
    """Turns per-tick PlayerTracker samples into a HUD-visible decision.

    Visible while any trigger is live; hold windows are measured from the
    last observed event, so a burst of damage/shots keeps the HUD up.
    Combat is handled outside (its own hysteresis) and OR-ed in by the caller.

        health   hp float changed      -> HOLD_HEALTH window
        ammo     clip float changed    -> HOLD_AMMO window
        reload   empty byte or ammo rising -> HOLD_RELOAD window
        aim      focus aim held        -> visible while held
        alt-fire alt bytes changed     -> HOLD_ALT window
        ui       new UI object / stack change -> HOLD_UI window
        layer    non-menu, non-benign screen entry -> sustained visible
        menu     open menu -> hiding disabled (caller enforces byte 0)
    """

    def __init__(self, hp_hold=HOLD_HEALTH, ammo_hold=HOLD_AMMO,
                 reload_hold=HOLD_RELOAD, alt_hold=HOLD_ALT,
                 ui_hold=HOLD_UI, layer_sustain=True):
        self.hp_hold = hp_hold
        self.ammo_hold = ammo_hold
        self.reload_hold = reload_hold
        self.alt_hold = alt_hold
        self.ui_hold = ui_hold
        self.hp_last = None
        self.ammo_last = {}
        self.alt_last = None
        self.window = {"hp": 0.0, "ammo": 0.0, "reload": 0.0,
                       "alt": 0.0, "ui": 0.0}
        self.aim = False
        self.menu = False
        self.layer = False
        self.layer_sustain = layer_sustain

    def update(self, s, now):
        """Returns (visible, reasons)."""
        reasons = []
        self.menu = bool(s.get("menu_open")) if s.get("ok") else False
        self.layer = (bool(s.get("stack_layer"))
                      if (s.get("ok") and self.layer_sustain) else False)
        if s.get("ok"):
            hp = s.get("hp")
            if hp is not None:
                if self.hp_last is not None and abs(hp - self.hp_last) > 0.01:
                    self.window["hp"] = now + self.hp_hold
                self.hp_last = hp
            for key in ("clip", "clip2"):
                v = s.get(key)
                if v is None:
                    continue
                old = self.ammo_last.get(key)
                if old is not None and abs(v - old) > 0.001:
                    self.window["ammo"] = now + self.ammo_hold
                    if v > old:
                        self.window["reload"] = now + self.reload_hold
                self.ammo_last[key] = v
            if s.get("reload"):
                self.window["reload"] = now + self.reload_hold
            alt = s.get("altfire")
            if alt is not None:
                if self.alt_last is not None and alt != self.alt_last:
                    self.window["alt"] = now + self.alt_hold
                self.alt_last = alt
            if s.get("ui_event"):
                self.window["ui"] = now + self.ui_hold
            self.aim = bool(s.get("aim"))
        else:
            self.aim = False

        if self.menu:
            reasons.append("menu")
        if self.layer:
            reasons.append("stack")
        if self.aim:
            reasons.append("aim")
        for key, why in (("hp", "health"), ("ammo", "ammo"),
                         ("reload", "reload"), ("alt", "alt-fire"),
                         ("ui", "ui")):
            if now < self.window[key]:
                reasons.append(why)
        return (bool(reasons), reasons)


# ---------------------------------------------------------------------------
# ShaderToggler access (group toggle state)
# ---------------------------------------------------------------------------

class GroupAccess:
    """Reads/writes ShaderToggler group toggle state with direct memory writes.

    No keyboard injection of any kind: the addon's per-group toggle byte
    (record +0x110) is written directly, layout re-validated every tick.
    mode "direct": armed and writing.
    mode "none":   layout not validated (addon missing/outdated) - detection only.
    """

    def __init__(self, mem, addon_base, group_index, expected_groups=0):
        self.mem = mem
        self.addon_base = addon_base
        self.group_index = group_index
        self.expected_groups = expected_groups
        self.mode = "none"
        self.rec0 = 0
        if addon_base:
            if not self._arm():
                log("HUD control disabled (detection still runs); will keep "
                    "retrying to arm")

    def _arm(self):
        """Validate the addon layout and arm direct mode. Returns True on success."""
        why = ""
        try:
            begin = self.mem.u64(self.addon_base + ADDON_RVA_GROUPVEC_BEGIN)
            end = self.mem.u64(self.addon_base + ADDON_RVA_GROUPVEC_END)
            if not (0x10000 < begin < end):
                why = "vector pointers implausible (begin=0x%X end=0x%X)" % (begin, end)
            elif (end - begin) % REC_SIZE:
                why = "vector size not a multiple of the record stride"
            else:
                n_groups = (end - begin) // REC_SIZE
                rec = begin + self.group_index * REC_SIZE
                # both bounds: a negative or oversized index must never pass
                if not (begin <= rec <= end - REC_SIZE):
                    why = "group %d out of range (%d groups)" % (self.group_index, n_groups)
                elif not (1 <= n_groups <= 64):
                    why = "implausible group count %d" % n_groups
                elif self.expected_groups and n_groups != self.expected_groups:
                    why = "group count %d != ini AmountGroups %d" % (n_groups, self.expected_groups)
                else:
                    key = self.mem.u8(rec + REC_KEY)
                    state = self.mem.u8(rec + REC_TOGGLED)
                    if not (0x01 <= key <= 0xFE):
                        why = "implausible key byte 0x%02X (wrong layout?)" % key
                    elif state not in (0, 1):
                        why = "implausible toggle state %d" % state
                    else:
                        self.rec0 = rec
                        self.mode = "direct"
                        log("group control armed: groups=%d rec0=0x%X state=%d "
                            "(direct memory write, no key simulation)"
                            % (n_groups, rec, state))
                        return True
        except OSError as e:
            why = "read failed (%s)" % e
        log("group control not armed: %s" % why)
        return False

    def retry(self):
        """Retry arming (the addon vector can populate after attach)."""
        if self.mode != "direct" and self.addon_base:
            self._arm()

    def read_state(self):
        if self.mode == "direct":
            try:
                return self.mem.u8(self.rec0 + REC_TOGGLED)
            except OSError:
                return None
        return None

    def enforce(self, desired):
        """Make group state == desired. Returns action string ('none' = no-op)."""
        if self.mode != "direct":
            return "none"
        try:
            # re-validate the vector every tick: the addon rebuilds it when
            # groups are edited, so rec0 could otherwise dangle
            begin = self.mem.u64(self.addon_base + ADDON_RVA_GROUPVEC_BEGIN)
            end = self.mem.u64(self.addon_base + ADDON_RVA_GROUPVEC_END)
            expected = begin + self.group_index * REC_SIZE
            if not (begin <= self.rec0 <= end - REC_SIZE) or self.rec0 != expected:
                log("group vector moved; re-validating")
                if not self._arm():
                    return "none"
            actual = self.mem.u8(self.rec0 + REC_TOGGLED)
            if actual == desired:
                return "none"
            self.mem.wpm(self.rec0 + REC_TOGGLED, bytes([desired]))
            check = self.mem.u8(self.rec0 + REC_TOGGLED)
            if check != desired:
                return "write-verify-failed(%d)" % check
            return "set %d" % desired
        except OSError as e:
            self.mode = "none"
            log("group write failed (%s); control paused until re-armed" % e)
            return "none"

    def restore_visible(self):
        """Best-effort: leave the group off (HUD visible) on clean shutdown."""
        if self.mode != "direct":
            return
        try:
            if self.mem.u8(self.rec0 + REC_TOGGLED) != 0:
                self.mem.wpm(self.rec0 + REC_TOGGLED, b"\x00")
                log("restored group to visible (byte 0) on exit")
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Hysteresis + desired-state mapping
# ---------------------------------------------------------------------------

class Hysteresis:
    """Enter combat state immediately; leave only after N consecutive idle ticks."""

    def __init__(self, exit_ticks):
        self.exit_ticks = max(1, exit_ticks)
        self.idle_ticks = 0
        self.state = False

    def update(self, raw_in_fight):
        if raw_in_fight:
            self.idle_ticks = 0
            self.state = True
        else:
            self.idle_ticks += 1
            if self.idle_ticks >= self.exit_ticks:
                self.state = False
        return self.state


def desired_group_state(visible, invert, force_visible=False):
    """Group byte: 0 = HUD visible, 1 = HUD hidden.

    Default: HUD visible while any trigger is live, hidden when idle.
    --invert flips that. An open menu - and any sustained screen layer -
    disables hiding entirely and wins over both directions (byte 0).
    """
    if force_visible:
        return 0
    want_hidden = not visible
    if invert:
        want_hidden = not want_hidden
    return 1 if want_hidden else 0


# ---------------------------------------------------------------------------
# Ini helpers (AmountGroups - used to cross-check the addon's group vector)
# ---------------------------------------------------------------------------

def read_ini(path):
    # RawConfigParser: ReShade inis are plain key=value; interpolation would
    # choke on stray '%' characters
    cp = configparser.RawConfigParser()
    try:
        cp.read(path, encoding="utf-8-sig")
    except configparser.Error as e:
        log("could not parse %s: %s" % (path, e))
    amount = 0
    try:
        amount = cp.getint("General", "AmountGroups", fallback=0)
    except ValueError:
        amount = 0
    return cp, amount


def state_histogram(states):
    parts = []
    for k in sorted(states, key=lambda x: (not isinstance(x, int), x)):
        parts.append("%s:%d" % (k, states[k]))
    return " ".join(parts) if parts else "-"


# ---------------------------------------------------------------------------
# Main loops
# ---------------------------------------------------------------------------

def run_live(args, pid, game_base, addon_base, ini_path, hmq_base=0):
    """Drive one attached game session. Returns 'calibrate-done' or 'process-exited'."""
    mem = ProcessMem(pid, read_only=args.dry_run or bool(args.calibrate))
    access = None
    try:
        _, amount_groups = read_ini(ini_path)
        access = GroupAccess(mem, addon_base, args.group,
                             expected_groups=amount_groups)
        detector = CombatDetector(mem, game_base)
        tracker = PlayerTracker(mem, game_base, hmq_base)
        tracker.tail_every = max(1, int(round(1.0 / args.interval)))
        logic = TriggerLogic(layer_sustain=not args.no_stack_layers)
        exit_ticks = max(1, math.ceil(args.exit_delay / args.interval))
        hyst = Hysteresis(exit_ticks)
        heartbeat_every = max(1, int(round(10.0 / args.interval)))
        retry_every = max(1, int(round(30.0 / args.interval)))
        calibrate_until = time.time() + args.calibrate if args.calibrate else 0
        tick = 0
        last_desired = None
        log("ticking every %.1fs, exit delay %.1fs (%s): triggers -> group byte 0 = HUD on, "
            "all quiet -> 1 = HUD off; menus force HUD on%s"
            % (args.interval, args.exit_delay, "%d tick(s)" % exit_ticks,
               " [DRY RUN]" if args.dry_run else ""))

        while mem.alive():
            t0 = time.time()
            s = detector.sample()
            ps = tracker.sample(t0)
            # unknown (detector not ok) is NOT evidence of being out of combat:
            # hold the previous effective state through transient read trouble
            eff = hyst.update(s["in_fight"]) if s["ok"] else hyst.state
            vis, reasons = logic.update(ps, t0)
            menu = bool(ps.get("menu_open")) if ps.get("ok") else False
            desired = desired_group_state(eff or vis, args.invert,
                                          menu or logic.layer)

            if args.calibrate:
                line = "em=0x%X enemies=%d threat=%d states={%s} in_fight=%d" % (
                    s["em"], s["count"], s["threat"],
                    state_histogram(s["states"]), int(s["in_fight"]))
                line += (" player=%d hp=%s clip=%s/%s reload=%d aim=%d "
                         "menu=%d layer=%d ui=%d" % (
                    int(ps["ok"]), ps.get("hp"), ps.get("clip"), ps.get("clip2"),
                    int(bool(ps.get("reload"))), int(bool(ps.get("aim"))),
                    int(bool(ps.get("menu_open"))),
                    int(bool(ps.get("stack_layer"))),
                    int(bool(ps.get("ui_event")))))
                if s["note"]:
                    line += " note='%s'" % s["note"]
                if ps.get("note"):
                    line += " pnote='%s'" % ps["note"]
                log("CAL %s" % line)
                if s["ok"] and tick % 5 == 0 and s["details"]:
                    for enemy, ctrl, comp, st in s["details"][:64]:
                        if st == -1:
                            tag = "no controller"
                        elif st == -2:
                            tag = "no aggression component"
                        elif st == -3:
                            tag = "unreadable"
                        else:
                            tag = "state=%d%s" % (st, " IN-COMBAT" if st in COMBAT_STATES else "")
                        log("CAL   enemy=0x%X ctrl=0x%X comp=0x%X %s"
                            % (enemy, ctrl, comp, tag))
                if time.time() >= calibrate_until:
                    log("calibrate window finished")
                    return "calibrate-done"
            else:
                if not s["ok"] and s["note"] and tick % heartbeat_every == 0:
                    log("waiting: %s" % s["note"])
                if not ps["ok"] and ps.get("note") and tick % heartbeat_every == 0:
                    log("player: %s" % ps["note"])

            action = "none"
            if not args.dry_run and not args.calibrate:
                action = access.enforce(desired)
            elif args.dry_run:
                cur = access.read_state()
                if cur is not None and cur != desired:
                    action = "would-set %d" % desired

            rtxt = ",".join(reasons) if reasons else ("combat" if eff else "idle")
            if last_desired is None:
                log("initial state: %s, group byte target %d%s"
                    % (rtxt, desired,
                       "" if action in ("none", "would-set %d" % desired)
                       else " (%s)" % action))
                last_desired = desired
            elif desired != last_desired:
                log("HUD %s: %s (group byte %d%s)" % (
                    "visible" if desired == 0 else "hidden", rtxt, desired,
                    ", %s" % action if action != "none" else ""))
                last_desired = desired
            elif action.startswith("set"):
                log("resync: group byte -> %d (%s)" % (desired, action))

            tick += 1
            # the addon module and/or its group vector can appear after attach
            # (ReShade/OptiScaler chains load late, addons hot-reload): rescan
            if tick % retry_every == 0:
                if access.mode != "direct":
                    if not access.addon_base:
                        b = module_bases(pid, {ADDON_DLL.lower()})
                        if b and ADDON_DLL.lower() in b:
                            access.addon_base = b[ADDON_DLL.lower()]
                            log("ShaderToggler addon appeared @ 0x%X" % access.addon_base)
                    access.retry()
                if not tracker.hmq_base:
                    b = module_bases(pid, {HMQ_DLL.lower()})
                    if b and HMQ_DLL.lower() in b:
                        tracker.set_hmq_base(b[HMQ_DLL.lower()])
            if tick % heartbeat_every == 0 and not args.calibrate:
                gs = access.read_state()
                log("tick %d: enemies=%d combat=%d/%d hp=%s ammo=%s/%s reload=%d aim=%d "
                    "menus=%d layer=%d ui=%d group=%s %s" % (
                        tick, s["count"], int(s["in_fight"]), int(eff),
                        ps.get("hp"), ps.get("clip"), ps.get("clip2"),
                        int(bool(ps.get("reload"))), int(bool(ps.get("aim"))),
                        int(bool(ps.get("menu_open"))),
                        int(bool(ps.get("stack_layer"))),
                        int(bool(ps.get("ui_event"))),
                        "-" if gs is None else gs, rtxt))

            elapsed = time.time() - t0
            time.sleep(max(0.0, args.interval - elapsed))
        return "process-exited"
    finally:
        if access is not None and not (args.dry_run or args.calibrate):
            access.restore_visible()
        mem.close()


def main_loop(args):
    ini_path = os.path.join(SCRIPT_DIR, INI_FILE)
    while True:
        if args.pid and not _pid_alive(args.pid):
            log("pid %d is gone; switching to auto-detection" % args.pid)
            args.pid = 0
        pid = args.pid or find_process_id(GAME_EXE)
        if not pid:
            log("waiting for %s ..." % GAME_EXE)
            time.sleep(2.0)
            continue
        log("found %s (pid %d); waiting for game module..." % (GAME_EXE, pid))
        # only the game DLL is mandatory; the addon is polled for a while but
        # its absence must not block detection-only operation
        bases = wait_for_modules(pid, {GAME_DLL.lower()}, timeout_s=180.0)
        if not bases:
            log("game module did not appear; game may have exited")
            continue
        game_base = bases[GAME_DLL.lower()]
        log("game DLL @ 0x%X" % game_base)
        hmq_base = 0
        b = module_bases(pid, {HMQ_DLL.lower()})
        if b and HMQ_DLL.lower() in b:
            hmq_base = b[HMQ_DLL.lower()]
            log("HMQ screen DLL @ 0x%X" % hmq_base)
        addon_base = 0
        deadline = time.time() + 15.0
        while time.time() < deadline and _pid_alive(pid):
            b = module_bases(pid, {ADDON_DLL.lower()})
            if b and ADDON_DLL.lower() in b:
                addon_base = b[ADDON_DLL.lower()]
                break
            time.sleep(1.0)
        if addon_base:
            log("ShaderToggler addon @ 0x%X" % addon_base)
        else:
            log_err("ShaderToggler.addon64 is not loaded yet - HUD control disabled "
                    "for now (needs ReShade add-on support); detection runs, "
                    "re-scanning every 30 s")
        try:
            status = run_live(args, pid, game_base, addon_base, ini_path, hmq_base)
        except KeyboardInterrupt:
            log("stopped by user")
            return 0
        except OSError as e:
            log("attach failed (%s); retrying..." % e)
            time.sleep(2.0)
            continue
        if status == "calibrate-done":
            return 0
        log("game process ended; waiting for a new session...")
        time.sleep(2.0)


# ---------------------------------------------------------------------------
# Self test (offline, no game needed)
# ---------------------------------------------------------------------------

class FakeMem:
    """Dict-backed ProcessMem stand-in for offline tests."""

    def __init__(self):
        self.map = {}

    def put(self, addr, blob):
        self.map[addr] = bytes(blob)

    def put8(self, addr, val):
        self.put(addr, bytes([val & 0xFF]))

    def put32(self, addr, val):
        self.put(addr, struct.pack("<I", val & 0xFFFFFFFF))

    def put64(self, addr, val):
        self.put(addr, struct.pack("<Q", val & 0xFFFFFFFFFFFFFFFF))

    def rpm(self, addr, size):
        b = self.map.get(addr)
        if b is None or len(b) < size:
            raise OSError("fake unmapped read @0x%X" % addr)
        return b[:size]

    def wpm(self, addr, data):
        if addr not in self.map:
            raise OSError("fake unmapped write @0x%X" % addr)
        self.map[addr] = bytes(data) + self.map[addr][len(data):]

    def u8(self, addr):
        return self.rpm(addr, 1)[0]

    def u32(self, addr):
        return struct.unpack("<I", self.rpm(addr, 4))[0]

    def u64(self, addr):
        return struct.unpack("<Q", self.rpm(addr, 8))[0]


def selftest():
    failures = []

    def check(name, cond):
        print("  %-52s %s" % (name, "OK" if cond else "FAIL"))
        if not cond:
            failures.append(name)

    print("selftest:")

    h = Hysteresis(3)
    seq = [h.update(x) for x in (True, False, False, False, False)]
    check("enter immediately, exit after 3 idle ticks", seq == [True, True, True, False, False])

    h = Hysteresis(3)
    seq = [h.update(x) for x in (True, False, True, False)]
    check("re-enter resets idle counter", seq == [True, True, True, True])

    h = Hysteresis(1)
    check("exit delay 1 tick", h.update(False) is False)

    check("default: in fight -> group 0 (HUD visible)",
          desired_group_state(True, False) == 0)
    check("default: out of fight -> group 1 (HUD hidden)",
          desired_group_state(False, False) == 1)
    check("--invert flips both directions",
          desired_group_state(True, True) == 1 and desired_group_state(False, True) == 0)

    check("PROCESSENTRY32W has expected size",
          ctypes.sizeof(PROCESSENTRY32W) >= 260 * 2 + 28)
    _wb = (wintypes.WCHAR * 16)("g", "a", "m", "e", ".", "d", "l", "l", "\0")
    check("wchar_str returns text (regression: str() gives repr)",
          wchar_str(_wb) == "game.dll")

    ini_path = os.path.join(SCRIPT_DIR, INI_FILE)
    if os.path.exists(ini_path):
        cp, amount = read_ini(ini_path)
        check("ini AmountGroups parsed", amount >= 1)
        # soft, user-configurable facts: warn, do not fail (keys are no longer
        # used by the tool at all - this is only informational for packaging)
        try:
            raw0 = cp.getint("Group0", "ToggleKey", fallback=0)
        except ValueError:
            raw0 = 0
        vk0 = (raw0 >> 24) & 0xFF
        if not (0x01 <= vk0 <= 0xFE):
            print("  note: Group0 ToggleKey parses to VK%02X - odd, but unused "
                  "by this tool" % vk0)
        check("ini Group0 section present", cp.has_section("Group0"))
    else:
        print("  (ini not found - skipping ini checks)")

    check("histogram formatting", state_histogram(Counter({4: 1, 5: 2})) == "4:1 5:2")
    check("offset sanity: EM data/count", EM_ENEMIES_COUNT - EM_ENEMIES_DATA == 8)
    check("offset sanity: record toggled byte", REC_TOGGLED == 0x110 and REC_SIZE == 280)

    # --- GroupAccess bounds (regression for out-of-vector group index) ---
    gm = FakeMem()
    ADDON = 0x180000000
    BEGIN = 0x1000000
    NREC = 2
    gm.put64(ADDON + ADDON_RVA_GROUPVEC_BEGIN, BEGIN)
    gm.put64(ADDON + ADDON_RVA_GROUPVEC_END, BEGIN + NREC * REC_SIZE)
    for i in range(NREC):
        base = BEGIN + i * REC_SIZE
        gm.put8(base + REC_KEY, 0x70)
        gm.put8(base + REC_TOGGLED, 0)

    ga = GroupAccess(gm, ADDON, -1, expected_groups=NREC)
    check("negative --group rejected (no direct mode)", ga.mode != "direct")
    ga = GroupAccess(gm, ADDON, NREC + 3, expected_groups=NREC)
    check("oversized --group rejected (no direct mode)", ga.mode != "direct")
    ga = GroupAccess(gm, ADDON, 0, expected_groups=NREC)
    check("valid --group arms direct mode", ga.mode == "direct")
    check("direct rec0 points at first record", ga.rec0 == BEGIN)
    act = ga.enforce(1)
    check("direct enforce writes toggle byte", act == "set 1" and gm.u8(BEGIN + REC_TOGGLED) == 1)
    act = ga.enforce(1)
    check("idempotent enforce is a no-op", act == "none")
    ga.restore_visible()
    check("restore_visible resets byte to 0", gm.u8(BEGIN + REC_TOGGLED) == 0)
    ga_bad = GroupAccess(gm, ADDON, 0, expected_groups=NREC + 99)
    check("ini/record group-count mismatch rejected", ga_bad.mode != "direct")

    # --- CombatDetector: EM selection + combat chain over a fake heap ---
    dm = FakeMem()
    GAME = 0x140000000
    GUA = 0x2000000
    CT = 0x3000000
    CH = 0x4000000
    CLS = 0x90000000
    STALE, CDO, FRESH = 0xA000000, 0xA100000, 0xA200000
    EARR = 0x6000000
    ENEMY = 0x7000000
    CTRL = 0x8000000
    COMP = 0x9000000

    dm.put64(GAME + RVA_GUOBJECTARRAY_IAT, GUA)
    dm.put64(GUA + OFF_GUA_CHUNKTABLE, CT)
    dm.put32(GUA + OFF_GUA_COUNT, 3)
    dm.put64(CT, CH)
    item = struct.pack("<QIIII", STALE, 0, 0, 0, 0) \
        + struct.pack("<QIIII", CDO, 0, 0, 0, 0) \
        + struct.pack("<QIIII", FRESH, 0, 0, 0, 0)
    dm.put(CH, item)
    dm.put64(GAME + RVA_ENEMYMANAGER_CLASS, CLS)

    def make_em(addr, internal, data, count):
        dm.put64(addr + UOBJECT_CLASS, CLS)
        dm.put32(addr + UOBJECT_INTERNAL_INDEX, internal)
        dm.put64(addr + EM_ENEMIES_DATA, data)
        dm.put32(addr + EM_ENEMIES_COUNT, count)

    make_em(STALE, 5, EARR, 2)      # stale but structurally intact
    make_em(CDO, 1, 0, 0)           # class default object
    make_em(FRESH, 9, EARR, 1)      # live instance (highest index)
    dm.put32(FRESH + EM_AUDIO_THREAT, 7)
    dm.put64(EARR, ENEMY)           # enemies TArray buffer
    dm.put64(ENEMY + ENEMY_CONTROLLER, CTRL)
    dm.put64(CTRL + CTRL_AGGR_COMP, COMP)
    dm.put8(COMP + AGGR_STATE, 5)   # EAS_InCombat

    det = CombatDetector(dm, GAME)
    s = det.sample()
    check("detector picks the newest valid EM (not CDO/stale)", det.em == FRESH)
    check("combat chain: state 5 -> in_fight", s["ok"] and s["in_fight"])
    check("enemy histogram reports one enemy", s["count"] == 1 and s["states"] == Counter({5: 1}))

    dm.put8(COMP + AGGR_STATE, 1)   # EAS_Unaware
    det.em = None                   # force rescan
    s = det.sample()
    check("state 1 -> out of fight", s["ok"] and not s["in_fight"])

    # count/pointer mismatch must be 'unknown', not 'idle' (M8)
    broken = FakeMem()
    broken.put64(GAME + RVA_ENEMYMANAGER_CLASS, CLS)
    broken.put64(FRESH + UOBJECT_CLASS, CLS)
    broken.put32(FRESH + UOBJECT_INTERNAL_INDEX, 9)
    broken.put64(FRESH + EM_ENEMIES_DATA, 0)
    broken.put32(FRESH + EM_ENEMIES_COUNT, 3)
    det2 = CombatDetector(broken, GAME)
    det2.em = FRESH
    s2 = det2.sample()
    check("count>0 with null data -> not ok (held, not idle)",
          not s2["ok"] and "mismatch" in s2["note"])

    # --- menu override + TriggerLogic hold windows ---------------------------
    check("menu open forces HUD visible even with --invert",
          desired_group_state(True, True, True) == 0
          and desired_group_state(False, False, True) == 0)
    check("menu closed keeps invert semantics",
          desired_group_state(True, True, False) == 1
          and desired_group_state(False, False, False) == 1)

    tl = TriggerLogic(hp_hold=3.0, ammo_hold=3.0, reload_hold=2.0,
                      alt_hold=4.0, ui_hold=6.0)
    v, r = tl.update({"ok": True, "aim": False}, 100.0)
    check("idle sample -> not visible", not v and not r)
    v, r = tl.update({"ok": True, "aim": True}, 101.0)
    check("focus aim held -> visible immediately", v and "aim" in r)
    v, _ = tl.update({"ok": True, "aim": False}, 102.0)
    check("aim released -> hidden again", not v)

    tl = TriggerLogic()
    tl.update({"ok": True, "hp": 2.0}, 0.0)
    v, r = tl.update({"ok": True, "hp": 1.0}, 1.0)
    check("hp drop -> visible (reason health)", v and "health" in r)
    v, _ = tl.update({"ok": True, "hp": 1.0}, 3.5)
    check("hp hold window (3 s) keeps HUD up", v)
    v, _ = tl.update({"ok": True, "hp": 1.0}, 4.5)
    check("hp window expires -> hidden", not v)

    tl = TriggerLogic()
    tl.update({"ok": True, "clip": 12.0}, 0.0)
    v, r = tl.update({"ok": True, "clip": 8.0}, 0.5)
    check("ammo drop -> visible (reason ammo)", v and "ammo" in r)
    v, _ = tl.update({"ok": True, "clip": 8.0}, 10.0)
    check("ammo window expires -> hidden", not v)

    tl = TriggerLogic()
    tl.update({"ok": True, "clip": 3.0}, 0.0)
    v, r = tl.update({"ok": True, "clip": 4.0}, 0.5)
    check("ammo rising -> reload reason too", v and "reload" in r and "ammo" in r)
    v, r = tl.update({"ok": True, "reload": True}, 2.0)
    check("empty/reloading byte -> visible (reason reload)", v and "reload" in r)

    tl = TriggerLogic()
    tl.update({"ok": True, "altfire": 0}, 0.0)
    v, r = tl.update({"ok": True, "altfire": 256}, 1.0)
    check("alt-fire byte change -> visible (reason alt-fire)",
          v and "alt-fire" in r)
    v, _ = tl.update({"ok": True, "altfire": 256}, 2.0)
    check("constant alt-fire byte alone does not re-trigger", v)
    v, _ = tl.update({"ok": True, "altfire": 256}, 6.0)
    check("alt-fire window expires -> hidden", not v)

    tl = TriggerLogic()
    v, r = tl.update({"ok": True, "ui_event": True}, 0.0)
    check("ui event -> visible (reason ui)", v and "ui" in r)
    v, _ = tl.update({"ok": True}, 3.0)
    check("ui window (6 s) keeps HUD up", v)
    v, _ = tl.update({"ok": True}, 7.0)
    check("ui window expires -> hidden", not v)

    v, r = tl.update({"ok": True, "menu_open": True}, 8.0)
    check("menu open -> visible (reason menu)", v and "menu" in r)

    v, r = tl.update({"ok": True, "stack_layer": True}, 9.0)
    check("screen layer -> visible (reason stack)", v and "stack" in r)
    v, r = tl.update({"ok": True, "stack_layer": True}, 40.0)
    check("screen layer sustains visibility (no window expiry)",
          v and "stack" in r)
    v, r = tl.update({"ok": True, "stack_layer": False}, 41.0)
    check("layer gone -> idle again", not v)
    tln = TriggerLogic(layer_sustain=False)
    v, _ = tln.update({"ok": True, "stack_layer": True}, 0.0)
    check("--no-stack-layers ignores layers", not v)

    check("screen layer forces byte 0 even with --invert",
          desired_group_state(False, True, True) == 0)
    check("stack classify: pause chain",
          classify_stack_chain([5, 7, 9], 7, 8) == (True, False))
    check("stack classify: tutorial-panel chain is benign",
          classify_stack_chain([5, 8, 9], 7, 8) == (False, True))
    check("stack classify: unknown chain = layer, no flags",
          classify_stack_chain([5, 9], 7, 8) == (False, False))

    check("offset sanity: player chain", PC_PAWN == 0x330 and PC_HUD == 0x390
          and CLIP_AMMO == 0x1A8 and CLIP_RELOAD == 0x1B4
          and HUD_MENU_COUNT == 0x4BC and FOCUS_AIM == 0x198)

    # --- PlayerTracker: discovery + signals over a fake heap -----------------
    pm = FakeMem()
    P_GAME = 0x140000000
    P_GUA = 0x2100000
    P_CT = 0x3100000
    P_CH = 0x4100000
    BASE_PC, BP_PC = 0xAA000, 0xAA100
    BASE_HC, BP_HC = 0xBB000, 0xBB100
    BASE_HUD, BP_HUD = 0xCC000, 0xCC100
    BASE_GUN, BP_GUN = 0xEE000, 0xEE100
    BASE_CLIP, BP_CLIP = 0xDD000, 0xDD100
    CDO_PC, PC = 0xA100000, 0xA200000
    PAWN, HC, HUD, GUN, CLIP = (0xB000000, 0xB100000, 0xB200000,
                                0xB300000, 0xB400000)

    pm.put64(P_GAME + RVA_GUOBJECTARRAY_IAT, P_GUA)
    pm.put64(P_GUA + OFF_GUA_CHUNKTABLE, P_CT)
    pm.put32(P_GUA + OFF_GUA_COUNT, 7)
    pm.put64(P_CT, P_CH)
    pm.put(P_CH, b"".join(
        struct.pack("<QIIII", a, f, 0, 0, 0)
        for a, f in ((CDO_PC, 0x10), (PC, 0), (PAWN, 0), (HC, 0),
                     (HUD, 0), (GUN, 0), (CLIP, 0))))
    pm.put64(P_GAME + RVA_CLASS_TOURISTPC, BASE_PC)
    pm.put64(P_GAME + RVA_CLASS_HEALTHCOMP, BASE_HC)
    pm.put64(P_GAME + RVA_CLASS_TOURISTHUD, BASE_HUD)
    pm.put64(P_GAME + RVA_CLASS_GUNBASE, BASE_GUN)
    pm.put64(P_GAME + RVA_CLASS_WEAPONCLIP, BASE_CLIP)
    pm.put64(BP_PC + UCLASS_SUPER, BASE_PC)
    pm.put64(BP_HC + UCLASS_SUPER, BASE_HC)
    pm.put64(BP_HUD + UCLASS_SUPER, BASE_HUD)
    pm.put64(BP_GUN + UCLASS_SUPER, BASE_GUN)
    pm.put64(BP_CLIP + UCLASS_SUPER, BASE_CLIP)
    pm.put64(CDO_PC + UOBJECT_CLASS, BP_PC)
    pm.put32(CDO_PC + UOBJECT_FLAGS, 0x10)
    pm.put64(PC + UOBJECT_CLASS, BP_PC)
    pm.put32(PC + UOBJECT_FLAGS, 0)
    pm.put64(PC + PC_PAWN, PAWN)
    pm.put64(PC + PC_HUD, HUD)
    pm.put64(PAWN + PAWN_HEALTH, HC)
    pm.put64(PAWN + PAWN_GUN1, GUN)
    pm.put64(HC + UOBJECT_CLASS, BP_HC)
    pm.put64(HUD + UOBJECT_CLASS, BP_HUD)
    pm.put64(GUN + UOBJECT_CLASS, BP_GUN)
    pm.put64(GUN + GUN_CLIP, CLIP)
    pm.put64(CLIP + UOBJECT_CLASS, BP_CLIP)
    pm.put(HC + HC_HP, struct.pack("<f", 2.0))
    pm.put(CLIP + CLIP_AMMO, struct.pack("<f", 12.0))
    pm.put8(CLIP + CLIP_RELOAD, 0)

    tr = PlayerTracker(pm, P_GAME)
    s = tr.sample(0.0)
    check("tracker skips the CDO and finds the live PC", s["ok"] and tr.pc == PC)
    check("tracker resolves pawn/health/hud/gun/clip chains",
          tr.pawn == PAWN and tr.hc == HC and tr.clip1 == CLIP and tr.hud == HUD)
    check("tracker reads hp + ammo floats", s["hp"] == 2.0 and s["clip"] == 12.0)
    check("tracker: idle sample -> no triggers",
          not s["reload"] and not s["aim"] and not s["menu_open"]
          and not s["ui_event"])

    pm.put32(HUD + HUD_MENU_COUNT, 1)
    s = tr.sample(1.0)
    check("menu counter -> menu_open", s["menu_open"])
    pm.put32(HUD + HUD_MENU_COUNT, 0)
    pm.put8(HUD + HUD_AIM, 1)
    s = tr.sample(2.0)
    check("HUD aim byte -> aim", s["aim"])
    pm.put8(HUD + HUD_AIM, 0)
    pm.put8(CLIP + CLIP_RELOAD, 1)
    s = tr.sample(3.0)
    check("clip reload byte -> reload", s["reload"])

    if failures:
        print("selftest: %d FAILURES: %s" % (len(failures), failures))
        return 1
    print("selftest: all checks passed")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="Dynamic Returnal HUD via ShaderToggler (trigger-state driven).")
    ap.add_argument("--interval", type=float, default=0.2,
                    help="reaction/poll interval in seconds (default: 0.2); "
                         "expensive ui tail scans stay ~1 s")
    ap.add_argument("--exit-delay", type=float, default=3.0,
                    help="seconds out of combat before hiding the HUD (default: 3.0)")
    ap.add_argument("--group", type=int, default=0,
                    help="ShaderToggler group index to drive (default: 0 = 'Toggle HUD')")
    ap.add_argument("--invert", action="store_true",
                    help="reverse direction (HUD hidden in fights, visible outside)")
    ap.add_argument("--no-stack-layers", action="store_true",
                    help="ignore screen-stack layers (e.g. tutorial prompt "
                         "banners) as a sustained HUD-on reason; they then "
                         "only raise the short ui window when they change")
    ap.add_argument("--dry-run", action="store_true",
                    help="detect and log only; never write memory")
    ap.add_argument("--calibrate", type=float, nargs="?", const=60.0, default=0.0,
                    help="dump detailed detection info for N seconds (default 60), no writes")
    ap.add_argument("--pid", type=int, default=0,
                    help="attach to a specific pid instead of auto-detect")
    ap.add_argument("--version", action="version",
                    version="hud_dynamic %s" % VERSION)
    ap.add_argument("--selftest", action="store_true",
                    help="run offline logic tests and exit")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if args.interval < 0.05:
        ap.error("--interval below 0.05s is not supported")
    if not (0 <= args.group < 64):
        ap.error("--group must be between 0 and 63")
    try:
        return main_loop(args) or 0
    except KeyboardInterrupt:
        log("stopped by user")
        return 0


if __name__ == "__main__":
    sys.exit(main())
