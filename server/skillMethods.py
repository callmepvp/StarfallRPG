from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import json
import math
import random

# load templates once
_ITEM_TEMPLATES_PATH = Path("data/itemTemplates.json")
_item_templates: Dict[str, Any] = {}
if _ITEM_TEMPLATES_PATH.exists():
    with _ITEM_TEMPLATES_PATH.open(encoding="utf-8") as fh:
        _item_templates = json.load(fh)


def stats_get(source: Optional[Dict[str, Any]], key: str, default):
    """
    Safe extractor:
    - if source is falsy: return default
    - if key exists directly on source: return it
    - if source['stats'] exists and is a dict and contains key: return it
    - else return default
    """
    if not source:
        return default
    if key in source:
        return source.get(key)
    s = source.get("stats")
    if isinstance(s, dict) and key in s:
        return s.get(key)
    return default


async def get_equipped_tool(db, user_id: int, slot: str) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """
    Fetches the player's equipment doc and returns:
      (tool_instance_dict or None, template_dict or None)

    - slot is like "farmingTool", "foragingTool", etc.
    - returns (None, None) if equipment missing or no tool equipped.
    """
    equip_doc = await db.equipment.find_one({"id": user_id})
    if not equip_doc:
        return None, None

    tool_iid = equip_doc.get(slot)
    if not tool_iid:
        return None, None

    instances = equip_doc.get("instances", []) or []
    tool_inst = next((it for it in instances if it.get("instance_id") == tool_iid), None)
    if not tool_inst:
        return None, None

    tmpl_name = tool_inst.get("template")
    tmpl = _item_templates.get(tmpl_name) if tmpl_name else None
    return tool_inst, tmpl


def calculate_final_qty(base_qty: int, tool_inst: Optional[Dict[str, Any]], template: Optional[Dict[str, Any]], skill_bonus: int) -> Tuple[int, bool, float]:
    """
    Compute final gathered integer quantity.

    - base_qty (int)
    - tool_inst: instance dict (may be None)
    - template: template dict (may be None)
    - skill_bonus: integer bonus (from skill doc) -> applied as 2% per bonus point (same as your existing logic)

    Returns (final_qty, bonus_gained_bool, float_qty_for_debugging)
    """
    # read multipliers (prefer instance then template then defaults)
    tool_yield = stats_get(tool_inst, "yield_multiplier",
                   stats_get(template, "yield_multiplier", 1.0))
    tool_extra = stats_get(tool_inst, "extra_roll_chance",
                   stats_get(template, "extra_roll_chance", 0.0))

    skill_mult = 1.0 + (skill_bonus * 0.02)

    float_qty = base_qty * tool_yield * skill_mult
    integer_qty = math.floor(float_qty)
    if random.random() < (float_qty - integer_qty):
        integer_qty += 1

    bonus_gained = False
    extra_chance = tool_extra + skill_bonus * 0.005
    if random.random() < extra_chance:
        integer_qty += 1
        bonus_gained = True

    final_qty = max(0, int(integer_qty))
    return final_qty, bonus_gained, float_qty


async def apply_gather_results(
    db,
    user_id: int,
    picked_key: str,
    final_qty: int,
    xp_per_unit: int,
    skill_prefix: str,
    skill_bonus_inc: int,
    essence_field: str,
    collection_key: str
) -> Dict[str, Any]:
    """
    Apply DB updates for a gather action and handle skill & collection levelups.

    - xp_per_unit: XP gained per unit (from item manifest)
    - skill_prefix: e.g. "farming" -> fields: farmingXP, farmingLevel, farmingBonus
    - skill_bonus_inc: how many 'bonus' points to increment on skill level up (your existing values)
    - essence_field: e.g. "farmingEssence"
    - collection_key: e.g. "crop" (collection document stores: { collection_key, collection_key + 'Level' })

    Returns summary dict:
    {
      "xp_gain": int,
      "skill_leveled": bool,
      "old_skill_level": int,
      "new_skill_level": int or None,
      "collection_leveled": bool,
      "old_collection_level": int,
      "new_collection_level": int or None
    }
    """
    # 1) inventory
    await db.inventory.update_one({"id": user_id}, {"$inc": {picked_key: final_qty}})

    # 2) stamina
    await db.general.update_one({"id": user_id}, {"$inc": {"stamina": -1}})

    # 3) XP
    xp_gain = xp_per_unit * final_qty
    skill_doc = await db.skills.find_one({"id": user_id})
    # defensive fetch
    old_xp = int(skill_doc.get(f"{skill_prefix}XP", 0))
    old_lvl = int(skill_doc.get(f"{skill_prefix}Level", 0))

    new_xp = old_xp + xp_gain
    lvl_threshold = 50 * old_lvl + 10

    skill_leveled = False
    new_level = None
    if new_xp >= lvl_threshold:
        skill_leveled = True
        leftover = new_xp - lvl_threshold
        new_level = old_lvl + 1
        await db.skills.update_one(
            {"id": user_id},
            {
                "$set": {f"{skill_prefix}Level": new_level, f"{skill_prefix}XP": leftover},
                "$inc": {f"{skill_prefix}Bonus": skill_bonus_inc}
            }
        )
    else:
        await db.skills.update_one({"id": user_id}, {"$set": {f"{skill_prefix}XP": new_xp}})

    # 4) essence (in general doc)
    await db.general.update_one({"id": user_id}, {"$inc": {essence_field: round(xp_gain * 0.35, 2)}})

    # 5) collection
    coll = await db.collections.find_one({"id": user_id})
    old_coll = int(coll.get(collection_key, 0))
    old_coll_lvl = int(coll.get(f"{collection_key}Level", 0))
    new_coll = old_coll + final_qty
    coll_thr = 50 * old_coll_lvl + 50

    coll_leveled = False
    new_coll_level = None
    if new_coll >= coll_thr:
        coll_leveled = True
        new_coll_level = old_coll_lvl + 1
        await db.collections.update_one(
            {"id": user_id},
            {"$set": {collection_key: new_coll, f"{collection_key}Level": new_coll_level}}
        )
        
        try:
            from server.userMethods import unlock_collection_recipes
            await unlock_collection_recipes(db, user_id, collection_key, new_coll_level)
        except Exception:
            # if something goes wrong, ignore (we don't want to break the gather)
            pass
    else:
        await db.collections.update_one({"id": user_id}, {"$set": {collection_key: new_coll}})

    return {
        "xp_gain": xp_gain,
        "skill_leveled": skill_leveled,
        "old_skill_level": old_lvl,
        "new_skill_level": new_level,
        "collection_leveled": coll_leveled,
        "old_collection_level": old_coll_lvl,
        "new_collection_level": new_coll_level
    }