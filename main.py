import os
import logging
import uuid
import yaml
from datetime import datetime, timezone
from typing import List, Dict, Any
import chainlit as cl
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.future import select
from tracking.database_models import (
    User,
    ChatThread,
    Message,
    AsyncSessionLocal,
    create_tables,
)

from rag.app import BossDBRAGApplication


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("bossdb_rag.log")],
)
logger = logging.getLogger(__name__)


DEFAULT_CONFIG = {
    "sources": {"urls": [], "github_orgs": []},
    "llm_config": {
        "default_llm": "anthropic.claude-3-sonnet-20240620-v1:0",
        "fast_llm": "anthropic.claude-3-haiku-20240307-v1:0",
        "embed_model": "cohere.embed-english-v3",
        "aws_region": "us-east-1",
        "aws_access_key_id": None,  # Must be provided via env var
        "aws_secret_access_key": None,  # Must be provided via env var
        "github_token": None,  # Optional
    },
    "limits": {
        "max_questions": 1000,
        "max_words": 100000,
        "max_total_tokens": 8192,
        "max_message_tokens": 4096,
    },
    "index_settings": {
        "force_reload": False,  # Whether to force rebuild the index
        "incremental": False,  # Whether to use incremental updates
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


app = None
max_questions = None
max_words = None


def get_client_ip() -> str:
    return "127.0.0.1"  # Placeholder


def generate_session_id() -> str:
    return str(uuid.uuid4())


def get_user_identifier(session_id: str) -> str:
    """Creates a unique user identifier by combining IP address and session ID.

    Args:
        session_id (str): The unique session identifier

    Returns:
        str: A combined identifier in the format "ip_sessionid"
    """
    ip = get_client_ip()
    return f"{ip}_{session_id}"


def log_user_activity(user_identifier: str, action: str, details: str = "") -> None:
    """Logs user activity for monitoring and debugging purposes.

    Args:
        user_identifier (str): The unique identifier for the user
        action (str): The action being performed
        details (str, optional): Additional details about the action. Defaults to ""
    """
    logger.info(
        f"User Activity - Identifier: {user_identifier}, Action: {action}, Details: {details}"
    )


async def get_or_create_user(session: AsyncSession, user_identifier: str) -> User:
    """Retrieves an existing user or creates a new one if not found.

    Args:
        session (AsyncSession): The database session
        user_identifier (str): The unique identifier for the user

    Returns:
        User: The retrieved or newly created user object
    """
    stmt = select(User).where(User.user_identifier == user_identifier)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    if not user:
        user = User(user_identifier=user_identifier, question_count=0, word_count=0)
        session.add(user)
        await session.commit()
        await session.refresh(user)
    return user


async def initialize_application() -> None:
    """Initializes the application by setting up database tables and RAG application.

    This function creates necessary database tables and initializes the BossDBRAGApplication.
    It's called once at startup.

    Raises:
        Exception: If initialization fails
    """
    global app, max_questions, max_words
    try:
        logger.info("Loading configuration...")
        config = load_config()

        logger.info("Creating database tables...")
        await create_tables()
        logger.info("Database tables created successfully.")

        logger.info("Initializing BossDBRAGApplication...")
        app = BossDBRAGApplication(
            urls=config["sources"].get("urls", DEFAULT_CONFIG["sources"]["urls"]),
            orgs=config["sources"].get(
                "github_orgs", DEFAULT_CONFIG["sources"]["github_orgs"]
            ),
            llm=config["llm_config"].get(
                "default_llm", DEFAULT_CONFIG["llm_config"]["default_llm"]
            ),
            fast_llm=config["llm_config"].get(
                "fast_llm", DEFAULT_CONFIG["llm_config"]["fast_llm"]
            ),
            embed_model=config["llm_config"].get(
                "embed_model", DEFAULT_CONFIG["llm_config"]["embed_model"]
            ),
            aws_access_key_id=config["llm_config"]["aws_access_key_id"],
            aws_secret_access_key=config["llm_config"]["aws_secret_access_key"],
            aws_region=config["llm_config"].get(
                "aws_region", DEFAULT_CONFIG["llm_config"]["aws_region"]
            ),
            github_token=config["llm_config"].get("github_token"),
            max_total_tokens=config["limits"].get(
                "max_total_tokens", DEFAULT_CONFIG["limits"]["max_total_tokens"]
            ),
            max_message_tokens=config["limits"].get(
                "max_message_tokens", DEFAULT_CONFIG["limits"]["max_message_tokens"]
            ),
            force_reload=config.get("index_settings", {}).get(
                "force_reload", DEFAULT_CONFIG["index_settings"]["force_reload"]
            ),
            incremental=config.get("index_settings", {}).get(
                "incremental", DEFAULT_CONFIG["index_settings"]["incremental"]
            ),
        )
        max_questions = config["limits"].get(
            "max_questions", DEFAULT_CONFIG["limits"]["max_questions"]
        )
        max_words = config["limits"].get(
            "max_words", DEFAULT_CONFIG["limits"]["max_words"]
        )

        await app.setup()
        logger.info("BossDBRAGApplication initialized successfully.")
    except Exception as e:
        logger.error(f"Error during application initialization: {str(e)}")
        raise


@cl.set_starters
async def set_starters() -> List[cl.Starter]:
    """Sets up starter messages for the chat interface.

    Returns:
        List[cl.Starter]: A list of starter messages with predefined questions
    """
    return [
        cl.Starter(
            label="What is BossDB?",
            message="What is BossDB?",
        ),
        cl.Starter(
            label="BossDB Data Details",
            message="Why type of data does BossDB have?  ",
        ),
        cl.Starter(
            label="Downloading Neuron Mesh",
            message="How do I download a mesh of a specific neuron ID from BossDB?",
        ),
        cl.Starter(
            label="Find BossDB Channels",
            message="How do I find all the BossDB channels for a project?",
        ),
    ]


@cl.on_chat_start
async def start():
    """Initializes a new chat session.

    This function is called when a new chat session starts. It:
    - Initializes the application if not already initialized
    - Creates a query processor for the session
    - Generates and stores session identifiers
    - Creates database records for the new chat session

    Raises:
        Exception: If initialization fails
    """
    global app

    try:
        logger.info("Starting new chat session...")
        if app is None:
            await initialize_application()
        if app is None:
            raise Exception("Initialization of application failed.")

        query_processor = await app.create_query_processor()
        cl.user_session.set("query_processor", query_processor)

        session_id = generate_session_id()
        user_identifier = get_user_identifier(session_id)
        cl.user_session.set("user_identifier", user_identifier)

        async with AsyncSessionLocal() as session:
            user = await get_or_create_user(session, user_identifier)
            chat_thread = ChatThread(user_id=user.id)
            session.add(chat_thread)
            await session.commit()
            cl.user_session.set("chat_thread_id", chat_thread.id)

        log_user_activity(user_identifier, "Session Started")

        logger.info("Chat session initialized successfully")
    except Exception as e:
        error_message = f"Error initializing the application: {str(e)}"
        logger.error(error_message, exc_info=True)
        await cl.Message(content=error_message).send()


@cl.on_message
async def main(message: cl.Message):
    """Processes incoming chat messages and generates responses.

    This function handles the main chat interaction loop. It:
    - Validates the session state
    - Updates user statistics
    - Enforces usage limits
    - Processes the query
    - Stores chat history
    - Returns the response

    Args:
        message (cl.Message): The incoming chat message

    Returns:
        None: Sends response through chainlit's message system
    """
    query_processor = cl.user_session.get("query_processor")
    chat_thread_id = cl.user_session.get("chat_thread_id")
    user_identifier = cl.user_session.get("user_identifier")

    if not all([query_processor, chat_thread_id, user_identifier]):
        logger.error("Session not properly initialized")
        await cl.Message(
            content="Session not properly initialized. Please restart the chat."
        ).send()
        return

    user_query = message.content

    try:
        async with AsyncSessionLocal() as session:
            user = await get_or_create_user(session, user_identifier)

            user.question_count += 1
            user.word_count += len(user_query.split())
            user.last_activity = datetime.now(timezone.utc)

            if user.question_count > max_questions or user.word_count > max_words:
                limit_message = f"You have reached the usage limit. Maximum {max_questions} questions or {max_words} words allowed."
                logger.info(
                    f"User reached limit - Identifier: {user_identifier}, Questions: {user.question_count}, Words: {user.word_count}"
                )
                await cl.Message(content=limit_message).send()
                log_user_activity(user_identifier, "Limit Reached", limit_message)
                await session.commit()
                return

            user_message = Message(
                chat_thread_id=chat_thread_id, is_user=True, content=user_query
            )
            session.add(user_message)
            await session.commit()

    except SQLAlchemyError as e:
        logger.error(f"Database error: {str(e)}")
        await cl.Message(content="An error occurred. Please try again later.").send()
        return

    logger.info(
        f"Processing user query - Identifier: {user_identifier}, Query: {user_query}"
    )
    log_user_activity(
        user_identifier, "Query Sent", f"Word count: {len(user_query.split())}"
    )

    try:
        result = await query_processor.query(user_query)
        response_text = result["response"]
        sources = result["sources"]

        if len(sources) > 0:
            source_text = "\n\n**Sources:**\n"
            for source in sources:
                source_text += f"{source['number']}. {source['url']}\n"
                source_text += f"   Relevance score: {source['score']:.2f}\n"
        else:
            source_text = ""

        full_response = f"{response_text}\n{source_text}"

        async with AsyncSessionLocal() as session:
            assistant_message = Message(
                chat_thread_id=chat_thread_id, is_user=False, content=full_response
            )
            session.add(assistant_message)
            await session.commit()

        await cl.Message(content=full_response).send()

        log_user_activity(user_identifier, "Response Sent", f"Sources: {len(sources)}")

    except Exception as e:
        error_msg = f"Error processing query: {str(e)}"
        logger.error(error_msg, exc_info=True)
        await cl.Message(
            content="I encountered an error processing your query. Please try again."
        ).send()
        log_user_activity(user_identifier, "Error", error_msg)


@cl.on_chat_end
async def end():
    """Handles chat session cleanup when a session ends.

    This function:
    - Updates the chat thread end time in the database
    - Logs the session end event
    """
    user_identifier = cl.user_session.get("user_identifier", "Unknown")
    chat_thread_id = cl.user_session.get("chat_thread_id")

    if chat_thread_id:
        async with AsyncSessionLocal() as session:
            chat_thread = await session.get(ChatThread, chat_thread_id)
            if chat_thread:
                chat_thread.end_time = datetime.now(timezone.utc)
                await session.commit()

    log_user_activity(user_identifier, "Session Ended")


if __name__ == "__main__":
    cl.run()
