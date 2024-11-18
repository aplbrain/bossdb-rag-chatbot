import logging
import json
from typing import Dict, Any, Optional
import tiktoken
from llama_index.core import VectorStoreIndex
from llama_index.core.chat_engine import ContextChatEngine
from llama_index.core.memory import ChatSummaryMemoryBuffer, ChatMemoryBuffer
from llama_index.core.llms import LLM

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


class QueryProcessor:
    """Class to process user queries against the index with memory."""

    def __init__(
        self,
        index: VectorStoreIndex,
        llm: LLM,
        summarizer_llm: Optional[LLM] = None,
        conversation_token_limit: int = 8192,
        max_input_tokens: int = 4096,
    ):
        """Initialize the query processor.

        Args:
            index: The VectorStoreIndex to query against
            summarizer_llm: Optional LLM for summarization. If None, uses windowed memory
            conversation_token_limit: Maximum number of tokens to maintain in memory
            max_input_tokens: Maximum number of tokens allowed in a single query
        """
        self.index = index
        self.llm = llm
        self.max_input_tokens = max_input_tokens
        self.tokenizer = tiktoken.get_encoding("cl100k_base")  # Default OpenAI encoding

        if summarizer_llm:
            logger.info("Initializing with ChatSummaryMemoryBuffer")
            self.memory = ChatSummaryMemoryBuffer.from_defaults(
                llm=summarizer_llm, token_limit=conversation_token_limit
            )
            memory_type = "summary"
        else:
            logger.info(f"No summarizer provided, initializing with ChatMemoryBuffer")
            self.memory = ChatMemoryBuffer.from_defaults(
                token_limit=conversation_token_limit,
            )
            memory_type = "window"

        system_prompt = (
            "You are an AI assistant specialized in providing information about BossDB, "
            "its tools, and related neuroscience data. Use the context provided to answer "
            "questions accurately. If you're unsure about something, please say so. "
        )

        if memory_type == "summary":
            system_prompt += "Previous conversation context will be provided as summaries when relevant."
        else:
            system_prompt += f"Previous conversation context will be dropped when it is old. Most recent messages will be maintained for context."

        self.chat_engine = self.index.as_chat_engine(
            chat_mode="context",
            llm=self.llm,
            memory=self.memory,
            system_prompt=system_prompt,
            verbose=True,
        )

    def _count_tokens(self, text: str) -> int:
        """Count the number of tokens in the input text."""
        return len(self.tokenizer.encode(text))

    async def query(self, user_query: str) -> Dict[str, Any]:
        """Query the index with chat history and return the response with detailed sources."""
        try:
            # Check token count
            token_count = self._count_tokens(user_query)
            if token_count > self.max_input_tokens:
                logger.warning(f"Query exceeds token limit: {token_count} tokens")
                return {
                    "response": "I apologize, but your input is too long. Please provide a shorter query (maximum 4096 tokens).",
                    "sources": [],
                    "memory_state": {
                        "type": "summary"
                        if isinstance(self.memory, ChatSummaryMemoryBuffer)
                        else "window",
                        "message_count": len(self.memory.get()),
                        "has_summary": isinstance(self.memory, ChatSummaryMemoryBuffer)
                        and any(msg.role == "system" for msg in self.memory.get()),
                    },
                }

            response = await self.chat_engine.achat(user_query)
            source_nodes = response.source_nodes
            sources = []

            for idx, node in enumerate(source_nodes, 1):
                metadata = node.metadata
                source_info = {
                    "number": idx,
                    "text": node.text[:200] + "..."
                    if len(node.text) > 200
                    else node.text,
                    "url": metadata.get("url", "Unknown source"),
                    "source_type": metadata.get("source_type", "Unknown type"),
                    "timestamp": metadata.get("timestamp", "Unknown time"),
                    "file_path": metadata.get("file_path", ""),
                    "score": float(node.score) if node.score else None,
                }

                if metadata.get("source_type") == "github":
                    source_info["github_info"] = {
                        "owner": metadata.get("owner", ""),
                        "repo": metadata.get("repo", ""),
                        "type": metadata.get("type", ""),
                    }

                sources.append(source_info)
                logging.info(
                    f"Source {idx} metadata: {json.dumps(source_info, indent=2)}"
                )

            current_memory = self.memory.get()
            memory_type = (
                "summary"
                if isinstance(self.memory, ChatSummaryMemoryBuffer)
                else "window"
            )

            for mem in current_memory:
                print(mem)

            logger.info(
                f"Current memory state ({memory_type}): {len(current_memory)} messages"
            )
            if current_memory and memory_type == "summary":
                logger.info(
                    f"Memory summary: {current_memory[0].content if current_memory[0].role == 'system' else 'No summary yet'}"
                )

            return {
                "response": str(response),
                "sources": sources,
                "memory_state": {
                    "type": memory_type,
                    "message_count": len(current_memory),
                    "has_summary": memory_type == "summary"
                    and any(msg.role == "system" for msg in current_memory),
                },
            }

        except Exception as e:
            logger.error(f"Error processing query: {str(e)}", exc_info=True)
            raise
