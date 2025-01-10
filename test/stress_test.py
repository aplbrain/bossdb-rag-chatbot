import asyncio
import time
import logging
from datetime import datetime
from typing import List, Dict, Any
import aiohttp
import pandas as pd
from playwright.async_api import async_playwright
import argparse
from collections import defaultdict
import numpy as np

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("stress_test.log"), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


class ChatSession:
    def __init__(self, base_url: str, session_id: int):
        self.base_url = base_url
        self.session_id = session_id
        self.metrics = []
        self.start_time = None
        self.end_time = None

    async def setup(self):
        """Initialize the browser session."""
        try:
            self.start_time = time.time()
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch()
            self.context = await self.browser.new_context()
            self.page = await self.context.new_page()

            # Add event listeners for network activity
            self.page.on(
                "request",
                lambda req: logger.debug(
                    f"Session {self.session_id} request: {req.url}"
                ),
            )
            self.page.on(
                "response",
                lambda res: logger.debug(
                    f"Session {self.session_id} response: {res.url} ({res.status})"
                ),
            )

            await self.page.goto(self.base_url)
            await asyncio.sleep(2)  # Wait for initial load
            logger.info(f"Session {self.session_id} setup complete")
        except Exception as e:
            logger.error(f"Session {self.session_id} setup error: {str(e)}")
            raise

    async def ask_question(self, question: str, question_index: int) -> Dict[str, Any]:
        """Ask a question and return metrics."""
        start_time = time.time()
        metrics = {
            "session_id": self.session_id,
            "question_index": question_index,
            "question": question,
            "timestamp": datetime.now(),
            "success": False,
            "error": None,
        }

        try:
            # Find and click the input field
            await self.page.get_by_role("textbox").click()
            await self.page.get_by_role("textbox").fill(question)
            await self.page.get_by_role("textbox").press("Enter")

            # Wait for response
            await self.page.wait_for_selector(".message-avatar", timeout=120000)
            response_text = await self.page.locator(
                ".message-avatar"
            ).last.text_content()

            metrics.update(
                {
                    "success": True,
                    "response_length": len(response_text),
                    "response_text": response_text[
                        :200
                    ],  # Store first 200 chars for analysis
                }
            )

        except Exception as e:
            error_msg = str(e)
            logger.error(
                f"Session {self.session_id} error on question {question_index}: {error_msg}"
            )
            metrics["error"] = error_msg
            response_text = "ERROR"

        metrics["duration"] = time.time() - start_time
        self.metrics.append(metrics)

        # Log progress
        logger.info(
            f"Session {self.session_id} - Question {question_index + 1} completed in {metrics['duration']:.2f}s"
        )

        return metrics

    async def cleanup(self):
        """Clean up browser resources."""
        try:
            await self.context.close()
            await self.browser.close()
            await self.playwright.stop()
            self.end_time = time.time()
            logger.info(f"Session {self.session_id} cleanup complete")
        except Exception as e:
            logger.error(f"Session {self.session_id} cleanup error: {str(e)}")

    @property
    def session_duration(self) -> float:
        """Calculate total session duration."""
        if self.start_time and self.end_time:
            return self.end_time - self.start_time
        return 0


async def run_session(
    base_url: str, session_id: int, questions: List[str]
) -> List[Dict[str, Any]]:
    """Run a single chat session."""
    session = ChatSession(base_url, session_id)
    try:
        await session.setup()
        for i, question in enumerate(questions):
            await session.ask_question(question, i)
            await asyncio.sleep(1)  # Brief pause between questions
        await session.cleanup()

        # Add session-level metrics
        for metric in session.metrics:
            metric["session_duration"] = session.session_duration

        return session.metrics
    except Exception as e:
        logger.error(f"Session {session_id} failed: {str(e)}")
        return []


def calculate_concurrent_sessions(df: pd.DataFrame) -> int:
    """Calculate the maximum number of concurrent sessions."""
    # Create a list of session start and end times
    events = []
    for session_id in df["session_id"].unique():
        session_data = df[df["session_id"] == session_id]
        start = session_data["timestamp"].min()
        end = session_data["timestamp"].max()
        events.append((start.timestamp(), 1))  # Session start
        events.append((end.timestamp(), -1))  # Session end

    # Sort events by timestamp
    events.sort()

    # Calculate maximum concurrent sessions
    current = max_concurrent = 0
    for _, change in events:
        current += change
        max_concurrent = max(max_concurrent, current)

    return max_concurrent


async def main(base_url: str, questions: List[str], num_sessions: int):
    """Run the stress test with multiple concurrent sessions."""
    start_time = time.time()

    logger.info(f"Starting stress test with {num_sessions} concurrent sessions")
    logger.info(f"Questions to ask: {questions}")

    # Create and run concurrent sessions
    tasks = [
        run_session(base_url, session_id, questions)
        for session_id in range(num_sessions)
    ]

    # Gather results with timeout handling
    all_metrics = []
    results = await asyncio.gather(*tasks, return_exceptions=True)
    end_time = time.time()

    # Process results
    active_sessions = 0
    for session_metrics in results:
        if isinstance(session_metrics, Exception):
            logger.error(f"Session error: {str(session_metrics)}")
        else:
            all_metrics.extend(session_metrics)
            active_sessions += 1

    # Create DataFrame and calculate statistics
    df = pd.DataFrame(all_metrics)

    # Group metrics by session_id to verify concurrency
    session_timings = df.groupby("session_id").agg(
        {"timestamp": ["min", "max"], "duration": ["count", "mean", "max"]}
    )

    # Calculate concurrent sessions
    max_concurrent = calculate_concurrent_sessions(df)

    # Calculate comprehensive statistics
    stats = {
        "total_requests": len(df),
        "active_sessions": active_sessions,
        "max_concurrent_sessions": max_concurrent,
        "success_rate": (df["success"].mean() * 100),
        "avg_duration": df["duration"].mean(),
        "p50_duration": df["duration"].quantile(0.5),
        "p95_duration": df["duration"].quantile(0.95),
        "p99_duration": df["duration"].quantile(0.99),
        "max_duration": df["duration"].max(),
        "total_duration": end_time - start_time,
        "responses_per_second": len(df) / (end_time - start_time),
    }

    # Save detailed results
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    df.to_csv(f"stress_test_results_{timestamp}.csv", index=False)

    # Save session timing analysis
    session_timings.to_csv(f"session_timings_{timestamp}.csv")

    # Print comprehensive report
    print("\nTest Results:")
    print(f"Total Requests: {stats['total_requests']}")
    print(f"Active Sessions: {stats['active_sessions']} of {num_sessions} attempted")
    print(f"Maximum Concurrent Sessions: {stats['max_concurrent_sessions']}")
    print(f"Success Rate: {stats['success_rate']:.2f}%")
    print(f"Responses per Second: {stats['responses_per_second']:.2f}")
    print("\nResponse Times:")
    print(f"Average: {stats['avg_duration']:.2f}s")
    print(f"Median (P50): {stats['p50_duration']:.2f}s")
    print(f"95th Percentile: {stats['p95_duration']:.2f}s")
    print(f"99th Percentile: {stats['p99_duration']:.2f}s")
    print(f"Maximum: {stats['max_duration']:.2f}s")
    print(f"\nTotal Test Duration: {stats['total_duration']:.2f}s")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run stress test for BossDB RAG")
    parser.add_argument("url", help="URL of the server")
    parser.add_argument(
        "--sessions", type=int, default=5, help="Number of concurrent sessions"
    )
    parser.add_argument(
        "--questions",
        type=str,
        nargs="+",
        default=[
            "What is BossDB?",
            # "How do I download data from BossDB?",
            # "What type of data is stored in BossDB?",
            # "How do I find a specific dataset?",
        ],
        help="List of questions to ask",
    )

    args = parser.parse_args()
    asyncio.run(main(args.url, args.questions, args.sessions))
