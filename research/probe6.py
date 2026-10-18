"""probe6: live watcher - component discovery on pawn + timed state logging."""
import struct, sys, time
sys.path.insert(0, ".")
import hud_dynamic as h

pid = h.find_process_id(h.GAME_EXE)
gb = h.module_bases(pid, {h.GAME_DLL.lower()})[h.GAME_DLL.lower()]
mem = h.ProcessMem(pid, read_only=True)


def u64(a):
    return mem.u64(a)


def u8(a):
    return mem.u8(a)


def i32(a):
    return struct.unpack("<i", mem.rpm(a, 4))[0]


def f32(a):
    return struct.unpack("<f", mem.rpm(a, 4))[0]


RVA = {
    "ATouristPlayerController": 0xF6F168,
    "AFirstPersonPlayerCharacter": 0xF5E948,
    "ATouristCharacter": 0xF6C4C8,
    "UHealthComponent": 0xF5FAF8,
    "UAltFireComponent": 0xF57B90,
    "UFocusAimComponent": 0xF5EBE0,
    "UGunComponent": 0xF5F558,
    "UReloadingClip": 0xF68360,
    "UOverheatingClip": 0xF64878,
    "UGunClip": 0xF5F3B8,
    "ATouristHUD": 0xF6EB10,
    "UTouristScreenManager": 0xF6FED8,
    "UPauseMenu": 0xF64B88,
    "UCrosshairWidget": 0xF5BA58,
    "UTouristTutorialWidget": 0xF704A0,
    "UPlayerHUDInfo": 0xF67038,
}
bases = {}
for nm, rva in RVA.items():
    bases[u64(gb + rva)] = nm


def chain(c, limit=20):
    out = []
    for _ in range(limit):
        if not c:
            break
        out.append(c)
        try:
            c = u64(c + 0x30)
        except OSError:
            break
    return out


SCAN_TARGETS = (
    "UHealthComponent", "UFocusAimComponent", "UAltFireComponent", "UGunComponent",
    "UReloadingClip", "UOverheatingClip", "UGunClip",
    "ATouristHUD", "UPlayerHUDInfo", "UPauseMenu", "UTouristTutorialWidget",
)


def comp_scan(obj, span=0x2800):
    found = []
    try:
        raw = mem.rpm(obj, span)
    except OSError:
        return found
    for off in range(0, len(raw) - 8, 8):
        p = struct.unpack_from("<Q", raw, off)[0]
        if p < 0x10000 or p > 0x7FFFFFFFFFFF:
            continue
        try:
            c = u64(p + 0x10)
        except OSError:
            continue
        if c < 0x10000:
            continue
        nm = None
        for b in chain(c, 14):
            if b in bases:
                nm = bases[b]
                break
        if nm in SCAN_TARGETS:
            found.append((nm, off, p))
    return found


PC = 0x3D13D4B60
try:
    PAWN = u64(PC + 0x330)
except OSError:
    PAWN = 0
print("PC=0x%X PAWN=0x%X" % (PC, PAWN))

outs = {}
scans = [("pawn", PAWN)]
if PC:
    scans.append(("pc", PC))
for tag, obj in scans:
    if not obj:
        continue
    hits = comp_scan(obj)
    print("--- scan %s 0x%X: %d comps" % (tag, obj, len(hits)))
    for nm, off, p in hits:
        print("    %s+0x%X -> %-24s 0x%X" % (tag, off, nm, p))
        outs.setdefault(nm, p)
        try:
            o = u64(p + 0x20)
        except OSError:
            o = 0
        if o > 0x10000:
            for nm2, off2, p2 in comp_scan(o, 0x1800):
                if nm2 not in outs:
                    outs[nm2] = p2
                    print("    (via outer 0x%X) -> %-24s 0x%X" % (o, nm2, p2))

HC = outs.get("UHealthComponent")
FOC = outs.get("UFocusAimComponent")
ALT = outs.get("UAltFireComponent")
GUN = outs.get("UGunComponent")
RCLIP = outs.get("UReloadingClip")
OCLIP = outs.get("UOverheatingClip")
GCLIP = outs.get("UGunClip")
HUD = outs.get("ATouristHUD")
HI = outs.get("UPlayerHUDInfo")
PM = outs.get("UPauseMenu")
TUT = outs.get("UTouristTutorialWidget")

if HI is None and PC:
    try:
        hi = u64(PC + 0x798)
        if hi > 0x10000:
            HI = hi
            print("HUDInfo via pc+0x798 = 0x%X" % hi)
    except OSError:
        pass

if HI:
    print("--- HUDInfo 0x%X first 0x100 bytes ---" % HI)
    try:
        raw = mem.rpm(HI, 0x100)
        for row in range(0, 0x100, 16):
            fs = struct.unpack_from("<4f", raw, row)
            print("  +0x%03X f: %s" % (row, " ".join("%.3f" % x if abs(x) < 1e8 else "big" for x in fs)))
    except OSError:
        pass

M1 = 0x3BB653A00
M2 = 0x3C2B6B200
HUD1 = 0x3D3A79580
HUD2 = 0x3AEFD9E80


def topname(M):
    try:
        n = i32(M + 0x138)
        if n <= 0 or n > 64:
            return n, 0
        base = u64(M + 0x130)
        ent = base + 24 * (n - 1)
        fn = struct.unpack("<I", mem.rpm(ent, 4))[0]
        return n, fn
    except OSError:
        return -999, 0


def line():
    parts = []
    parts.append("pc=%X" % PC)
    if PAWN:
        try:
            parts.append("pawn=%X" % u64(PC + 0x330))
        except OSError:
            parts.append("pawn=gone")
    if HC:
        try:
            parts.append("hp=%.1f/%d" % (f32(HC + 0x2AC), u8(HC + 0x2A8)))
        except OSError:
            parts.append("hp=gone")
    if FOC:
        try:
            parts.append("fox=%d,%d" % (u8(FOC + 0x179), u8(FOC + 0x17A)))
        except OSError:
            pass
    if ALT:
        try:
            parts.append("alt=%d,%d,%d fl=%d" % (u8(ALT + 0x271), u8(ALT + 0x272),
                                                 u8(ALT + 0x273), u8(ALT + 0x27C)))
        except OSError:
            pass
    if RCLIP:
        try:
            parts.append("rclip=%d,%d,%d" % (i32(RCLIP + 0x294), i32(RCLIP + 0x29C), u8(RCLIP + 0x2A4)))
        except OSError:
            pass
    if OCLIP:
        try:
            parts.append("oclip=%d cool=%d,%d" % (i32(OCLIP + 0x294), u8(OCLIP + 0x2CF), u8(OCLIP + 0x2CD)))
        except OSError:
            pass
    if GCLIP:
        try:
            parts.append("gclip=%d" % i32(GCLIP + 0x294))
        except OSError:
            pass
    n1, f1 = topname(M1)
    parts.append("M1=%d(%d)" % (n1, f1))
    n2, f2 = topname(M2)
    parts.append("M2=%d(%d)" % (n2, f2))
    for tag, HD in (("hud1", HUD1), ("hud2", HUD2)):
        if HD:
            try:
                parts.append("%s.420=%X" % (tag, u64(HD + 0x420)))
            except OSError:
                pass
    if PM:
        try:
            parts.append("pm=%X" % PM)
        except OSError:
            pass
    if TUT:
        try:
            parts.append("tut=1" % ())
        except Exception:
            pass
    return " ".join(parts)


print("start watch")
t0 = time.time()
while time.time() - t0 < 240:
    ts = time.time() - t0
    try:
        print("%7.1f %s" % (ts, line()))
    except OSError as e:
        print("%7.1f ERR %s" % (ts, e))
    sys.stdout.flush()
    time.sleep(0.5)
print("done")
