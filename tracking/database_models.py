from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId
from typing import Optional, List, Dict, Any
import datetime
import logging
from datetime import datetime, timezone

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


class DatabaseManager:
    """
    Singleton database manager to handle MongoDB connections and operations.
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(DatabaseManager, cls).__new__(cls)
            cls._instance.initialized = False
        return cls._instance

    async def initialize(
        self, uri: str = "mongodb://localhost:27017", db_name: str = "bossdb_rag"
    ):
        """Initialize MongoDB connection."""
        if not self.initialized:
            try:
                self.client = AsyncIOMotorClient(uri)
                self.db = self.client[db_name]
                # Create indexes
                await self.db.users.create_index("user_identifier", unique=True)
                await self.db.chat_threads.create_index("user_id")
                await self.db.messages.create_index("chat_thread_id")
                self.initialized = True
                logger.info("MongoDB connection initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize MongoDB connection: {e}")
                raise

    async def close(self):
        """Close MongoDB connection."""
        if hasattr(self, "client"):
            self.client.close()
            self.initialized = False


class User:
    """User model for MongoDB."""

    @staticmethod
    async def create_or_get(user_identifier: str) -> Dict[str, Any]:
        """Create a new user or get existing one."""
        db = DatabaseManager().db
        user = await db.users.find_one({"user_identifier": user_identifier})

        if not user:
            user = {
                "user_identifier": user_identifier,
                "question_count": 0,
                "word_count": 0,
                "created_at": datetime.now(timezone.utc),
                "last_activity": datetime.now(timezone.utc),
            }
            result = await db.users.insert_one(user)
            user["_id"] = result.inserted_id

        return user

    @staticmethod
    async def update_activity(user_id: ObjectId, question_length: int) -> None:
        """Update user activity metrics."""
        db = DatabaseManager().db
        await db.users.update_one(
            {"_id": user_id},
            {
                "$inc": {"question_count": 1, "word_count": question_length},
                "$set": {"last_activity": datetime.now(timezone.utc)},
            },
        )

    @staticmethod
    async def get_usage_stats(user_id: ObjectId) -> Dict[str, int]:
        """Get user usage statistics."""
        db = DatabaseManager().db
        user = await db.users.find_one({"_id": user_id})
        return {
            "question_count": user.get("question_count", 0),
            "word_count": user.get("word_count", 0),
        }


class ChatThread:
    """Chat thread model for MongoDB."""

    @staticmethod
    async def create(user_id: ObjectId) -> str:
        """Create a new chat thread."""
        db = DatabaseManager().db
        thread = {
            "user_id": user_id,
            "start_time": datetime.now(timezone.utc),
            "end_time": None,
        }
        result = await db.chat_threads.insert_one(thread)
        return str(result.inserted_id)

    @staticmethod
    async def end(thread_id: str) -> None:
        """Mark a chat thread as ended."""
        db = DatabaseManager().db
        await db.chat_threads.update_one(
            {"_id": ObjectId(thread_id)},
            {"$set": {"end_time": datetime.now(timezone.utc)}},
        )

    @staticmethod
    async def get_messages(thread_id: str) -> List[Dict[str, Any]]:
        """Get all messages in a thread."""
        db = DatabaseManager().db
        cursor = db.messages.find({"chat_thread_id": ObjectId(thread_id)}).sort(
            "timestamp", 1
        )
        return await cursor.to_list(length=None)


class Message:
    """Message model for MongoDB."""

    @staticmethod
    async def create(thread_id: str, content: str, is_user: bool) -> str:
        """Create a new message."""
        db = DatabaseManager().db
        message = {
            "chat_thread_id": ObjectId(thread_id),
            "content": content,
            "is_user": is_user,
            "timestamp": datetime.now(timezone.utc),
        }
        result = await db.messages.insert_one(message)
        return str(result.inserted_id)


# Initialize database connection
async def initialize_database(
    uri: str = "mongodb://localhost:27017", db_name: str = "bossdb_rag"
):
    """Initialize the database connection."""
    db_manager = DatabaseManager()
    await db_manager.initialize(uri, db_name)


async def cleanup_database():
    """Cleanup database connections."""
    db_manager = DatabaseManager()
    await db_manager.close()
