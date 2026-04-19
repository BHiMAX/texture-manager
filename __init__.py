# ══════════════════════════════════════════════════════════════════════════════
# Texture File Path Editor  v2.0.0
# ══════════════════════════════════════════════════════════════════════════════

bl_info = {
    "name":        "Texture File Path Editor",
    "author":      "BHiMAX",
    "version":     (2, 0, 0),
    "blender":     (4, 2, 0),
    "location":    "Properties > Scene > Texture File Path Editor",
    "description": "Manage, relink, gather and inspect all texture paths in one panel",
    "tracker_url": "https://github.com/BHiMAX/texture-manager/issues",
    "category":    "Material",
}

import bpy
import os
import shutil
from collections import defaultdict, deque
from bpy.types  import Operator, Panel, UIList, PropertyGroup
from bpy.props  import (BoolProperty, StringProperty, IntProperty,
                        CollectionProperty, EnumProperty, PointerProperty)


# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════

OCTANE_IMAGE_NODES = {
    "ShaderNodeOctImageTexture", "ShaderNodeOctGrayImageTexture",
    "ShaderNodeOctAlphaImageTexture", "ShaderNodeOctFloatImageTexture",
    "ShaderNodeOctFloatImageTex", "ShaderNodeOctGreyscaleImageTexture",
    "ShaderNodeOctRGBImageTexture", "OctaneImageTexture",
    "OctaneImage", "OctaneImageTextureNode",
}

FILTER_ITEMS = [
    ("ALL",       "All",       "Show all textures"),
    ("CONNECTED", "Connected", "Show only connected textures"),
    ("MISSING",   "Missing",   "Show only missing textures"),
    ("PACKED",    "Packed",    "Show only packed textures"),
    ("UNUSED",    "Unused",    "Show images not used in any node"),
]

OUTPUT_TYPES = {
    "OUTPUT_MATERIAL", "OUTPUT_WORLD", "OUTPUT_LIGHT",
    "OCT_OUTPUT_AOV", "OCTANE_MATERIAL_OUTPUT", "OCTANE_SHADER_OUT",
}


# ══════════════════════════════════════════════════════════════════════════════
# CACHE
# ══════════════════════════════════════════════════════════════════════════════

_cache: dict = {}

def _get(scene_name: str) -> list:
    return _cache.get(scene_name, [])

def _set(scene_name: str, data: list) -> None:
    _cache[scene_name] = data


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def image_status(img) -> str:
    if img.packed_file:
        return "PACKED"
    if img.source == "FILE" and img.filepath:
        return "CONNECTED" if os.path.exists(bpy.path.abspath(img.filepath)) else "MISSING"
    return "MISSING"


def image_folder(img) -> str:
    if img.packed_file:
        return "[Packed]"
    if img.filepath:
        d = os.path.dirname(bpy.path.abspath(img.filepath))
        return (d or "(No Path)").replace("\\", "/")
    return "(No Path)"


def image_is_unused(img) -> bool:
    for mat in bpy.data.materials:
        if not (mat.use_nodes and mat.node_tree):
            continue
        for node in mat.node_tree.nodes:
            if getattr(node, "image", None) == img:
                return False
    for tex in bpy.data.textures:
        if getattr(tex, "image", None) == img:
            return False
    return True


def image_info(img) -> str:
    try:
        if img.size[0] and img.size[1]:
            cs = img.colorspace_settings.name if hasattr(img, "colorspace_settings") else ""
            return f"{img.size[0]}x{img.size[1]}  {cs}"
    except Exception:
        pass
    return ""


def build_file_index(root_dir: str) -> dict:
    index = {}
    if not (root_dir and os.path.isdir(root_dir)):
        return index
    for dirpath, _, files in os.walk(root_dir):
        for f in files:
            index[f.lower()] = os.path.join(dirpath, f)
    return index


def _connected_nodes(nt) -> set:
    connected = set()
    queue     = deque()
    for n in nt.nodes:
        if n.type in OUTPUT_TYPES:
            connected.add(n)
            queue.append(n)
    while queue:
        n = queue.popleft()
        for inp in n.inputs:
            for link in inp.links:
                up = link.from_node
                if up not in connected:
                    connected.add(up)
                    queue.append(up)
    return connected


def _count_by_status() -> dict:
    counts = {"ALL": 0, "CONNECTED": 0, "MISSING": 0, "PACKED": 0, "UNUSED": 0}
    for img in bpy.data.images:
        counts["ALL"] += 1
        st = image_status(img)
        if st in counts:
            counts[st] += 1
        if image_is_unused(img):
            counts["UNUSED"] += 1
    return counts


def _rebuild_list_from_cache(scene):
    backup = _get(scene.name)
    scene.texmgr_list.clear()
    for data in backup:
        if data["item_type"] == 0:
            _add_item(scene, data)
        else:
            hdr = next((h for h in backup
                        if h["item_type"] == 0 and h["display_name"] == data["dir_path"]), None)
            if hdr and not hdr.get("is_expanded", True):
                continue
            _add_item(scene, data)
    try:
        scene.texmgr_list_index = -1
    except Exception:
        pass


def _add_item(scene, data: dict):
    it = scene.texmgr_list.add()
    for k, v in data.items():
        try:
            setattr(it, k, v)
        except Exception:
            pass


def _disk_size_mb(img) -> float:
    try:
        p = bpy.path.abspath(img.filepath)
        if os.path.isfile(p):
            return os.path.getsize(p) / (1024 * 1024)
    except Exception:
        pass
    return 0.0


# ══════════════════════════════════════════════════════════════════════════════
# PROPERTY GROUPS
# ══════════════════════════════════════════════════════════════════════════════

class TexItem(PropertyGroup):
    item_type:      IntProperty(default=1)
    display_name:   StringProperty(default="")
    image_name_ref: StringProperty(default="")
    dir_path:       StringProperty(default="")
    status:         StringProperty(default="MISSING")
    is_expanded:    BoolProperty(default=True)
    is_selected:    BoolProperty(default=False)
    img_info:       StringProperty(default="")
    is_unused:      BoolProperty(default=False)


class TexMgrSettings(PropertyGroup):
    show_stats:        BoolProperty(name="Stats",       default=False)
    show_compare:      BoolProperty(name="Compare",     default=False)
    compare_directory: StringProperty(name="Compare Dir", subtype="DIR_PATH")


# ══════════════════════════════════════════════════════════════════════════════
# UI LIST
# ══════════════════════════════════════════════════════════════════════════════

class TEXMGR_UL_list(UIList):
    def draw_item(self, context, layout, data, item, icon,
                  active_data, active_propname, index):

        if item.item_type == 0:
            split    = layout.split(factor=0.03)
            col_tri  = split.column(align=True)
            col_main = split.column(align=True)
            tri = "TRIA_DOWN" if item.is_expanded else "TRIA_RIGHT"
            op  = col_tri.operator("texmgr.toggle_group", text="", icon=tri, emboss=False)
            op.group_index = index
            row = col_main.row(align=True)
            chk = row.operator("texmgr.toggle_select", text="",
                               icon="CHECKBOX_HLT" if item.is_selected else "CHECKBOX_DEHLT",
                               emboss=False)
            chk.group_index = index
            left = row.row(align=True)
            left.label(text=item.display_name, icon="FILE_FOLDER")
            right = row.row(align=True)
            right.alignment = "RIGHT"
            right.label(text=f"({item.image_name_ref})")
            cp = right.operator("texmgr.copy_path", text="", icon="COPYDOWN", emboss=False)
            cp.group_index = index
            return

        STATUS_ICON = {
            "CONNECTED": "CHECKMARK",
            "MISSING":   "CANCEL",
            "PACKED":    "PACKAGE",
        }
        split    = layout.split(factor=0.05)
        col_icon = split.column(align=True)
        col_main = split.column(align=True)
        col_icon.alert = (item.status == "MISSING")
        col_icon.label(text="", icon=STATUS_ICON.get(item.status, "QUESTION"))
        row = col_main.row(align=True)
        row.alert = (item.status == "MISSING")
        left = row.row(align=True)
        left.label(text=item.display_name)
        right = row.row(align=True)
        right.alignment = "RIGHT"
        if item.is_unused:
            right.label(text="unused", icon="ORPHAN_DATA")
        if item.img_info:
            right.label(text=item.img_info)
        op = right.operator("texmgr.open_node", text="", icon="NODE", emboss=False)
        op.image_name = item.image_name_ref
        rn = right.operator("texmgr.rename_image", text="", icon="GREASEPENCIL", emboss=False)
        rn.image_name = item.image_name_ref


# ══════════════════════════════════════════════════════════════════════════════
# OPERATORS — List management
# ══════════════════════════════════════════════════════════════════════════════

class TEXMGR_OT_refresh(Operator):
    bl_idname      = "texmgr.refresh"
    bl_label       = "Refresh"
    bl_description = "Scan all images and rebuild the list"

    def execute(self, context):
        scene       = context.scene
        filter_mode = scene.texmgr_filter
        backup      = _get(scene.name)
        prev        = {(e["item_type"], e["display_name"]): e
                       for e in backup if e["item_type"] == 0}
        grouped: dict = defaultdict(list)
        for img in bpy.data.images:
            grouped[image_folder(img)].append(img)
        all_data = []
        for folder, imgs in sorted(grouped.items()):
            def _passes(img):
                st = image_status(img)
                if filter_mode == "ALL":    return True
                if filter_mode == "UNUSED": return image_is_unused(img)
                return st == filter_mode
            visible = [(img, image_status(img)) for img in imgs if _passes(img)]
            if not visible:
                continue
            old = prev.get((0, folder), {})
            all_data.append({
                "item_type": 0, "display_name": folder,
                "image_name_ref": str(len(visible)), "dir_path": folder,
                "status": "HEADER", "is_expanded": old.get("is_expanded", False),
                "is_selected": old.get("is_selected", False),
                "img_info": "", "is_unused": False,
            })
            for img, st in visible:
                all_data.append({
                    "item_type": 1, "display_name": img.name,
                    "image_name_ref": img.name, "dir_path": folder,
                    "status": st, "is_expanded": True, "is_selected": False,
                    "img_info": image_info(img), "is_unused": image_is_unused(img),
                })
        _set(scene.name, all_data)
        _rebuild_list_from_cache(scene)
        self.report({"INFO"}, f"Found {len(bpy.data.images)} image(s) in {len(grouped)} folder(s).")
        return {"FINISHED"}


class TEXMGR_OT_toggle_group(Operator):
    bl_idname = "texmgr.toggle_group"; bl_label = "Toggle Group"
    bl_description = "Expand or collapse this folder group"
    group_index: IntProperty()
    def execute(self, context):
        scene = context.scene
        items = scene.texmgr_list
        if not (0 <= self.group_index < len(items)): return {"CANCELLED"}
        item = items[self.group_index]
        if item.item_type != 0: return {"CANCELLED"}
        item.is_expanded = not item.is_expanded
        backup = _get(scene.name)
        for e in backup:
            if e["item_type"] == 0 and e["display_name"] == item.display_name:
                e["is_expanded"] = item.is_expanded; break
        _set(scene.name, backup)
        _rebuild_list_from_cache(scene)
        return {"FINISHED"}


class TEXMGR_OT_toggle_select(Operator):
    bl_idname = "texmgr.toggle_select"; bl_label = "Toggle Select"
    bl_description = "Select or deselect this folder for batch operations"
    group_index: IntProperty()
    def execute(self, context):
        scene = context.scene
        items = scene.texmgr_list
        if not (0 <= self.group_index < len(items)): return {"CANCELLED"}
        item = items[self.group_index]
        if item.item_type != 0: return {"CANCELLED"}
        item.is_selected = not item.is_selected
        backup = _get(scene.name)
        for e in backup:
            if e["item_type"] == 0 and e["display_name"] == item.display_name:
                e["is_selected"] = item.is_selected; break
        _set(scene.name, backup)
        try: scene.texmgr_list_index = -1
        except Exception: pass
        return {"FINISHED"}


class TEXMGR_OT_copy_path(Operator):
    bl_idname = "texmgr.copy_path"; bl_label = "Copy Path"
    bl_description = "Copy this folder path to the clipboard"
    group_index: IntProperty()
    def execute(self, context):
        items = context.scene.texmgr_list
        if not (0 <= self.group_index < len(items)): return {"CANCELLED"}
        item = items[self.group_index]
        if item.item_type != 0: return {"CANCELLED"}
        context.window_manager.clipboard = item.display_name
        self.report({"INFO"}, f"Copied: {item.display_name}")
        return {"FINISHED"}


class TEXMGR_OT_select_by_status(Operator):
    bl_idname = "texmgr.select_by_status"; bl_label = "Select by Status"
    bl_description = "Select all folder groups containing images of this status"
    status: StringProperty()
    def execute(self, context):
        scene  = context.scene
        backup = _get(scene.name)
        folders = set()
        for e in backup:
            if e["item_type"] == 1:
                if self.status == "UNUSED":
                    img = bpy.data.images.get(e["image_name_ref"])
                    if img and image_is_unused(img): folders.add(e["dir_path"])
                elif e["status"] == self.status:
                    folders.add(e["dir_path"])
        count = 0
        for e in backup:
            if e["item_type"] == 0 and e["display_name"] in folders:
                e["is_selected"] = True; count += 1
        _set(scene.name, backup)
        _rebuild_list_from_cache(scene)
        self.report({"INFO"}, f"Selected {count} folder(s).")
        return {"FINISHED"}


class TEXMGR_OT_deselect_all(Operator):
    bl_idname = "texmgr.deselect_all"; bl_label = "Deselect All"
    bl_description = "Deselect all folder groups"
    def execute(self, context):
        backup = _get(context.scene.name)
        for e in backup:
            if e["item_type"] == 0: e["is_selected"] = False
        _set(context.scene.name, backup)
        _rebuild_list_from_cache(context.scene)
        return {"FINISHED"}


class TEXMGR_OT_rename_image(Operator):
    bl_idname  = "texmgr.rename_image"; bl_label = "Rename Image"
    bl_description = "Rename this image datablock"; bl_options = {"REGISTER","UNDO"}
    image_name: StringProperty()
    new_name:   StringProperty(name="New Name")
    def invoke(self, context, event):
        self.new_name = self.image_name
        return context.window_manager.invoke_props_dialog(self)
    def draw(self, context): self.layout.prop(self, "new_name", text="Name")
    def execute(self, context):
        img = bpy.data.images.get(self.image_name)
        if not img: self.report({"ERROR"}, "Image not found."); return {"CANCELLED"}
        img.name = self.new_name.strip() or self.image_name
        bpy.ops.texmgr.refresh()
        self.report({"INFO"}, f"Renamed to '{img.name}'."); return {"FINISHED"}


# ══════════════════════════════════════════════════════════════════════════════
# OPERATORS — Relocate / Gather / Pack / Unpack
# ══════════════════════════════════════════════════════════════════════════════

class TEXMGR_OT_relocate(Operator):
    bl_idname = "texmgr.relocate"; bl_label = "Relink"
    bl_description = "Search chosen directory recursively and relink matching textures"
    @classmethod
    def poll(cls, context):
        d = context.scene.texmgr_directory.strip()
        return bool(d) and os.path.isdir(bpy.path.abspath(d))
    def execute(self, context):
        scene    = context.scene
        root_dir = bpy.path.abspath(scene.texmgr_directory.strip())
        selected = {it.display_name for it in scene.texmgr_list
                    if it.item_type == 0 and it.is_selected}
        index  = build_file_index(root_dir)
        images = [img for img in bpy.data.images
                  if not img.packed_file
                  and (not selected or image_folder(img) in selected)]
        wm = context.window_manager
        wm.progress_begin(0, max(len(images), 1))
        relinked = 0
        for i, img in enumerate(images):
            wm.progress_update(i)
            filepath = bpy.path.abspath(img.filepath) if img.filepath else ""
            filename = os.path.basename(filepath) or img.name
            if not filename: continue
            found = index.get(filename.lower())
            if not found: continue
            try:
                img.source = "FILE"; img.filepath = found; img.reload(); relinked += 1
            except Exception: pass
        wm.progress_end()
        bpy.ops.texmgr.refresh()
        self.report({"INFO"}, f"Relinked {relinked} texture(s)."); return {"FINISHED"}


class TEXMGR_OT_gather(Operator):
    bl_idname = "texmgr.gather"; bl_label = "Collect"
    bl_description = "Copy all externally linked texture files into the chosen directory"
    @classmethod
    def poll(cls, context):
        d = context.scene.texmgr_directory.strip()
        return bool(d) and os.path.isdir(bpy.path.abspath(d))
    def execute(self, context):
        dest   = bpy.path.abspath(context.scene.texmgr_directory.strip())
        images = list(bpy.data.images)
        wm     = context.window_manager; wm.progress_begin(0, max(len(images), 1))
        copied = skipped = 0
        for i, img in enumerate(images):
            wm.progress_update(i)
            if img.packed_file or not img.filepath: skipped += 1; continue
            src = bpy.path.abspath(img.filepath)
            if not os.path.exists(src): skipped += 1; continue
            dst = os.path.join(dest, os.path.basename(src))
            try:
                if os.path.abspath(src) != os.path.abspath(dst): shutil.copy2(src, dst)
                copied += 1
            except Exception: skipped += 1
        wm.progress_end()
        self.report({"INFO"}, f"Collected {copied}, skipped {skipped}."); return {"FINISHED"}


class TEXMGR_OT_pack_selected(Operator):
    bl_idname = "texmgr.pack_selected"; bl_label = "Pack"
    bl_description = "Pack images from selected folder groups into the blend file"
    @classmethod
    def poll(cls, context):
        return any(it.is_selected and it.item_type == 0 for it in context.scene.texmgr_list)
    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)
    def execute(self, context):
        selected = {it.display_name for it in context.scene.texmgr_list
                    if it.item_type == 0 and it.is_selected}
        count = 0
        for img in bpy.data.images:
            if img.packed_file or image_folder(img) not in selected: continue
            try: img.pack(); count += 1
            except Exception: pass
        bpy.ops.texmgr.refresh()
        self.report({"INFO"}, f"Packed {count} image(s)."); return {"FINISHED"}


class TEXMGR_OT_unpack(Operator):
    bl_idname = "texmgr.unpack"; bl_label = "Unpack..."
    bl_description = "Unpack packed images from the blend file to disk"
    method: EnumProperty(name="Method", items=[
        ("USE_LOCAL",    "Use files in current directory", ""),
        ("WRITE_LOCAL",  "Write files to current directory", ""),
        ("USE_ORIGINAL", "Use original file paths", ""),
        ("REMOVE",       "Remove packed data", ""),
    ], default="WRITE_LOCAL")
    def invoke(self, context, event): return context.window_manager.invoke_props_dialog(self)
    def draw(self, context): self.layout.prop(self, "method", expand=True)
    def execute(self, context):
        selected = [it.display_name for it in context.scene.texmgr_list
                    if it.item_type == 0 and it.is_selected]
        count = 0
        for img in bpy.data.images:
            if not img.packed_file: continue
            if selected and image_folder(img) not in selected: continue
            try: img.unpack(method=self.method); count += 1
            except Exception: pass
        bpy.ops.texmgr.refresh()
        self.report({"INFO"}, f"Unpacked {count} image(s)."); return {"FINISHED"}


# ══════════════════════════════════════════════════════════════════════════════
# OPERATORS — Image data actions
# ══════════════════════════════════════════════════════════════════════════════

class TEXMGR_OT_delete_missing(Operator):
    bl_idname = "texmgr.delete_missing"; bl_label = "Delete Missing & Unused"
    bl_description = "Remove images missing from disk AND images not used in any node"
    @classmethod
    def poll(cls, context):
        return any(image_status(img)=="MISSING" or image_is_unused(img)
                   for img in bpy.data.images)
    def invoke(self, context, event): return context.window_manager.invoke_confirm(self, event)
    def execute(self, context):
        removed = 0
        for img in list(bpy.data.images):
            if image_status(img) == "MISSING" or image_is_unused(img):
                try: bpy.data.images.remove(img, do_unlink=True); removed += 1
                except Exception: pass
        bpy.ops.texmgr.refresh()
        self.report({"INFO"}, f"Deleted {removed} image(s)."); return {"FINISHED"}

class TEXMGR_OT_remap_dupes(Operator):
    bl_idname = "texmgr.remap_dupes"; bl_label = "Remap Duplicates"
    bl_description = "Remap duplicate image nodes to originals, then delete unused copies"
    def invoke(self, context, event): return context.window_manager.invoke_confirm(self, event)
    def execute(self, context):
        groups: dict = defaultdict(list)
        for img in bpy.data.images:
            base = (img.name.rsplit(".", 1)[0]
                    if "." in img.name and img.name.rsplit(".", 1)[1].isdigit()
                    else img.name)
            groups[base].append(img)
        to_delete = []; remapped = 0
        for base, imgs in groups.items():
            if len(imgs) <= 1: continue
            imgs.sort(key=lambda i: i.name); original = imgs[0]
            for dup in imgs[1:]:
                if dup == original: continue
                for mat in bpy.data.materials:
                    if not (mat.use_nodes and mat.node_tree): continue
                    for node in mat.node_tree.nodes:
                        if node.type == "TEX_IMAGE" and getattr(node,"image",None) == dup:
                            node.image = original; remapped += 1
                for tex in bpy.data.textures:
                    if getattr(tex,"image",None) == dup: tex.image = original; remapped += 1
                if dup.users == 0: to_delete.append(dup)
        deleted = 0
        for img in to_delete:
            if img.users == 0:
                try: bpy.data.images.remove(img); deleted += 1
                except Exception: pass
        bpy.ops.texmgr.refresh()
        if not remapped and not deleted: self.report({"INFO"}, "No duplicates found.")
        else: self.report({"INFO"}, f"Remapped {remapped}, deleted {deleted}.")
        return {"FINISHED"}


class TEXMGR_OT_paths_relative(Operator):
    bl_idname = "texmgr.paths_relative"; bl_label = "Make Relative"
    bl_description = "Make all texture paths relative to the blend file"
    @classmethod
    def poll(cls, context): return bool(bpy.data.filepath)
    def execute(self, context):
        count = 0
        for img in bpy.data.images:
            if img.packed_file or not img.filepath: continue
            try:
                abs_p = bpy.path.abspath(img.filepath)
                if os.path.isfile(abs_p): img.filepath = bpy.path.relpath(abs_p); count += 1
            except Exception: pass
        bpy.ops.texmgr.refresh()
        self.report({"INFO"}, f"Made {count} path(s) relative."); return {"FINISHED"}


class TEXMGR_OT_paths_absolute(Operator):
    bl_idname = "texmgr.paths_absolute"; bl_label = "Make Absolute"
    bl_description = "Make all texture paths absolute"
    def execute(self, context):
        count = 0
        for img in bpy.data.images:
            if img.packed_file or not img.filepath: continue
            try: img.filepath = bpy.path.abspath(img.filepath); count += 1
            except Exception: pass
        bpy.ops.texmgr.refresh()
        self.report({"INFO"}, f"Made {count} path(s) absolute."); return {"FINISHED"}


class TEXMGR_OT_multi_edit_path(Operator):
    bl_idname = "texmgr.multi_edit_path"; bl_label = "Change Directory"
    bl_description = "Change directory for all images in selected folder groups"
    bl_options = {"REGISTER","UNDO"}
    new_dir: StringProperty(name="New Directory", subtype="DIR_PATH")
    @classmethod
    def poll(cls, context):
        return any(it.is_selected and it.item_type==0 for it in context.scene.texmgr_list)
    def invoke(self, context, event):
        self.new_dir = ""; return context.window_manager.invoke_props_dialog(self)
    def draw(self, context): self.layout.prop(self, "new_dir", text="Directory")
    def execute(self, context):
        selected = {it.display_name for it in context.scene.texmgr_list
                    if it.item_type == 0 and it.is_selected}
        new_dir = bpy.path.abspath(self.new_dir.strip())
        if not os.path.isdir(new_dir):
            self.report({"ERROR"}, "Directory does not exist."); return {"CANCELLED"}
        count = 0
        for img in bpy.data.images:
            if img.packed_file or image_folder(img) not in selected: continue
            filename = os.path.basename(bpy.path.abspath(img.filepath)) if img.filepath else img.name
            try: img.filepath = os.path.join(new_dir, filename); img.reload(); count += 1
            except Exception: pass
        bpy.ops.texmgr.refresh()
        self.report({"INFO"}, f"Updated {count} image(s)."); return {"FINISHED"}


class TEXMGR_OT_open_node(Operator):
    bl_idname = "texmgr.open_node"; bl_label = "Select Node"
    bl_description = "Select the object using this texture and jump to its node"
    image_name: StringProperty()
    def _find_node(self, image):
        for mat in bpy.data.materials:
            if not (mat.use_nodes and mat.node_tree): continue
            for node in mat.node_tree.nodes:
                idname = getattr(node,"bl_idname","") or getattr(node,"type","")
                if ((node.type=="TEX_IMAGE" or idname in OCTANE_IMAGE_NODES)
                        and getattr(node,"image",None)==image): return mat, node
        return None, None
    def _find_owner(self, mat):
        return next((obj for obj in bpy.data.objects
                     if obj.type=="MESH" and any(s.material==mat for s in obj.material_slots)), None)
    def _find_shader_editor(self, context):
        for area in context.screen.areas:
            if area.type != "NODE_EDITOR": continue
            for sp in area.spaces:
                if getattr(sp,"tree_type","") == "ShaderNodeTree": return area, sp
        return None, None
    def execute(self, context):
        image = bpy.data.images.get(self.image_name)
        if not image: self.report({"ERROR"}, "Image not found."); return {"CANCELLED"}
        mat, node = self._find_node(image)
        if not node: self.report({"WARNING"}, f"Not used in any shader node."); return {"CANCELLED"}
        owner = self._find_owner(mat)
        if owner:
            try:
                bpy.ops.object.select_all(action="DESELECT")
                owner.select_set(True); context.view_layer.objects.active = owner
            except Exception: pass
        area, space = self._find_shader_editor(context)
        if not area: self.report({"WARNING"}, "No Shader Editor open."); return {"CANCELLED"}
        try: space.shader_type = "OBJECT"
        except Exception: pass
        try:
            for n in mat.node_tree.nodes: n.select = False
            node.select = True; mat.node_tree.nodes.active = node
            space.node_tree = mat.node_tree
        except Exception: pass
        try:
            with context.temp_override(area=area, space_data=space, region=area.regions[-1]):
                bpy.ops.node.view_selected("INVOKE_DEFAULT", use_all=False)
        except Exception: pass
        self.report({"INFO"}, f"{owner.name if owner else '?'} -> {mat.name} -> {node.name}")
        return {"FINISHED"}


# ══════════════════════════════════════════════════════════════════════════════
# NODE CLEANUP
# ══════════════════════════════════════════════════════════════════════════════

def _cleanup(mat) -> int:
    if not (mat and mat.node_tree): return 0
    nt = mat.node_tree; unused = set(nt.nodes) - _connected_nodes(nt); count = 0
    for n in list(unused):
        try: nt.nodes.remove(n); count += 1
        except Exception: pass
    return count


class NODE_OT_cleanup_selected(Operator):
    bl_idname = "node.cleanup_selected"; bl_label = "Clean Selected"
    bl_description = "Remove disconnected nodes from materials on selected objects"
    bl_options = {"REGISTER","UNDO"}
    def invoke(self, context, event): return context.window_manager.invoke_confirm(self, event)
    def execute(self, context):
        removed = sum(_cleanup(s.material) for obj in context.selected_objects
                      for s in getattr(obj,"material_slots",[]) if s.material)
        self.report({"INFO"}, f"Removed {removed} unused node(s)."); return {"FINISHED"}


class NODE_OT_cleanup_all(Operator):
    bl_idname = "node.cleanup_all"; bl_label = "Clean All"
    bl_description = "Remove disconnected nodes from every material in this file"
    bl_options = {"REGISTER","UNDO"}
    def invoke(self, context, event): return context.window_manager.invoke_confirm(self, event)
    def execute(self, context):
        removed = sum(_cleanup(m) for m in bpy.data.materials)
        self.report({"INFO"}, f"Removed {removed} unused node(s)."); return {"FINISHED"}


# ══════════════════════════════════════════════════════════════════════════════
# PANEL
# ══════════════════════════════════════════════════════════════════════════════

class TEXMGR_PT_panel(Panel):
    bl_label = "Texture File Path Editor"; bl_idname = "TEXMGR_PT_panel"
    bl_space_type = "PROPERTIES"; bl_region_type = "WINDOW"; bl_context = "scene"

    def draw_header(self, context):
        has_missing = any(image_status(img)=="MISSING" for img in bpy.data.images)
        self.layout.alert = has_missing
        self.layout.label(text="", icon="IMAGE_DATA")

    def draw(self, context):
        layout = self.layout
        scene  = context.scene
        if not hasattr(scene, 'texmgr_filter'):
            layout.label(text="Restart Blender to finish loading.", icon='INFO')
            return
        settings = scene.texmgr_settings
        counts   = _count_by_status()

        # ── Filter + Refresh ──────────────────────────────────────────────
        top = layout.row(align=True)
        top.prop(scene, "texmgr_filter", text="")
        top.operator("texmgr.refresh", text="", icon="FILE_REFRESH")

        layout.separator(factor=0.4)

        # ── File Operations ──────────────────────────────────────────────
        rel = layout.box()
        rel.label(text="File Operations", icon="FILE_FOLDER")
        rel.prop(scene, "texmgr_directory", text="")
        r1 = rel.row(align=True); r1.scale_y = 1.1
        r1.operator("texmgr.relocate", icon="UV_SYNC_SELECT")
        r1.operator("texmgr.gather",   icon="IMPORT")
        if scene.texmgr_filter == "PACKED":
            rel.operator("texmgr.unpack", icon="PACKAGE")
        layout.separator(factor=0.4)

        # ── Texture list ──────────────────────────────────────────────────
        if not bpy.data.images:
            box = layout.box()
            box.label(text="No images in this file.", icon="INFO")
            box.operator("texmgr.refresh", text="Refresh", icon="FILE_REFRESH")
        else:
            layout.template_list("TEXMGR_UL_list", "texmgr_list",
                                 scene, "texmgr_list", scene, "texmgr_list_index", rows=10)

        layout.separator(factor=0.4)

        # ── Image data ────────────────────────────────────────────────────
        img_box = layout.box()
        img_box.label(text="Image Data", icon="IMAGE_DATA")
        r1 = img_box.row(align=True)
        r1.operator("texmgr.remap_dupes",    text="Remap Dupes",    icon="IMAGE_DATA")
        r1.operator("texmgr.delete_missing", text="Delete Missing/Unused", icon="TRASH")

        layout.separator(factor=0.2)

        # ── Node graph ────────────────────────────────────────────────────
        ng = layout.box()
        ng.label(text="Node Graph", icon="NODETREE")
        row = ng.row(align=True)
        row.operator("node.cleanup_selected", text="Clean Selected", icon="NODE")
        row.operator("node.cleanup_all",      text="Clean All",      icon="SCENE_DATA")

        layout.separator(factor=0.2)

        # ── Stats (collapsible) ───────────────────────────────────────────
        st_hdr = layout.row(align=True)
        st_hdr.prop(settings, "show_stats", text="",
                    icon="TRIA_DOWN" if settings.show_stats else "TRIA_RIGHT", emboss=False)
        st_hdr.label(text="Stats", icon="INFO")

        if settings.show_stats:
            sb = layout.box().column(align=True)
            total_mb = sum(_disk_size_mb(img) for img in bpy.data.images if not img.packed_file)
            sb.label(text=f"Total:      {counts['ALL']}")
            sb.label(text=f"Connected:  {counts['CONNECTED']}")
            sb.label(text=f"Missing:    {counts['MISSING']}")
            sb.label(text=f"Packed:     {counts['PACKED']}")
            sb.label(text=f"Unused:     {counts['UNUSED']}")
            sb.separator(factor=0.3)
            sb.label(text=f"Disk size:  {total_mb:.1f} MB")


# ══════════════════════════════════════════════════════════════════════════════
# REGISTRATION
# ══════════════════════════════════════════════════════════════════════════════

classes = (
    TexItem, TexMgrSettings, TEXMGR_UL_list,
    TEXMGR_OT_refresh, TEXMGR_OT_toggle_group, TEXMGR_OT_toggle_select,
    TEXMGR_OT_copy_path, TEXMGR_OT_select_by_status, TEXMGR_OT_deselect_all,
    TEXMGR_OT_rename_image, TEXMGR_OT_relocate, TEXMGR_OT_gather,
    TEXMGR_OT_pack_selected, TEXMGR_OT_unpack, TEXMGR_OT_delete_missing,
    TEXMGR_OT_remap_dupes, TEXMGR_OT_paths_relative,
    TEXMGR_OT_paths_absolute, TEXMGR_OT_multi_edit_path,
    TEXMGR_OT_open_node, NODE_OT_cleanup_selected, NODE_OT_cleanup_all,
    TEXMGR_PT_panel,
)



@bpy.app.handlers.persistent
def _on_load(filepath):
    try: bpy.ops.texmgr.refresh()
    except Exception: pass


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    sce = bpy.types.Scene
    sce.texmgr_list       = CollectionProperty(type=TexItem)
    sce.texmgr_list_index = IntProperty(default=-1)
    sce.texmgr_filter     = EnumProperty(name="Filter", items=FILTER_ITEMS, default="ALL")
    sce.texmgr_directory   = StringProperty(name="Directory", subtype="DIR_PATH")
    sce.texmgr_settings    = PointerProperty(type=TexMgrSettings)
    if _on_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load)


def unregister():
    if _on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load)
    for cls in reversed(classes):
        try: bpy.utils.unregister_class(cls)
        except Exception: pass
    sce = bpy.types.Scene
    for attr in ("texmgr_list","texmgr_list_index","texmgr_filter",
                 "texmgr_directory","texmgr_settings"):
        try: delattr(sce, attr)
        except Exception: pass
    _cache.clear()


if __name__ == "__main__":
    register()
