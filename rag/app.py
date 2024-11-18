import logging
from datetime import datetime
from llama_index.llms.bedrock import Bedrock
from llama_index.embeddings.bedrock import BedrockEmbedding
from llama_index.core import Settings

from .index_builder import IndexBuilder
from .query_processor import QueryProcessor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


class BossDBRAGApplication:
    """Main application class for BossDB RAG.

    This class manages the core functionality of the BossDB RAG application,
    including index building, query processing, and AWS LLM service integration.
    It handles the setup of language models, embeddings, and maintains the
    configuration for data sources.

    Attributes:
        urls (List[str]): List of URLs to scrape for building the knowledge base.
        orgs (List[str]): List of GitHub organizations to include in the knowledge base.
        llm (str): Model identifier for the main language model (e.g., Claude 3 Sonnet).
        fast_llm (str): Model identifier for the faster, summarization language model (e.g., Claude 3 Haiku).
        embed_model (str): Model identifier for the embedding model.
        aws_access_key_id (str): AWS access key for Bedrock API access.
        aws_secret_access_key (str): AWS secret key for Bedrock API access.
        aws_region (str): AWS region for Bedrock service.
        github_token (str): GitHub access token for repository access.
        max_total_tokens (int): Maximum total tokens allowed in a conversation. Defaults to 8192.
        max_message_tokens (int): Maximum tokens allowed in a single message. Defaults to 4096.
        temperature (float): Temperature setting for language model output. Defaults to 0.1.
        index_builder (IndexBuilder): Component for building and managing the vector index.
        index: The vector index used for document retrieval.
    """

    def __init__(
        self,
        urls,
        orgs,
        llm,
        fast_llm,
        embed_model,
        aws_access_key_id,
        aws_secret_access_key,
        aws_region,
        github_token,
        max_total_tokens=8192,
        max_message_tokens=4096,
        temperature=0.1,
    ):
        """Initialize the BossDB RAG application with default configurations."""
        self.urls = urls
        self.orgs = orgs
        self.llm = llm
        self.fast_llm = fast_llm
        self.embed_model = embed_model
        self.aws_access_key_id = aws_access_key_id
        self.aws_secret_access_key = aws_secret_access_key
        self.aws_region = aws_region
        self.github_token = github_token
        self.temperature = temperature

        Settings.llm = Bedrock(
            model=self.llm,
            aws_access_key_id=self.aws_access_key_id,
            aws_secret_access_key=self.aws_secret_access_key,
            region_name=self.aws_region,
            temperature=self.temperature,
        )
        Settings.embed_model = BedrockEmbedding(
            model=self.embed_model,
            region_name=self.aws_region,
            aws_access_key_id=self.aws_access_key_id,
            aws_secret_access_key=self.aws_secret_access_key,
        )

        self.index_builder = IndexBuilder()
        self.index = None
        self.max_total_tokens = max_total_tokens
        self.max_message_tokens = max_message_tokens

    async def setup(self) -> None:
        """Set up the RAG application by building or loading the document index.

        Initializes the vector index by either loading a previously built index
        from storage or creating a new one from the configured data sources.
        Uses GitHub token if available for accessing private repositories.

        Raises:
            Exception: If setup fails due to index building or loading errors
        """
        try:
            logger.info("Starting BossDBRAGApplication setup...")

            setup_start_time = datetime.now()
            self.index = await self.index_builder.build_or_load_index(
                self.urls, self.orgs, github_token=self.github_token
            )
            setup_end_time = datetime.now()

            setup_duration = (setup_end_time - setup_start_time).total_seconds()
            logger.info(f"Index setup completed in {setup_duration} seconds")
        except Exception as e:
            logger.error(f"Error in setup: {str(e)}", exc_info=True)
            raise

    async def create_query_processor(self) -> QueryProcessor:
        """Create and configure a new query processor instance.

        Sets up a new QueryProcessor with the configured language models and parameters.
        Creates two Bedrock LLM instances:
        - Main LLM for generating responses (Claude 3 Sonnet)
        - Summarizer LLM for memory management (Claude 3 Haiku)

        Returns:
            QueryProcessor: Configured query processor instance ready for handling queries

        Raises:
            Exception: If creation of language models or query processor fails
        """
        main_llm = Bedrock(
            model=self.llm,
            aws_access_key_id=self.aws_access_key_id,
            aws_secret_access_key=self.aws_secret_access_key,
            region_name=self.aws_region,
            temperature=self.temperature,
            max_tokens=self.max_message_tokens,
        )
        summarizer_llm = Bedrock(
            model=self.fast_llm,
            aws_access_key_id=self.aws_access_key_id,
            aws_secret_access_key=self.aws_secret_access_key,
            region_name=self.aws_region,
            temperature=0,
            max_tokens=self.max_total_tokens // 4,
        )

        return QueryProcessor(
            self.index,
            main_llm,
            summarizer_llm=summarizer_llm,
            conversation_token_limit=self.max_total_tokens,
            max_input_tokens=self.max_message_tokens,
        )
