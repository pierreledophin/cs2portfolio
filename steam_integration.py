"""
Steam Integration Module

Fonctions pour auto-détecter les skins CS2 depuis l'inventaire Steam.
"""

import os
import time
import requests
import pandas as pd
from typing import Optional, List, Tuple

# Configuration
STEAM_API_BASE = "https://api.steampowered.com"
STEAM_COMMUNITY_BASE = "https://steamcommunity.com"

CS2_APPID = 730
CS2_CONTEXT_ID = 2


def get_steam_id_from_vanity(vanity_url: str, steam_api_key: str) -> Optional[str]:
    """
    Convertir une vanity URL Steam (ex: 'pierreledophin') en SteamID64.
    
    Args:
        vanity_url: Vanity URL (ex: 'pierreledophin')
        steam_api_key: Clé API Steam
        
    Returns:
        SteamID64 ou None
    """
    if not steam_api_key or not vanity_url:
        return None
    
    try:
        url = f"{STEAM_API_BASE}/ISteamUser/ResolveVanityURL/v1/"
        params = {"vanityurl": vanity_url.strip(), "key": steam_api_key}
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        
        if data.get("response", {}).get("success") == 1:
            return str(data["response"]["steamid"])
        return None
    except Exception as e:
        print(f"[ERROR] ResolveVanityURL: {e}")
        return None


def fetch_steam_inventory(steam_id: str, timeout: int = 20) -> List[dict]:
    """
    Récupérer l'inventaire CS2 (AppID 730, Context 2) d'un utilisateur.
    
    Args:
        steam_id: SteamID64 de l'utilisateur
        timeout: Timeout en secondes
        
    Returns:
        Liste des items avec market_hash_name, asset_id, classid, etc.
    """
    if not steam_id:
        return []
    
    try:
        # Inventory API v2 (plus fiable)
        url = f"{STEAM_COMMUNITY_BASE}/inventory/{steam_id}/{CS2_APPID}/{CS2_CONTEXT_ID}"
        params = {"l": "english", "count": 5000}
        print(f"[DEBUG] Fetching inventory from: {url}")
        print(f"[DEBUG] Params: {params}")
        
        r = requests.get(url, params=params, timeout=timeout)
        print(f"[DEBUG] Response status: {r.status_code}")
        print(f"[DEBUG] Response headers: {dict(r.headers)}")
        
        r.raise_for_status()
        data = r.json()
        
        print(f"[DEBUG] Response data keys: {list(data.keys()) if isinstance(data, dict) else 'not dict'}")
        print(f"[DEBUG] Success field: {data.get('success') if isinstance(data, dict) else 'N/A'}")
        
        # Vérifier les erreurs
        if not data.get("success"):
            print(f"[WARN] Inventory API returned success=false")
            print(f"[DEBUG] Full response: {data}")
            return []
        
        # Vérifier s'il y a des assets
        assets = data.get("assets", [])
        descriptions = data.get("descriptions", [])
        
        if not assets:
            print(f"[WARN] No assets found in inventory")
            return []
        
        if not descriptions:
            print(f"[WARN] No descriptions found in inventory")
            return []
        
        print(f"[DEBUG] Found {len(assets)} assets and {len(descriptions)} descriptions")
        
        # Extraire les assets
        assets = data.get("assets", [])
        print(f"[DEBUG] Found {len(assets)} assets")
        
        for asset in assets:
            classid = asset.get("classid")
            if not classid or classid not in descriptions:
                print(f"[DEBUG] Skipping asset {asset.get('assetid')} - classid {classid} not in descriptions")
                continue
            
            desc = descriptions[classid]
            market_hash = desc.get("market_hash_name", "")
            
            if not market_hash:
                print(f"[DEBUG] Skipping asset {asset.get('assetid')} - no market_hash_name")
                continue
            
            items.append({
                "market_hash_name": market_hash.strip(),
                "asset_id": asset.get("assetid"),
                "classid": classid,
                "instance_id": asset.get("instanceid"),
                "float_value": desc.get("floatvalue"),
                "item_name": desc.get("name", ""),
                "type": desc.get("type", ""),
            })
        
        print(f"[INFO] Fetched {len(items)} items from Steam inventory for {steam_id}")
        return items
        
    except Exception as e:
        print(f"[ERROR] fetch_steam_inventory: {e}")
        import traceback
        traceback.print_exc()
        return []


def detect_new_skins(
    steam_items: List[dict],
    holdings_df: pd.DataFrame,
    include_duplicates: bool = True
) -> pd.DataFrame:
    """
    Comparer les items Steam avec holdings.csv et retourner les NOUVEAUX.
    
    Args:
        steam_items: Liste des items depuis Steam
        holdings_df: DataFrame holdings.csv actuel
        include_duplicates: Si True, compter les qty > 1 des items déjà présents
        
    Returns:
        DataFrame des items à importer
    """
    if not steam_items:
        return pd.DataFrame(columns=["market_hash_name", "qty", "type", "item_name"])
    
    # Compter les items par name dans Steam
    steam_counts = {}
    for item in steam_items:
        name = item["market_hash_name"]
        steam_counts[name] = steam_counts.get(name, 0) + 1
    
    # Holdings actuels
    if holdings_df.empty:
        holdings_counts = {}
    else:
        holdings_counts = holdings_df.groupby("market_hash_name")["qty"].sum().to_dict()
    
    # Items à ajouter
    new_items = []
    
    for name, steam_qty in steam_counts.items():
        holdings_qty = holdings_counts.get(name, 0)
        
        if steam_qty > holdings_qty:
            qty_to_add = steam_qty - holdings_qty
            # Trouver un example item pour ce name (pour item_name, type)
            example = next((i for i in steam_items if i["market_hash_name"] == name), None)
            
            new_items.append({
                "market_hash_name": name,
                "qty": qty_to_add,
                "type": example.get("type", "") if example else "",
                "item_name": example.get("item_name", "") if example else "",
                "float_value": example.get("float_value") if example else None,
            })
    
    return pd.DataFrame(new_items)


def import_new_skins_to_holdings(
    new_skins_df: pd.DataFrame,
    holdings_df: pd.DataFrame,
    default_price: float = 0.0
) -> pd.DataFrame:
    """
    Ajouter les nouveaux skins à holdings.csv.
    
    Args:
        new_skins_df: DataFrame des skins à ajouter
        holdings_df: DataFrame holdings.csv actuel
        default_price: Prix par défaut pour les nouveaux items
        
    Returns:
        DataFrame holdings.csv mise à jour
    """
    if new_skins_df.empty:
        return holdings_df
    
    rows_to_add = []
    for _, row in new_skins_df.iterrows():
        rows_to_add.append({
            "market_hash_name": row["market_hash_name"],
            "qty": int(row["qty"]),
            "buy_price_usd": default_price,
            "buy_date": "",
            "notes": f"Auto-imported from Steam inventory",
        })
    
    new_df = pd.DataFrame(rows_to_add)
    result = pd.concat([holdings_df, new_df], ignore_index=True)
    
    # Dédupliquer/consolider si le même item existe déjà
    result = result.groupby("market_hash_name", as_index=False).agg({
        "qty": "sum",
        "buy_price_usd": "first",
        "buy_date": "first",
        "notes": "first",
    })
    
    return result


def validate_steam_api_key(steam_api_key: str) -> bool:
    """
    Valider si la clé API Steam est valide (test simple).
    """
    if not steam_api_key:
        return False
    
    try:
        url = f"{STEAM_API_BASE}/ISteamUser/GetPlayerSummaries/v2/"
        params = {"key": steam_api_key, "steamids": "76561198123456789"}
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        return True
    except Exception:
        return False


def check_inventory_accessibility(steam_id: str) -> dict:
    """
    Vérifier si l'inventaire Steam est accessible.
    Retourne un dict avec le statut et les détails.
    """
    try:
        url = f"{STEAM_COMMUNITY_BASE}/inventory/{steam_id}/730/2"
        params = {"l": "english", "count": 1}  # count=1 pour test rapide
        
        r = requests.get(url, params=params, timeout=10)
        
        result = {
            "status_code": r.status_code,
            "accessible": False,
            "reason": "",
            "data": None
        }
        
        if r.status_code == 200:
            try:
                data = r.json()
                result["data"] = data
                result["accessible"] = data.get("success", False)
                if not result["accessible"]:
                    result["reason"] = "API returned success=false"
                elif not data.get("assets"):
                    result["reason"] = "No assets in inventory"
                else:
                    result["reason"] = "OK"
            except Exception as e:
                result["reason"] = f"Invalid JSON response: {e}"
        elif r.status_code == 403:
            result["reason"] = "Inventory is private (403 Forbidden)"
        elif r.status_code == 404:
            result["reason"] = "Profile or inventory not found (404)"
        else:
            result["reason"] = f"HTTP {r.status_code}"
            
        return result
        
    except Exception as e:
        return {
            "status_code": None,
            "accessible": False,
            "reason": f"Request failed: {e}",
            "data": None
        }
