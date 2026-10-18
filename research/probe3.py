"""probe3: identity resolution - flag semantics, CDO check, pawn chase."""
import struct, sys
sys.path.insert(0, ".")
import hud_dynamic as h

pid = h.find_process_id(h.GAME_EXE)
gb = h.module_bases(pid, {h.GAME_DLL.lower()})[h.GAME_DLL.lower()]
mem = h.ProcessMem(pid, read_only=True)


def u64(a):
    return mem.u64(a)


def u32(a):
    return mem.u32(a)


BASE = {
    0xF6F168: "ATouristPlayerController",
    0xF5E948: "AFirstPersonPlayerCharacter",
    0xF6C4C8: "ATouristCharacter",
    0xF5FAF8: "UHealthComponent",
    0xF57B90: "UAltFireComponent",
    0xF5EBE0: "UFocusAimComponent",
    0xF5F558: "UGunComponent",
    0xF68360: "UReloadingClip",
    0xF64878: "UOverheatingClip",
    0xF5F3B8: "UGunClip",
    0xF6EB10: "ATouristHUD",
    0xF6FED8: "UTouristScreenManager",
    0xF64B88: "UPauseMenu",
    0xF5BA58: "UCrosshairWidget",
    0xF704A0: "UTouristTutorialWidget",
    0xF67038: "UPlayerHUDInfo",
}
bases = {}
for rva, nm in BASE.items():
    bases[u64(gb + rva)] = nm


def chain(c, limit=24):
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


cands = [
    ("ctrl_3BB696E00", 0x3BB696E00),
    ("afppc_3A8EFC940", 0x3A8EFC940),
    ("atchar_150E6C870", 0x150E6C870),
    ("cmgrCDO_3BB655980", 0x3BB655980),
    ("cmgr_3BB653A00", 0x3BB653A00),
    ("hud_3D3A79580", 0x3D3A79580),
    ("hudCDO_150E01420", 0x150E01420),
]
for nm, o in cands:
    try:
        fl = u32(o + 8)
        cl = u64(o + 0x10)
        cdo = u64(cl + 0x110)
        out = u64(o + 0x20)
        nid = u32(o + 0x18)
        ii = u32(o + 0x0C)
        print("%-20s flags=%08X cls=0x%X cdoField=0x%X isCDO=%s outer=0x%X nameIdx=%d intIdx=%d" % (
            nm, fl, cl, cdo, (o == cdo), out, nid, ii))
        print("   clsChain=%s" % ",".join(bases.get(x, hex(x)) for x in chain(cl)[:8]))
    except OSError as e:
        print(nm, "read fail", e)

print()
try:
    pawn = u64(0x3BB696E00 + 0x330)
    print("ctrl+0x330 pawn=0x%X" % pawn)
    if pawn >= 0x10000:
        pcl = u64(pawn + 0x10)
        print("  pawn cls=0x%X chain=%s" % (pcl, ",".join(bases.get(x, hex(x)) for x in chain(pcl)[:8])))
        hc = u64(pawn + 0x668)
        print("  pawn+0x668 HC=0x%X" % hc)
        if hc >= 0x10000:
            print("  hp=%.2f max=%.2f alive=%d dmg=%d" % (
                struct.unpack("<f", mem.rpm(hc + 0x2AC, 4))[0],
                struct.unpack("<f", mem.rpm(hc + 0x318, 4))[0],
                mem.u8(hc + 0x2A8), mem.u8(hc + 0x33B)))
    hi = u64(0x3BB696E00 + 0x798)
    print("ctrl+0x798 HUDInfo=0x%X  (probe1 saw 0x3B7D40BA0)" % hi)
    print("ctrl bytes +0x820=%d +0x870=%d +0x678=%d +0x779=%d +0x77B=%d +0x800=%d +0x802=%d" % (
        mem.u8(0x3BB696E00 + 0x820), mem.u8(0x3BB696E00 + 0x870), mem.u8(0x3BB696E00 + 0x678),
        mem.u8(0x3BB696E00 + 0x779), mem.u8(0x3BB696E00 + 0x77B),
        mem.u8(0x3BB696E00 + 0x800), mem.u8(0x3BB696E00 + 0x802)))
    print("ctrl ints +0x828=%d +0x854=%d" % (
        struct.unpack("<i", mem.rpm(0x3BB696E00 + 0x828, 4))[0],
        struct.unpack("<i", mem.rpm(0x3BB696E00 + 0x854, 4))[0]))
except OSError as e:
    print("ctrl read fail:", e)

print()
for nm, o in [("afppc", 0x3A8EFC940), ("atchar", 0x150E6C870)]:
    try:
        hc = u64(o + 0x668)
        print("%s +0x668 HC=0x%X" % (nm, hc))
    except OSError as e:
        print(nm, "fail", e)

mem.close()
