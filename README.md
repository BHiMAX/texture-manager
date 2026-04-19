[Uploading README.md…]()
# Texture_Manager # 

A Blender addon to manage, relink, gather and inspect all texture paths in one panel.

**Location:** Properties → Scene → Texture File Path Editor

---

## Features

- **Filter textures** by status — All, Connected, Missing, Packed, or Unused
- **Relink** — search a directory recursively and automatically relink missing textures by filename
- **Collect** — copy all external textures into a single folder
- **Pack / Unpack** — pack images into the blend file or unpack them back to disk
- **Batch path editing** — change the directory for entire folder groups at once
- **Make Relative / Absolute** — convert all texture paths in one click
- **Remap Duplicates** — merge duplicate image datablocks and clean up the extras
- **Delete Missing & Unused** — remove broken or orphaned images from the file
- **Node cleanup** — remove disconnected nodes from selected objects or all materials
- **Stats panel** — total image count, breakdown by status, and total disk size
- **Octane Render support** — detects Octane image texture nodes alongside standard ones

---

## Requirements

- Blender 4.2 or newer

---

## Installation

1. Download the latest `.zip` from the [Releases](../../releases) page
2. In Blender: **Edit → Preferences → Add-ons → Install**
3. Select the downloaded `.zip`
4. Enable **Texture File Path Editor** in the list

> If upgrading from a previous version, **remove the old addon first** and restart Blender before installing the new one.

---

## Usage

Open the panel at **Properties → Scene** (the camera icon) → scroll down to **Texture File Path Editor**.

Click **Refresh** to scan all images in the current file. From there:

- Use the **filter dropdown** to narrow down what's shown
- **Check folders** in the list to select them for batch operations
- Point the **directory field** to a folder, then hit **Relink** or **Collect**

---

## Bug Reports

Found a bug? Open an issue on the [Issues](../../issues) page. Please include your Blender version and a short description of what went wrong.

---

## License

GPL-3.0-or-later — see [LICENSE](LICENSE) for details.
