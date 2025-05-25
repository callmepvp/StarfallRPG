import time
from typing import Dict, Any

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
