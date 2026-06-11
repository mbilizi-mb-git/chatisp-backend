#!/usr/bin/env python3
"""
Script de génération de données avancées pour un utilisateur spécifique.
Crée un utilisateur (ou utilise un existant) et génère plusieurs conversations
sur des sujets complexes (extraterrestres, physique quantique, IA, etc.)
avec des échanges réalistes (2-3 messages par conversation).

Usage:
    python scripts/generate_user_data.py --email user@example.com --password MonPass123 --display-name "Nom"
    [--conversations 5] [--url http://localhost:8000]
"""

import argparse
import asyncio
import json
import random
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import httpx
from faker import Faker

# Configuration
DEFAULT_URL = "http://localhost:8000"
DEFAULT_CONVERSATIONS = 10
TIMEOUT = 120.0

fake = Faker()

# Sujets avancés et questions génératrices
TOPICS = [
    "Extraterrestres",
    "Physique quantique",
    "Mystère de l'IA",
    "Internet et réseaux",
    "Voyage dans le temps",
    "Multivers",
    "Conscience artificielle",
    "Théorie des cordes",
    "Exoplanètes habitables",
    "Singularité technologique",
    "Cryptographie quantique",
    "Matière noire",
    "Origine de la vie",
    "Réalité virtuelle",
    "Superintelligence",
]


async def register_or_login(
    client: httpx.AsyncClient, base_url: str, email: str, password: str, display_name: str
) -> Tuple[bool, Optional[str], Optional[str]]:
    """Crée l'utilisateur s'il n'existe pas, ou se connecte. Retourne (success, token, user_id)."""
    # Tentative d'inscription
    try:
        resp = await client.post(
            f"{base_url}/api/v1/auth/register",
            json={"email": email, "password": password, "display_name": display_name},
            timeout=TIMEOUT,
        )
        if resp.status_code == 201:
            data = resp.json()
            token = data.get("access_token")
            headers = {"Authorization": f"Bearer {token}"}
            me_resp = await client.get(f"{base_url}/api/v1/auth/me", headers=headers)
            if me_resp.status_code == 200:
                user_id = me_resp.json().get("id")
                print(f"✅ Utilisateur créé : {email}")
                return True, token, user_id
        elif resp.status_code == 409:
            print(f"ℹ️ Utilisateur {email} existe déjà, tentative de connexion...")
            login_resp = await client.post(
                f"{base_url}/api/v1/auth/login",
                json={"email": email, "password": password},
                timeout=TIMEOUT,
            )
            if login_resp.status_code == 200:
                data = login_resp.json()
                token = data.get("access_token")
                headers = {"Authorization": f"Bearer {token}"}
                me_resp = await client.get(f"{base_url}/api/v1/auth/me", headers=headers)
                if me_resp.status_code == 200:
                    user_id = me_resp.json().get("id")
                    print(f"✅ Connexion réussie pour {email}")
                    return True, token, user_id
            print("❌ Échec de la connexion")
            return False, None, None
        else:
            print(f"❌ Échec inscription/connexion : {resp.status_code} - {resp.text}")
            return False, None, None
    except Exception as e:
        print(f"❌ Erreur réseau : {e}")
        return False, None, None


async def create_conversation(client: httpx.AsyncClient, base_url: str, token: str) -> Optional[str]:
    """Crée une conversation et retourne son ID."""
    headers = {"Authorization": f"Bearer {token}"}
    try:
        resp = await client.post(f"{base_url}/api/v1/conversations", headers=headers, json={}, timeout=TIMEOUT)
        if resp.status_code == 201:
            data = resp.json()
            return data.get("id")
        else:
            print(f"❌ Échec création conversation : {resp.status_code}")
            return None
    except Exception as e:
        print(f"❌ Erreur création conversation : {e}")
        return None


async def send_message_and_get_response(
    client: httpx.AsyncClient, base_url: str, token: str, conv_id: str, user_message: str
) -> bool:
    """Envoie un message à l'IA et reçoit la réponse complète via streaming. Retourne True si succès."""
    headers = {"Authorization": f"Bearer {token}"}
    try:
        async with client.stream(
            "POST",
            f"{base_url}/api/v1/chat/stream",
            headers=headers,
            json={"conversation_id": conv_id, "content": user_message},
            timeout=TIMEOUT,
        ) as response:
            if response.status_code != 200:
                print(f"❌ Erreur HTTP {response.status_code} pour message: {user_message[:50]}")
                return False
            full_response = []
            async for line in response.aiter_lines():
                if line.startswith("data:"):
                    try:
                        data = json.loads(line[5:])
                    except json.JSONDecodeError:
                        continue
                    token_chunk = data.get("token")
                    if token_chunk is not None:
                        full_response.append(token_chunk)
                    elif data.get("done"):
                        break
            if full_response:
                print(f"   → Réponse reçue ({len(''.join(full_response))} caractères)")
                return True
            else:
                print("   ⚠️ Aucune réponse reçue")
                return False
    except Exception as e:
        print(f"❌ Erreur lors de l'envoi : {e}")
        return False


async def generate_conversation(
    client: httpx.AsyncClient,
    base_url: str,
    token: str,
    topic: str,
    messages_count: int = 3,
) -> bool:
    """Crée une conversation sur un sujet donné et envoie quelques messages."""
    conv_id = await create_conversation(client, base_url, token)
    if not conv_id:
        return False

    print(f"\n📚 Conversation sur : {topic} (ID: {conv_id[:8]}...)")

    for i in range(messages_count):
        # Générer une question réaliste
        question = fake.sentence(nb_words=random.randint(8, 20)).rstrip(".") + "?"
        if random.random() > 0.5:
            question = f"En ce qui concerne {topic}, {question.lower()}"
        else:
            question = f"Pourriez-vous m'expliquer {topic} ? {question}"

        print(f"   → Envoi message {i+1}/{messages_count} : {question[:80]}...")
        success = await send_message_and_get_response(client, base_url, token, conv_id, question)
        if not success:
            print(f"   ⚠️ Échec à l'échange {i+1}")
        await asyncio.sleep(0.5)

    return True


async def main():
    parser = argparse.ArgumentParser(description="Génère des conversations avancées pour un utilisateur spécifique")
    parser.add_argument("--email", required=True, help="Email de l'utilisateur")
    parser.add_argument("--password", required=True, help="Mot de passe")
    parser.add_argument("--display-name", required=True, help="Nom affiché")
    parser.add_argument("--conversations", type=int, default=DEFAULT_CONVERSATIONS, help="Nombre de conversations à créer")
    parser.add_argument("--url", default=DEFAULT_URL, help="URL du backend")
    args = parser.parse_args()

    base_url = args.url.rstrip("/")
    print(f"🚀 Génération de données pour {args.email}")
    print(f"URL: {base_url}")
    print(f"Nombre de conversations: {args.conversations}")
    print("-" * 50)

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        success, token, user_id = await register_or_login(
            client, base_url, args.email, args.password, args.display_name
        )
        if not success or not token:
            print("❌ Impossible de continuer sans authentification")
            sys.exit(1)

        print(f"✅ Authentifié (user_id: {user_id})")

        # Générer les sujets (assez pour le nombre demandé)
        topics = random.sample(TOPICS, min(len(TOPICS), args.conversations))
        while len(topics) < args.conversations:
            topics.append(random.choice(TOPICS))

        success_count = 0
        for idx, topic in enumerate(topics[: args.conversations], 1):
            print(f"\n[{idx}/{args.conversations}] Création conversation sur '{topic}'...")
            ok = await generate_conversation(
                client, base_url, token, topic,
                messages_count=random.randint(2, 3)
            )
            if ok:
                success_count += 1
            await asyncio.sleep(1)

    print("\n" + "=" * 50)
    print(f"✅ Terminé. Conversations créées avec succès : {success_count}/{args.conversations}")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())