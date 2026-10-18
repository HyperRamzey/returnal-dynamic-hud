import sys
sys.path.insert(0, r"D:\projects\xlamobot")
from pathlib import Path
from nexus_patch.smali import patch_request_entry_value_probe
root = Path(r"C:\Users\admin\AppData\Local\Temp\opencode\probeproof")
print("first run:", patch_request_entry_value_probe(root))
print("second run:", patch_request_entry_value_probe(root))
text = (root / "NexusOverlayHost.smali").read_text(encoding="utf-8")
for marker in ("entry_drop:paid", "entry_drop:nullentry", "entry_drop:norow",
               "entry_drop:notavail", "entry_drop:pending", "entry_drop:p1null",
               "entry_drop:nosnap", "entry_queued"):
    print(marker, text.count(f'"{marker}"'))
for label in (":nexus_nullentry", ":nexus_norow", ":nexus_notavail", ":nexus_nosnap"):
    print(label, text.count(label))
