"""probe8: FName pool blocks array (incl. image regions) + full name identity."""
import ctypes, struct, sys, time
sys.path.insert(0, ".")
import hud_dynamic as h

pid = h.find_process_id(h.GAME_EXE)
k32 = ctypes.windll.kernel32
hproc = k32.OpenProcess(0x400 | 0x10, False, pid)
if not hproc:
    raise SystemExit("OpenProcess failed")


class MBI(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_ulonglong),
        ("AllocationBase", ctypes.c_ulonglong),
        ("AllocationProtect", ctypes.c_ulong),
        ("__a1", ctypes.c_ulong),
        ("RegionSize", ctypes.c_ulonglong),
        ("State", ctypes.c_ulong),
        ("Protect", ctypes.c_ulong),
        ("Type", ctypes.c_ulong),
        ("__a2", ctypes.c_ulong),
    ]


def rpm(addr, n):
    buf = (ctypes.c_char * n)()
    got = ctypes.c_size_t(0)
    ok = k32.ReadProcessMemory(hproc, ctypes.c_void_p(addr), buf, n, ctypes.byref(got))
    if not ok or got.value != n:
        return None
    return buf.raw


def u32(a):
    b = rpm(a, 4)
    return struct.unpack("<I", b)[0] if b else 0


def u64(a):
    b = rpm(a, 8)
    return struct.unpack("<Q", b)[0] if b else 0


def u16(a):
    b = rpm(a, 2)
    return struct.unpack("<H", b)[0] if b else 0


def iter_regions():
    mbi = MBI()
    addr = 0x10000
    end = 0x7FFFFFFF0000
    while addr < end:
        r = k32.VirtualQueryEx(hproc, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi))
        if r == 0:
            break
        yield (mbi.BaseAddress, mbi.RegionSize, mbi.State, mbi.Protect, mbi.Type)
        addr = mbi.BaseAddress + mbi.RegionSize


def scan_multi(needles, limits=None, maxtypes=(0x20000, 0x40000, 0x1000000)):
    hits = {nd: [] for nd in needles}
    limits = limits or {nd: 8 for nd in needles}
    for base, size, state, prot, typ in iter_regions():
        if state != 0x1000 or typ not in maxtypes:
            continue
        if prot & 0x101:
            continue
        if prot not in (0x02, 0x04, 0x08, 0x20, 0x40, 0x80):
            continue
        off = 0
        step = 1 << 20
        while off < size:
            n = min(step, size - off)
            data = rpm(base + off, n)
            if data:
                for nd in needles:
                    if len(hits[nd]) >= limits[nd]:
                        continue
                    i = data.find(nd)
                    while i != -1:
                        hits[nd].append(base + off + i)
                        if len(hits[nd]) >= limits[nd]:
                            break
                        i = data.find(nd, i + 1)
            off += n
            if all(len(hits[nd]) >= limits[nd] for nd in needles):
                break
        if all(len(hits[nd]) >= limits[nd] for nd in needles):
            break
    return hits


needle = b"Default__TouristPlayerController"
cdo_idx = u32(0x3BB696E00 + 0x18)
block = cdo_idx >> 16
off = (cdo_idx & 0xFFFF) * 2
print("cdo_idx=%d block=%d off=0x%X" % (cdo_idx, block, off))

entry2 = 0x3A8D6F4C4
print("entry2 hdr = 0x%04X (expect 0x%04X)" % (u16(entry2), len(needle) << 1))
block_base = entry2 - off
print("block_base2 = 0x%X (align64k=%s)" % (block_base, block_base % 0x10000 == 0))

t0 = time.time()
pat = struct.pack("<Q", block_base)
hh = scan_multi([pat], limits={pat: 64})
print("pattern hits: %d in %.1fs" % (len(hh[pat]), time.time() - t0))


def fname_try(idx, base):
    if idx == 0:
        return "None"
    blk = idx >> 16
    o2 = (idx & 0xFFFF) * 2
    bp = u64(base + 8 * blk)
    if not bp:
        return None
    hb = rpm(bp + o2, 2)
    if not hb:
        return None
    hh2 = struct.unpack("<H", hb)[0]
    ln = hh2 >> 1
    if ln > 1024:
        return None
    if hh2 & 1:
        sb = rpm(bp + o2 + 2, ln * 2)
        return sb.decode("utf-16-le", "replace") if sb else None
    sb = rpm(bp + o2 + 2, ln)
    return sb.decode("latin1") if sb else None


pool = None
for b in hh[pat]:
    cand = b - block * 8
    if cand < 0x10000:
        continue
    nm = fname_try(cdo_idx, cand)
    ok = nm == needle.decode("latin1")
    print("  cand blocks@0x%X -> cdo name=%r match=%s" % (cand, nm, ok))
    if ok:
        pool = cand
        b0 = u64(cand)
        n0 = fname_try(0xFFFFFFFF & (0), cand)
        print("  block0=0x%X first entry name=%r" % (b0, fname_try(0, cand)))
        break

if not pool:
    print("POOL NOT FOUND")
    raise SystemExit(1)

print("POOL @ 0x%X" % pool)


def fname(idx):
    return fname_try(idx, pool) or "<bad %d>" % idx


def oname(a):
    return fname(u32(a + 0x18))


def ocname(a):
    c = u64(a + 0x10)
    return fname(u32(c + 0x18)) if c else "?"


print()
print("=== identity dump ===")
gb = h.module_bases(pid, {h.GAME_DLL.lower()})[h.GAME_DLL.lower()]
MODS = {}
try:
    mods = h.module_bases(pid, {h.GAME_DLL.lower(), "returnal-hmqscreen-win64-shipping.dll"})
    MODS.update(mods)
except Exception as e:
    print("module_bases fail:", e)
hmq = MODS.get("returnal-hmqscreen-win64-shipping.dll")
print("hmq base:", hex(hmq) if hmq else "?")

cands = [
    ("ctrlCDO_3BB696E00", 0x3BB696E00),
    ("pc?3D13D4B60", 0x3D13D4B60),
    ("pc?3D1ACEAC0", 0x3D1ACEAC0),
    ("pawn?6E950000", 0x6E950000),
    ("cls3CB870400", 0x3CB870400),
    ("cls3D4495D80", 0x3D4495D80),
    ("cls3A8764C30", 0x3A8764C30),
    ("liveHUD1_3D3A79580", 0x3D3A79580),
    ("liveHUD2_3AEFD9E80", 0x3AEFD9E80),
    ("liveCM1_3BB653A00", 0x3BB653A00),
    ("liveCM2_3C2B6B200", 0x3C2B6B200),
    ("hudinfo_3C794C040", 0x3C794C040),
    ("hud1420_3E1218BC0", 0x3E1218BC0),
    ("health_59EBD850", 0x59EBD850),
    ("cls_3A879BC80", 0x3A879BC80),
    ("cls_3A8756940", 0x3A8756940),
    ("cls_3CC563500", 0x3CC563500),
    ("cls_3CC56E080", 0x3CC56E080),
]
for tag, a in cands:
    try:
        print("%-24s %-46s cls=%-46s outer=%s" % (tag, oname(a), ocname(a), oname(u64(a + 0x20)) or "0"))
    except Exception as e:
        print(tag, "fail", e)

if hmq:
    for tag, rva in (("HMQSubtitlePlayer_cls", 0xA3370), ("HMQSubtitlesWidget_cls", 0xA33A8)):
        c = u64(hmq + rva)
        print("%-24s class@0x%X name=%r" % (tag, c, fname(u32(c + 0x18)) if c else "?"))

print()
print("=== full class table + live instances ===")
gua = u64(gb + h.RVA_GUOBJECTARRAY_IAT)
ct = u64(gua + h.OFF_GUA_CHUNKTABLE)
count = u32(gua + h.OFF_GUA_COUNT)
rev = {}
t0 = time.time()
idx = 0
cache = {}
while idx < count:
    cn = idx >> 16
    cb = cache.get(cn)
    if cb is None:
        cb = u64(ct + 8 * cn)
        cache[cn] = cb
    here = min(0x10000, count - (cn << 16))
    if cb >= 0x10000:
        raw = rpm(cb, here * 24)
        if raw:
            for j in range(here):
                off2 = j * 24
                obj = struct.unpack_from("<Q", raw, off2)[0]
                if not obj:
                    continue
                if struct.unpack_from("<I", raw, off2 + 8)[0] & 0x20000000:
                    continue
                c = u64(obj + 0x10)
                if c:
                    rev.setdefault(c, []).append(obj)
    idx = (cn + 1) << 16
name_of_class = {c: fname(u32(c + 0x18)) for c in rev}
print("scan: %d classes in %.1fs" % (len(rev), time.time() - t0))

print()
print("--- live PlayerController class objects ---")
for c, objs in rev.items():
    cn = name_of_class[c]
    if "PlayerController" in cn and "Default__" not in cn:
        live = [o for o in objs if not (u32(o + 8) & 0x10)]
        if live:
            print("  %s: %d live %s" % (cn, len(live), [hex(x) for x in live[:3]]))
            for o in live[:2]:
                p330 = u64(o + 0x330)
                print("     0x%X pawn+330=%s(0x%X)" % (o, oname(p330) if p330 > 0x10000 else "0", p330))
                if p330 > 0x10000:
                    hc = u64(p330 + 0x668)
                    fb = rpm(hc + 0x2AC, 4) if hc > 0x10000 else None
                    hp = struct.unpack("<f", fb)[0] if fb else -1
                    print("        pawn+668=%s(0x%X) hp=%.2f" % (oname(hc) if hc > 0x10000 else "0", hc, hp))

print()
print("--- character-ish live classes ---")
for c, objs in rev.items():
    cn = name_of_class[c]
    if any(k in cn for k in ("FirstPerson", "TouristCharacter", "PlayerCharacter")) and "Default__" not in cn:
        live = [o for o in objs if not (u32(o + 8) & 0x10)]
        if live:
            print("  %s: %d live %s" % (cn, len(live), [hex(x) for x in live[:3]]))

print()
print("--- gun/weapon live classes ---")
for c, objs in rev.items():
    cn = name_of_class[c]
    if any(k in cn for k in ("Gun", "Weapon", "Clip")) and "Default__" not in cn:
        live = [o for o in objs if not (u32(o + 8) & 0x10)]
        if live and len(live) < 40:
            print("  %-46s live=%d %s" % (cn, len(live), [hex(x) for x in live[:4]]))

print()
print("--- named widgets: Pause/Subtitle/Tutorial/ScreenManager ---")
for c, objs in rev.items():
    cn = name_of_class[c]
    if any(k in cn for k in ("Pause", "Subtitle", "Tutorial", "ScreenManager", "Crosshair", "HUDInfo")):
        live = [o for o in objs if not (u32(o + 8) & 0x10)]
        if live:
            print("  %-52s live=%d %s" % (cn, len(live), [hex(x) for x in live[:4]]))
