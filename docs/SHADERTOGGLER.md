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
- **Subtitles vanish** while the HUD is hidden: they use the shared UI-text
  shader `1844482002` — resolved 2026-10-19, see the subtitle verdict below.

## Subtitle fix — verdict (2026-10-19): no shader separation

Direct test, subtitle line on screen (scout-log cue, game paused):

- the Group2 key (`{1844482002}` alone) makes the subtitle vanish together
  with the rest of the HUD text → the subtitle is drawn by the shared UI
  shader `1844482002`;
- removing that hash from Group0 would disable HUD hiding entirely (Group0
  would keep only the minimap hash `2457571040`), so it stays.

"Only the subtitles" is therefore unreachable through ShaderToggler. The
adopted mechanism is the **tool-side cue trigger**: the HUD is shown while a
subtitle cue is active (`SayManager` queue `num>0` — spans the whole cue,
including inter-line gaps; live chain documented in `docs/PROCESS.md`).

The only route to true subtitle-only display left would be an external
overlay drawing the (fully readable) subtitle text while the HUD stays
hidden — possible, not built.
