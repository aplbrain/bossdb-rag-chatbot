import os
import logging
from typing import List, Optional
from llama_index.core import (
    VectorStoreIndex,
    StorageContext,
    load_index_from_storage,
)

from .splitter import Splitter
from .data_loader import DataLoader

STORAGE_DIR = "./storage"
DATA_LOADED_FLAG = os.path.join(STORAGE_DIR, ".data_loaded")

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
    index or loading an existing one from storage.

    Attributes:
        index (Optional[VectorStoreIndex]): The vector store index used for document retrieval
        splitter (Splitter): Component for splitting documents into appropriate chunks
    """

    def __init__(self):
        """Initialize the IndexBuilder with default configurations.

        Sets up the initial state with an empty index (vector database) and creates a new Splitter
        instance for document processing.
        """
        self.index = None
        self.splitter = Splitter()

    async def build_or_load_index(
        self, urls: List[str], orgs: List[str], github_token: Optional[str] = None
    ) -> VectorStoreIndex:
        """Build a new vector index or load an existing one from storage.

        This method determines whether to build a new index or load an existing one based
        on the presence of stored index data. When building a new index, it:
        1. Loads data from all specified URLs and GitHub organizations
        2. Processes the documents through the splitter
        3. Creates a vector index from the processed documents
        4. Persists the index to storage for future use

        Args:
            urls (List[str]): List of URLs to process and include in the index
            orgs (List[str]): List of GitHub organizations whose repositories should be included
            github_token (Optional[str]): GitHub access token for accessing private repositories
                                        or avoiding rate limits. Defaults to None.

        Returns:
            VectorStoreIndex: The loaded or newly built vector index ready for querying

        Raises:
            ValueError: If no documents are successfully loaded during index building
            Exception: If there are errors during index building or loading

        Example:
            ```python
            builder = IndexBuilder()
            urls = ["https://example.com/docs"]
            orgs = ["example-org"]
            index = await builder.build_or_load_index(urls, orgs, github_token="token")
            ```
        """
        try:
            if os.path.exists(STORAGE_DIR) and os.path.exists(DATA_LOADED_FLAG):
                logging.info("Loading existing index from storage...")
                storage_context = StorageContext.from_defaults(persist_dir=STORAGE_DIR)
                self.index = load_index_from_storage(storage_context)
            else:
                logging.info("Building new index...")
                data_loader = DataLoader(urls, orgs, github_token)
                documents = await data_loader.load_all_data()

                if not documents:
                    raise ValueError("No documents were loaded successfully")

                processed_documents = []
                for doc in documents:
                    processed_documents.extend(self.splitter.split(doc))

                os.makedirs(STORAGE_DIR, exist_ok=True)
                self.index = VectorStoreIndex.from_documents(
                    documents, show_progress=True
                )
                self.index.storage_context.persist(persist_dir=STORAGE_DIR)

                with open(DATA_LOADED_FLAG, "w") as f:
                    f.write("1")

                data_loader.cleanup()

            return self.index

        except Exception as e:
            logging.error(f"Error in build_or_load_index: {e}")
            raise
