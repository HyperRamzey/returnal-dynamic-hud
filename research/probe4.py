"""probe4: resolve live object graph - who owns whom, chains, menu members."""
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


def chain_raw(c, limit=16):
    out = []
    for _ in range(limit):
        if not c:
            break
        out.append(c)
        try:
            c = u64(c + 0x30)
        except OSError as e:
            out.append(("ERR", e))
            break
    return out


def describe(tag, o):
    try:
        fl = u32(o + 8)
        cl = u64(o + 0x10)
        out = u64(o + 0x20)
        nid = u32(o + 0x18)
        ii = u32(o + 0x0C)
        ch = chain_raw(cl)
        chs = ",".join(bases.get(x, hex(x)) if isinstance(x, int) else str(x) for x in ch)
        print("%-26s 0x%-12X flags=%08X cls=0x%-12X outer=0x%-12X nameIdx=%-9d intIdx=%d" % (
            tag, o, fl, cl, out, nid, ii))
        print("      chain=[%s]" % chs)
    except OSError as e:
        print(tag, hex(o), "fail:", e)


print("=== candidate objects ===")
for tag, o in [
    ("hudinfo-outer_3D1ACEAC0", 0x3D1ACEAC0),
    ("hudinfo-outer2_3D13D4B60", 0x3D13D4B60),
    ("hud-outer_3CB870400", 0x3CB870400),
    ("cmgr-outer_3B0EF5F00", 0x3B0EF5F00),
    ("cmgr2-outer_3D845BA00", 0x3D845BA00),
    ("hc-outer_3B0EC0100", 0x3B0EC0100),
    ("hc-outer_1512909A0", 0x1512909A0),
    ("hc-outer_3B0EC10F0", 0x3B0EC10F0),
    ("hc-outer_55397090", 0x55397090),
    ("liveHUD_3D3A79580", 0x3D3A79580),
    ("liveHUD2_3AEFD9E80", 0x3AEFD9E80),
    ("liveCM_3BB653A00", 0x3BB653A00),
    ("liveCM2_3C2B6B200", 0x3C2B6B200),
]:
    describe(tag, o)

print()
print("=== live controller hunt: pawn fields ===")
for tag, o in [("hudinfo-outer_3D1ACEAC0", 0x3D1ACEAC0), ("hudinfo-outer2_3D13D4B60", 0x3D13D4B60)]:
    try:
        p330 = u64(o + 0x330)
        p2a8 = u64(o + 0x2A8)
        print("%s +0x330=0x%X +0x2A8=0x%X" % (tag, p330, p2a8))
        for pt, pv in [("+0x330", p330), ("+0x2A8", p2a8)]:
            if pv >= 0x10000:
                pcl = u64(pv + 0x10)
                print("   pawn@%s 0x%X cls=0x%X chain=%s" % (
                    pt, pv, pcl,
                    ",".join(bases.get(x, hex(x)) for x in chain_raw(pcl)[:8])))
    except OSError as e:
        print(tag, "fail:", e)

print()
print("=== HUD menu members ===")
for tag, o in [("hud1", 0x3D3A79580), ("hud2", 0x3AEFD9E80)]:
    try:
        print("%s +0x420=0x%X +0x522=%d +0x4B8=%.3f" % (
            tag, u64(o + 0x420), mem.u8(o + 0x522),
            struct.unpack("<f", mem.rpm(o + 0x4B8, 4))[0]))
    except OSError as e:
        print(tag, "fail:", e)

print()
print("=== screen managers: first 0x200 bytes (TArray hunt) ===")
for tag, o in [("cm1", 0x3BB653A00), ("cm2", 0x3C2B6B200)]:
    try:
        raw = mem.rpm(o, 0x1C0)
        for row in range(0, 0x1C0, 16):
            qs = struct.unpack_from("<2Q", raw, row)
            line = " ".join("%s" % ("0x%X" % q if q > 0x10000 else str(q)) for q in qs)
            print("  %s +%03X  %s" % (tag, row, line))
    except OSError as e:
        print(tag, "fail:", e)

mem.close()
