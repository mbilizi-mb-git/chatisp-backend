#!/usr/bin/env python3
"""
Script de test de charge et de génération de données pour ChatISP AI backend.
Crée 10 utilisateurs aléatoires, chacun avec des conversations et messages,
et exporte un rapport CSV détaillé.

Usage: python scripts/load_test.py [--url http://localhost:8000] [--users 10]
"""

import argparse
import asyncio
import csv
import json
import random
import string
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

import httpx
from faker import Faker
from tqdm import tqdm

# Ajout du répertoire parent pour importer les modules (optionnel)
sys.path.insert(0, str(Path(__file__).parent.parent))

# Configuration par défaut
DEFAULT_URL = "http://localhost:8000"
DEFAULT_USER_COUNT = 10
DEFAULT_CONVERSATIONS_PER_USER = 2
DEFAULT_MESSAGES_PER_CONVERSATION = 3

fake = Faker()


class LoadTestResult:
    """Stocke les résultats du test pour un utilisateur."""
    def __init__(self, email: str):
        self.email = email
        self.password: str = ""
        self.user_id: str = ""
        self.created: bool = False
        self.login_success: bool = False
        self.conversations: List[Dict] = []
        self.messages_sent: int = 0
        self.messages_received: int = 0
        self.errors: List[str] = []
        self.start_time: float = 0.0
        self.end_time: float = 0.0

    def duration(self) -> float:
        return self.end_time - self.start_time if self.end_time else 0.0


async def register_user(client: httpx.AsyncClient, base_url: str) -> Tuple[bool, Optional[str], Optional[str], Optional[str]]:
    """Inscrit un utilisateur aléatoire. Retourne (success, email, password, user_id)."""
    email = fake.email()
    password = ''.join(random.choices(string.ascii_letters + string.digits, k=12))
    display_name = fake.name()
    try:
        resp = await client.post(
            f"{base_url}/api/v1/auth/register",
            json={"email": email, "password": password, "display_name": display_name},
            timeout=60.0
        )
        if resp.status_code == 201:
            data = resp.json()
            # Récupérer l'ID utilisateur via /me
            token = data.get("access_token")
            headers = {"Authorization": f"Bearer {token}"}
            me_resp = await client.get(f"{base_url}/api/v1/auth/me", headers=headers)
            if me_resp.status_code == 200:
                user_id = me_resp.json().get("id")
                return True, email, password, user_id
            else:
                return True, email, password, None
        else:
            return False, None, None, None
    except Exception as e:
        print(f"Erreur inscription: {e}")
        return False, None, None, None


async def login_user(client: httpx.AsyncClient, base_url: str, email: str, password: str) -> Optional[str]:
    """Connecte un utilisateur et retourne le token."""
    try:
        resp = await client.post(
            f"{base_url}/api/v1/auth/login",
            json={"email": email, "password": password},
            timeout=60.0
        )
        if resp.status_code == 200:
            data = resp.json()
            return data.get("access_token")
        return None
    except Exception:
        return None


async def create_conversation(client: httpx.AsyncClient, base_url: str, token: str) -> Optional[str]:
    """Crée une conversation et retourne son ID."""
    headers = {"Authorization": f"Bearer {token}"}
    try:
        resp = await client.post(f"{base_url}/api/v1/conversations", headers=headers, json={}, timeout=60.0)
        if resp.status_code == 201:
            data = resp.json()
            return data.get("id")
        return None
    except Exception:
        return None


async def send_message(client: httpx.AsyncClient, base_url: str, token: str, conv_id: str, content: str) -> bool:
    """Envoie un message avec streaming et attend la réponse complète."""
    headers = {"Authorization": f"Bearer {token}"}
    try:
        async with client.stream(
            "POST",
            f"{base_url}/api/v1/chat/stream",
            headers=headers,
            json={"conversation_id": conv_id, "content": content},
            timeout=60.0
        ) as response:
            if response.status_code != 200:
                return False
            received_tokens = False
            async for line in response.aiter_lines():
                if line.startswith("data:"):
                    try:
                        data = json.loads(line[5:])
                    except json.JSONDecodeError:
                        continue
                    if "token" in data:
                        received_tokens = True
                    elif data.get("done"):
                        return received_tokens
            return False
    except Exception:
        return False


async def test_user(client: httpx.AsyncClient, base_url: str, user_index: int, conversations_per_user: int, messages_per_conversation: int, pbar: tqdm) -> LoadTestResult:
    """Test complet pour un utilisateur."""
    result = LoadTestResult(f"user{user_index}@test.local")
    result.start_time = time.time()
    # Inscription
    success, email, password, user_id = await register_user(client, base_url)
    if not success:
        result.errors.append("Inscription échouée")
        result.end_time = time.time()
        pbar.update(1)
        return result
    result.email = email
    result.password = password
    result.user_id = user_id or ""
    result.created = True

    # Connexion
    token = await login_user(client, base_url, email, password)
    if not token:
        result.errors.append("Connexion échouée")
        result.end_time = time.time()
        pbar.update(1)
        return result
    result.login_success = True

    # Création des conversations
    for conv_i in range(conversations_per_user):
        conv_id = await create_conversation(client, base_url, token)
        if not conv_id:
            result.errors.append(f"Échec création conversation {conv_i}")
            continue
        conv_data = {"id": conv_id, "messages": []}
        # Envoyer des messages
        for msg_i in range(messages_per_conversation):
            user_msg = fake.sentence()
            success = await send_message(client, base_url, token, conv_id, user_msg)
            if success:
                result.messages_sent += 1
                result.messages_received += 1  # une réponse par message
                conv_data["messages"].append({"user": user_msg, "assistant": "received"})
            else:
                result.errors.append(f"Échec message {msg_i} conv {conv_i}")
        result.conversations.append(conv_data)

    result.end_time = time.time()
    pbar.update(1)
    return result


async def run_load_test(base_url: str, user_count: int, conversations_per_user: int, messages_per_conversation: int) -> List[LoadTestResult]:
    """Exécute le test de charge sur plusieurs utilisateurs."""
    print(f"🚀 Démarrage du test de charge sur {user_count} utilisateurs")
    print(f"URL: {base_url}")
    print(f"Conversations par utilisateur: {conversations_per_user}")
    print(f"Messages par conversation: {messages_per_conversation}")
    print("-" * 50)

    async with httpx.AsyncClient(timeout=60.0) as client:
        # Vérifier que le backend est accessible
        try:
            resp = await client.get(f"{base_url}/api/v1/health")
            if resp.status_code != 200:
                print("❌ Backend inaccessible")
                sys.exit(1)
            print("✅ Backend joignable")
        except Exception as e:
            print(f"❌ Erreur connexion: {e}")
            sys.exit(1)

        results = []
        with tqdm(total=user_count, desc="Création utilisateurs", unit="user") as pbar:
            tasks = [test_user(client, base_url, i, conversations_per_user, messages_per_conversation, pbar) for i in range(user_count)]
            results = await asyncio.gather(*tasks)

    return results


def export_to_csv(results: List[LoadTestResult], filename: str = "load_test_results.csv"):
    """Exporte les résultats dans un fichier CSV."""
    if not results:
        print("Aucun résultat à exporter")
        return
    rows = []
    for r in results:
        rows.append({
            "email": r.email,
            "password": r.password,
            "user_id": r.user_id,
            "created": r.created,
            "login_success": r.login_success,
            "conversations_count": len(r.conversations),
            "messages_sent": r.messages_sent,
            "messages_received": r.messages_received,
            "errors": "|".join(r.errors) if r.errors else "",
            "duration_seconds": round(r.duration(), 2),
        })
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(f"📊 Résultats exportés vers {filename}")


def print_summary(results: List[LoadTestResult]):
    """Affiche un résumé dans la console."""
    if not results:
        return
    total_users = len(results)
    success_reg = sum(1 for r in results if r.created)
    success_login = sum(1 for r in results if r.login_success)
    total_conv = sum(len(r.conversations) for r in results)
    total_msg_sent = sum(r.messages_sent for r in results)
    total_msg_recv = sum(r.messages_received for r in results)
    total_errors = sum(len(r.errors) for r in results)

    print("\n" + "=" * 50)
    print("📈 RÉSUMÉ DU TEST DE CHARGE")
    print("=" * 50)
    print(f"Utilisateurs tentés        : {total_users}")
    print(f"Inscriptions réussies      : {success_reg}/{total_users}")
    print(f"Connexions réussies        : {success_login}/{total_users}")
    print(f"Conversations créées       : {total_conv}")
    print(f"Messages envoyés           : {total_msg_sent}")
    print(f"Messages reçus (réponses)  : {total_msg_recv}")
    print(f"Erreurs totales            : {total_errors}")
    avg_duration = sum(r.duration() for r in results) / total_users if total_users else 0
    print(f"Durée moyenne par utilisateur: {avg_duration:.2f}s")
    print("=" * 50)


async def main():
    parser = argparse.ArgumentParser(description="Test de charge pour ChatISP AI")
    parser.add_argument("--url", default=DEFAULT_URL, help="URL du backend")
    parser.add_argument("--users", type=int, default=DEFAULT_USER_COUNT, help="Nombre d'utilisateurs à créer")
    parser.add_argument("--conversations", type=int, default=DEFAULT_CONVERSATIONS_PER_USER, help="Conversations par utilisateur")
    parser.add_argument("--messages", type=int, default=DEFAULT_MESSAGES_PER_CONVERSATION, help="Messages par conversation")
    parser.add_argument("--output", default="load_test_results.csv", help="Fichier CSV de sortie")
    args = parser.parse_args()

    base_url = args.url.rstrip("/")
    results = await run_load_test(
        base_url,
        args.users,
        args.conversations,
        args.messages
    )
    export_to_csv(results, args.output)
    print_summary(results)

    # Afficher les détails des erreurs si présentes
    if any(r.errors for r in results):
        print("\n⚠️ Détails des erreurs:")
        for r in results:
            if r.errors:
                print(f"  {r.email}: {', '.join(r.errors)}")


if __name__ == "__main__":
    asyncio.run(main())