#!/usr/bin/env python3
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx

async def reset_password(admin_email, admin_password, target_email, new_password):
    async with httpx.AsyncClient() as client:
        # Login admin
        resp = await client.post("http://localhost:8000/api/v1/auth/login", json={
            "email": admin_email, "password": admin_password
        })
        if resp.status_code != 200:
            print("❌ Échec connexion admin")
            return
        token = resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        
        # Récupérer l'ID de l'utilisateur cible
        resp = await client.get(f"http://localhost:8000/api/v1/admin/users?search={target_email}", headers=headers)
        if resp.status_code != 200:
            print("❌ Échec recherche utilisateur")
            return
        items = resp.json().get("items", [])
        if not items:
            print(f"❌ Utilisateur {target_email} non trouvé")
            return
        user_id = items[0]["id"]
        
        # Réinitialiser le mot de passe
        resp = await client.post(
            f"http://localhost:8000/api/v1/admin/users/{user_id}/reset-password",
            headers=headers,
            params={"new_password": new_password}
        )
        if resp.status_code == 200:
            print(f"✅ Mot de passe de {target_email} réinitialisé avec succès")
        else:
            print(f"❌ Échec : {resp.status_code} - {resp.text}")

if __name__ == "__main__":
    if len(sys.argv) != 5:
        print("Usage: python reset_password.py <admin_email> <admin_password> <target_email> <new_password>")
        sys.exit(1)
    asyncio.run(reset_password(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]))