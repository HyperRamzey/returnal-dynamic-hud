# ShaderToggler integration

`hud_dynamic` does not hide anything itself. The actual shader blocking is
done by [ShaderToggler](https://github.com/FransBouma/ShaderToggler) — a
ReShade addon by Frans Bouma (MIT,
[releases](https://github.com/FransBouma/ShaderToggler/releases); ReShade
itself from <https://reshade.me>) — the tool only flips one byte.

## How the integration works

- The addon keeps a `std::vector<Record>` of groups: globals at addon RVA
  `0x23AF8` (begin) / `0x23B00` (end), record size 280 bytes (`0x118`).
- Record `+0x110` is the toggle byte: `1` = the group's shaders are blocked,
  `0` = they draw normally. The tool writes this byte directly — no key
  simulation of any kind.
- The group index driven by the tool is `--group N` (default 0 = "Toggle
  HUD"). The addon's own hotkey still works; the tool re-asserts its state
  within ~0.2 s.
- Which pixels are affected by a group is entirely the group's shader hash
  list in `ShaderToggler.ini`. The tool never edits the ini.

## Current groups (shipped configuration)

The exact working configuration is shipped in this repo as
[`setup/ShaderToggler.ini`](../setup/ShaderToggler.ini) (SHA256
`27A042E807B8FBC8C211B58F794753FF5A483545CB52CF9DFFF581354933E7C3`) — copy it
next to the game exe (same folder as `ShaderToggler.addon64`). The tool never
edits the ini.

| group | name | hashes |
|---|---|---|
| 0 | Toggle HUD | 2457571040, 1844482002 |
| 1 | Except Minimap | 1844482002, 3005719831 |
| 2 | Except Minimap+Crosshair | 1844482002 |
| 3 | Toggle Crosshair | 3005719831 |

Observed consequences:

- **Crosshair survives** HUD hiding: hash `3005719831` is not in Group0.
- **Tutorial banner backgrounds survive** HUD hiding mid-banner (the
  "leftover boxes"): the banner background uses shader(s) outside Group0.
  v1.3.0's sustained layer rule means the HUD no longer hides mid-banner, so
  this is now only a belt-and-braces concern.
- **Subtitles vanish** while the HUD is hidden: the subtitle text shader is
  inside Group0's list (either the shared UI-text hash or the group-only
  2457571040 — unknown until hunted).

## Open work: the subtitle fix (one in-game shader hunt)

Goal: subtitle text visible while everything else stays hidden ("only the
subtitles", user request).

1. Play an audio log (a subtitle line shows on screen).
2. Open the ShaderToggler shader-hunting feature in the ReShade overlay while
   the subtitle is visible (see the ShaderToggler README for hunting mode /
   hotkeys). Note the hash(es) drawn by the subtitle text.
3. If the subtitle hash is distinct from the rest of the HUD text: **remove
   that hash from Group0**. Subtitles then always draw; the tool still
   toggles everything else.
4. Optionally, while a tutorial banner is up, catch the banner-background
   shader and **add it to Group0** so even a mid-banner hide would leave no
   leftovers.
5. Save the ReShade config. A game restart applies it.

If step 3 shows the subtitle uses the same hash as all other HUD text,
shader-level separation is impossible; the fallback is a UI-event trigger
(whole HUD shows while a subtitle line is up — see `docs/PROCESS.md`,
open items).
