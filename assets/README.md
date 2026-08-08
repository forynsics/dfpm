# Site assets

Pixel art for the landing site, starring **Brix**, the dfpm mascot.

Every file is loaded optionally: `app.js` probes each one, and a slot with no file
behind it falls back to a quiet placeholder rather than a broken image.

| File | Where it appears |
| --- | --- |
| `brix-hero.png` | Overview hero, beside the headline |
| `brix-clipboard.png` | Sidebar card |
| `brix-magnifier.png` | How it works, step 1 (review) |
| `brix-thumbsup.png` | How it works, step 5 (activate) |
| `brix-box.png` | Catalog banner |
| `brix-sleeping.png` | Overview, beside "what dfpm is not" |
| `brix-laptop.png` | Unused, kept for future pages |
| `divider-dam.png` | Section dividers on three pages |
| `parallax-far.png` | Hero, slowest layer — distant pine line |
| `parallax-mid.png` | Hero, middle layer — evergreen forest |
| `parallax-near.png` | Hero, fastest layer — riverbank and logs |

## These files are processed, not raw exports

The originals were 1536×1024 with large transparent margins, totalling about
25 MB. They were trimmed to their content bounds, downscaled, and re-encoded,
which brought the set to under 4 MB without any visible loss.

If you regenerate art, run the same preparation before committing it. Do not drop
a raw 2 MB export in here.

**They are single compositions, not tiles.** The CSS never repeats them; the
dividers and parallax layers are centred and scaled to fit. If you want true
horizontal tiling later, the art has to be authored seamlessly for it.

## Generating replacements

- **PNG with a real alpha channel.** Transparency in the alpha channel, not
  painted as a background colour.
- **No text in the artwork.** Image models garble small lettering — earlier
  attempts came back with caps reading `OFPM` and `DPPM`. Generate a blank amber
  patch on the cap; the wordmark is set in CSS, where it is crisp and correctly
  lowercase.
- **Generate at two to four times the display size.** The slots use
  `image-rendering: pixelated`, so downscaling stays sharp and upscaling does not.

## Palette

| Role | Hex |
| --- | --- |
| Amber (accent) | `#fca311` |
| Navy (deep) | `#14213d` |
| Cream (paper) | `#f4f2ed` |
| Ink (outline) | `#000000` |
| Warm brown (fur) | `#8a5a2b` |
