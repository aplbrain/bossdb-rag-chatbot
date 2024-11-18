import logging
import json
import re
from typing import Dict, Any, Optional, List, Tuple
import tiktoken
from llama_index.core import VectorStoreIndex, Response
from llama_index.core.chat_engine import ContextChatEngine
from llama_index.core.memory import ChatSummaryMemoryBuffer, ChatMemoryBuffer
from llama_index.core.llms import LLM

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


class ToolManager:
    """Manages BossDB API tools and their execution."""

    def __init__(self):
        self.base_url = "https://api.metadata.bossdb.org/api/v2"
        self.tools = {
            "search_datasets": self._search_datasets,
            "list_collections": self._list_collections,
            "get_dataset_details": self._get_dataset_details,
            "search_publications": self._search_publications,
        }

    async def _make_request(
        self, endpoint: str, params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        import aiohttp

        url = f"{self.base_url}/{endpoint}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as response:
                response.raise_for_status()
                return await response.json()

    async def _search_datasets(self, query: str, limit: int = 5) -> Dict[str, Any]:
        return await self._make_request(
            "datasets", params={"search": query, "limit": limit}
        )

    async def _list_collections(self, limit: int = 10) -> Dict[str, Any]:
        return await self._make_request("collections", params={"limit": limit})

    async def _get_dataset_details(self, dataset_id: str) -> Dict[str, Any]:
        return await self._make_request(f"datasets/{dataset_id}")

    async def _search_publications(self, query: str, limit: int = 5) -> Dict[str, Any]:
        return await self._make_request(
            "publications", params={"search": query, "limit": limit}
        )

    def get_tool_descriptions(self) -> str:
        return """Available tools:
- search_datasets: Search for datasets based on keywords
- list_collections: List available collections in BossDB
- get_dataset_details: Get detailed information about a specific dataset
- search_publications: Search for publications related to datasets"""


class QueryProcessor:
    """Enhanced query processor that integrates chat with tool usage."""

    def __init__(
        self,
        index: VectorStoreIndex,
        llm: LLM,
        summarizer_llm: Optional[LLM] = None,
        conversation_token_limit: int = 8192,
        max_input_tokens: int = 4096,
    ):
        self.index = index
        self.llm = llm
        self.max_input_tokens = max_input_tokens
        self.tokenizer = tiktoken.get_encoding("cl100k_base")
        self.tool_manager = ToolManager()

        if summarizer_llm:
            self.memory = ChatSummaryMemoryBuffer.from_defaults(
                llm=summarizer_llm, token_limit=conversation_token_limit
            )
        else:
            self.memory = ChatMemoryBuffer.from_defaults(
                token_limit=conversation_token_limit,
            )

        system_prompt = f"""You are an AI assistant specialized in providing information about BossDB, 
        its tools, and related neuroscience data. You have access to both a knowledge base and real-time 
        API tools for querying BossDB metadata.

        {self.tool_manager.get_tool_descriptions()}

        When you need to use a tool, format your response as:
        TOOL_REQUEST: {{"tool": "tool_name", "params": {{"param1": "value1"}}}}

        After receiving tool results, provide a complete and coherent response incorporating both 
        the tool data and relevant context from the knowledge base."""

        self.chat_engine = self.index.as_chat_engine(
            chat_mode="context",
            llm=self.llm,
            memory=self.memory,
            system_prompt=system_prompt,
            verbose=True,
        )

    async def _process_tool_request(
        self, response: str
    ) -> Tuple[Optional[Dict[str, Any]], str]:
        """Extract and process tool request from response if present."""
        tool_match = re.search(r"TOOL_REQUEST: ({.*})", response)
        if not tool_match:
            return None, response

        try:
            tool_request = json.loads(tool_match.group(1))
            tool_name = tool_request.get("tool")
            params = tool_request.get("params", {})

            if tool_name not in self.tool_manager.tools:
                return None, response

            tool_result = await self.tool_manager.tools[tool_name](**params)
            return tool_result, response
        except Exception as e:
            logger.error(f"Error processing tool request: {str(e)}")
            return None, response

    async def _get_final_response(
        self, initial_response: str, tool_result: Optional[Dict[str, Any]]
    ) -> Response:
        """Get final response incorporating tool results if available."""
        if not tool_result:
            return initial_response

        # Remove the tool request from the initial response
        clean_response = re.sub(r"TOOL_REQUEST: {.*}", "", initial_response).strip()

        # Create a follow-up prompt incorporating tool results
        follow_up = f"""Based on the initial response:
{clean_response}

And the tool results:
{json.dumps(tool_result, indent=2)}

Please provide a complete and coherent response incorporating both the tool data and the context."""

        final_response = await self.chat_engine.achat(follow_up)
        return final_response

    def _count_tokens(self, text: str) -> int:
        return len(self.tokenizer.encode(text))

    async def query(self, user_query: str) -> Dict[str, Any]:
        """Process user query with integrated tool usage."""
        try:
            token_count = self._count_tokens(user_query)
            if token_count > self.max_input_tokens:
                return {
                    "response": "I apologize, but your input is too long. Please provide a shorter query.",
                    "sources": [],
                    "tool_usage": None,
                }

            # Get initial response that might include tool request
            initial_response = await self.chat_engine.achat(user_query)

            # Process any tool requests
            tool_result, clean_response = await self._process_tool_request(
                str(initial_response)
            )

            # Get final response incorporating tool results if necessary
            final_response = await self._get_final_response(clean_response, tool_result)

            # Process sources
            source_nodes = getattr(final_response, "source_nodes", [])
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
                    "score": float(node.score) if node.score else None,
                }
                sources.append(source_info)

            return {
                "response": str(final_response),
                "sources": sources,
                "tool_usage": {
                    "tool_used": bool(tool_result),
                    "tool_result": tool_result,
                }
                if tool_result
                else None,
            }

        except Exception as e:
            logger.error(f"Error processing query: {str(e)}", exc_info=True)
            raise
