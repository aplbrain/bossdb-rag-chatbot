import base64
import asyncio
import logging
import requests
from typing import List, Optional
from urllib.parse import urlparse
from pathlib import Path
import tempfile
import json
import nbformat
from bs4 import BeautifulSoup
from llama_index.core import Document
from llama_index.readers.web import SimpleWebPageReader
from llama_index.readers.github import GithubRepositoryReader, GithubClient
from llama_index.readers.json import JSONReader
from llama_index.readers.file import IPYNBReader

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


class DataLoader:
    """A versatile data loader for processing content from various sources.

    This class handles loading and processing data from different sources including GitHub
    repositories, JSON APIs, Jupyter notebooks, and web pages. It supports various file
    formats and content types, converting them into Document objects for further processing.

    Attributes:
        urls (List[str]): List of URLs to process
        orgs (List[str]): List of GitHub organizations to process
        documents (List[Document]): Collected documents after processing
        github_client (Optional[GithubClient]): GitHub client for repository access
        temp_dir (str): Temporary directory path for file processing
    """

    def __init__(
        self, urls: List[str], orgs: List[str], github_token: Optional[str] = None
    ):
        """Initialize the DataLoader with URLs and GitHub configuration.

        Args:
            urls (List[str]): List of URLs to process
            orgs (List[str]): List of GitHub organizations to process
            github_token (Optional[str], optional): GitHub access token for API access.
                                                    Defaults to None.
        """
        self.urls = urls
        self.orgs = orgs
        self.documents: List[Document] = []
        if github_token is None:
            self.github_client = None
        else:
            self.github_client = GithubClient(github_token)
            self.github_client._endpoints["getRepos"] = "/users/{owner}/repos"
            self.github_client._endpoints[
                "getRepoContent"
            ] = "/repos/{owner}/{repo}/contents/{path}"
        self.temp_dir = tempfile.mkdtemp()

    async def load_all_data(self) -> List[Document]:
        """Load and process data from all configured sources asynchronously.

        Processes all URLs and GitHub organizations concurrently, handling any errors
        that occur during processing of individual sources.

        Returns:
            List[Document]: List of processed documents from all sources.
        """
        tasks = [self.process_url(url) for url in self.urls]
        tasks += [self.load_org_readmes(org) for org in self.orgs]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, List) and result:
                self.documents.extend(result)
            elif isinstance(result, Exception):
                logging.error(f"Error processing URL: {result}")
        return self.documents

    async def process_url(self, url: str) -> List[Document]:
        """Process a single URL based on its type and content.

        Routes the URL to appropriate processor based on its type (GitHub, JSON,
        notebook, or webpage).

        Handles GitHub URLs differently based on their pattern:
        - blob: Single file
        - wiki: Wiki pages
        - tree: Directory
        - others: Entire repository

        Args:
            url (str): URL to process

        Returns:
            List[Document]: List of processed documents from the URL.
        """
        try:
            parsed_url = urlparse(url)

            if parsed_url.hostname == "github.com":
                return await self.process_github_url(url)

            if url.endswith(".json") or "api" in url.lower():
                return await self.process_json_url(url)

            if url.endswith(".ipynb"):
                return await self.process_notebook_url(url)

            return await self.process_webpage(url)
        except Exception as e:
            logging.error(f"Error processing URL {url}: {str(e)}", exc_info=True)
            return []

    async def process_github_url(self, url: str) -> List[Document]:
        """Process GitHub repository URLs with enhanced handling of different URL patterns.

        Args:
            url (str): GitHub URL to process

        Returns:
            List[Document]: Processed documents from the GitHub source

        Raises:
            ValueError: If GitHub token is required but not provided
        """
        if not self.github_client:
            logging.warning("GitHub token not provided. Falling back to web scraping.")
            return await self.process_webpage(url)

        try:
            parts = url.split("github.com/")[1].split("/")
            owner, repo = parts[0], parts[1]

            if "blob" in url:
                return await self._process_github_blob(url, owner, repo, parts)
            elif "wiki" in url:
                return await self._process_github_wiki(url, owner, repo)
            elif "tree" in url:
                return await self._process_github_tree(url, owner, repo, parts)
            else:
                return await self._process_github_repo(url, owner, repo)

        except Exception as e:
            logging.error(f"Error processing GitHub URL {url}: {e}")
            return []

    async def _process_github_blob(
        self, url: str, owner: str, repo: str, parts: List[str]
    ) -> List[Document]:
        """Process a single file from GitHub repository.

        Args:
            url (str): Original GitHub URL
            owner (str): Repository owner
            repo (str): Repository name
            parts (List[str]): URL parts for path construction

        Returns:
            List[Document]: Processed documents from the file
        """
        file_path = "/".join(parts[4:])
        raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/master/{file_path}"
        documents = await self.process_url(raw_url)
        for doc in documents:
            doc.metadata = doc.metadata or {}
            doc.metadata.update(
                {
                    "url": url,
                    "source_type": "github_blob",
                    "file_path": file_path,
                    "owner": owner,
                    "repo": repo,
                }
            )
        return documents

    async def _process_github_wiki(
        self, url: str, owner: str, repo: str
    ) -> List[Document]:
        """Process GitHub wiki pages.

        Args:
            url (str): Wiki URL
            owner (str): Repository owner
            repo (str): Repository name

        Returns:
            List[Document]: Processed documents from all wiki pages
        """
        wiki_docs = []
        main_page_docs = await self.process_webpage(url)
        wiki_docs.extend(main_page_docs)

        response = await self._async_get(url)
        soup = BeautifulSoup(response.text, "html.parser")
        wiki_links = set(
            [
                f"https://github.com{a['href']}"
                for a in soup.find_all("a", href=True)
                if "/wiki/" in a["href"]
                and not a["href"].startswith("http")
                and not a["href"].endswith("/_history")
                and not a["href"].endswith("/_edit")
            ]
        )

        for wiki_link in wiki_links:
            try:
                page_docs = await self.process_webpage(wiki_link)
                for doc in page_docs:
                    doc.metadata = doc.metadata or {}
                    doc.metadata.update(
                        {
                            "url": wiki_link,
                            "source_type": "github_wiki",
                            "owner": owner,
                            "repo": repo,
                        }
                    )
                wiki_docs.extend(page_docs)
            except Exception as e:
                logging.error(f"Error processing wiki page {wiki_link}: {e}")

        return wiki_docs

    async def _process_github_tree(
        self, url: str, owner: str, repo: str, parts: List[str]
    ) -> List[Document]:
        """Process a GitHub repository directory.

        Args:
            url (str): Directory URL
            owner (str): Repository owner
            repo (str): Repository name
            parts (List[str]): URL parts for path construction

        Returns:
            List[Document]: Processed documents from the directory
        """
        target_dir = "/".join(parts[4:])
        reader = GithubRepositoryReader(
            github_client=self.github_client,
            owner=owner,
            repo=repo,
            filter_directories=(
                [target_dir],
                GithubRepositoryReader.FilterType.INCLUDE,
            ),
            filter_file_extensions=(
                [".md", ".py", ".ipynb", ".json"],
                GithubRepositoryReader.FilterType.INCLUDE,
            ),
            verbose=False,
            concurrent_requests=10,
        )
        try:
            docs = await reader.aload_data(branch="main")
        except:
            docs = await reader.aload_data(branch="master")
        for doc in docs:
            doc.metadata = doc.metadata or {}
            doc.metadata.update(
                {
                    "url": url,
                    "source_type": "github_directory",
                    "owner": owner,
                    "repo": repo,
                    "file_path": doc.metadata.get("file_path", ""),
                }
            )
        return docs

    async def _process_github_repo(
        self, url: str, owner: str, repo: str
    ) -> List[Document]:
        """Process an entire GitHub repository.

        Args:
            url (str): Repository URL
            owner (str): Repository owner
            repo (str): Repository name

        Returns:
            List[Document]: Processed documents from the repository
        """
        reader = GithubRepositoryReader(
            github_client=self.github_client,
            owner=owner,
            repo=repo,
            filter_file_extensions=(
                [".md", ".py", ".ipynb", ".json"],
                GithubRepositoryReader.FilterType.INCLUDE,
            ),
            verbose=False,
            concurrent_requests=10,
        )
        try:
            docs = await reader.aload_data(branch="main")
        except:
            docs = await reader.aload_data(branch="master")
        for doc in docs:
            doc.metadata = doc.metadata or {}
            doc.metadata.update(
                {
                    "url": url,
                    "source_type": "github_repo",
                    "owner": owner,
                    "repo": repo,
                    "file_path": doc.metadata.get("file_path", ""),
                }
            )
        return docs

    async def process_json_url(self, url: str) -> List[Document]:
        """Process JSON content from URLs.

        Args:
            url (str): URL to JSON content

        Returns:
            List[Document]: Processed documents from JSON content

        Note:
            Creates a temporary file for processing and cleans up afterward.
        """
        try:
            response = await self._async_get(url)
            json_content = response.json()

            temp_file = Path(self.temp_dir) / f"temp_{hash(url)}.json"
            with open(temp_file, "w") as f:
                json.dump(json_content, f)

            reader = JSONReader()
            documents = reader.load_data(temp_file)

            for doc in documents:
                doc.metadata = doc.metadata or {}
                doc.metadata.update(
                    {"url": url, "file_path": str(temp_file), "source_type": "json"}
                )

            temp_file.unlink()

            return documents

        except Exception as e:
            logging.error(f"Error processing JSON from {url}: {e}")
            return []

    async def process_notebook_url(self, url: str) -> List[Document]:
        """Process Jupyter notebook content.

        Creates a temporary file for processing and cleans up afterward.

        Args:
            url (str): URL to Jupyter notebook

        Returns:
            List[Document]: Processed documents from notebook content
        """
        try:
            response = await self._async_get(url)
            notebook_content = response.json()

            temp_file = Path(self.temp_dir) / f"temp_{hash(url)}.ipynb"
            with open(temp_file, "w") as f:
                nbformat.write(notebook_content, f)

            reader = IPYNBReader()
            documents = reader.load_data(temp_file)

            for doc in documents:
                doc.metadata = doc.metadata or {}
                doc.metadata.update(
                    {"url": url, "file_path": str(temp_file), "source_type": "notebook"}
                )

            temp_file.unlink()

            return documents

        except Exception as e:
            logging.error(f"Error processing notebook from {url}: {e}")
            return []

    async def process_webpage(self, url: str) -> List[Document]:
        """Process regular webpage content.

        Args:
            url (str): Webpage URL

        Returns:
            List[Document]: Processed documents from webpage content
        """
        try:
            # Currently does not support live pages, aka JS created like most of the BossDB website
            reader = SimpleWebPageReader(html_to_text=True)
            documents = await reader.aload_data([url])

            for doc in documents:
                doc.metadata = doc.metadata or {}
                doc.metadata.update({"url": url, "source_type": "webpage"})

            return documents

        except Exception as e:
            logging.error(f"Error processing webpage {url}: {e}")
            return []

    async def _async_get(self, url: str) -> requests.Response:
        """Make async HTTP GET request.

        Args:
            url (str): URL to fetch

        Returns:
            requests.Response: Response from the request

        Raises:
            requests.exceptions.RequestException: If the request fails
        """
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, requests.get, url)
        response.raise_for_status()
        return response

    async def load_org_readmes(self, org_name: str) -> List[Document]:
        """Load README files from all public repositories in a GitHub organization.

        Args:
            org_name (str): The name of the GitHub organization

        Returns:
            List[Document]: List of processed README documents

        Raises:
            ValueError: If GitHub token is not provided
        """
        if not self.github_client:
            raise ValueError("GitHub token required to fetch organization repositories")

        retries = 0
        timeout = 5

        repos_response = await self.github_client.request(
            "getRepos",
            "GET",
            owner=org_name,
            timeout=timeout,
            retries=retries,
        )

        documents = []
        if repos_response.status_code == 200:
            for repo in repos_response.json():
                try:
                    repo_name = repo["name"]
                    readme_response = await self.github_client.request(
                        "getRepoContent",
                        "GET",
                        owner=org_name,
                        repo=repo_name,
                        path="README.md",
                        timeout=timeout,
                        retries=retries,
                    )

                    if readme_response.status_code == 200:
                        readme_data = readme_response.json()
                        if readme_data.get("sha"):
                            blob = await self.github_client.get_blob(
                                owner=org_name,
                                repo=repo_name,
                                file_sha=readme_data["sha"],
                                timeout=timeout,
                                retries=retries,
                            )

                        if blob and blob.content:
                            content = base64.b64decode(blob.content).decode("utf-8")
                            branch = repo.get("default_branch", "master")
                            metadata = {
                                "source": "github",
                                "source_type": "readme",
                                "organization": org_name,
                                "repository": repo_name,
                                "repository_url": repo["html_url"],
                                "repository_description": repo.get("description", ""),
                                "repository_created_at": repo.get("created_at", ""),
                                "repository_updated_at": repo.get("updated_at", ""),
                                "repository_stars": repo.get("stargazers_count", 0),
                                "repository_forks": repo.get("forks_count", 0),
                                "repository_language": repo.get("language", ""),
                                "repository_topics": repo.get("topics", []),
                                "repository_visibility": repo.get("visibility", ""),
                                "readme_sha": readme_data["sha"],
                                "file_path": "README.md",
                                "url": f"https://github.com/{org_name}/{repo_name}/blob/{branch}/README.md",
                            }
                            document = Document(
                                text=content,
                                metadata=metadata,
                                id_=f"github_readme_{org_name}_{repo_name}_{readme_data['sha'][:8]}",
                            )

                            documents.append(document)
                except Exception as e:
                    logging.error(f"Error fetching README for {repo_name}: {str(e)}")
                    continue

        return documents

    def cleanup(self) -> None:
        """Cleans up temporary files and directories created during data processing.

        Raises:
            None: Errors are caught and logged but not raised to prevent interruption
                  of the cleanup process
        """
        try:
            import shutil

            shutil.rmtree(self.temp_dir)
        except Exception as e:
            logging.error(f"Error cleaning up temporary files: {e}")
