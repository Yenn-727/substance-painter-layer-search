# Layer Search for Substance 3D Painter

A search bar in the Layers panel header, between the channel dropdown ("Base color") and the layer icons.
Type a name, click a result, and the stack opens the parent groups, selects the layer and scrolls to it.

## Features

- Live search of every layer and group in the active texture set (matches anywhere in the name or path)
- Click a result to select the layer, expand its parent groups and scroll it into view
- The results list stays open, so you can click through several results quickly
- You can scroll and click the layer stack with the results open
- Each result shows the layer name and its parent path in grey
- Styled to match the channel dropdown, and resizes with the panel
- Up / Down and Enter work in the box; Esc hides the list (anywhere), and clears the box when you're typing in it

## Install

1. Download `layer_search.py`.
2. Copy it to `Documents/Adobe/Adobe Substance 3D Painter/python/plugins/`.
3. Start Painter and enable it from the **Python** menu (`layer_search`).

To update, replace the file and restart Painter.

## Compatibility

- Tested on **Substance 3D Painter 12.2**.
- Needs **10.1 or newer**: it uses PySide6 and the layer stack Python API.
- Painter's panel layout isn't part of its public API, so the box finds the Layers header by widget names
  (`channelSelector`, `LayersStackView`). A future Painter update could break that; please open an issue with your version.

## Settings

Near the top of `layer_search.py`:

- `GAP` - spacing around the box
- `INCLUDE_EFFECTS` - also search effects (fills, filters and so on)

## Credits

Written with help from Claude (Anthropic).

## Licence

MIT - see [LICENSE](LICENSE).
