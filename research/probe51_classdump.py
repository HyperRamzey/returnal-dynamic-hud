"""probe51_classdump.py - generic UClass + instance dump for trigger RE.

PROBE51_CLASSES="AltFireComponent,InteractionManagerComponent" (comma list)
For each class: UClass object(s), property list (name@offset via FField walk),
up to 4 instances: name/class/outer/owner + keyword field values + hex window.
"""
import ctypes
import os
import struct
import sys
import time

import hud_dynamic as h

CORE_DLL = "Returnal-Core-Win64-Shipping.dll"
BLOCKS_RVA = 0x5C2950
GUA_IAT_RVA = 0x8A15B0
WANT = [c.strip() for c in os.environ.get(
    "PROBE51_CLASSES", "AltFireComponent,InteractionManagerComponent").split(",")
    if c.strip()]
OUTLOG = r"C:\Users\admin\AppData\Local\Temp\opencode\probe51.out"

_lf = open(OUTLOG, "a", encoding="utf-8")


def say(*a):
    s = " ".join(str(x) for x in a)
    print(s.encode("cp1252", "replace").decode("cp1252"), flush=True)
    _lf.write(s + "\n")
    _lf.flush()


say("=== probe51 %s want=%s ===" % (time.strftime("%Y-%m-%d %H:%M:%S"), WANT))

pid = h.find_process_id(h.GAME_EXE)
bases = h.module_bases(pid, {CORE_DLL.lower(), h.GAME_DLL.lower()})
core = bases.get(CORE_DLL.lower())
game = bases.get(h.GAME_DLL.lower())
say("pid=%d core=0x%X game=0x%X" % (pid, core or 0, game or 0))
if not (core and game):
    sys.exit(1)

k32 = ctypes.windll.kernel32
k32.OpenProcess.restype = ctypes.c_void_p
k32.OpenProcess.argtypes = [ctypes.c_uint, ctypes.c_int, ctypes.c_uint]
k32.ReadProcessMemory.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                  ctypes.c_void_p, ctypes.c_size_t,
                                  ctypes.POINTER(ctypes.c_size_t)]
H = k32.OpenProcess(0x0410, 0, pid)
assert H, "OpenProcess failed"
_RB = ctypes.create_string_buffer(0x10000)
_BIG = ctypes.create_string_buffer(4 << 20)


def rpm(a, n):
    buf = _BIG if n > 0x10000 else _RB
    got = ctypes.c_size_t(0)
    if (not k32.ReadProcessMemory(H, ctypes.c_void_p(a), buf, n,
                                  ctypes.byref(got)) or got.value != n):
        raise OSError("rpm fail 0x%X n=%d" % (a, n))
    return buf.raw[:n]


def u8(a):
    return rpm(a, 1)[0]


def u32(a):
    return struct.unpack("<I", rpm(a, 4))[0]


def u64(a):
    return struct.unpack("<Q", rpm(a, 8))[0]


def f32(a):
    return struct.unpack("<f", rpm(a, 4))[0]


def okp(p):
    return 0x10000 <= p < 0x7FFFFFFFFFFF


# ---- GNames ----
BLOCKS0 = core + BLOCKS_RVA
CB = u32(BLOCKS0 - 8)
CUR = u32(BLOCKS0 - 4)
IDS = {}
for B in range(CB + 1):
    blk = u64(BLOCKS0 + 8 * B)
    if blk < 0x10000:
        continue
    size = 0x20000 if B != CB else min(CUR, 0x20000)
    try:
        data = rpm(blk, size)
    except OSError:
        continue
    off = 0
    while off + 2 <= size:
        hdr = struct.unpack_from("<H", data, off)[0]
        ln = hdr >> 6
        if ln == 0 or ln > 1023:
            break
        wide = hdr & 1
        nb = ln * (2 if wide else 1)
        if off + 2 + nb > size:
            break
        raw = data[off + 2: off + 2 + nb]
        nm = (raw.decode("utf-16-le", "replace") if wide
              else raw.decode("latin-1", "replace")).split("\x00")[0]
        IDS[(B << 16) | (off >> 1)] = nm
        off += (2 + nb + 1) & ~1
say("names: %d" % len(IDS))


def oname(o):
    try:
        return IDS.get(u32(o + 0x18), "?")
    except OSError:
        return "?"


# ---- GObjects scan ----
gua = u64(game + GUA_IAT_RVA)
ctab = u64(gua + 0x10)
cnt = u32(gua + 0x24)
say("GUA 0x%X cnt=%d" % (gua, cnt))
objs = {w: {"cls": [], "inst": []} for w in WANT}
buf = None
cur_ch = -1
for i in range(cnt):
    ch = i >> 16
    if ch != cur_ch:
        cur_ch = ch
        cbase = u64(ctab + 8 * ch)
        buf = None
        if okp(cbase):
            try:
                buf = rpm(cbase, 65536 * 24)
            except OSError:
                buf = None
    if buf is None:
        continue
    off = (i & 0xFFFF) * 24
    flags = struct.unpack_from("<I", buf, off + 8)[0]
    if flags & 0x20000000:
        continue
    obj = struct.unpack_from("<Q", buf, off)[0]
    if not okp(obj):
        continue
    try:
        nm = IDS.get(u32(obj + 0x18))
        if not nm:
            continue
        c = u64(obj + 0x10)
        cn = IDS.get(u32(c + 0x18), "?") if okp(c) else "?"
    except OSError:
        continue
    for w in WANT:
        if nm == w and cn in ("Class", "BlueprintGeneratedClass"):
            objs[w]["cls"].append(obj)
        elif cn == w and not nm.startswith("Default__"):
            objs[w]["inst"].append(obj)

KEYS = ("fuel", "cool", "ready", "mode", "firing", "ammo", "timer",
        "altfire", "owner", "interact", "prompt")


def props(cls):
    out = []
    try:
        cp = u64(cls + 0x50)
    except OSError:
        return out
    guard = 0
    while okp(cp) and guard < 400:
        try:
            nm = IDS.get(u32(cp + 0x28), "?")
            off = u32(cp + 0x4C)
        except OSError:
            break
        out.append((nm, off))
        try:
            cp = u64(cp + 0x20)
        except OSError:
            break
        guard += 1
    return out


def hexwin(base, a, n):
    try:
        d = rpm(a, n)
    except OSError as e:
        say("    hex fail %s" % e)
        return
    for i in range(0, n, 16):
        say("    +%03X  %s" % (base + i - base, " ".join("%02X" % b for b in d[i:i + 16])))


for w in WANT:
    r = objs[w]
    say("[%s] classes=%d instances=%d" % (w, len(r["cls"]), len(r["inst"])))
    for c in r["cls"][:2]:
        pl = props(c)
        say("  UCLASS 0x%X name=%s props=%d" % (c, oname(c), len(pl)))
        line = ["%s@%X" % (nm, off) for nm, off in pl]
        for i in range(0, len(line), 5):
            say("    " + " ".join(line[i:i + 5]))
        r["props"] = pl
    for o in r["inst"][:4]:
        cn = oname(u64(o + 0x10))
        outer = u64(o + 0x20)
        say("  INST 0x%X name=%s outer=0x%X(%s)" % (o, oname(o), outer, oname(outer)))
        for nm, off in r.get("props", []):
            low = nm.lower()
            if not any(k in low for k in KEYS) or off > 0x600:
                continue
            try:
                b = rpm(o + off, 8)
                v64 = struct.unpack("<Q", b)[0]
                vi = struct.unpack("<I", b)[0]
                vf = struct.unpack("<f", b)[0]
                say("    %s@%X = Q:%X I:%d F:%.4f B0:%d" % (nm, off, v64, vi, vf, b[0]))
            except OSError:
                pass
        if w == "AltFireComponent":
            say("    hex 0x260..0x360:")
            hexwin(0x260, o + 0x260, 0x100)
say("done")
