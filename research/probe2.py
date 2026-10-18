"""probe2: subclass-aware live discovery + identity + baselines."""
import struct, sys, time
sys.path.insert(0, ".")
import hud_dynamic as h

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

pid = h.find_process_id(h.GAME_EXE)
gb = h.module_bases(pid, {h.GAME_DLL.lower()})[h.GAME_DLL.lower()]
mem = h.ProcessMem(pid, read_only=True)
bases = {}
for name, rva in RVA.items():
    bases[name] = mem.u64(gb + rva)

gua = mem.u64(gb + h.RVA_GUOBJECTARRAY_IAT)
ct = mem.u64(gua + h.OFF_GUA_CHUNKTABLE)
count = mem.u32(gua + h.OFF_GUA_COUNT)

rev = {}
t0 = time.time()
idx = 0
cache = {}
while idx < count:
    cn = idx >> 16
    cb = cache.get(cn)
    if cb is None:
        try:
            cb = mem.u64(ct + 8 * cn)
        except OSError:
            cb = 0
        cache[cn] = cb
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
                if c:
                    rev.setdefault(c, []).append(obj)
    idx = (cn + 1) << 16

print("objects: %d classes in %.2fs" % (len(rev), time.time() - t0))


def chain(c, limit=32):
    out = []
    for _ in range(limit):
        if not c:
            break
        out.append(c)
        try:
            c = mem.u64(c + 0x30)
        except OSError:
            break
    return out


t0 = time.time()
chains = {}
for c in rev:
    chains[c] = tuple(chain(c))
print("chains: %.2fs" % (time.time() - t0))

UBASES = [b for b in bases.values() if b]


def find(base_name):
    bp = bases[base_name]
    subs = [c for c, ch in chains.items() if bp in ch]
    objs = []
    for c in subs:
        for o in rev.get(c, ()):
            try:
                fl = mem.u32(o + 8)
            except OSError:
                continue
            objs.append((o, c, bool(fl & 0x10)))
    return objs


print()
live_cache = {}
for name in bases:
    objs = find(name)
    live = [x for x in objs if not x[2]]
    cdo = [x for x in objs if x[2]]
    live_cache[name] = live
    print("%-30s live=%d cdo=%d" % (name, len(live), len(cdo)))
    for o, c, isc in live[:6]:
        try:
            outer = mem.u64(o + 0x20)
        except OSError:
            outer = 0
        print("    LIVE 0x%-12X cls=0x%-12X outer=0x%X" % (o, c, outer))

MA = 0x3A83E7FE0
try:
    c = mem.u64(MA + 0x10)
    ch = chain(c)
    matches = [n for n, b in bases.items() if b in ch]
    print()
    print("mystery actor 0x%X class=0x%X chainlen=%d matches=%s" % (MA, c, len(ch), matches))
except OSError as e:
    print("mystery actor read fail:", e)


def f32(a):
    return struct.unpack("<f", mem.rpm(a, 4))[0]


PCs = live_cache.get("ATouristPlayerController", [])
CHs = live_cache.get("AFirstPersonPlayerCharacter", [])
PC = PCs[0][0] if PCs else None
CH = CHs[0][0] if CHs else None
print()
print("live PC=0x%X CH=0x%X" % (PC or 0, CH or 0))
if PC:
    try:
        print("PC+0x798 HUDInfo ptr: 0x%X" % mem.u64(PC + 0x798))
        print("PC bytes: +0x820=%d +0x870=%d +0x678=%d" % (
            mem.u8(PC + 0x820), mem.u8(PC + 0x870), mem.u8(PC + 0x678)))
    except OSError as e:
        print("PC read fail:", e)
if CH:
    try:
        HC = mem.u64(CH + 0x668)
        print("CH+0x668 HC: 0x%X" % HC)
        if HC >= 0x10000:
            print("  hp=%.2f max=%.2f alive=%d dmg=%d" % (
                f32(HC + 0x2AC), f32(HC + 0x318), mem.u8(HC + 0x2A8), mem.u8(HC + 0x33B)))
    except OSError as e:
        print("CH read fail:", e)

print()
for nm in ("UFocusAimComponent", "UAltFireComponent", "UGunComponent",
           "UReloadingClip", "UOverheatingClip", "UGunClip"):
    for o, c, isc in live_cache.get(nm, []):
        try:
            outer = mem.u64(o + 0x20)
        except OSError:
            outer = 0
        extra = ""
        if nm == "UFocusAimComponent":
            extra = " aim179=%d aim17A=%d" % (mem.u8(o + 0x179), mem.u8(o + 0x17A))
        elif nm == "UAltFireComponent":
            extra = " altMode=%d firing=%d shot=%d fuel=%d" % (
                mem.u8(o + 0x271), mem.u8(o + 0x272), mem.u8(o + 0x273), mem.u8(o + 0x27C))
        elif nm == "UReloadingClip":
            extra = " bullets=%d fired=%d reloading=%d" % (
                struct.unpack("<i", mem.rpm(o + 0x294, 4))[0],
                struct.unpack("<i", mem.rpm(o + 0x29C, 4))[0], mem.u8(o + 0x2A4))
        print("%-20s 0x%-12X cls=0x%-12X outer=0x%X%s" % (nm, o, c, outer, extra))

print()
print("--- UPauseMenu live instances (widget baseline dump) ---")
for o, c, isc in live_cache.get("UPauseMenu", []):
    print("  widget 0x%X cls=0x%X" % (o, c))
    try:
        raw = mem.rpm(o, 0x180)
    except OSError:
        continue
    for row in range(0, 0x180, 16):
        print("    +%03X  %s" % (row, " ".join("%02X" % b for b in raw[row:row + 16])))

mem.close()
