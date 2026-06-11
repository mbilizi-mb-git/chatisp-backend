#!/usr/bin/env python3
"""
Script d'ingestion des documents dans la base vectorielle ChromaDB pour ChatISP AI.

Supporte les formats : JSONL, TXT, PDF.
Les fichiers JSONL doivent contenir une ligne par document avec au minimum un champ "text" (ou "content").
Les métadonnées supplémentaires peuvent être incluses dans l'objet JSON.
Ingestion incrémentale basée sur la date de modification ou un hash du contenu.
Peut traiter un fichier spécifique ou tous les fichiers d'un dossier.
"""

import argparse
import asyncio
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set

from dotenv import load_dotenv
from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

# Charge le .env situé dans le répertoire parent
env_path = Path(__file__).parent.parent / '.env'
load_dotenv(env_path)

# Ajout du répertoire parent pour pouvoir importer les modules de l'application
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.config import get_settings
from app.core.logging import get_logger
from app.rag.vector_store import VectorStore

logger = get_logger("ingest")
settings = get_settings()

# Constantes
PROCESSED_FILES_PATH = Path(settings.CACHE_DIR) / "processed_files.json"
CHUNK_SIZE = 800
CHUNK_OVERLAP = 80
SUPPORTED_EXTENSIONS = {".jsonl", ".txt", ".pdf", ".JSONL", ".TXT", ".PDF"}


def print_header():
    """Affiche un en‑tête stylisé."""
    print("\n" + "=" * 60)
    print("🔍 CHATISP AI - INGESTION DE DOCUMENTS")
    print("=" * 60 + "\n")


def print_footer(success: int, total: int, chunks: int):
    """Affiche un résumé final."""
    print("\n" + "=" * 60)
    if success == total:
        print(f"✨ INGESTION RÉUSSIE ✨")
    else:
        print(f"⚠️ INGESTION TERMINÉE AVEC DES ERREURS")
    print(f"   Fichiers traités avec succès : {success}/{total}")
    print(f"   Nombre total de chunks ajoutés : {chunks}")
    print("=" * 60 + "\n")


def load_processed_files() -> Dict[str, float]:
    """Charge le dictionnaire des fichiers déjà traités avec leur timestamp."""
    if not PROCESSED_FILES_PATH.exists():
        return {}
    try:
        with open(PROCESSED_FILES_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            # S'assurer que les clés sont des chaînes et les valeurs des floats
            return {str(k): float(v) for k, v in data.items()}
    except Exception as e:
        logger.error(f"Erreur lors du chargement des fichiers traités: {e}")
        return {}


def save_processed_files(processed: Dict[str, float]) -> None:
    """Sauvegarde le dictionnaire des fichiers traités."""
    try:
        PROCESSED_FILES_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(PROCESSED_FILES_PATH, "w", encoding="utf-8") as f:
            json.dump(processed, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Erreur lors de la sauvegarde des fichiers traités: {e}")
        raise


def get_file_mod_time(file_path: Path) -> float:
    """Retourne le timestamp de dernière modification du fichier."""
    try:
        stat = file_path.stat()
        return stat.st_mtime
    except Exception as e:
        logger.error(f"Impossible d'obtenir la date de modification de {file_path}: {e}")
        return 0.0


def compute_file_hash(file_path: Path) -> str:
    """Calcule un hash MD5 du contenu du fichier pour détection de changement."""
    try:
        hasher = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                hasher.update(chunk)
        return hasher.hexdigest()
    except Exception as e:
        logger.error(f"Erreur lors du calcul du hash de {file_path}: {e}")
        return ""


def needs_processing(file_path: Path, processed: Dict[str, float], use_hash: bool = False) -> bool:
    """
    Détermine si un fichier doit être (re)traité.
    Si use_hash est True, compare le hash du contenu plutôt que la date.
    Par défaut utilise la date de modification.
    """
    str_path = str(file_path.absolute())
    current_mtime = get_file_mod_time(file_path)
    if current_mtime == 0.0:
        return False  # Fichier inaccessible, on ignore
    last_mtime = processed.get(str_path)
    if last_mtime is None:
        return True
    if use_hash:
        current_hash = compute_file_hash(file_path)
        last_hash = processed.get(str_path + "_hash")
        return current_hash != last_hash
    return current_mtime > last_mtime


def mark_processed(file_path: Path, processed: Dict[str, float], use_hash: bool = False) -> None:
    """Marque un fichier comme traité avec sa date (et éventuellement son hash)."""
    str_path = str(file_path.absolute())
    processed[str_path] = get_file_mod_time(file_path)
    if use_hash:
        processed[str_path + "_hash"] = compute_file_hash(file_path)


def load_jsonl(file_path: Path) -> List[Document]:
    """Charge un fichier JSONL et le convertit en liste de Documents."""
    documents = []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError as e:
                    logger.warning(f"Ligne {line_num} ignorée (JSON invalide): {e}")
                    continue

                # Extraire le texte : chercher les champs 'text', 'content'
                text = data.get("text") or data.get("content")
                if not text:
                    logger.warning(f"Ligne {line_num} ignorée : pas de champ 'text' ou 'content'")
                    continue

                # Copier les métadonnées en supprimant les champs de contenu
                metadata = {k: v for k, v in data.items() if k not in ("text", "content")}
                metadata["source_file"] = str(file_path)
                metadata["line"] = line_num
                doc = Document(page_content=text, metadata=metadata)
                documents.append(doc)
    except Exception as e:
        logger.error(f"Erreur lors de la lecture du fichier JSONL {file_path}: {e}")
        return []
    return documents


def load_document(file_path: Path) -> List[Document]:
    """Charge un document selon son extension."""
    ext = file_path.suffix.lower()
    try:
        if ext == ".pdf":
            loader = PyPDFLoader(str(file_path))
            docs = loader.load()
            # Ajouter la source dans les métadonnées
            for doc in docs:
                doc.metadata["source_file"] = str(file_path)
            return docs
        elif ext == ".txt":
            loader = TextLoader(str(file_path), encoding="utf-8")
            docs = loader.load()
            for doc in docs:
                doc.metadata["source_file"] = str(file_path)
            return docs
        elif ext == ".jsonl":
            return load_jsonl(file_path)
        else:
            logger.warning(f"Extension non supportée: {ext} pour {file_path}")
            return []
    except Exception as e:
        logger.error(f"Erreur lors du chargement de {file_path}: {e}")
        return []


def split_documents(documents: List[Document], chunk_size: int, chunk_overlap: int) -> List[Document]:
    """Découpe les documents en chunks."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=len,
        separators=["\n\n", "\n", ". ", "! ", "? ", "; ", ": ", ", ", " ", ""],
        keep_separator=True,
    )
    return splitter.split_documents(documents)


def enrich_metadata(documents: List[Document], source_file: Path) -> List[Document]:
    """Ajoute des métadonnées communes à tous les chunks d'un fichier."""
    enriched = []
    file_hash = hashlib.md5(str(source_file.absolute()).encode()).hexdigest()[:8]
    for i, doc in enumerate(documents):
        doc.metadata.update(
            {
                "source_type": "academic",  # On garde "academic" pour compatibilité, même si général
                "chunk_index": i,
                "chunk_id": f"{file_hash}_{i}",
                "ingestion_date": datetime.utcnow().isoformat(),
            }
        )
        enriched.append(doc)
    return enriched


async def ingest_file(
    file_path: Path,
    vector_store: VectorStore,
    processed: Dict[str, float],
    use_hash: bool = False,
    chunk_size: int = CHUNK_SIZE,
    chunk_overlap: int = CHUNK_OVERLAP,
) -> int:
    """
    Ingest un fichier unique.
    Retourne le nombre de chunks ajoutés (0 en cas d'échec).
    """
    print(f"📄 Traitement de {file_path}...", end="", flush=True)
    docs = load_document(file_path)
    if not docs:
        print(" ❌ Aucun document chargé")
        logger.warning(f"Aucun document chargé depuis {file_path}")
        return 0

    chunks = split_documents(docs, chunk_size, chunk_overlap)
    if not chunks:
        print(" ❌ Aucun chunk généré")
        logger.warning(f"Aucun chunk généré pour {file_path}")
        return 0

    enriched = enrich_metadata(chunks, file_path)

    try:
        # Ajout à la base vectorielle
        await vector_store.add_documents(enriched)
        # Marquer comme traité
        mark_processed(file_path, processed, use_hash)
        print(f" ✅ {len(enriched)} chunks ajoutés")
        logger.info(f"✅ {file_path} traité avec succès ({len(enriched)} chunks).")
        return len(enriched)
    except Exception as e:
        print(f" ❌ Erreur : {e}")
        logger.error(f"Erreur lors de l'ajout à Chroma pour {file_path}: {e}")
        return 0


async def ingest_all(
    directory: Path,
    reset: bool = False,
    use_hash: bool = False,
    recursive: bool = False,
    incremental: bool = True,
    chunk_size: int = CHUNK_SIZE,
    chunk_overlap: int = CHUNK_OVERLAP,
) -> None:
    """
    Parcourt un dossier et ingère tous les fichiers supportés.
    Si reset est True, vide la collection avant de commencer.
    Si incremental est True, seuls les fichiers nouveaux ou modifiés sont traités.
    Sinon, tous les fichiers sont traités (l'état est tout de même mis à jour).
    """
    print_header()

    # Initialisation du vector store
    try:
        vector_store = VectorStore()
        # S'assurer que la collection existe (initialisation lazy)
        await vector_store.ensure_collection()
        print("✅ Connexion à la base vectorielle établie")
    except Exception as e:
        logger.error(f"Impossible d'initialiser le vector store: {e}")
        print(f"❌ Erreur : impossible d'initialiser la base vectorielle - {e}")
        sys.exit(1)

    # Réinitialisation si demandé
    if reset:
        try:
            print("⚠️ Réinitialisation de la collection demandée...")
            import shutil
            chroma_path = Path(settings.CHROMA_PATH)
            if chroma_path.exists():
                shutil.rmtree(chroma_path)
                print("✅ Dossier Chroma supprimé")
            else:
                print("ℹ️ Dossier Chroma inexistant, rien à supprimer")
            # Recréer l'instance
            vector_store = VectorStore()
            await vector_store.ensure_collection()
            # On vide aussi le fichier de suivi
            save_processed_files({})
            print("✅ Collection recréée et état réinitialisé")
        except Exception as e:
            logger.error(f"Erreur lors de la réinitialisation: {e}")
            print(f"❌ Erreur lors de la réinitialisation : {e}")
            sys.exit(1)

    # Charger les fichiers déjà traités
    processed = load_processed_files()

    # Récupérer tous les fichiers du dossier avec extensions supportées
    files: Set[Path] = set()
    if recursive:
        for ext in SUPPORTED_EXTENSIONS:
            files.update(directory.rglob(f"*{ext}"))
    else:
        for ext in SUPPORTED_EXTENSIONS:
            files.update(directory.glob(f"*{ext}"))

    if not files:
        print("⚠️ Aucun fichier supporté trouvé dans le dossier.")
        return

    # Filtrer ceux qui nécessitent un traitement selon le mode incrémental
    if incremental:
        to_process = [f for f in files if needs_processing(f, processed, use_hash)]
        print(f"📊 {len(to_process)} fichiers à traiter sur {len(files)} trouvés (mode incrémental).")
    else:
        to_process = list(files)
        print(f"📊 Traitement de tous les {len(to_process)} fichiers (mode non incrémental).")

    if not to_process:
        print("✨ Aucun fichier à traiter.")
        return

    total_chunks = 0
    success_count = 0
    for file_path in to_process:
        chunks = await ingest_file(file_path, vector_store, processed, use_hash, chunk_size, chunk_overlap)
        if chunks > 0:
            success_count += 1
            total_chunks += chunks

    # Sauvegarder l'état des fichiers traités
    save_processed_files(processed)

    print_footer(success_count, len(to_process), total_chunks)


async def ingest_single(
    file_path: Path,
    use_hash: bool = False,
    chunk_size: int = CHUNK_SIZE,
    chunk_overlap: int = CHUNK_OVERLAP,
) -> None:
    """Ingère un seul fichier spécifique."""
    print_header()

    if not file_path.exists():
        print(f"❌ Le fichier {file_path} n'existe pas.")
        sys.exit(1)

    # Initialisation
    try:
        vector_store = VectorStore()
        await vector_store.ensure_collection()
        print("✅ Connexion à la base vectorielle établie")
    except Exception as e:
        logger.error(f"Erreur d'initialisation du vector store: {e}")
        print(f"❌ Erreur : impossible d'initialiser la base vectorielle - {e}")
        sys.exit(1)

    processed = load_processed_files()
    # Pour un fichier unique, on le traite toujours (peu importe incremental)
    chunks = await ingest_file(file_path, vector_store, processed, use_hash, chunk_size, chunk_overlap)
    if chunks > 0:
        save_processed_files(processed)
        print("\n✨ INGESTION DU FICHIER RÉUSSIE ✨")
        print(f"   {chunks} chunks ajoutés")
    else:
        print("\n❌ ÉCHEC DE L'INGESTION")
        sys.exit(1)


def main() -> None:
    """Point d'entrée principal."""
    parser = argparse.ArgumentParser(description="Ingestion de documents dans la base vectorielle ChatISP AI")
    parser.add_argument(
        "--dir",
        type=str,
        help="Dossier contenant les documents (PDF/TXT/JSONL).",
    )
    parser.add_argument(
        "--file", type=str, help="Fichier spécifique à ingérer (ignore --dir)."
    )
    parser.add_argument(
        "--reset", action="store_true", help="Réinitialiser la collection avant ingestion."
    )
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="Mode incrémental : n'ingère que les fichiers nouveaux ou modifiés. (Par défaut, si l'option n'est pas fournie, tous les fichiers sont traités.)",
    )
    parser.add_argument(
        "--use-hash",
        action="store_true",
        help="Utiliser le hash du contenu plutôt que la date de modification pour détecter les changements.",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Parcourir récursivement les sous-dossiers (avec --dir).",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=CHUNK_SIZE,
        help=f"Taille des chunks en caractères (défaut: {CHUNK_SIZE})",
    )
    parser.add_argument(
        "--chunk-overlap",
        type=int,
        default=CHUNK_OVERLAP,
        help=f"Chevauchement des chunks en caractères (défaut: {CHUNK_OVERLAP})",
    )
    args = parser.parse_args()

    if not args.file and not args.dir:
        parser.error("Soit --file soit --dir doit être fourni.")

    if args.file and args.dir:
        parser.error("Les options --file et --dir sont mutuellement exclusives.")

    if args.file:
        asyncio.run(
            ingest_single(
                Path(args.file),
                use_hash=args.use_hash,
                chunk_size=args.chunk_size,
                chunk_overlap=args.chunk_overlap,
            )
        )
    else:
        directory = Path(args.dir)
        if not directory.is_dir():
            logger.error(f"Le dossier {directory} n'existe pas ou n'est pas un répertoire.")
            print(f"❌ Le dossier {directory} n'existe pas ou n'est pas un répertoire.")
            sys.exit(1)
        asyncio.run(
            ingest_all(
                directory,
                reset=args.reset,
                use_hash=args.use_hash,
                recursive=args.recursive,
                incremental=args.incremental,
                chunk_size=args.chunk_size,
                chunk_overlap=args.chunk_overlap,
            )
        )


if __name__ == "__main__":
    main()