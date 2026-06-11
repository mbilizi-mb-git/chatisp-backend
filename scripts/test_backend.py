#!/usr/bin/env python3
"""
Script interactif de test complet du backend ChatISP AI.
Authentification JWT, gestion des conversations (CRUD), chat en streaming.
Avec rendu Markdown via Rich (affichage formaté après streaming).
Ajout de la gestion d'épinglage (/pin) et améliorations professionnelles.
Version premium : export, recherche, statistiques, reconnexion auto.
"""

import argparse
import asyncio
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

import httpx
from dotenv import load_dotenv
from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

# Ajout du parent pour importer les settings
sys.path.insert(0, str(Path(__file__).parent.parent))
from app.core.config import get_settings

load_dotenv()
settings = get_settings()

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

BASE_URL = "http://localhost:8000"
TIMEOUT = 30.0

console = Console()


# ----------------------------------------------------------------------
# Exceptions personnalisées
# ----------------------------------------------------------------------
class APIError(Exception):
    """Erreur générique de l'API."""
    pass


class AuthenticationError(APIError):
    """Erreur d'authentification."""
    pass


class NetworkError(APIError):
    """Erreur réseau ou timeout."""
    pass


# ----------------------------------------------------------------------
# Modèles de données
# ----------------------------------------------------------------------
@dataclass
class UserProfile:
    """Profil utilisateur."""
    id: str
    email: str
    display_name: str
    created_at: str


@dataclass
class Conversation:
    """Conversation."""
    id: str
    title: str
    is_pinned: bool
    updated_at: str
    preview: Optional[str] = None


@dataclass
class Message:
    """Message."""
    id: str
    conversation_id: str
    role: str
    content: str
    created_at: str


@dataclass
class Stats:
    """Statistiques de session."""
    messages_sent: int = 0
    messages_received: int = 0
    total_response_time: float = 0.0
    start_time: float = field(default_factory=time.time)

    @property
    def avg_response_time(self) -> float:
        if self.messages_received == 0:
            return 0.0
        return self.total_response_time / self.messages_received

    @property
    def session_duration(self) -> float:
        return time.time() - self.start_time


# ----------------------------------------------------------------------
# Client API asynchrone
# ----------------------------------------------------------------------
class ChatISPClient:
    """Client HTTP pour interagir avec le backend ChatISP AI."""

    def __init__(self, base_url: str = BASE_URL, timeout: float = TIMEOUT):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None
        self._token: Optional[str] = None
        self._email: Optional[str] = None
        self._password: Optional[str] = None  # Pour reconnexion auto

    async def __aenter__(self):
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._client:
            await self._client.aclose()

    def set_token(self, token: str, email: str = None, password: str = None):
        self._token = token
        if email:
            self._email = email
        if password:
            self._password = password

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    async def _request(self, method: str, path: str, retry_auth: bool = True, **kwargs) -> Dict[str, Any]:
        """Effectue une requête HTTP et gère les erreurs, avec reconnexion auto si token expiré."""
        if not self._client:
            raise RuntimeError("Client non initialisé. Utilisez le contexte 'async with'.")
        try:
            resp = await self._client.request(
                method,
                path,
                headers=self._headers(),
                **kwargs
            )
            # Si token expiré et qu'on a des identifiants, on tente une reconnexion
            if resp.status_code == 401 and retry_auth and self._email and self._password:
                logger.info("Token expiré, tentative de reconnexion...")
                new_token = await self.login(self._email, self._password)
                self.set_token(new_token, self._email, self._password)
                # Réessayer la requête originale
                return await self._request(method, path, retry_auth=False, **kwargs)
            if resp.status_code >= 400:
                detail = None
                try:
                    error_data = resp.json()
                    detail = error_data.get("detail")
                except Exception:
                    pass
                if isinstance(detail, str):
                    raise APIError(f"Erreur {resp.status_code}: {detail}")
                elif isinstance(detail, list):
                    first = detail[0] if detail else {}
                    msg = first.get("msg", "Erreur de validation")
                    raise APIError(f"Erreur {resp.status_code}: {msg}")
                else:
                    raise APIError(f"Erreur HTTP {resp.status_code}")
            return resp.json() if resp.status_code != 204 else {}
        except httpx.TimeoutException as e:
            raise NetworkError(f"Timeout après {self.timeout}s") from e
        except httpx.ConnectError as e:
            raise NetworkError(f"Impossible de se connecter à {self.base_url}") from e
        except Exception as e:
            raise APIError(str(e)) from e

    # ------------------------------------------------------------------
    # Endpoints d'authentification
    # ------------------------------------------------------------------
    async def register(self, email: str, password: str, display_name: str) -> str:
        """Inscription. Retourne le token JWT."""
        data = await self._request(
            "POST",
            "/api/v1/auth/register",
            json={"email": email, "password": password, "display_name": display_name},
            retry_auth=False
        )
        token = data.get("access_token")
        if not token:
            raise APIError("Token manquant dans la réponse")
        return token

    async def login(self, email: str, password: str) -> str:
        """Connexion. Retourne le token JWT."""
        data = await self._request(
            "POST",
            "/api/v1/auth/login",
            json={"email": email, "password": password},
            retry_auth=False
        )
        token = data.get("access_token")
        if not token:
            raise APIError("Token manquant dans la réponse")
        return token

    async def get_me(self) -> UserProfile:
        """Récupère le profil utilisateur."""
        data = await self._request("GET", "/api/v1/auth/me")
        return UserProfile(
            id=data["id"],
            email=data["email"],
            display_name=data["display_name"],
            created_at=data["created_at"]
        )

    # ------------------------------------------------------------------
    # Conversations
    # ------------------------------------------------------------------
    async def list_conversations(self, limit: int = 20, cursor: Optional[str] = None) -> List[Conversation]:
        """Liste les conversations."""
        params = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        data = await self._request("GET", "/api/v1/conversations", params=params)
        items = data.get("items", [])
        return [
            Conversation(
                id=item["id"],
                title=item.get("title", ""),
                is_pinned=item.get("is_pinned", False),
                updated_at=item.get("updated_at", ""),
                preview=item.get("preview")
            )
            for item in items
        ]

    async def create_conversation(self) -> str:
        """Crée une nouvelle conversation. Retourne l'ID."""
        data = await self._request("POST", "/api/v1/conversations", json={})
        return data["id"]

    async def rename_conversation(self, conv_id: str, title: str) -> bool:
        """Renomme une conversation."""
        await self._request("PUT", f"/api/v1/conversations/{conv_id}/rename", json={"title": title})
        return True

    async def delete_conversation(self, conv_id: str) -> bool:
        """Supprime une conversation."""
        await self._request("DELETE", f"/api/v1/conversations/{conv_id}")
        return True

    async def pin_conversation(self, conv_id: str, is_pinned: bool) -> bool:
        """Épingle ou désépingle une conversation."""
        await self._request("PATCH", f"/api/v1/conversations/{conv_id}/pin", json={"is_pinned": is_pinned})
        return True

    async def get_conversation_messages(self, conv_id: str, limit: int = 50) -> List[Message]:
        """Récupère les messages d'une conversation."""
        data = await self._request("GET", f"/api/v1/conversations/{conv_id}/messages", params={"limit": limit})
        items = data.get("items", [])
        return [
            Message(
                id=item["id"],
                conversation_id=item["conversation_id"],
                role=item["role"],
                content=item["content"],
                created_at=item["created_at"]
            )
            for item in items
        ]

    async def send_message_stream(self, conv_id: str, content: str) -> str:
        """
        Envoie un message et reçoit la réponse en streaming.
        Retourne la réponse complète (pour affichage Markdown final).
        """
        if not self._client:
            raise RuntimeError("Client non initialisé")
        headers = self._headers()
        full_response = ""
        try:
            async with self._client.stream(
                "POST",
                "/api/v1/chat/stream",
                headers=headers,
                json={"conversation_id": conv_id, "content": content},
                timeout=self.timeout,
            ) as response:
                if response.status_code != 200:
                    raise APIError(f"Erreur HTTP {response.status_code}")
                console.print("\n🤖 Réponse (streaming) : ", end="", style="bold green")
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    try:
                        data = json.loads(line[5:])
                    except json.JSONDecodeError:
                        continue
                    if "token" in data and data["token"] is not None:
                        token_text = data["token"]
                        full_response += token_text
                        console.print(token_text, end="", style="white")
                    elif data.get("done"):
                        break
                console.print()
                if not full_response:
                    raise APIError("Aucune réponse reçue")
        except httpx.TimeoutException as e:
            raise NetworkError("Timeout lors du streaming") from e
        except Exception as e:
            raise APIError(str(e)) from e
        return full_response


# ----------------------------------------------------------------------
# Interface interactive en ligne de commande
# ----------------------------------------------------------------------
class InteractiveChat:
    """Interface utilisateur en ligne de commande."""

    def __init__(self, client: ChatISPClient):
        self.client = client
        self.current_conv_id: Optional[str] = None
        self.user: Optional[UserProfile] = None
        self.stats = Stats()
        self.search_results: List[Message] = []

    def _print_help(self):
        console.print("\n[bold cyan]=" * 60 + "[/]")
        console.print("[bold]💬 MODE CHAT - Commandes disponibles :[/]")
        console.print("  /new      - Créer une nouvelle conversation")
        console.print("  /list     - Lister toutes vos conversations")
        console.print("  /switch   - Changer de conversation")
        console.print("  /history  - Afficher l'historique de la conversation actuelle")
        console.print("  /rename   - Renommer la conversation actuelle")
        console.print("  /pin      - Épingler/désépingler la conversation active (toggle)")
        console.print("  /del      - Supprimer la conversation actuelle (et en créer une nouvelle)")
        console.print("  /search <mot> - Rechercher dans l'historique de la conversation active")
        console.print("  /export [json|md|txt] - Exporter la conversation active")
        console.print("  /stats    - Afficher les statistiques de session")
        console.print("  /exit     - Quitter")
        console.print("[bold cyan]=" * 60 + "[/]")

    async def _show_history(self):
        if not self.current_conv_id:
            console.print("[red]❌ Aucune conversation active.[/]")
            return
        messages = await self.client.get_conversation_messages(self.current_conv_id, limit=100)
        if not messages:
            console.print("[yellow]📭 Aucun message dans cette conversation.[/]")
            return
        console.print(f"\n[bold]📜 Historique de la conversation (id: {self.current_conv_id[:8]}...) :[/]")
        for msg in messages:
            role = "🧑‍💻 Utilisateur" if msg.role == "user" else "🤖 Assistant"
            if msg.role == "assistant":
                console.print(f"[bold]{role}:[/]")
                console.print(Markdown(msg.content))
            else:
                content = msg.content.replace("\n", " ")
                console.print(f"[bold]{role}:[/] {content[:200]}{'…' if len(content) > 200 else ''}")
        console.print()

    async def _list_conversations(self):
        convs = await self.client.list_conversations()
        if not convs:
            console.print("[yellow]📭 Aucune conversation trouvée.[/]")
            return
        table = Table(title="Vos conversations", style="cyan")
        table.add_column("#", style="dim")
        table.add_column("📌", style="bold yellow")
        table.add_column("Titre", style="bold")
        table.add_column("ID", style="dim")
        table.add_column("Dernière activité", style="dim")
        for i, c in enumerate(convs, 1):
            pinned = "📌" if c.is_pinned else " "
            table.add_row(str(i), pinned, c.title or "(sans titre)", c.id[:8], c.updated_at[:19])
        console.print(table)

    async def _switch_conversation(self):
        convs = await self.client.list_conversations()
        if not convs:
            console.print("[yellow]📭 Aucune conversation. Créez-en une avec /new.[/]")
            return
        console.print("\n[bold]Choisissez une conversation :[/]")
        for i, c in enumerate(convs, 1):
            pinned = "📌 " if c.is_pinned else "   "
            console.print(f"  {i}. {pinned}{c.title or '(sans titre)'} (id: {c.id[:8]}...)")
        try:
            choice = int(console.input("[bold]Numéro : [/]"))
            if 1 <= choice <= len(convs):
                self.current_conv_id = convs[choice - 1].id
                console.print(f"[green]✅ Conversation changée : {self.current_conv_id}[/]")
                await self._show_history()
            else:
                console.print("[red]❌ Numéro invalide[/]")
        except ValueError:
            console.print("[red]❌ Entrez un nombre[/]")

    async def _rename_conversation(self):
        if not self.current_conv_id:
            console.print("[red]❌ Aucune conversation active.[/]")
            return
        new_title = console.input("[bold]Nouveau titre : [/]").strip()
        if not new_title:
            console.print("[red]❌ Titre invalide[/]")
            return
        try:
            await self.client.rename_conversation(self.current_conv_id, new_title)
            console.print(f"[green]✅ Conversation renommée : {new_title}[/]")
        except APIError as e:
            console.print(f"[red]❌ {e}[/]")

    async def _toggle_pin(self):
        if not self.current_conv_id:
            console.print("[red]❌ Aucune conversation active.[/]")
            return
        convs = await self.client.list_conversations()
        current = next((c for c in convs if c.id == self.current_conv_id), None)
        if not current:
            console.print("[red]❌ Conversation non trouvée.[/]")
            return
        new_state = not current.is_pinned
        try:
            await self.client.pin_conversation(self.current_conv_id, new_state)
            if new_state:
                console.print(f"[green]✅ Conversation épinglée : {self.current_conv_id}[/]")
            else:
                console.print(f"[green]✅ Conversation désépinglée : {self.current_conv_id}[/]")
        except APIError as e:
            console.print(f"[red]❌ {e}[/]")

    async def _delete_conversation(self):
        if not self.current_conv_id:
            console.print("[red]❌ Aucune conversation active.[/]")
            return
        confirm = console.input(f"[yellow]⚠️ Supprimer définitivement la conversation {self.current_conv_id[:8]}... ? (o/N) : [/]").strip().lower()
        if confirm not in ("o", "oui", "y", "yes"):
            console.print("[green]✅ Annulé.[/]")
            return
        try:
            await self.client.delete_conversation(self.current_conv_id)
            console.print("[green]✅ Conversation supprimée[/]")
            new_id = await self.client.create_conversation()
            self.current_conv_id = new_id
            console.print(f"[green]✅ Nouvelle conversation créée : {self.current_conv_id}[/]")
        except APIError as e:
            console.print(f"[red]❌ {e}[/]")

    async def _search_history(self, keyword: str):
        if not self.current_conv_id:
            console.print("[red]❌ Aucune conversation active.[/]")
            return
        messages = await self.client.get_conversation_messages(self.current_conv_id, limit=200)
        results = [m for m in messages if keyword.lower() in m.content.lower()]
        if not results:
            console.print(f"[yellow]🔍 Aucun message contenant '{keyword}' trouvé.[/]")
            return
        console.print(f"\n[bold]🔍 Résultats pour '{keyword}' :[/]")
        for msg in results:
            role = "🧑‍💻 Utilisateur" if msg.role == "user" else "🤖 Assistant"
            snippet = msg.content[:150].replace("\n", " ")
            console.print(f"[bold]{role}:[/] {snippet}...")
        console.print()

    async def _export_conversation(self, format: str = "md"):
        if not self.current_conv_id:
            console.print("[red]❌ Aucune conversation active.[/]")
            return
        messages = await self.client.get_conversation_messages(self.current_conv_id, limit=500)
        if not messages:
            console.print("[yellow]📭 Aucun message à exporter.[/]")
            return
        conv_info = await self.client.list_conversations()
        conv_title = next((c.title for c in conv_info if c.id == self.current_conv_id), "Conversation")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"export_{self.current_conv_id[:8]}_{timestamp}.{format}"
        if format == "json":
            data = {
                "conversation_id": self.current_conv_id,
                "title": conv_title,
                "exported_at": datetime.now().isoformat(),
                "messages": [
                    {"role": m.role, "content": m.content, "created_at": m.created_at}
                    for m in messages
                ]
            }
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        elif format == "md":
            lines = [f"# {conv_title}\n", f"**Exporté le :** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n", "---\n"]
            for m in messages:
                role = "**Utilisateur**" if m.role == "user" else "**Assistant**"
                lines.append(f"### {role}")
                lines.append(m.content)
                lines.append(f"*{m.created_at}*\n")
            with open(filename, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
        else:  # txt
            lines = [f"Conversation: {conv_title}\n", f"Date d'export: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n", "=" * 60 + "\n"]
            for m in messages:
                role = "UTILISATEUR" if m.role == "user" else "ASSISTANT"
                lines.append(f"[{role}] {m.created_at}")
                lines.append(m.content)
                lines.append("-" * 40)
            with open(filename, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
        console.print(f"[green]✅ Conversation exportée dans {filename}[/]")

    async def _show_stats(self):
        panel = Panel(
            f"[bold]Messages envoyés :[/] {self.stats.messages_sent}\n"
            f"[bold]Messages reçus :[/] {self.stats.messages_received}\n"
            f"[bold]Temps moyen de réponse :[/] {self.stats.avg_response_time:.2f}s\n"
            f"[bold]Durée de la session :[/] {self.stats.session_duration:.1f}s",
            title="Statistiques de la session",
            border_style="cyan"
        )
        console.print(panel)

    async def run(self, initial_conv_id: str):
        self.current_conv_id = initial_conv_id
        self._print_help()

        while True:
            try:
                prompt = f"[{self.current_conv_id[:8]}] > "
                user_input = console.input(prompt).strip()
                if not user_input:
                    continue

                if user_input.lower() in ("/exit", "exit", "quit", "q"):
                    console.print("[bold]👋 Au revoir ![/]")
                    break

                if user_input.startswith("/"):
                    cmd = user_input.lower()
                    if cmd == "/new":
                        try:
                            new_id = await self.client.create_conversation()
                            self.current_conv_id = new_id
                            console.print(f"[green]✅ Nouvelle conversation : {self.current_conv_id}[/]")
                        except APIError as e:
                            console.print(f"[red]❌ {e}[/]")
                    elif cmd == "/list":
                        await self._list_conversations()
                    elif cmd == "/switch":
                        await self._switch_conversation()
                    elif cmd == "/history":
                        await self._show_history()
                    elif cmd == "/rename":
                        await self._rename_conversation()
                    elif cmd == "/pin":
                        await self._toggle_pin()
                    elif cmd == "/del":
                        await self._delete_conversation()
                    elif cmd.startswith("/search"):
                        parts = cmd.split(maxsplit=1)
                        if len(parts) < 2:
                            console.print("[red]Usage: /search <mot>[/]")
                        else:
                            await self._search_history(parts[1])
                    elif cmd.startswith("/export"):
                        parts = cmd.split(maxsplit=1)
                        fmt = parts[1] if len(parts) > 1 else "md"
                        if fmt not in ("json", "md", "txt"):
                            console.print("[red]Format invalide. Utilisez json, md ou txt.[/]")
                        else:
                            await self._export_conversation(fmt)
                    elif cmd == "/stats":
                        await self._show_stats()
                    else:
                        console.print("[yellow]Commande inconnue. Tapez /help pour la liste.[/]")
                    continue

                # Envoi du message en streaming
                start_time = time.time()
                self.stats.messages_sent += 1
                try:
                    full_response = await self.client.send_message_stream(self.current_conv_id, user_input)
                    elapsed = time.time() - start_time
                    self.stats.total_response_time += elapsed
                    self.stats.messages_received += 1
                    if full_response:
                        console.print("\n[bold green]📝 Réponse formatée :[/]")
                        console.print(Markdown(full_response))
                        console.print()
                except APIError as e:
                    console.print(f"\n[red]❌ {e}[/]")
                except NetworkError as e:
                    console.print(f"\n[red]❌ {e}[/]")
                except Exception as e:
                    console.print(f"\n[red]❌ Erreur inattendue : {e}[/]")

            except KeyboardInterrupt:
                console.print("\n\n[bold]👋 Interruption. Au revoir ![/]")
                break
            except EOFError:
                break


# ----------------------------------------------------------------------
# Fonction principale
# ----------------------------------------------------------------------
async def main():
    parser = argparse.ArgumentParser(description="Test interactif du backend ChatISP AI")
    parser.add_argument("--url", default="http://localhost:8000", help="URL du backend")
    parser.add_argument("--debug", action="store_true", help="Activer les logs de debug")
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    base_url = args.url.rstrip("/")
    logger.info(f"🚀 Démarrage du test interactif pour {base_url}")

    async with ChatISPClient(base_url=base_url, timeout=TIMEOUT) as client:
        # Vérification de la santé du backend
        try:
            await client._request("GET", "/api/v1/health", retry_auth=False)
            logger.info("✅ Backend joignable")
        except APIError as e:
            logger.error(f"❌ Backend inaccessible : {e}")
            sys.exit(1)
        except NetworkError as e:
            logger.error(f"❌ Connexion impossible : {e}")
            sys.exit(1)

        console.print("\n[bold]🔐 Authentification[/]")
        console.print("1. Se connecter (email/mot de passe)")
        console.print("2. S'inscrire")
        choice = console.input("[bold]Choix (1/2) : [/]").strip()

        token = None
        email = None
        password = None
        if choice == "1":
            email = console.input("[bold]Email : [/]").strip()
            password = console.input("[bold]Mot de passe : [/]").strip()
            try:
                token = await client.login(email, password)
                logger.info("✅ Connexion réussie")
            except APIError as e:
                logger.error(f"❌ {e}")
                sys.exit(1)
        elif choice == "2":
            email = console.input("[bold]Email : [/]").strip()
            password = console.input("[bold]Mot de passe (min 6 caractères) : [/]").strip()
            display_name = console.input("[bold]Nom affiché : [/]").strip()
            try:
                token = await client.register(email, password, display_name)
                logger.info("✅ Inscription réussie")
            except APIError as e:
                logger.error(f"❌ {e}")
                sys.exit(1)
        else:
            logger.error("Choix invalide")
            sys.exit(1)

        client.set_token(token, email, password)

        # Récupération du profil
        try:
            user = await client.get_me()
            logger.info(f"✅ Connecté en tant que : {user.display_name} ({user.email})")
        except APIError as e:
            logger.error(f"❌ Impossible de récupérer le profil : {e}")
            sys.exit(1)

        # Lister les conversations existantes
        conversations = await client.list_conversations()
        conv_id = None
        if conversations:
            console.print(f"\n[bold]📂 {len(conversations)} conversation(s) existante(s) :[/]")
            for i, c in enumerate(conversations, 1):
                pinned = "📌 " if c.is_pinned else "   "
                console.print(f"  {i}. {pinned}{c.title or '(sans titre)'} (id: {c.id[:8]}...)")
            console.print("\n[bold]Que voulez-vous faire ?[/]")
            console.print("  1. Reprendre une conversation existante")
            console.print("  2. Créer une nouvelle conversation")
            sub_choice = console.input("[bold]Choix (1/2) : [/]").strip()
            if sub_choice == "1":
                try:
                    idx = int(console.input("[bold]Numéro : [/]")) - 1
                    if 0 <= idx < len(conversations):
                        conv_id = conversations[idx].id
                        logger.info(f"Conversation sélectionnée : {conv_id}")
                    else:
                        logger.warning("Numéro invalide, création d'une nouvelle conversation")
                        conv_id = await client.create_conversation()
                except ValueError:
                    logger.warning("Entrée invalide, création d'une nouvelle conversation")
                    conv_id = await client.create_conversation()
            else:
                conv_id = await client.create_conversation()
        else:
            logger.info("Aucune conversation existante. Création d'une nouvelle...")
            conv_id = await client.create_conversation()

        if not conv_id:
            logger.error("Impossible de créer ou sélectionner une conversation")
            sys.exit(1)

        logger.info(f"✅ Conversation active : {conv_id}")

        # Affichage de l'historique de la conversation active
        interactive = InteractiveChat(client)
        interactive.user = user
        await interactive.run(conv_id)

    logger.info("✨ Fin du test interactif ✨")


if __name__ == "__main__":
    asyncio.run(main())