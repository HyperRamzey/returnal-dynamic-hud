"""probe5: FName pool discovery + name resolution + identity dump."""
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


def scan_regions(needle, limit_hits=40, max_bytes=8 * 1024 ** 3):
    hits = []
    mbi = MBI()
    addr = 0x10000
    end = 0x7FFFFFFF0000
    total = 0
    while addr < end and total < max_bytes:
        r = k32.VirtualQueryEx(hproc, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi))
        if r == 0:
            break
        base = mbi.BaseAddress
        size = mbi.RegionSize
        addr = base + size
        if size == 0 or mbi.State != 0x1000 or mbi.Type != 0x20000:
            continue
        if mbi.Protect not in (0x04, 0x08, 0x40, 0x80, 0x02):
            continue
        off = 0
        step = 1 << 20
        while off < size:
            n = min(step, size - off)
            data = rpm(base + off, n)
            if data:
                total += n
                i = data.find(needle)
                while i != -1:
                    hits.append(base + off + i)
                    if len(hits) >= limit_hits:
                        break
                    i = data.find(needle, i + 1)
            off += n
            if len(hits) >= limit_hits:
                break
    return hits, total


t0 = time.time()
needle = b"Default__ATouristPlayerController"
hits, total = scan_regions(needle)
print("scan1: %d hits, %.0f MB in %.1fs" % (len(hits), total / 1e6, time.time() - t0))

good = []
for a in hits[:40]:
    hdr_b = rpm(a - 2, 2)
    if not hdr_b:
        continue
    hdr = struct.unpack("<H", hdr_b)[0]
    ln = hdr >> 1
    wide = hdr & 1
    ok = (ln == len(needle)) and wide == 0
    print("  hit 0x%X hdr=%04X len=%d wide=%d ok=%s" % (a, hdr, ln, wide, ok))
    if ok:
        good.append(a)

if not good:
    print("no ANSI hit with valid header; trying wide scan")
    t0 = time.time()
    wide_needle = "Default__ATouristPlayerController".encode("utf-16-le")
    hits, total = scan_regions(wide_needle)
    print("scan1w: %d hits in %.1fs" % (len(hits), time.time() - t0))
    for a in hits[:10]:
        print("  wh 0x%X" % a)

entry_start = good[0] if good else (hits[0] - 2 if hits else None)
if entry_start is None:
    raise SystemExit("no entry found")

IDX = 13859426
blockid = IDX >> 16
blkoff = (IDX & 0xFFFF) * 2
block_base = entry_start - blkoff
print("blockid=%d blkoff=0x%X block_base=0x%X" % (blockid, blkoff, block_base))

t0 = time.time()
pat = struct.pack("<Q", block_base)
hits2, total2 = scan_regions(pat, limit_hits=64)
print("scan2: %d hits in %.1fs" % (len(hits2), time.time() - t0))

blocks_base = None
for a in hits2:
    cand = a - blockid * 8
    if cand < 0x10000:
        continue
    b0 = rpm(cand, 8)
    if not b0:
        continue
    p0 = struct.unpack("<Q", b0)[0]
    s = rpm(p0, 8) if p0 else None
    tag = "?"
    if s and s[2:6] == b"None":
        tag = "NONE-OK"
    print("  cand blocks@0x%X block0=0x%X %s" % (cand, p0, tag))
    if tag == "NONE-OK" and blocks_base is None:
        blocks_base = cand
if blocks_base is None and hits2:
    for a in hits2:
        cand = a - blockid * 8
        if cand >= 0x10000 and rpm(cand, 8):
            blocks_base = cand
            break
print("blocks_base = 0x%X" % (blocks_base or 0))
if not blocks_base:
    raise SystemExit("blocks array not found")


def fname(idx):
    if idx == 0:
        return "None"
    blk = idx >> 16
    off = (idx & 0xFFFF) * 2
    bp_b = rpm(blocks_base + 8 * blk, 8)
    if not bp_b:
        return "<unreadable blk %d idx %d>" % (blk, idx)
    bp = struct.unpack("<Q", bp_b)[0]
    if bp == 0:
        return "<empty blk %d idx %d>" % (blk, idx)
    h_b = rpm(bp + off, 2)
    if not h_b:
        return "<bad entry idx %d>" % idx
    hh = struct.unpack("<H", h_b)[0]
    ln = hh >> 1
    if ln > 1000:
        return "<insane len %d idx %d>" % (ln, idx)
    if hh & 1:
        b = rpm(bp + off + 2, ln * 2)
        return b.decode("utf-16-le", "replace") if b else "<bad wide>"
    b = rpm(bp + off + 2, ln)
    return b.decode("latin1") if b else "<bad ansi>"


gb = h.module_bases(pid, {h.GAME_DLL.lower()})[h.GAME_DLL.lower()]
pCtrlClass = struct.unpack("<Q", rpm(gb + 0xF6F168, 8))[0]
print("verify: class@0x%X name = %r" % (pCtrlClass, fname(struct.unpack("<I", rpm(pCtrlClass + 0x18, 4))[0])))

print()
print("=== identity dump ===")
cands = [
    ("hudinfo-outer2_3D13D4B60", 0x3D13D4B60),
    ("hudinfo-outer_3D1ACEAC0", 0x3D1ACEAC0),
    ("obj_6E950000", 0x6E950000),
    ("liveHUD1_3D3A79580", 0x3D3A79580),
    ("liveHUD2_3AEFD9E80", 0x3AEFD9E80),
    ("liveCM_3BB653A00", 0x3BB653A00),
    ("liveCM2_3C2B6B200", 0x3C2B6B200),
    ("cls_3CB870400", 0x3CB870400),
    ("cls_3D4495D80", 0x3D4495D80),
    ("cls_3A8764C30", 0x3A8764C30),
    ("ctrlCDO_3BB696E00", 0x3BB696E00),
    ("afppcCDO_3A8EFC940", 0x3A8EFC940),
    ("atcharCDO_150E6C870", 0x150E6C870),
]
for tag, a in cands:
    try:
        nm = fname(struct.unpack("<I", rpm(a + 0x18, 4))[0])
        c = struct.unpack("<Q", rpm(a + 0x10, 8))[0]
        cn = fname(struct.unpack("<I", rpm(c + 0x18, 4))[0])
        o = struct.unpack("<Q", rpm(a + 0x20, 8))[0]
        on = fname(struct.unpack("<I", rpm(o + 0x18, 4))[0]) if o > 0x10000 else "0"
        print("%-26s %-42s cls=%-42s outer=%s" % (tag, nm, cn, on))
    except Exception as e:
        print(tag, "fail", e)

print()
print("=== full object scan + class name table ===")
gua = struct.unpack("<Q", rpm(gb + h.RVA_GUOBJECTARRAY_IAT, 8))[0]
ct = struct.unpack("<Q", rpm(gua + h.OFF_GUA_CHUNKTABLE, 8))[0]
count = struct.unpack("<I", rpm(gua + h.OFF_GUA_COUNT, 4))[0]
rev = {}
t0 = time.time()
idx = 0
cache = {}
while idx < count:
    cn = idx >> 16
    cb = cache.get(cn)
    if cb is None:
        b = rpm(ct + 8 * cn, 8)
        cb = struct.unpack("<Q", b)[0] if b else 0
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
                c_b = rpm(obj + 0x10, 8)
                if not c_b:
                    continue
                c = struct.unpack("<Q", c_b)[0]
                if c:
                    rev.setdefault(c, []).append(obj)
    idx = (cn + 1) << 16
print("scan: %d classes in %.1fs" % (len(rev), time.time() - t0))

pat = ("Player", "Tourist", "Gun", "Clip", "Health", "Focus", "Screen", "HUD", "Pause",
       "Crosshair", "Tutorial", "Subtitle", "Weapon", "Bullet", "Ammo", "Combat")
t0 = time.time()
hits3 = 0
for c, objs in rev.items():
    cb2 = rpm(c + 0x18, 4)
    if not cb2:
        continue
    cn2 = fname(struct.unpack("<I", cb2)[0])
    if not any(p.lower() in cn2.lower() for p in pat):
        continue
    live = []
    for o in objs:
        fb = rpm(o + 8, 4)
        if not fb:
            continue
        if struct.unpack("<I", fb)[0] & 0x10:
            continue
        live.append(o)
    if not live:
        continue
    hits3 += 1
    if hits3 < 70:
        print("  %-46s live=%d %s" % (cn2, len(live), [hex(x) for x in live[:4]]))
print("classes printed: %d (%.1fs)" % (hits3, time.time() - t0))
