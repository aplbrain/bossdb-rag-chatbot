import asyncio
import logging
from motor.motor_asyncio import AsyncIOMotorClient
from tabulate import tabulate
from typing import List, Dict, Any
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


async def connect_db(
    uri: str = "mongodb://admin:password123@localhost:27017",
    db_name: str = "bossdb_rag",
) -> AsyncIOMotorClient:
    """Connect to MongoDB database."""
    try:
        client = AsyncIOMotorClient(uri)
        db = client[db_name]
        await db.command("ping")  # Test connection
        logger.info("Successfully connected to MongoDB")
        return db
    except Exception as e:
        logger.error(f"Failed to connect to MongoDB: {e}")
        raise


async def format_document(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Format MongoDB document for display."""
    formatted = {}
    for key, value in doc.items():
        if isinstance(value, datetime):
            formatted[key] = value.isoformat()
        elif isinstance(value, (dict, list)):
            formatted[key] = str(value)
        else:
            formatted[key] = value
    return formatted


async def view_collection(db, collection_name: str) -> None:
    """View and display contents of a collection."""
    try:
        total_count = await db[collection_name].count_documents({})
        print(f"\nCollection: {collection_name} (Total documents: {total_count})")

        cursor = db[collection_name].find().limit(5)
        documents = await cursor.to_list(length=5)

        if not documents:
            print("No documents found in collection")
            return

        formatted_docs = []
        headers = set()
        for doc in documents:
            formatted_doc = await format_document(doc)
            headers.update(formatted_doc.keys())
            formatted_docs.append(formatted_doc)

        rows = []
        headers = sorted(list(headers))
        for doc in formatted_docs:
            row = [doc.get(header, "") for header in headers]
            rows.append(row)

        print(tabulate(rows, headers=headers, tablefmt="grid"))

    except Exception as e:
        logger.error(f"Error viewing collection {collection_name}: {e}")


async def view_database(
    uri: str = "mongodb://admin:password123@localhost:27017",
    db_name: str = "bossdb_rag",
):
    """View the contents of all collections in the MongoDB database."""
    try:
        db = await connect_db(uri, db_name)

        print(f"\nDatabase: {db_name}")

        collections = await db.list_collection_names()

        if not collections:
            print("No collections found in database")
            return

        for collection_name in collections:
            await view_collection(db, collection_name)

    except Exception as e:
        logger.error(f"Error viewing database: {e}")
        raise
    finally:
        if "db" in locals():
            await db.client.close()


def main():
    """Main entry point for the database viewer."""
    try:
        asyncio.run(view_database())
    except Exception as e:
        logger.error(f"Failed to view database: {e}")
        raise


if __name__ == "__main__":
    main()
