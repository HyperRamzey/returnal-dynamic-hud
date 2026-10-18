"""probe7: FName pool discovery (multi-needle) + full name-based identity."""
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


def scan_multi(needles, limits=None, maxtypes=(0x20000, 0x40000)):
    hits = {nd: [] for nd in needles}
    limits = limits or {nd: 8 for nd in needles}
    total = 0
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
                total += n
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
    return hits, total


t0 = time.time()
needles = [b"Default__TouristPlayerController", b"Default__ATouristPlayerController",
           b"Player.HUD.CrosshairOff"]
hits, total = scan_multi(needles)
print("scan: %.0f MB in %.1fs" % (total / 1e6, time.time() - t0))
for nd in needles:
    print("  %-40r hits=%d %s" % (nd, len(hits[nd]), [hex(x) for x in hits[nd][:4]]))

cdo_idx = u32(0x3BB696E00 + 0x18)
print("ctrl CDO nameIdx = %d (0x%X) block=%d off=0x%X" % (cdo_idx, cdo_idx, cdo_idx >> 16, (cdo_idx & 0xFFFF) * 2))


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
    hh = struct.unpack("<H", hb)[0]
    ln = hh >> 1
    if ln > 1024:
        return None
    if hh & 1:
        sb = rpm(bp + o2 + 2, ln * 2)
        return sb.decode("utf-16-le", "replace") if sb else None
    sb = rpm(bp + o2 + 2, ln)
    return sb.decode("latin1") if sb else None


pool = None
for nd in needles:
    if pool:
        break
    for a in hits[nd]:
        entry = a - 2
        hb = rpm(entry, 2)
        if not hb:
            continue
        hdr = struct.unpack("<H", hb)[0]
        if (hdr >> 1) != len(nd) or (hdr & 1):
            continue
        block = cdo_idx >> 16
        off = (cdo_idx & 0xFFFF) * 2
        block_base = entry - off
        if block_base < 0x10000:
            continue
        pat = struct.pack("<Q", block_base)
        hh2, _ = scan_multi([pat], limits={pat: 24})
        for b in hh2[pat]:
            cand = b - block * 8
            if cand < 0x10000:
                continue
            nm = fname_try(cdo_idx, cand)
            if nm and nm.encode("latin1", "replace") == nd:
                pool = cand
                print("POOL FOUND @ 0x%X via %r" % (cand, nd))
                break
        if pool:
            break

if not pool:
    print("POOL NOT FOUND - diagnostics above")
    raise SystemExit(1)


def fname(idx):
    if idx == 0:
        return "None"
    r = fname_try(idx, pool)
    return r if r is not None else "<bad %d>" % idx


def oname(a):
    return fname(u32(a + 0x18))


def ocname(a):
    c = u64(a + 0x10)
    return fname(u32(c + 0x18)) if c else "?"


print()
print("=== identity dump ===")
gb = h.module_bases(pid, {h.GAME_DLL.lower()})[h.GAME_DLL.lower()]
cands = [
    ("ctrlCDO_3BB696E00", 0x3BB696E00),
    ("afppcCDO_3A8EFC940", 0x3A8EFC940),
    ("atcharCDO_150E6C870", 0x150E6C870),
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
    ("CDO_classes_3A879BC80", 0x3A879BC80),
    ("CDO_class_3A8756940", 0x3A8756940),
    ("CDO_cls4_3CC563500", 0x3CC563500),
]
for tag, a in cands:
    try:
        print("%-24s %-44s cls=%-44s outer=%s" % (tag, oname(a), ocname(a), oname(u64(a + 0x20)) or "0"))
    except Exception as e:
        print(tag, "fail", e)

print()
print("=== class-name scan for live instances ===")
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
                off = j * 24
                obj = struct.unpack_from("<Q", raw, off)[0]
                if not obj:
                    continue
                if struct.unpack_from("<I", raw, off + 8)[0] & 0x20000000:
                    continue
                c = u64(obj + 0x10)
                if c:
                    rev.setdefault(c, []).append(obj)
    idx = (cn + 1) << 16
print("scan: %d classes in %.1fs" % (len(rev), time.time() - t0))

name_of_class = {}
for c in rev:
    name_of_class[c] = fname(u32(c + 0x18))

PAT = ("player", "tourist", "gun", "clip", "weapon", "health", "focus", "altfire",
       "screen", "hud", "pause", "crosshair", "tutorial", "subtitle", "bullet", "ammo")
shown = 0
for c, objs in rev.items():
    cn = name_of_class[c]
    low = cn.lower()
    if not any(p in low for p in PAT):
        continue
    live = [o for o in objs if not (u32(o + 8) & 0x10)]
    if not live:
        continue
    shown += 1
    if shown <= 90:
        print("  %-52s live=%d %s" % (cn, len(live), [hex(x) for x in live[:4]]))
print("class rows: %d" % shown)

print()
print("=== live objects: PlayerController / FirstPerson classes ===")
for c, objs in rev.items():
    cn = name_of_class[c]
    if ("PlayerController" in cn) or ("FirstPerson" in cn):
        live = [o for o in objs if not (u32(o + 8) & 0x10)]
        print("  class %s: %d live" % (cn, len(live)))
        for o in live[:4]:
            try:
                p330 = u64(o + 0x330)
                p798 = u64(o + 0x798)
                extra = ""
                if p330 > 0x10000:
                    extra += " +330=%s(0x%X)" % (oname(p330), p330)
                if p798 > 0x10000:
                    extra += " +798=%s(0x%X)" % (oname(p798), p798)
                print("    0x%X%s" % (o, extra))
                if p330 > 0x10000:
                    hc = u64(p330 + 0x668)
                    if hc > 0x10000:
                        import struct as st
                        fb = rpm(hc + 0x2AC, 4)
                        hp = st.unpack("<f", fb)[0] if fb else -1
                        print("        pawn+668=%s(0x%X) hp=%.2f alive=%d" % (
                            oname(hc), hc, hp, rpm(hc + 0x2A8, 1)[0] if rpm(hc + 0x2A8, 1) else -1))
            except Exception as e:
                print("    fail", e)
