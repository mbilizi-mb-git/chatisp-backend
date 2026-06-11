#!/usr/bin/env python3
"""
Script complet de vérification de la santé du backend ChatISP AI.
Teste tous les endpoints critiques et génère un rapport détaillé.

Usage:
    python scripts/health_check.py [--url http://localhost:8000] [--admin-email admin@example.com --admin-password password]
"""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

import httpx
from datetime import datetime

# Couleurs pour le terminal
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
RESET = "\033[0m"

BASE_URL = "http://localhost:8000"
TIMEOUT = 30.0


class HealthCheck:
    def __init__(self, base_url: str, admin_email: str = None, admin_password: str = None):
        self.base_url = base_url
        self.admin_email = admin_email
        self.admin_password = admin_password
        self.results: List[Tuple[str, bool, str]] = []
        self.test_user_email = None
        self.test_user_password = None
        self.test_user_token = None
        self.test_user_id = None
        self.test_conv_id = None

    def log(self, message: str, status: bool = None):
        if status is None:
            print(f"  {message}")
        elif status:
            print(f"{GREEN}✅ {message}{RESET}")
        else:
            print(f"{RED}❌ {message}{RESET}")

    def add_result(self, test_name: str, passed: bool, message: str = ""):
        self.results.append((test_name, passed, message))
        if passed:
            print(f"{GREEN}✅ {test_name}{RESET}")
        else:
            print(f"{RED}❌ {test_name} : {message}{RESET}")

    async def test_health(self, client: httpx.AsyncClient) -> bool:
        """Test /health et /ready"""
        try:
            resp = await client.get("/api/v1/health")
            if resp.status_code != 200:
                self.add_result("Health endpoint", False, f"Status {resp.status_code}")
                return False
            self.add_result("Health endpoint", True)
        except Exception as e:
            self.add_result("Health endpoint", False, str(e))
            return False

        try:
            resp = await client.get("/api/v1/ready")
            if resp.status_code != 200:
                self.add_result("Readiness endpoint", False, f"Status {resp.status_code}")
                return False
            self.add_result("Readiness endpoint", True)
            return True
        except Exception as e:
            self.add_result("Readiness endpoint", False, str(e))
            return False

    async def test_register(self, client: httpx.AsyncClient) -> bool:
        """Test inscription d'un nouvel utilisateur"""
        import random
        self.test_user_email = f"test_{random.randint(10000, 99999)}_{int(time.time())}@example.com"
        self.test_user_password = "Test123456"
        display_name = "Test User"

        try:
            resp = await client.post(
                "/api/v1/auth/register",
                json={"email": self.test_user_email, "password": self.test_user_password, "display_name": display_name}
            )
            if resp.status_code == 201:
                data = resp.json()
                self.test_user_token = data.get("access_token")
                self.add_result("User registration", True)
                return True
            else:
                self.add_result("User registration", False, f"Status {resp.status_code}")
                return False
        except Exception as e:
            self.add_result("User registration", False, str(e))
            return False

    async def test_login(self, client: httpx.AsyncClient) -> bool:
        """Test connexion"""
        try:
            resp = await client.post(
                "/api/v1/auth/login",
                json={"email": self.test_user_email, "password": self.test_user_password}
            )
            if resp.status_code == 200:
                data = resp.json()
                self.test_user_token = data.get("access_token")
                self.add_result("User login", True)
                return True
            else:
                self.add_result("User login", False, f"Status {resp.status_code}")
                return False
        except Exception as e:
            self.add_result("User login", False, str(e))
            return False

    async def test_get_me(self, client: httpx.AsyncClient) -> bool:
        """Test récupération du profil"""
        headers = {"Authorization": f"Bearer {self.test_user_token}"}
        try:
            resp = await client.get("/api/v1/auth/me", headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                self.test_user_id = data.get("id")
                self.add_result("Get current user profile", True)
                return True
            else:
                self.add_result("Get current user profile", False, f"Status {resp.status_code}")
                return False
        except Exception as e:
            self.add_result("Get current user profile", False, str(e))
            return False

    async def test_create_conversation(self, client: httpx.AsyncClient) -> bool:
        """Test création d'une conversation"""
        headers = {"Authorization": f"Bearer {self.test_user_token}"}
        try:
            resp = await client.post("/api/v1/conversations", headers=headers, json={})
            if resp.status_code == 201:
                data = resp.json()
                self.test_conv_id = data.get("id")
                self.add_result("Create conversation", True)
                return True
            else:
                self.add_result("Create conversation", False, f"Status {resp.status_code}")
                return False
        except Exception as e:
            self.add_result("Create conversation", False, str(e))
            return False

    async def test_list_conversations(self, client: httpx.AsyncClient) -> bool:
        """Test liste des conversations"""
        headers = {"Authorization": f"Bearer {self.test_user_token}"}
        try:
            resp = await client.get("/api/v1/conversations", headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                if len(data.get("items", [])) >= 1:
                    self.add_result("List conversations", True)
                    return True
                else:
                    self.add_result("List conversations", False, "No conversations found")
                    return False
            else:
                self.add_result("List conversations", False, f"Status {resp.status_code}")
                return False
        except Exception as e:
            self.add_result("List conversations", False, str(e))
            return False

    async def test_chat_stream(self, client: httpx.AsyncClient) -> bool:
        """Test streaming d'un message"""
        headers = {"Authorization": f"Bearer {self.test_user_token}"}
        message = "Bonjour, dis-moi quelque chose de simple."
        try:
            async with client.stream(
                "POST",
                "/api/v1/chat/stream",
                headers=headers,
                json={"conversation_id": self.test_conv_id, "content": message},
                timeout=TIMEOUT,
            ) as response:
                if response.status_code != 200:
                    self.add_result("Chat stream", False, f"Status {response.status_code}")
                    return False
                received_tokens = False
                async for line in response.aiter_lines():
                    if line.startswith("data:"):
                        data = json.loads(line[5:])
                        if "token" in data:
                            received_tokens = True
                        elif data.get("done"):
                            break
                if received_tokens:
                    self.add_result("Chat stream", True)
                    return True
                else:
                    self.add_result("Chat stream", False, "No tokens received")
                    return False
        except Exception as e:
            self.add_result("Chat stream", False, str(e))
            return False

    async def test_get_messages(self, client: httpx.AsyncClient) -> bool:
        """Test récupération de l'historique des messages"""
        headers = {"Authorization": f"Bearer {self.test_user_token}"}
        try:
            resp = await client.get(f"/api/v1/conversations/{self.test_conv_id}/messages", headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                if len(data.get("items", [])) >= 2:  # user + assistant
                    self.add_result("Get conversation messages", True)
                    return True
                else:
                    self.add_result("Get conversation messages", False, f"Only {len(data.get('items', []))} messages")
                    return False
            else:
                self.add_result("Get conversation messages", False, f"Status {resp.status_code}")
                return False
        except Exception as e:
            self.add_result("Get conversation messages", False, str(e))
            return False

    async def test_regenerate(self, client: httpx.AsyncClient) -> bool:
        """Test régénération de réponse"""
        headers = {"Authorization": f"Bearer {self.test_user_token}"}
        try:
            async with client.stream(
                "POST",
                f"/api/v1/conversations/{self.test_conv_id}/regenerate",
                headers=headers,
                timeout=TIMEOUT,
            ) as response:
                if response.status_code != 200:
                    self.add_result("Regenerate response", False, f"Status {response.status_code}")
                    return False
                received_tokens = False
                async for line in response.aiter_lines():
                    if line.startswith("data:"):
                        data = json.loads(line[5:])
                        if "token" in data:
                            received_tokens = True
                        elif data.get("done"):
                            break
                if received_tokens:
                    self.add_result("Regenerate response", True)
                    return True
                else:
                    self.add_result("Regenerate response", False, "No tokens")
                    return False
        except Exception as e:
            self.add_result("Regenerate response", False, str(e))
            return False

    async def test_delete_conversation(self, client: httpx.AsyncClient) -> bool:
        """Test suppression de conversation"""
        headers = {"Authorization": f"Bearer {self.test_user_token}"}
        try:
            resp = await client.delete(f"/api/v1/conversations/{self.test_conv_id}", headers=headers)
            if resp.status_code == 204:
                self.add_result("Delete conversation", True)
                return True
            else:
                self.add_result("Delete conversation", False, f"Status {resp.status_code}")
                return False
        except Exception as e:
            self.add_result("Delete conversation", False, str(e))
            return False

    async def test_check_email(self, client: httpx.AsyncClient) -> bool:
        """Test validation email en temps réel"""
        try:
            # Email valide et non utilisé
            resp = await client.get(f"/api/v1/auth/check-email?email={self.test_user_email}")
            if resp.status_code != 200:
                self.add_result("Email check endpoint", False, f"Status {resp.status_code}")
                return False
            data = resp.json()
            if data.get("valid") and data.get("exists"):
                self.add_result("Email check endpoint", True)
                return True
            else:
                self.add_result("Email check endpoint", False, "Unexpected response")
                return False
        except Exception as e:
            self.add_result("Email check endpoint", False, str(e))
            return False

    async def test_admin_endpoints(self, client: httpx.AsyncClient) -> bool:
        """Test endpoints admin (si credentials fournis)"""
        if not self.admin_email or not self.admin_password:
            self.log("Skipping admin tests (no admin credentials)", None)
            return True

        # Connexion admin
        try:
            resp = await client.post(
                "/api/v1/auth/login",
                json={"email": self.admin_email, "password": self.admin_password}
            )
            if resp.status_code != 200:
                self.add_result("Admin login", False, "Invalid credentials")
                return False
            admin_token = resp.json()["access_token"]
            admin_headers = {"Authorization": f"Bearer {admin_token}"}
            self.add_result("Admin login", True)
        except Exception as e:
            self.add_result("Admin login", False, str(e))
            return False

        # Tester /admin/stats
        try:
            resp = await client.get("/api/v1/admin/stats", headers=admin_headers)
            if resp.status_code != 200:
                self.add_result("Admin /stats", False, f"Status {resp.status_code}")
                return False
            self.add_result("Admin /stats", True)
        except Exception as e:
            self.add_result("Admin /stats", False, str(e))
            return False

        # Tester /admin/users
        try:
            resp = await client.get("/api/v1/admin/users", headers=admin_headers)
            if resp.status_code != 200:
                self.add_result("Admin /users", False, f"Status {resp.status_code}")
                return False
            self.add_result("Admin /users", True)
        except Exception as e:
            self.add_result("Admin /users", False, str(e))
            return False

        # Tester /admin/users/{user_id} (utiliser l'ID du test user)
        if self.test_user_id:
            try:
                resp = await client.get(f"/api/v1/admin/users/{self.test_user_id}", headers=admin_headers)
                if resp.status_code != 200:
                    self.add_result("Admin /users/{id}", False, f"Status {resp.status_code}")
                    return False
                self.add_result("Admin /users/{id}", True)
            except Exception as e:
                self.add_result("Admin /users/{id}", False, str(e))
                return False

        # Tester export CSV
        try:
            resp = await client.get("/api/v1/admin/export/users", headers=admin_headers)
            if resp.status_code != 200:
                self.add_result("Admin export users", False, f"Status {resp.status_code}")
                return False
            self.add_result("Admin export users", True)
        except Exception as e:
            self.add_result("Admin export users", False, str(e))
            return False

        return True

    async def test_delete_account(self, client: httpx.AsyncClient) -> bool:
        """Test suppression du compte de test"""
        headers = {"Authorization": f"Bearer {self.test_user_token}"}
        try:
            resp = await client.delete("/api/v1/auth/account", headers=headers)
            if resp.status_code == 204:
                self.add_result("Delete user account", True)
                return True
            else:
                self.add_result("Delete user account", False, f"Status {resp.status_code}")
                return False
        except Exception as e:
            self.add_result("Delete user account", False, str(e))
            return False

    async def run(self):
        print(f"\n{BLUE}🔍 CHATISP AI - HEALTH CHECK{RESET}")
        print(f"Target: {self.base_url}\n")

        async with httpx.AsyncClient(base_url=self.base_url, timeout=TIMEOUT) as client:
            # Étape 1 : Santé de base
            if not await self.test_health(client):
                print(f"\n{RED}❌ Backend inaccessible. Arrêt.{RESET}")
                sys.exit(1)

            # Étape 2 : Inscription
            if not await self.test_register(client):
                print(f"\n{RED}❌ Échec d'inscription. Arrêt.{RESET}")
                sys.exit(1)

            # Étape 3 : Connexion
            if not await self.test_login(client):
                print(f"\n{RED}❌ Échec de connexion. Arrêt.{RESET}")
                sys.exit(1)

            # Étape 4 : Profil
            if not await self.test_get_me(client):
                print(f"\n{RED}❌ Échec récupération profil. Arrêt.{RESET}")
                sys.exit(1)

            # Étape 5 : Création conversation
            if not await self.test_create_conversation(client):
                print(f"\n{RED}❌ Échec création conversation. Arrêt.{RESET}")
                sys.exit(1)

            # Étape 6 : Liste conversations
            await self.test_list_conversations(client)

            # Étape 7 : Chat stream
            if not await self.test_chat_stream(client):
                print(f"\n{RED}❌ Échec streaming. Arrêt.{RESET}")
                sys.exit(1)

            # Étape 8 : Historique messages
            await self.test_get_messages(client)

            # Étape 9 : Régénération
            await self.test_regenerate(client)

            # Étape 10 : Suppression conversation
            await self.test_delete_conversation(client)

            # Étape 11 : Validation email
            await self.test_check_email(client)

            # Étape 12 : Admin (si configuré)
            await self.test_admin_endpoints(client)

            # Étape 13 : Suppression compte (nettoyage)
            await self.test_delete_account(client)

        # Résumé final
        print(f"\n{BLUE}{'='*50}{RESET}")
        print(f"{BLUE}📊 RÉSUMÉ DES TESTS{RESET}")
        passed = sum(1 for _, p, _ in self.results if p)
        total = len(self.results)
        print(f"Tests réussis : {GREEN}{passed}{RESET} / {total}")
        if passed == total:
            print(f"{GREEN}✨ TOUS LES TESTS ONT RÉUSSI ✨{RESET}")
        else:
            print(f"{RED}⚠️ {total - passed} test(s) échoué(s){RESET}")
            for name, ok, msg in self.results:
                if not ok:
                    print(f"  - {name}: {msg}")

        return passed == total


async def main():
    parser = argparse.ArgumentParser(description="Health check for ChatISP AI backend")
    parser.add_argument("--url", default="http://localhost:8000", help="Backend URL")
    parser.add_argument("--admin-email", help="Admin email for testing admin endpoints")
    parser.add_argument("--admin-password", help="Admin password")
    args = parser.parse_args()

    checker = HealthCheck(args.url.rstrip("/"), args.admin_email, args.admin_password)
    success = await checker.run()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())