# SCRIPT is still a WORK-IN-PROGRESS and may not fully work yet

import asyncio
import logging
import os
import yaml
from typing import Dict, Any, Optional, Union
from llama_index.llms.bedrock import Bedrock
from llama_index.embeddings.bedrock import BedrockEmbedding
from llama_index.core import Settings, VectorStoreIndex

from rag.index_builder import IndexBuilder

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("index_builder.log")],
)
logger = logging.getLogger(__name__)


DEFAULT_CONFIG: Dict[str, Any] = {
    "sources": {"urls": [], "github_orgs": []},
    "llm_config": {
        "embed_model": "cohere.embed-english-v3",
        "aws_region": "us-east-1",
        "aws_access_key_id": None,
        "aws_secret_access_key": None,
        "github_token": None,
    },
    "index_settings": {
        "force_reload": False,
        "incremental": False,
    },
}


def load_config() -> Dict[str, Any]:
    """Load configuration from YAML file and process environment variables.

    Returns:
        Dict[str, Any]: Processed configuration dictionary
    """
    config_path = os.path.join(os.path.dirname(__file__), "config.yaml")

    with open(config_path, "r") as file:
        config = yaml.safe_load(file)

    def process_env_vars(item):
        if isinstance(item, str) and item.startswith("OS_ENV_"):
            env_var = item[7:]  # Remove "OS_ENV_" prefix
            value = os.getenv(env_var)
            if value is None:
                raise EnvironmentError(
                    f"Required environment variable {env_var} not set"
                )
            return value
        elif isinstance(item, dict):
            return {k: process_env_vars(v) for k, v in item.items()}
        elif isinstance(item, list):
            return [process_env_vars(v) for v in item]
        return item

    return process_env_vars(config)


async def build_index() -> Optional[VectorStoreIndex]:
    """Build or load the vector index using configuration settings.

    This function handles the entire index building process, including:
    1. Loading and validating configuration
    2. Setting up the embedding model with AWS Bedrock
    3. Initializing and running the index builder
    4. Logging statistics about the built index

    The index is built based on the sources specified in the config file,
    which can include both URLs and GitHub organizations. The function supports
    both creating a new index and incrementally updating an existing one.

    Returns:
        Optional[VectorStoreIndex]: The built or loaded vector index if successful,
            None if an error occurs during the build process.

    Raises:
        Exception: If there are errors during configuration loading or index building.
            The specific exception types depend on the failure mode:
            - EnvironmentError: Missing required environment variables
            - ValueError: Invalid configuration values
            - Various exceptions from llama_index during index building
    """
    try:
        logger.info("Loading configuration...")
        config = load_config()

        # Configure the embedding model
        Settings.embed_model = BedrockEmbedding(
            model=config["llm_config"].get(
                "embed_model", DEFAULT_CONFIG["llm_config"]["embed_model"]
            ),
            region_name=config["llm_config"].get(
                "aws_region", DEFAULT_CONFIG["llm_config"]["aws_region"]
            ),
            aws_access_key_id=config["llm_config"]["aws_access_key_id"],
            aws_secret_access_key=config["llm_config"]["aws_secret_access_key"],
        )

        # Initialize the index builder
        index_builder = IndexBuilder()

        # Build or load the index
        logger.info("Building/loading index...")
        index = await index_builder.build_or_load_index(
            urls=config["sources"].get("urls", DEFAULT_CONFIG["sources"]["urls"]),
            orgs=config["sources"].get(
                "github_orgs", DEFAULT_CONFIG["sources"]["github_orgs"]
            ),
            github_token=config["llm_config"].get("github_token"),
            force_reload=config.get("index_settings", {}).get(
                "force_reload", DEFAULT_CONFIG["index_settings"]["force_reload"]
            ),
            incremental=config.get("index_settings", {}).get(
                "incremental", DEFAULT_CONFIG["index_settings"]["incremental"]
            ),
        )

        # Get and log index statistics
        stats = index_builder.get_index_stats()
        logger.info("Index statistics:")
        logger.info(f"- Last update: {stats['last_update']}")
        logger.info(f"- Total documents: {stats['total_documents']}")
        logger.info(f"- Processed URLs: {stats['processed_urls']}")
        logger.info(f"- Processed organizations: {stats['processed_orgs']}")

        logger.info("Index build completed successfully")
        return index

    except Exception as e:
        logger.error(f"Error building index: {str(e)}", exc_info=True)
        raise


if __name__ == "__main__":
    """Main entry point for the standalone index builder script.

    Runs the index building process and handles any exceptions that occur,
    logging them appropriately.
    """
    try:
        asyncio.run(build_index())
    except Exception as e:
        logger.error(f"Failed to build index: {str(e)}")
        raise
