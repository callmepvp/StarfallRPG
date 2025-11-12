import time
from typing import Dict, Any

import json
from pathlib import Path

def regenerate_stamina(user_data: Dict) -> Dict:
    """Regenerates stamina based on time elapsed."""
    now = time.time()
    max_stamina = user_data.get("maxStamina", 200)
    current_stamina = user_data.get("stamina", 0)
    last_update = user_data.get("lastStaminaUpdate", now)

    # 1 stamina every 3 minutes = 180 seconds
    elapsed = now - last_update
    regen_amount = int(elapsed // 180)

    if regen_amount > 0 and current_stamina < max_stamina:
        new_stamina = min(current_stamina + regen_amount, max_stamina)
        user_data["stamina"] = new_stamina
        user_data["lastStaminaUpdate"] = now  # reset timer
    elif current_stamina >= max_stamina:
        user_data["lastStaminaUpdate"] = now  # don't stack regeneration

    return user_data

def calculate_power_rating(user: dict) -> int:
    """Calculates and returns a player's Power Rating."""
    strength = user.get("strength", 0)
    defense = user.get("defense", 0)
    evasion = user.get("evasion", 0)
    accuracy = user.get("accuracy", 0)
    max_hp = user.get("maxHP", 100)

    bonus_hp = max(0, max_hp - 100)
    bonus_hp_score = bonus_hp // 5  # every 5 HP above base = +1 power

    power = strength + defense + evasion + accuracy + bonus_hp_score
    return power

def has_skill_resources(subarea: Dict[str, Any], items: Dict[str, Any], skill_type: str) -> bool:
    return any(
        item_name in items and items[item_name].get("type") == skill_type
        for item_name in subarea.get("resources", [])
    )

async def unlock_collection_recipes(db, user_id: int, collection_name: str, new_level: int):
    """
    Checks the data/collections/{collection_name}.json file for recipes unlocked at this level
    and adds them to the player's recipes collection in MongoDB.
    """
    collection_path = Path(f"data/collections/{collection_name}.json")

    if not collection_path.exists():
        print(f"[WARN] No collection data file found for {collection_name}")
        return

    with open(collection_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Recipes unlocked at this level (stored as a list under the stringified level key)
    unlocked_recipes = data.get(str(new_level), [])
    if not unlocked_recipes:
        return  # No unlocks for this level

    # Ensure player has a recipe document
    rec_doc = await db.recipes.find_one({"id": user_id})
    if not rec_doc:
        await db.recipes.insert_one({"id": user_id})
        rec_doc = {"id": user_id}

    # Prepare update fields
    update_fields = {recipe.lower(): True for recipe in unlocked_recipes}

    # Apply unlocks
    await db.recipes.update_one(
        {"id": user_id},
        {"$set": update_fields},
        upsert=True
    )

    print(f"[INFO] Unlocked {len(unlocked_recipes)} recipes for {collection_name} level {new_level} (User {user_id})")