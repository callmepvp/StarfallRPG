#this file will hold all important methods to save, load and handle inventory, collection, area and general data.

from json import loads
from pathlib import Path

from pymongo import MongoClient

#Retrieve tokens & Initialize database
data = loads(Path("data/config.json").read_text())
itemsData = loads(Path("data/items.json").read_text())
collectionData = loads(Path("data/collections/herb.json").read_text())
DATABASE_TOKEN = data['DATABASE_TOKEN']

cluster = MongoClient(DATABASE_TOKEN)
general = cluster['alphaworks']['general']
inventory = cluster['alphaworks']['inventory']
skills = cluster['alphaworks']['skills']
collections = cluster['alphaworks']['collections']
recipes = cluster['alphaworks']['recipes']
areas = cluster['alphaworks']['areas']

#* Data Management Methods
#Some methods also return a wrapped text array that must be taken as an output

def updateInventory(userID: int, item: str, amount: int):
    currentInventory = inventory.find_one({'id' : userID, item : {'$exists' : True}})
    if currentInventory is None:
        inventory.update_one({'id' : userID}, {"$set":{item : amount}})
    else:
        inventory.update_one({'id' : userID}, {"$set":{item : currentInventory[item] + amount}})

def updateEssence(userID: int, skill: str, xp: int, messageArray):
    Essence = skill + "Essence"
    existingEssence = general.find_one({'id' : userID})[Essence]
    essenceFormula = round((xp * 0.35), 2)

    general.update_one({'id' : userID}, {"$set":{Essence : existingEssence + essenceFormula}})
    messageArray.append(f"\n :sparkles: You gained **{essenceFormula} {skill.capitalize()} Essence!**")

    return messageArray

def updateSkills(userID: int, skill: str, xp: int, messageArray):
    skillXP = skill + 'XP'
    skillLevel = skill + 'Level'
    skillBonus = skill + 'Bonus'
    existingXP = skills.find_one({'id' : userID})[skillXP]
    existingLevel = skills.find_one({'id' : userID})[skillLevel]
    existingBonus = skills.find_one({'id' : userID})[skillBonus]
    bonusAmount = 1 #depends on skill

    if existingXP + xp >= (50*existingLevel+10):
        leftoverXP = (existingXP + xp) - (50*existingLevel+10)
        if leftoverXP == 0:
            skills.update_one({'id' : userID}, {"$set":{skillXP : 0, skillLevel : existingLevel + 1}})
        else:
            skills.update_one({'id' : userID}, {"$set":{skillXP : leftoverXP, skillLevel : existingLevel + 1}})

        skills.update_one({'id' : userID}, {"$set":{skillBonus : existingBonus + bonusAmount}})
        messageArray.append('\n' f':star: You gained **{xp} {skill.capitalize()}** XP!' '\n' f'**[LEVEL UP]** Your **{skill.capitalize()}** leveled up! You are now **{skill.capitalize()}** level **{existingLevel + 1}**!' '\n' f'**[LEVEL BONUS]** **WIP** Bonus: **{existingBonus}** ⇒ **{existingBonus + bonusAmount}**')
    else:
        skills.update_one({'id' : userID}, {"$set":{skillXP : existingXP + xp}})
        messageArray.append('\n' f':star: You gained **{xp} {skill.capitalize()}** XP!')

    return messageArray

#! change all collections to be in one file like the items file, also update it so the amount of collection is available based on only the level (maybe)
def updateCollections(userID: int, amount: int, collectionType: str, messageArray):
    collection = collectionType
    collectionLevel = collectionType + "Level"
    currentCollection = collections.find_one({'id' : userID})[collection]
    currentCollectionLevel = collections.find_one({'id' : userID})[collectionLevel]

    if currentCollection + amount >= (currentCollectionLevel*50 + 50):
        collections.update_one({'id' : userID}, {"$set":{collection : currentCollection + amount}})
        collections.update_one({'id' : userID}, {"$set":{collectionLevel : currentCollectionLevel + 1}})
        messageArray.append('\n' f'**[COLLECTION]** **{collectionType}** Collection Level **{currentCollectionLevel}** ⇒ **{currentCollectionLevel + 1}**')
    
        #Give collection rewards
        for i in collectionData[f"{collections.find_one({'id' : userID})[collectionLevel]}"]:
            print(collectionData[f"{collections.find_one({'id' : userID})[collectionLevel]}"])
            recipes.update_one({'id' : userID}, {"$set":{i : True}}) #Update the users recipes
    else:
        collections.update_one({'id' : userID}, {"$set":{collection : currentCollection + amount}})

    return messageArray


#* Resource Management Methods

#Also returns their weights by default
def updateAndReturnAvailableResources(userID: int, skill: str):

    searchTier = skill + "Tier"
    searchAvailable = "available" + skill[:2].capitalize()
    tier = skills.find_one({'id' : userID})[searchTier]

    choices, weights = [], []
    if '1' in tier:
        tier = tier[1:]
        for itemName, itemData in itemsData['items'].items():
            if itemData["location"] == "plains" and itemData["tier"] == "hand":
                choices.append(itemName)
                weights.append(itemData["weight"])

        skills.update_one({'id' : userID}, {"$set":{searchTier : tier}})
        areas.update_one({'id' : userID}, {"$set":{searchAvailable : [choices, weights]}})
    else:
        infoArray = areas.find_one({'id' : userID})[searchAvailable]
        choices, weights = infoArray[0], infoArray[1]

    return choices, weights
