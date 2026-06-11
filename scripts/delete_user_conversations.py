#!/usr/bin/env python3
"""
Script pour supprimer toutes les conversations d'un utilisateur spécifique.

Utilise l'API admin (requiert les droits administrateur) ou le token de l'utilisateur lui-même.

Usage:
    python scripts/delete_user_conversations.py --email user@example.com --admin-email admin@example.com --admin-password pass
    OU
    python scripts/delete_user_conversations.py --user-id uuid --admin-email admin@example.com --admin-password pass
    OU (si l'utilisateur est le même que l'admin)
    python scripts/delete_user_conversations.py --email user@example.com --use-user-token (avec --user-password)
"""

import argparse
import asyncio
import json
import sys
from typing import Optional, List, Dict

import httpx

DEFAULT_URL = "http://localhost:8000"
TIMEOUT = 60.0


async def login(client: httpx.AsyncClient, base_url: str, email: str, password: str) -> Optional[str]:
    """Connecte un utilisateur et retourne son token."""
    try:
        resp = await client.post(
            f"{base_url}/api/v1/auth/login",
            json={"email": email, "password": password},
            timeout=TIMEOUT,
        )
        if resp.status_code == 200:
            data = resp.json()
            return data.get("access_token")
        else:
            print(f"❌ Échec connexion pour {email}: {resp.status_code} - {resp.text}")
            return None
    except Exception as e:
        print(f"❌ Erreur réseau : {e}")
        return None


async def get_user_conversations(
    client: httpx.AsyncClient, base_url: str, token: str, user_id: str
) -> List[Dict]:
    """Récupère toutes les conversations d'un utilisateur (via endpoint admin)."""
    headers = {"Authorization": f"Bearer {token}"}
    conversations = []
    cursor = None
    limit = 50
    while True:
        params = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        try:
            resp = await client.get(
                f"{base_url}/api/v1/admin/users/{user_id}/conversations",
                headers=headers,
                params=params,
                timeout=TIMEOUT,
            )
            if resp.status_code != 200:
                print(f"❌ Échec récupération conversations: {resp.status_code} - {resp.text}")
                break
            data = resp.json()
            items = data.get("items", [])
            conversations.extend(items)
            cursor = data.get("next_cursor")
            if not cursor or not items:
                break
        except Exception as e:
            print(f"❌ Erreur lors de la récupération : {e}")
            break
    return conversations


async def delete_conversation(client: httpx.AsyncClient, base_url: str, token: str, conv_id: str) -> bool:
    """Supprime une conversation via l'API admin (ou utilisateur)."""
    headers = {"Authorization": f"Bearer {token}"}
    try:
        resp = await client.delete(
            f"{base_url}/api/v1/conversations/{conv_id}",
            headers=headers,
            timeout=TIMEOUT,
        )
        return resp.status_code == 204
    except Exception as e:
        print(f"❌ Erreur suppression {conv_id}: {e}")
        return False


async def get_user_id_by_email(client: httpx.AsyncClient, base_url: str, admin_token: str, email: str) -> Optional[str]:
    """Récupère l'ID d'un utilisateur via son email (endpoint admin)."""
    headers = {"Authorization": f"Bearer {admin_token}"}
    try:
        # Rechercher l'utilisateur par email
        resp = await client.get(
            f"{base_url}/api/v1/admin/users?search={email}",
            headers=headers,
            timeout=TIMEOUT,
        )
        if resp.status_code != 200:
            print(f"❌ Échec recherche utilisateur: {resp.status_code}")
            return None
        data = resp.json()
        users = data.get("items", [])
        for u in users:
            if u.get("email") == email:
                return u.get("id")
        print(f"❌ Utilisateur avec email {email} non trouvé")
        return None
    except Exception as e:
        print(f"❌ Erreur recherche : {e}")
        return None


async def delete_user_conversations_admin(
    base_url: str, admin_email: str, admin_password: str, target_email: str = None, target_user_id: str = None
) -> None:
    """Supprime toutes les conversations d'un utilisateur en utilisant un compte admin."""
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        # 1. Connexion admin
        admin_token = await login(client, base_url, admin_email, admin_password)
        if not admin_token:
            print("❌ Impossible de se connecter avec le compte admin")
            sys.exit(1)

        # 2. Récupérer l'ID de l'utilisateur cible
        if target_user_id:
            user_id = target_user_id
        elif target_email:
            user_id = await get_user_id_by_email(client, base_url, admin_token, target_email)
            if not user_id:
                sys.exit(1)
        else:
            print("❌ Spécifiez --email ou --user-id")
            sys.exit(1)

        print(f"🎯 Utilisateur cible : {user_id}")

        # 3. Récupérer toutes les conversations
        conversations = await get_user_conversations(client, base_url, admin_token, user_id)
        print(f"📋 Nombre de conversations trouvées : {len(conversations)}")

        if not conversations:
            print("✅ Aucune conversation à supprimer")
            return

        # 4. Supprimer chaque conversation
        success_count = 0
        for conv in conversations:
            conv_id = conv.get("id")
            if not conv_id:
                continue
            ok = await delete_conversation(client, base_url, admin_token, conv_id)
            if ok:
                success_count += 1
                print(f"   ✅ Supprimée : {conv_id[:8]}...")
            else:
                print(f"   ❌ Échec suppression : {conv_id[:8]}...")

        print(f"\n✅ Suppression terminée : {success_count}/{len(conversations)} conversations supprimées.")


async def delete_user_conversations_self(
    base_url: str, user_email: str, user_password: str
) -> None:
    """Supprime toutes les conversations de l'utilisateur lui-même (en utilisant son propre token)."""
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        # 1. Connexion utilisateur
        user_token = await login(client, base_url, user_email, user_password)
        if not user_token:
            print("❌ Impossible de se connecter avec les identifiants utilisateur")
            sys.exit(1)

        # 2. Récupérer ses propres conversations (endpoint utilisateur standard)
        headers = {"Authorization": f"Bearer {user_token}"}
        conversations = []
        cursor = None
        limit = 50
        while True:
            params = {"limit": limit}
            if cursor:
                params["cursor"] = cursor
            resp = await client.get(
                f"{base_url}/api/v1/conversations",
                headers=headers,
                params=params,
                timeout=TIMEOUT,
            )
            if resp.status_code != 200:
                print(f"❌ Échec récupération conversations: {resp.status_code}")
                break
            data = resp.json()
            items = data.get("items", [])
            conversations.extend(items)
            cursor = data.get("next_cursor")
            if not cursor or not items:
                break

        print(f"📋 Nombre de conversations trouvées : {len(conversations)}")

        if not conversations:
            print("✅ Aucune conversation à supprimer")
            return

        # 3. Supprimer chaque conversation
        success_count = 0
        for conv in conversations:
            conv_id = conv.get("id")
            if not conv_id:
                continue
            ok = await delete_conversation(client, base_url, user_token, conv_id)
            if ok:
                success_count += 1
                print(f"   ✅ Supprimée : {conv_id[:8]}...")
            else:
                print(f"   ❌ Échec suppression : {conv_id[:8]}...")

        print(f"\n✅ Suppression terminée : {success_count}/{len(conversations)} conversations supprimées.")


async def main():
    parser = argparse.ArgumentParser(description="Supprimer toutes les conversations d'un utilisateur")
    parser.add_argument("--email", help="Email de l'utilisateur cible")
    parser.add_argument("--user-id", help="ID de l'utilisateur cible")
    parser.add_argument("--admin-email", help="Email du compte admin (requis pour supprimer les conversations d'un autre utilisateur)")
    parser.add_argument("--admin-password", help="Mot de passe du compte admin")
    parser.add_argument("--use-user-token", action="store_true", help="Utiliser les identifiants de l'utilisateur cible pour supprimer ses propres conversations (pas besoin d'admin)")
    parser.add_argument("--user-password", help="Mot de passe de l'utilisateur cible (si --use-user-token)")
    parser.add_argument("--url", default=DEFAULT_URL, help="URL du backend")
    args = parser.parse_args()

    base_url = args.url.rstrip("/")

    if args.use_user_token:
        if not args.email or not args.user_password:
            print("❌ Avec --use-user-token, vous devez fournir --email et --user-password")
            sys.exit(1)
        await delete_user_conversations_self(base_url, args.email, args.user_password)
    else:
        if not args.admin_email or not args.admin_password:
            print("❌ Mode admin : fournissez --admin-email et --admin-password")
            sys.exit(1)
        if not args.email and not args.user_id:
            print("❌ Spécifiez --email ou --user-id de l'utilisateur cible")
            sys.exit(1)
        await delete_user_conversations_admin(
            base_url,
            args.admin_email,
            args.admin_password,
            target_email=args.email,
            target_user_id=args.user_id,
        )


if __name__ == "__main__":
    asyncio.run(main())