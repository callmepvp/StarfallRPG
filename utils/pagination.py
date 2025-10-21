from __future__ import annotations
import math
from typing import Any, Dict, List, Sequence

# Build inventory pages from an inventory document.
def build_inventory_pages(
    inv_doc: Dict[str, Any],
    items_manifest: Dict[str, Any],
    max_slots: int,
    items_per_page: int = 10,
    title: str = "Inventory"
) -> List[str]:
    """
    Convert inventory document -> pages (list[str]).
    inv_doc: mongo document for db.inventory
    items_manifest: data/items.json['items'] mapping for names & emojis
    max_slots: maxInventory to display in header
    items_per_page: page size
    """
    if not inv_doc:
        return [f"**{title}** — 0 items\n\n*(empty)*"]

    # Filter out metadata fields
    item_entries = [
        (k, inv_doc[k]) for k in inv_doc.keys()
        if k not in ("_id", "id") and isinstance(inv_doc[k], int) and inv_doc[k] > 0
    ]
    if not item_entries:
        return [f"**{title}** — 0 items\n\n*(empty)*"]

    # Build display lines
    lines: List[str] = []
    for key, qty in sorted(item_entries):
        emoji = items_manifest.get(key, {}).get("emoji", "")
        name = items_manifest.get(key, {}).get("name", key).title()
        lines.append(f"{qty} x {name} {emoji}".strip())

    pages: List[str] = []
    total_pages = max(1, math.ceil(len(lines) / items_per_page))
    for p in range(total_pages):
        start = p * items_per_page
        end = start + items_per_page
        page_lines = lines[start:end]
        header = f"**{title}** — Page {p+1}/{total_pages} — {len(lines):,}/{max_slots:,} slots \n\n"
        pages.append(header + "\n".join(page_lines))

    return pages


# Build pages for instances array (owned item instances)
def build_instance_pages(
    instances: Sequence[Dict[str, Any]],
    page_size: int = 15,
    title: str = "Items"
) -> List[str]:
    """
    Convert list of instance docs -> pages (list[str]).
    instances: list-like of instance dicts with 'instance_id', 'template', 'custom_name', 'enchants'
    """
    insts = list(instances or [])
    if not insts:
        return [f"**{title}** — 0 items\n\n*(no instances)*"]

    total_pages = max(1, math.ceil(len(insts) / page_size))
    pages: List[str] = []
    for p in range(total_pages):
        start = p * page_size
        end = start + page_size
        page_items = insts[start:end]
        header = f"**{title}** — Page {p+1}/{total_pages} — {len(insts)} total instance(s)\n\n"
        lines: List[str] = []
        for inst in page_items:
            iid = inst.get("instance_id", "<no-id>")
            template = inst.get("template", "Unknown")
            custom = inst.get("custom_name")
            enchants = inst.get("enchants") or []
            name_part = template if not custom else f"{template} ({custom})"
            enchants_part = f" [enchants: {len(enchants)}]" if enchants else ""
            lines.append(f"`{iid}` — {name_part}{enchants_part}")
        pages.append(header + "\n".join(lines))
    return pages
