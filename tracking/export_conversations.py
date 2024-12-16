import asyncio
import argparse
import json
from datetime import datetime, timezone
import logging
from motor.motor_asyncio import AsyncIOMotorClient
from typing import List, Dict, Any
from bson import ObjectId

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


class DateTimeEncoder(json.JSONEncoder):
    """Custom JSON encoder to handle datetime and ObjectId objects."""

    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, ObjectId):
            return str(obj)
        return super().default(obj)


async def connect_db(
    uri: str = "mongodb://admin:password123@localhost:27017",
    db_name: str = "bossdb_rag",
) -> AsyncIOMotorClient:
    """Connect to MongoDB database."""
    try:
        client = AsyncIOMotorClient(uri)
        db = client[db_name]
        await db.command("ping")
        logger.info("Successfully connected to MongoDB")
        return db
    except Exception as e:
        logger.error(f"Failed to connect to MongoDB: {e}")
        raise


async def get_conversations(
    db, start_date: datetime, end_date: datetime
) -> List[Dict[str, Any]]:
    """Retrieve full conversations from MongoDB within the specified date range."""
    conversations = []

    try:
        thread_cursor = db.chat_threads.find(
            {"start_time": {"$gte": start_date, "$lte": end_date}}
        )

        async for thread in thread_cursor:
            thread_id = thread["_id"]

            user = await db.users.find_one({"_id": thread["user_id"]})

            messages = (
                await db.messages.find({"chat_thread_id": thread_id})
                .sort("timestamp", 1)
                .to_list(length=None)
            )

            conversation = {
                "thread_id": str(thread_id),
                "user_identifier": user["user_identifier"] if user else "unknown",
                "start_time": thread["start_time"],
                "end_time": thread.get("end_time"),
                "exchanges": [],
                "total_messages": len(messages),
            }

            current_exchange = None
            for idx, message in enumerate(messages):
                if message["is_user"]:
                    if current_exchange:
                        conversation["exchanges"].append(current_exchange)

                    current_exchange = {
                        "exchange_number": len(conversation["exchanges"]) + 1,
                        "timestamp": message["timestamp"],
                        "context": {
                            "previous_exchanges": len(conversation["exchanges"]),
                            "position_in_conversation": idx + 1,
                        },
                        "question": message["content"],
                        "answer": None,
                        "has_followup": False,
                    }
                elif current_exchange is not None:
                    current_exchange["answer"] = message["content"]

                    if idx < len(messages) - 1 and messages[idx + 1]["is_user"]:
                        current_exchange["has_followup"] = True

            if current_exchange:
                conversation["exchanges"].append(current_exchange)

            conversation["metrics"] = {
                "total_exchanges": len(conversation["exchanges"]),
                "total_messages": len(messages),
                "conversation_duration": (
                    (
                        thread.get("end_time", datetime.now(timezone.utc))
                        - thread["start_time"]
                    ).total_seconds()
                    if thread.get("end_time")
                    else None
                ),
            }

            conversations.append(conversation)

        return conversations

    except Exception as e:
        logger.error(f"Error retrieving conversations: {e}")
        raise


async def export_conversations(
    start_date_str: str, end_date_str: str, output_file: str
):
    """Export conversations to a JSON file."""
    try:
        start_date = datetime.fromisoformat(start_date_str.replace("Z", "+00:00"))
        end_date = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))

        db = await connect_db()

        conversations = await get_conversations(db, start_date, end_date)

        total_exchanges = sum(
            conv["metrics"]["total_exchanges"] for conv in conversations
        )
        total_messages = sum(
            conv["metrics"]["total_messages"] for conv in conversations
        )

        output_data = {
            "metadata": {
                "start_date": start_date,
                "end_date": end_date,
                "total_conversations": len(conversations),
                "total_exchanges": total_exchanges,
                "total_messages": total_messages,
                "export_time": datetime.now(timezone.utc),
            },
            "conversations": conversations,
        }

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(output_data, f, indent=2, cls=DateTimeEncoder)

        logger.info(
            f"Successfully exported {len(conversations)} conversations to {output_file}"
        )

        print(f"\nExport Summary:")
        print(f"Date Range: {start_date.date()} to {end_date.date()}")
        print(f"Total Conversations: {len(conversations)}")
        print(f"Total Exchanges: {total_exchanges}")
        print(f"Total Messages: {total_messages}")
        print(
            f"Average Exchanges per Conversation: {total_exchanges/len(conversations):.2f}"
        )
        print(f"Output File: {output_file}")

    except Exception as e:
        logger.error(f"Error exporting conversations: {e}")
        raise
    finally:
        if "db" in locals():
            await db.client.close()


def main():
    """Main entry point for the script."""
    parser = argparse.ArgumentParser(
        description="Export conversations from MongoDB within a date range."
    )
    parser.add_argument(
        "start_date",
        help="Start date in ISO format (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SSZ)",
    )
    parser.add_argument(
        "end_date", help="End date in ISO format (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SSZ)"
    )
    parser.add_argument(
        "--output",
        default="conversations.json",
        help="Output JSON file path (default: conversations.json)",
    )

    args = parser.parse_args()

    try:
        asyncio.run(export_conversations(args.start_date, args.end_date, args.output))
    except Exception as e:
        logger.error(f"Script execution failed: {e}")
        raise


if __name__ == "__main__":
    main()
