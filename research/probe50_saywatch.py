"""probe50_saywatch.py - live subtitle chain watcher.

Chain under test:
  SayHUD (+0x730 VerticalBox_Entries / +0x728 VerticalBox_ClosedCaptions_Entries)
   -> Slots -> slot.Content (WBP_SayEntry row)
   -> row +0x720 (RichTextBlock_Line) -> Text FText -> string
Also logs: SayManager Entries[0..2] text/id, SayHUD uber-frame (P+0x20 entry /
P+0xE8 FString), row Visibility/SayId/SpeakerList.

PROBE50_MIN=<minutes> to watch; 0 = one-shot dump only.
"""
import ctypes
import os
import re
import struct
import sys
import time

import hud_dynamic as h

CORE_DLL = "Returnal-Core-Win64-Shipping.dll"
BLOCKS_RVA = 0x5C2950
GUA_IAT_RVA = 0x8A15B0
VTF_ENTRY_RVA = 0x98DD48
OUTLOG = r"C:\Users\admin\AppData\Local\Temp\opencode\probe50.out"
WATCH_MIN = float(os.environ.get("PROBE50_MIN", "0"))

_lf = open(OUTLOG, "a", encoding="utf-8")


def say(*a):
    s = " ".join(str(x) for x in a)
    # console is cp1252: sanitise it only for stdout, keep the log utf-8
    print(s.encode("cp1252", "replace").decode("cp1252"), flush=True)
    _lf.write(s + "\n")
    _lf.flush()


def ts():
    return time.strftime("%H:%M:%S") + (".%03d" % (time.time() % 1 * 1000))


say("=== probe50 %s watch=%s ===" % (time.strftime("%Y-%m-%d %H:%M:%S"),
                                     WATCH_MIN))
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


def u32(a):
    return struct.unpack("<I", rpm(a, 4))[0]


def u64(a):
    return struct.unpack("<Q", rpm(a, 8))[0]


def u8(a):
    return rpm(a, 1)[0]


def okp(p):
    return 0x10000 <= p < 0x7FFFFFFFFFFF


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


def fname(idx):
    return IDS.get(idx)


def fstr(p):
    data, num, mx = struct.unpack("<QII", rpm(p, 16))
    if num > 0x400 or mx > 0x1000 or num > mx or num == 0:
        return None
    if not okp(data):
        return None
    raw = rpm(data, 2 * num)
    return raw.decode("utf-16-le", "replace").rstrip("\x00")


def td_strings(td):
    res = []
    try:
        blob = rpm(td, 0xA0)
    except OSError:
        return res
    for off in range(0, 0xA0 - 16 + 1, 8):
        p, n2, m2 = struct.unpack_from("<QII", blob, off)
        if 0 < n2 <= 0x400 and n2 <= m2 <= 0x1000 and okp(p):
            try:
                raw = rpm(p, 2 * n2)
                t = raw.decode("utf-16-le", "replace").rstrip("\x00")
                if t and all(ch >= " " or ch in "\t" for ch in t):
                    res.append((off, t))
            except (OSError, UnicodeError):
                pass
    return res


def ftext_str(p):
    """read FText at p -> best string"""
    try:
        td = u64(p)
    except OSError:
        return None
    if not okp(td):
        return None
    ss = td_strings(td)
    return ss[0][1] if ss else None


def objname(p):
    try:
        return IDS.get(u32(p + 0x18))
    except OSError:
        return None


def objclass(p):
    try:
        c = u64(p + 0x10)
        return IDS.get(u32(c + 0x18)) if okp(c) else None
    except OSError:
        return None


# ---- object scan ----
gua = u64(game + GUA_IAT_RVA)
ctab = u64(gua + 0x10)
cnt = u32(gua + 0x24)
allhits = []
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
        low = nm.lower()
        if not ("sayhud" in low or "sayentry" in low or "saymanager" in low):
            continue
        c = u64(obj + 0x10)
        cn = IDS.get(u32(c + 0x18), "?") if okp(c) else "?"
        allhits.append((obj, nm, cn))
    except OSError:
        continue

huds = [(o, nm, cn) for o, nm, cn in allhits
        if cn == "WBP_SayHUD_C" and not nm.startswith("Default__")]
mans = [(o, nm, cn) for o, nm, cn in allhits
        if cn == "SayManagerComponent" and not nm.startswith("Default__")]
mans = [(o, nm) for o, nm, cn in mans if nm == "SayManager"]
rows_known = [(o, nm) for o, nm, cn in allhits
              if cn == "WBP_SayEntry_C" and not nm.startswith("Default__")]
say("huds=%d mans=%d rows=%d" % (len(huds), len(mans), len(rows_known)))
say("SM: %s" % ["0x%X" % o for o, nm in mans])
say("HUDs: %s" % " ".join("0x%X(P=0x%X)" % (o, u64(o + 0x720))
                          if okp(u64(o + 0x720)) else "0x%X" % o
                          for o, nm, cn in huds))

# ---- property offset resolution (empirical: ChildProperties +0x50,
#      SuperStruct +0x40) ----
_prop_cache = {}


def find_prop(cls, name, maxn=4000):
    key = (cls, name)
    if key in _prop_cache:
        return _prop_cache[key]
    c = cls
    lvl = 0
    res = None
    while okp(c) and lvl < 40:
        try:
            root = u64(c + 0x50)
        except OSError:
            break
        f = root
        for _ in range(maxn):
            if not okp(f):
                break
            try:
                nm = IDS.get(u32(f + 0x28))
                if nm == name:
                    res = u32(f + 0x4C)
                    break
                nxt = u64(f + 0x20)
            except OSError:
                break
            if not nxt:
                break
            f = nxt
        if res is not None:
            break
        try:
            c = u64(c + 0x40)
        except OSError:
            break
        lvl += 1
    _prop_cache[key] = res
    return res


GAME_VT = game + VTF_ENTRY_RVA
vis_off = slots_off = content_off = text_off = None
actif = None
for o, nm, cn in huds:
    try:
        P = u64(o + 0x720)
        if okp(P) and u64(P + 0x20) == GAME_VT and u32(P + 0x28) != 0xFFFFFFFF:
            actif = o
    except OSError:
        pass
say("active-looking HUD: 0x%X" % (actif or 0))

# resolve offsets from known row widgets (independent of parenting)
row_objs = [o for o, nm in rows_known if okp(o)]
for row in row_objs:
    try:
        rtb = u64(row + 0x720)
        if okp(rtb) and "RichText" in (objclass(rtb) or ""):
            text_off = find_prop(u64(rtb + 0x10), "Text")
            if text_off is not None:
                break
    except OSError:
        pass
if row_objs:
    try:
        vis_off = find_prop(u64(row_objs[0] + 0x10), "Visibility")
        if vis_off is None:
            vis_off = find_prop(u64(row_objs[0] + 0x10), "visibility")
    except OSError:
        pass
say("offsets: Visibility=0x%X Text=0x%X" % (vis_off or 0, text_off or 0))

# vbox diagnostics for the active HUD
vbox_list = []
if actif:
    for vo, tag in ((0x728, "CC"), (0x730, "EN")):
        try:
            v = u64(actif + vo)
        except OSError:
            continue
        if okp(v) and objclass(v) == "VerticalBox":
            vbox_list.append((v, tag))
for v, tag in vbox_list:
    try:
        if slots_off is None:
            slots_off = find_prop(u64(v + 0x10), "Slots")
        data = u64(v + slots_off)
        num = u32(v + slots_off + 8)
        say("vbox %s 0x%X slots=0x%X num=%d" % (tag, v, data, num))
        if okp(data) and 0 < num < 64:
            for si in range(min(num, 8)):
                slot = u64(data + 8 * si)
                cn2 = objclass(slot) if okp(slot) else None
                if content_off is None and okp(slot):
                    content_off = find_prop(u64(slot + 0x10), "Content")
                row = 0
                if content_off is not None and okp(slot):
                    row = u64(slot + content_off)
                say("   slot%d 0x%X %s -> row=0x%X %s"
                    % (si, slot, cn2, row,
                       objclass(row) if okp(row) else ""))
    except OSError as e:
        say("vbox %s fail %s" % (tag, e))
say("offsets: Slots=0x%X Content=0x%X" % (slots_off or 0, content_off or 0))

# class-chain diagnostic: why no Visibility? look for *isib* props
for diag_tag, diag_obj in (("ROW", row_objs[0] if row_objs else None),
                           ("RTB", None)):
    if not diag_obj:
        continue
    try:
        c = u64(diag_obj + 0x10)
        for lvl in range(12):
            if not okp(c):
                break
            cn = IDS.get(u32(c + 0x18), "?")
            f = u64(c + 0x50)
            found = []
            for _ in range(4000):
                if not okp(f):
                    break
                nm2 = IDS.get(u32(f + 0x28))
                if nm2 and "isib" in nm2:
                    found.append("%s@0x%X" % (nm2, u32(f + 0x4C)))
                nxt = u64(f + 0x20)
                if not nxt:
                    break
                f = nxt
            say("  classchain %s lvl%d %s visib=%s" % (diag_tag, lvl, cn,
                                                       found or "-"))
            c = u64(c + 0x40)
    except OSError as e:
        say("  classchain %s fail %s" % (diag_tag, e))


def vbox_rows(vbox_owner, voff, tag):
    out = []
    try:
        v = u64(vbox_owner + voff)
        if not okp(v) or objclass(v) != "VerticalBox":
            return out
        if slots_off is None or content_off is None:
            return out
        data = u64(v + slots_off)
        num = u32(v + slots_off + 8)
        if not okp(data) or num > 64:
            return out
        for si in range(num):
            slot = u64(data + 8 * si)
            if not okp(slot):
                continue
            row = u64(slot + content_off)
            if okp(row) and (objclass(row) or "").startswith("WBP_SayEntry"):
                out.append((vbox_owner, tag, si, row))
    except OSError:
        pass
    return out


rows_all = []
for o, nm, cn in huds:
    rows_all += vbox_rows(o, 0x728, "CC")
    rows_all += vbox_rows(o, 0x730, "EN")


def row_report(row):
    vis = u8(row + vis_off) if vis_off is not None else None
    rtb = u64(row + 0x720)
    txt = None
    txt2 = None
    if okp(rtb):
        if text_off is not None:
            txt = ftext_str(rtb + text_off)
        txt2 = ftext_str(rtb + 0x530) if txt is None else None
    sayid = u32(row + 0x730)
    sl = ""
    try:
        d, n, m = struct.unpack("<QII", rpm(row + 0x738, 16))
        if okp(d) and 0 < n <= 32:
            names = []
            for k in range(min(n, 4)):
                names.append(str(fname(u32(d + 8 * k))))
            sl = "spk=[%s]" % ",".join(names)
    except OSError:
        pass
    return "row=0x%X hud=0x%X box=%s vis=%s sayid=%d %s text=%r" % (
        row, 0, "?", vis, sayid, sl, txt)


def sm_report():
    out = []
    for o, nm in mans:
        try:
            data = u64(o + 0x1C0)
            num = u32(o + 0x1C8)
            if num == 0 or not okp(data):
                out.append("SM 0x%X num=%d" % (o, num))
                continue
            line = "SM 0x%X num=%d" % (o, num)
            for i in range(min(num, 3)):
                ep = data + i * 0xB8
                t = ftext_str(ep + 0x70)
                line += " | e%d(id=%d %r)" % (i, u32(ep + 8), t)
            out.append(line)
        except OSError as e:
            out.append("SM 0x%X fail %s" % (o, e))
    return out


def hud_frames():
    out = []
    for o, nm, cn in huds:
        try:
            P = u64(o + 0x720)
            if okp(P) and u64(P + 0x20) == GAME_VT:
                eid = u32(P + 0x28)
                t = None
                if eid != 0xFFFFFFFF:
                    t = ftext_str(P + 0x90) or fstr(P + 0xE8)
                if eid != 0xFFFFFFFF or t:
                    out.append("frame 0x%X hud=0x%X E.id=%d text=%r"
                               % (P, o, eid, t))
        except OSError:
            pass
    return out


# ---- one-shot dump ----
for hud, tag, si, row in rows_all:
    say("VBOX %s " % tag + row_report(row).replace("hud=0x0", "hud=0x%X" % hud))
for o, nm, cn in huds:
    P = u64(o + 0x720)
    if okp(P) and u64(P + 0x20) == GAME_VT:
        say("HUD 0x%X +718=%X +720=0x%X +728=0x%X +730=0x%X +738=0x%X +740=0x%X"
            % (o, u32(o + 0x718), P, u64(o + 0x728), u64(o + 0x730),
               u64(o + 0x738), u64(o + 0x740)))
for l in sm_report():
    say(l)
for l in hud_frames():
    say(l)
for row in row_objs:
    say("ROWK " + row_report(row))

if WATCH_MIN > 0:
    say("watch start %s" % ts())
    last = None
    t0 = time.time()
    while time.time() - t0 < WATCH_MIN * 60:
        try:
            rows_now = []
            for o, nm, cn in huds:
                rows_now += vbox_rows(o, 0x728, "CC")
                rows_now += vbox_rows(o, 0x730, "EN")
            sig_rows = []
            for hud, tag, si, row in rows_now:
                vis = u8(row + vis_off) if vis_off is not None else None
                rtb = u64(row + 0x720)
                txt = ftext_str(rtb + text_off) if (
                    okp(rtb) and text_off is not None) else None
                sayid = u32(row + 0x730)
                sig_rows.append((row, tag, vis, sayid, txt))
            sig_sm = tuple(sm_report())
            sig_fr = tuple(hud_frames())
            sig_kr = []
            for row in row_objs:
                vis = u8(row + vis_off) if vis_off is not None else None
                rtb = u64(row + 0x720)
                txt = ftext_str(rtb + text_off) if (
                    okp(rtb) and text_off is not None) else None
                sig_kr.append((row, vis, u32(row + 0x730), txt))
            sig = (tuple(sig_rows), sig_sm, sig_fr, tuple(sig_kr))
        except OSError:
            sig = None
        if sig != last:
            last = sig
            say("---- %s ----" % ts())
            if sig:
                for row, tag, vis, sayid, txt in sig[0]:
                    say("  ROW 0x%X box=%s vis=%s sayid=%d text=%r"
                        % (row, tag, vis, sayid, txt))
                for l in sig[1]:
                    say("  " + l)
                for l in sig[2]:
                    say("  " + l)
                for row, vis, sayid, txt in sig[3]:
                    say("  ROWK 0x%X vis=%s sayid=%d text=%r"
                        % (row, vis, sayid, txt))
        time.sleep(0.4)

say("done")
