import os
import shutil
import json
import logging
import hashlib
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any, Set
from llama_index.core import (
    VectorStoreIndex,
    StorageContext,
    load_index_from_storage,
    Document,
)

from .splitter import Splitter
from .data_loader import DataLoader

STORAGE_DIR = "./storage"
INDEX_METADATA_FILE = os.path.join(STORAGE_DIR, "index_metadata.json")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


class IndexBuilder:
    """Class to build and manage vector indices for document retrieval.

    This class handles the creation and persistence of vector indices used for document
    retrieval in the RAG system. It manages the process of loading documents from various
    sources, processing them through the document splitter, and either building a new
    index or loading an existing one from storage. Supports both full rebuilds and
    incremental updates.

    Attributes:
        index (Optional[VectorStoreIndex]): The vector store index used for document retrieval
        splitter (Splitter): Component for splitting documents into appropriate chunks
        metadata (Dict[str, Any]): Metadata about the index including processing history
    """

    def __init__(self):
        """Initialize the IndexBuilder with default configurations.

        Sets up the initial state with an empty index (vector database), creates a new Splitter
        instance for document processing, and loads existing metadata if available.
        """
        self.index = None
        self.splitter = Splitter()
        self.metadata = self._load_metadata()

    def _load_metadata(self) -> Dict[str, Any]:
        """Load index metadata from storage if it exists.

        Returns:
            Dict[str, Any]: Dictionary containing index metadata including:
                - last_update: Timestamp of last index update
                - document_hashes: Dictionary mapping URLs to content hashes
                - processed_urls: Set of processed URLs
                - processed_orgs: Set of processed GitHub organizations
        """
        if os.path.exists(INDEX_METADATA_FILE):
            with open(INDEX_METADATA_FILE, "r") as f:
                return json.load(f)
        return {
            "last_update": None,
            "document_hashes": {},
            "processed_urls": set(),
            "processed_orgs": set(),
        }

    def _save_metadata(self) -> None:
        """Save current index metadata to storage.

        Persists the current state of the index metadata to disk, including:
        - Processing history
        - Document hashes
        - Last update timestamp
        """
        metadata_to_save = self.metadata.copy()
        metadata_to_save["processed_urls"] = list(self.metadata["processed_urls"])
        metadata_to_save["processed_orgs"] = list(self.metadata["processed_orgs"])

        os.makedirs(STORAGE_DIR, exist_ok=True)
        with open(INDEX_METADATA_FILE, "w") as f:
            json.dump(metadata_to_save, f, indent=2)

    def _compute_document_hash(self, document: Document) -> str:
        """Compute a hash for a document based on its content and metadata.

        Args:
            document (Document): The document to hash

        Returns:
            str: SHA-256 hash of the document's content and metadata
        """
        content = document.text.encode("utf-8")
        metadata_str = json.dumps(document.metadata, sort_keys=True).encode("utf-8")
        return hashlib.sha256(content + metadata_str).hexdigest()

    async def _process_new_documents(
        self,
        urls: List[str],
        orgs: List[str],
        github_token: Optional[str],
        check_hash: bool = False,
    ) -> List[Document]:
        """Process documents that haven't been indexed yet or need updating.

        Args:
            urls (List[str]): List of URLs to process
            orgs (List[str]): List of GitHub organizations to process
            github_token (Optional[str]): GitHub access token
            check_hash (bool): Whether to check hash before adding as new document

        Returns:
            List[Document]: List of processed documents that need to be added/updated
        """
        data_loader = DataLoader(urls, orgs, github_token)
        all_documents = await data_loader.load_all_data()
        data_loader.cleanup()

        new_documents = []
        processed_urls = set()
        processed_orgs = set()

        for doc in all_documents:
            doc_hash = self._compute_document_hash(doc)
            url = doc.metadata.get("url", "")
            org = doc.metadata.get("organization", "")

            if not check_hash or (
                doc_hash != self.metadata["document_hashes"].get(url, "")
            ):
                processed_docs = self.splitter.split(doc)
                new_documents.extend(processed_docs)
                self.metadata["document_hashes"][url] = doc_hash

            if url:
                processed_urls.add(url)
            if org:
                processed_orgs.add(org)

        self.metadata["processed_urls"].update(processed_urls)
        self.metadata["processed_orgs"].update(processed_orgs)

        return new_documents

    async def build_or_load_index(
        self,
        urls: List[str],
        orgs: List[str],
        github_token: Optional[str] = None,
        force_reload: bool = False,
        incremental: bool = True,
    ) -> VectorStoreIndex:
        """Build a new vector index or update an existing one.

        This method determines whether to build a new index, update an existing one, or
        load from storage based on the provided parameters and existing state. When
        building or updating an index, it:
        1. Loads and processes data from specified URLs and GitHub organizations
        2. Processes the documents through the splitter
        3. Creates or updates the vector index
        4. Persists the index and metadata to storage

        Args:
            urls (List[str]): List of URLs to process and include in the index
            orgs (List[str]): List of GitHub organizations whose repositories should be included
            github_token (Optional[str]): GitHub access token for accessing private repositories
                                        or avoiding rate limits. Defaults to None.
            force_reload (bool): If True, rebuilds the entire index from scratch.
                               Defaults to False.
            incremental (bool): If True, only processes new or modified documents.
                              Defaults to True.

        Returns:
            VectorStoreIndex: The loaded or newly built vector index ready for querying

        Raises:
            ValueError: If no documents are successfully loaded during index building
            Exception: If there are errors during index building or loading

        Example:
            ```python
            builder = IndexBuilder()

            # Incremental update
            index = await builder.build_or_load_index(
                urls=["https://docs.example.com"],
                orgs=["example-org"],
                github_token="token",
                incremental=True
            )

            # Force complete rebuild
            index = await builder.build_or_load_index(
                urls=urls,
                orgs=orgs,
                github_token=token,
                force_reload=True
            )
            ```
        """
        incremental = False if force_reload else incremental
        try:
            self.metadata["processed_urls"] = set(self.metadata["processed_urls"])
            self.metadata["processed_orgs"] = set(self.metadata["processed_orgs"])

            if force_reload:
                logger.info("Force reload requested. Building new index...")
                if os.path.exists(STORAGE_DIR):
                    shutil.rmtree(STORAGE_DIR)
                self.metadata = {
                    "last_update": None,
                    "document_hashes": {},
                    "processed_urls": set(),
                    "processed_orgs": set(),
                }

            new_urls = list(
                set(urls) - self.metadata["processed_urls"]
                if incremental
                else set(urls)
            )
            new_orgs = list(
                set(orgs) - self.metadata["processed_orgs"]
                if incremental
                else set(orgs)
            )

            if os.path.exists(STORAGE_DIR):
                logger.info("Loading existing index from storage...")
                storage_context = StorageContext.from_defaults(persist_dir=STORAGE_DIR)
                self.index = load_index_from_storage(storage_context)
                if not (new_urls or new_orgs):
                    return self.index

            new_documents = await self._process_new_documents(
                new_urls,
                new_orgs,
                github_token,
                check_hash=False,
            )

            if new_documents:
                if self.index and incremental and not force_reload:
                    logger.info("Updating existing index with new documents...")
                    self.index.insert_nodes(new_documents)
                else:
                    logger.info("Building new index...")
                    self.index = VectorStoreIndex(new_documents, show_progress=True)
                    os.makedirs(STORAGE_DIR, exist_ok=True)
                    self.index.storage_context.persist(persist_dir=STORAGE_DIR)
                self.metadata["last_update"] = datetime.now(timezone.utc).isoformat()
                self._save_metadata()
            else:
                logger.info("No new documents to process")
                try:
                    storage_context = StorageContext.from_defaults(
                        persist_dir=STORAGE_DIR
                    )
                    self.index = load_index_from_storage(storage_context)
                except FileNotFoundError:
                    logger.info("Building new index...")
                    self.index = VectorStoreIndex([], show_progress=True)
                    os.makedirs(STORAGE_DIR, exist_ok=True)
                    self.index.storage_context.persist(persist_dir=STORAGE_DIR)
                    self.metadata["last_update"] = datetime.now(
                        timezone.utc
                    ).isoformat()
                    self._save_metadata()

            return self.index

        except Exception as e:
            logger.error(f"Error in build_or_load_index: {str(e)}", exc_info=True)
            raise

    def get_index_stats(self) -> Dict[str, Any]:
        """Get statistics about the current index.

        Returns:
            Dict[str, Any]: Dictionary containing index statistics including:
                - last_update: Timestamp of last index update
                - total_documents: Number of documents in the index
                - processed_urls: Number of processed URLs
                - processed_orgs: Number of processed organizations
        """
        return {
            "last_update": self.metadata["last_update"],
            "total_documents": len(self.metadata["document_hashes"]),
            "processed_urls": len(self.metadata["processed_urls"]),
            "processed_orgs": len(self.metadata["processed_orgs"]),
        }
