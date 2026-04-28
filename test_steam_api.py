#!/usr/bin/env python3
"""
Script de test pour l'API Steam Inventory
Utilise-le pour déboguer les problèmes d'inventaire Steam
"""

import os
import sys
import requests
from steam_integration import get_steam_id_from_vanity, fetch_steam_inventory

def main():
    print("🔧 Test de l'API Steam Inventory")
    print("=" * 50)

    # Charger la clé API
    steam_api_key = os.getenv("STEAM_API_KEY", "")
    if not steam_api_key:
        print("❌ STEAM_API_KEY non trouvée dans les variables d'environnement")
        print("Définis-la avec: export STEAM_API_KEY=ta_clé")
        return

    print("✅ STEAM_API_KEY trouvée")

    # Demander la vanity URL
    vanity_url = input("Entre ta vanity URL Steam (ex: pierreledophin): ").strip()
    if not vanity_url:
        print("❌ Vanity URL requise")
        return

    print(f"🔍 Recherche du SteamID pour: {vanity_url}")

    # Obtenir le SteamID
    steam_id = get_steam_id_from_vanity(vanity_url, steam_api_key)
    if not steam_id:
        print("❌ Impossible de trouver le compte Steam")
        return

    print(f"✅ SteamID trouvé: {steam_id}")

    # Tester l'inventaire
    print("📦 Récupération de l'inventaire CS2...")
    items = fetch_steam_inventory(steam_id)

    if not items:
        print("❌ Aucun item trouvé dans l'inventaire CS2")
        print("\n🔍 Vérifications:")
        print("1. Ton inventaire Steam est-il public?")
        print("2. As-tu des skins CS2?")
        print(f"3. Teste cette URL dans ton navigateur: https://steamcommunity.com/inventory/{steam_id}/730/2")
    else:
        print(f"✅ {len(items)} items trouvés!")
        print("\n📋 Échantillon d'items:")
        for i, item in enumerate(items[:5]):
            print(f"  {i+1}. {item['market_hash_name']} (type: {item['type']})")

if __name__ == "__main__":
    main()
