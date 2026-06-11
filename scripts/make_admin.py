#!/usr/bin/env python3
"""
Script pour gérer les droits administrateur des utilisateurs.
Peut promouvoir ou rétrograder un utilisateur (is_admin = True/False).
À exécuter une fois pour le(s) compte(s) du créateur (MBILIZI) et éventuellement d'autres admins.

Usage:
    python scripts/make_admin.py --email regoryallison@example.org --set-admin
    python scripts/make_admin.py --email renedesign36@gmail.com --set-admin
    python scripts/make_admin.py --email renedesign36@gmail.com --remove-admin
    python scripts/make_admin.py --email test@gmail.com --remove-admin
    python scripts/make_admin.py --list-admins
"""

import asyncio
import argparse
import sys
from pathlib import Path

# Ajouter le répertoire parent au path pour importer les modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select, update
from app.core.database import AsyncSessionLocal
from app.models.user import User


async def set_admin(email: str, admin_status: bool) -> None:
    """
    Définit le statut is_admin d'un utilisateur.
    admin_status=True pour promouvoir, False pour rétrograder.
    """
    async with AsyncSessionLocal() as db:
        # Vérifier si l'utilisateur existe
        stmt = select(User).where(User.email == email)
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()
        if not user:
            print(f"❌ Aucun utilisateur trouvé avec l'email {email}.")
            return

        # Mettre à jour is_admin
        stmt = update(User).where(User.email == email).values(is_admin=admin_status)
        await db.execute(stmt)
        await db.commit()

        if admin_status:
            print(f"✅ L'utilisateur {email} est maintenant administrateur.")
        else:
            print(f"✅ Les droits administrateur de {email} ont été révoqués.")


async def list_admins() -> None:
    """Liste tous les utilisateurs ayant is_admin = True."""
    async with AsyncSessionLocal() as db:
        stmt = select(User).where(User.is_admin == True)
        result = await db.execute(stmt)
        admins = result.scalars().all()
        if not admins:
            print("📭 Aucun administrateur trouvé.")
            return
        print("\n👑 Liste des administrateurs :")
        for admin in admins:
            print(f"  - {admin.email} (id: {admin.id})")
        print()


async def main():
    parser = argparse.ArgumentParser(description="Gestion des droits administrateur.")
    parser.add_argument("--email", type=str, help="Email de l'utilisateur cible")
    parser.add_argument("--set-admin", action="store_true", help="Promouvoir l'utilisateur en admin")
    parser.add_argument("--remove-admin", action="store_true", help="Révoquer les droits admin")
    parser.add_argument("--list-admins", action="store_true", help="Lister tous les administrateurs")
    args = parser.parse_args()

    if args.list_admins:
        await list_admins()
    elif args.email:
        if args.set_admin:
            await set_admin(args.email, True)
        elif args.remove_admin:
            await set_admin(args.email, False)
        else:
            print("❌ Spécifiez --set-admin ou --remove-admin pour modifier les droits.")
            sys.exit(1)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())