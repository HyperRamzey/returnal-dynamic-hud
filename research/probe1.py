"""One-shot live probe: resolve classes + read all candidate HUD-trigger state."""
import struct, sys, time
sys.path.insert(0, ".")
import hud_dynamic as h

game_dll_rvas = {
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

pid = h.find_process_id(h.GAME_EXE)
print("pid:", pid)
gb = h.module_bases(pid, {h.GAME_DLL.lower()})[h.GAME_DLL.lower()]
print("game base: 0x%X" % gb)
mem = h.ProcessMem(pid, read_only=True)

cls = {}
for name, rva in game_dll_rvas.items():
    v = mem.u64(gb + rva)
    cls[name] = v
    print("class %-30s -> 0x%X" % (name, v))

want = {v: k for k, v in cls.items() if v}
inst = {k: [] for k in cls}
gua = mem.u64(gb + h.RVA_GUOBJECTARRAY_IAT)
chunk_table = mem.u64(gua + h.OFF_GUA_CHUNKTABLE)
count = mem.u32(gua + h.OFF_GUA_COUNT)
print("GUObjectArray: 0x%X count=%d" % (gua, count))
t0 = time.time()
idx = 0
cache = {}
while idx < count:
    cn = idx >> 16
    if cn not in cache:
        try:
            cache[cn] = mem.u64(chunk_table + 8 * cn)
        except OSError:
            cache[cn] = 0
    cb = cache[cn]
    here = min(0x10000, count - (cn << 16))
    if cb >= 0x10000:
        try:
            raw = mem.rpm(cb, here * 24)
        except OSError:
            raw = None
        if raw:
            for j in range(here):
                off = j * 24
                obj = struct.unpack_from("<Q", raw, off)[0]
                if not obj:
                    continue
                if struct.unpack_from("<I", raw, off + 8)[0] & 0x20000000:
                    continue
                try:
                    c = mem.u64(obj + 0x10)
                except OSError:
                    continue
                nm = want.get(c)
                if nm:
                    inst[nm].append(obj)
    idx = (cn + 1) << 16
print("scan done in %.2fs" % (time.time() - t0))

for k in cls:
    objs = inst[k]
    print("%-30s instances=%d %s" % (k, len(objs), [hex(o) for o in objs[:6]]))

def f32(a):
    return struct.unpack("<f", mem.rpm(a, 4))[0]

def i32(a):
    return struct.unpack("<i", mem.rpm(a, 4))[0]

def newest(objs):
    best, bk = None, -1
    for o in objs:
        try:
            fl = mem.u32(o + 8)
        except OSError:
            continue
        if fl & 0x10:          # CDO
            continue
        ii = mem.u32(o + 0x0C)
        if ii > bk:
            bk, best = ii, o
    return best

PC = newest(inst["ATouristPlayerController"])
CH = newest(inst["AFirstPersonPlayerCharacter"])
print()
print("controller: 0x%X  character: 0x%X" % (PC or 0, CH or 0))

if PC:
    print("PC+0x798 (HUDInfo ptr): 0x%X" % mem.u64(PC + 0x798))
    print("PC pause-ish bytes: +0x820=%d +0x870=%d +0x678=%d +0x779=%d +0x77B=%d +0x800=%d +0x802=%d" % (
        mem.u8(PC + 0x820), mem.u8(PC + 0x870), mem.u8(PC + 0x678),
        mem.u8(PC + 0x779), mem.u8(PC + 0x77B), mem.u8(PC + 0x800), mem.u8(PC + 0x802)))
    print("PC ints: +0x828=%d +0x854=%d" % (i32(PC + 0x828), i32(PC + 0x854)))
    hid = mem.u64(PC + 0x798)
    if hid:
        print("--- PlayerHUDInfo 0x%X first 0x100 bytes ---" % hid)
        raw = mem.rpm(hid, 0x100)
        for row in range(0, 0x100, 16):
            fs = struct.unpack_from("<4f", raw, row)
            print("  +0x%03X  f: %-32s %s" % (row, " ".join("%.3f" % x for x in fs),
                  " ".join("%08X" % struct.unpack_from("<I", raw, row + 4 * k)[0] for k in range(4))))

if CH:
    HC = mem.u64(CH + 0x668)
    print("character+0x668 HealthComponent: 0x%X" % HC)
    if HC:
        print("  health=%.2f maxhealth=%.2f alive=%d didTakeDamage=%d low=%d crit=%d" % (
            f32(HC + 0x2AC), f32(HC + 0x318), mem.u8(HC + 0x2A8),
            mem.u8(HC + 0x33B), mem.u8(HC + 0x334), mem.u8(HC + 0x335)))

for k in ("UFocusAimComponent", "UAltFireComponent", "UGunComponent"):
    for o in inst[k]:
        try:
            outer = mem.u64(o + 0x20)
        except OSError:
            outer = 0
        extra = ""
        if k == "UFocusAimComponent":
            extra = " aim179=%d aim17A=%d" % (mem.u8(o + 0x179), mem.u8(o + 0x17A))
        elif k == "UAltFireComponent":
            extra = " altMode=%d firing=%d shot=%d fuel=%d" % (
                mem.u8(o + 0x271), mem.u8(o + 0x272), mem.u8(o + 0x273), mem.u8(o + 0x27C))
        print("%-22s 0x%X outer=0x%X%s" % (k, o, outer, extra))

for k in ("UReloadingClip", "UOverheatingClip", "UGunClip"):
    for o in inst[k]:
        try:
            outer = mem.u64(o + 0x20)
        except OSError:
            outer = 0
        print("%-18s 0x%X outer=0x%X bullets=%d bFiredLocal=%d reloading=%d" % (
            k, o, outer, i32(o + 0x294) if k == "UReloadingClip" else -1,
            i32(o + 0x29C) if k == "UReloadingClip" else -1,
            mem.u8(o + 0x2A4) if k == "UReloadingClip" else -1))

for o in inst["UGunComponent"]:
    print("UGunComponent 0x%X outer=0x%X" % (o, mem.u64(o + 0x20)))
    try:
        raw = mem.rpm(o, 0x500)
    except OSError:
        continue
    for addr in range(0, 0x500 - 8, 8):
        p = struct.unpack_from("<Q", raw, addr)[0]
        if 0x10000 < p < 0x7FFFFFFFFFFF:
            try:
                c = mem.u64(p + 0x10)
            except OSError:
                continue
            nm = want.get(c)
            if nm and "Clip" in nm:
                print("    gun+0x%X -> %s 0x%X" % (addr, nm, p))

mem.close()
