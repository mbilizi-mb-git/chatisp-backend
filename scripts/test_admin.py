#!/usr/bin/env python3
"""
Script de test complet du panneau d'administration.
Crée un utilisateur normal, le promeut admin, puis teste tous les endpoints admin.
À exécuter après avoir lancé le serveur.

Usage: python scripts/test_admin.py
"""

import asyncio
import json
import sys
from pathlib import Path

import httpx
from sqlalchemy import update

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.database import AsyncSessionLocal
from app.models.user import User

BASE_URL = "http://localhost:8000"
TIMEOUT = 30.0


async def promote_to_admin(email: str) -> bool:
    """Promotion directe en base de données."""
    async with AsyncSessionLocal() as db:
        stmt = update(User).where(User.email == email).values(is_admin=True)
        result = await db.execute(stmt)
        await db.commit()
        return result.rowcount > 0


async def demote_user(email: str) -> bool:
    """Rétrogradation (retrait des droits admin)."""
    async with AsyncSessionLocal() as db:
        stmt = update(User).where(User.email == email).values(is_admin=False)
        result = await db.execute(stmt)
        await db.commit()
        return result.rowcount > 0


async def test_admin_flow():
    """Test complet du panneau admin."""
    print("🚀 Test du panneau d'administration")
    print("=" * 60)

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=TIMEOUT) as client:
        # 1. Inscription d'un nouvel utilisateur
        test_email = f"admin_test_{asyncio.get_event_loop().time()}_{id(object())}@example.com"
        test_password = "Test123456"
        test_name = "Admin Tester"
        print(f"\n📝 Création de l'utilisateur : {test_email}")
        resp = await client.post(
            "/api/v1/auth/register",
            json={"email": test_email, "password": test_password, "display_name": test_name}
        )
        if resp.status_code != 201:
            print(f"❌ Échec inscription : {resp.text}")
            return
        token = resp.json()["access_token"]
        print("✅ Inscription réussie")

        # 2. Promotion admin
        print(f"\n👑 Promotion de {test_email} en administrateur...")
        ok = await promote_to_admin(test_email)
        if not ok:
            print("❌ Échec promotion")
            return
        print("✅ Promotion réussie")

        # 3. Connexion pour obtenir un token admin
        print("\n🔐 Reconnexion avec le compte admin...")
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": test_email, "password": test_password}
        )
        if resp.status_code != 200:
            print(f"❌ Échec connexion : {resp.text}")
            return
        admin_token = resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {admin_token}"}
        print("✅ Connexion réussie")

        # 4. Récupérer l'ID utilisateur via /me
        resp = await client.get("/api/v1/auth/me", headers=headers)
        user_id = resp.json()["id"]

        # 5. Tester les endpoints admin
        print("\n📊 Test des endpoints admin :")

        # Stats
        resp = await client.get("/api/v1/admin/stats", headers=headers)
        if resp.status_code == 200:
            stats = resp.json()
            print(f"  ✅ /admin/stats : total_users={stats['total_users']}, active={stats['active_users_last_24h']}")
        else:
            print(f"  ❌ /admin/stats échoué : {resp.status_code}")

        # Liste utilisateurs
        resp = await client.get("/api/v1/admin/users", headers=headers)
        if resp.status_code == 200:
            users = resp.json()
            print(f"  ✅ /admin/users : {users['total']} utilisateurs")
        else:
            print(f"  ❌ /admin/users échoué : {resp.status_code}")

        # Détail utilisateur
        resp = await client.get(f"/api/v1/admin/users/{user_id}", headers=headers)
        if resp.status_code == 200:
            user_detail = resp.json()
            print(f"  ✅ /admin/users/{{id}} : {user_detail['email']} (admin={user_detail['is_admin']})")
        else:
            print(f"  ❌ /admin/users/{{id}} échoué : {resp.status_code}")

        # Conversations de l'utilisateur (doit être vide)
        resp = await client.get(f"/api/v1/admin/users/{user_id}/conversations", headers=headers)
        if resp.status_code == 200:
            convs = resp.json()
            print(f"  ✅ /admin/users/{{id}}/conversations : {convs['total']} conversation(s)")
        else:
            print(f"  ❌ /admin/users/{{id}}/conversations échoué : {resp.status_code}")

        # Créer une conversation pour tester les exports
        conv_resp = await client.post("/api/v1/conversations", headers=headers, json={})
        conv_id = conv_resp.json()["id"]
        # Envoyer un message pour avoir des données
        async with client.stream(
            "POST", "/api/v1/chat/stream", headers=headers,
            json={"conversation_id": conv_id, "content": "Message de test admin"}
        ) as stream:
            async for _ in stream.aiter_lines():
                pass

        # Récupérer les messages de la conversation (admin)
        resp = await client.get(f"/api/v1/admin/conversations/{conv_id}/messages", headers=headers)
        if resp.status_code == 200:
            msgs = resp.json()
            print(f"  ✅ /admin/conversations/{{id}}/messages : {len(msgs)} messages")
        else:
            print(f"  ❌ /admin/conversations/{{id}}/messages échoué : {resp.status_code}")

        # Export CSV users
        resp = await client.get("/api/v1/admin/export/users", headers=headers)
        if resp.status_code == 200:
            print("  ✅ /admin/export/users : CSV récupéré")
        else:
            print(f"  ❌ /admin/export/users échoué : {resp.status_code}")

        # Export conversations
        resp = await client.get("/api/v1/admin/export/conversations", headers=headers)
        if resp.status_code == 200:
            print("  ✅ /admin/export/conversations : CSV récupéré")
        else:
            print(f"  ❌ /admin/export/conversations échoué : {resp.status_code}")

        # Export messages
        resp = await client.get("/api/v1/admin/export/messages", headers=headers)
        if resp.status_code == 200:
            print("  ✅ /admin/export/messages : CSV récupéré")
        else:
            print(f"  ❌ /admin/export/messages échoué : {resp.status_code}")

        # Réinitialisation du mot de passe (admin)
        new_pass = "NewPass123"
        resp = await client.post(
            f"/api/v1/admin/users/{user_id}/reset-password",
            headers=headers,
            params={"new_password": new_pass}
        )
        if resp.status_code == 200:
            print("  ✅ /admin/users/{id}/reset-password : succès")
            # Tester la reconnexion avec le nouveau mot de passe
            login_resp = await client.post(
                "/api/v1/auth/login",
                json={"email": test_email, "password": new_pass}
            )
            if login_resp.status_code == 200:
                print("      ✅ Reconnexion avec nouveau mot de passe OK")
            else:
                print("      ❌ Reconnexion échouée")
        else:
            print(f"  ❌ /admin/users/{{id}}/reset-password échoué : {resp.status_code}")

        # Test de rétrogradation (retrait des droits admin)
        print("\n🔻 Rétrogradation de l'utilisateur...")
        ok = await demote_user(test_email)
        if ok:
            print("  ✅ Droits admin retirés")
            # Vérifier que l'endpoint admin n'est plus accessible
            resp = await client.get("/api/v1/admin/stats", headers=headers)
            if resp.status_code == 403:
                print("  ✅ Accès admin correctement refusé (403)")
            else:
                print(f"  ❌ Accès admin toujours possible ? (status {resp.status_code})")
        else:
            print("  ❌ Échec rétrogradation")

        # Nettoyage : suppression du compte de test
        print("\n🧹 Suppression du compte de test...")
        resp = await client.delete("/api/v1/auth/account", headers=headers)
        if resp.status_code == 204:
            print("✅ Compte supprimé")
        else:
            print(f"❌ Échec suppression : {resp.status_code}")

    print("\n✨ Test terminé.")


if __name__ == "__main__":
    asyncio.run(test_admin_flow())