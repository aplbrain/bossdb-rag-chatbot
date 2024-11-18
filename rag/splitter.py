import os
from typing import List
from llama_index.core import Document
from llama_index.core.node_parser import (
    CodeSplitter,
    MarkdownNodeParser,
    SentenceSplitter,
    JSONNodeParser,
)


class Splitter:
    """A document splitter that handles different file types with appropriate parsing strategies.

    This class provides functionality to split documents into appropriate chunks based on their
    file type (Python code, Markdown, JSON, Jupyter notebooks, or plain text). It uses specialized
    splitters for each file type to ensure optimal chunking for the document's content type.

    Attributes:
        code_splitter: Specialized splitter for Python code files
        markdown_splitter: Specialized splitter for Markdown files
        json_splitter: Specialized splitter for JSON files
        text_splitter: Generic splitter for plain text using sentence boundaries
    """

    def __init__(self):
        """Initializes the Splitter with specialized parsers for different file types.

        Sets up four different types of splitters:
        - CodeSplitter for Python files and Jupyter notebooks
        - MarkdownNodeParser for Markdown files
        - JSONNodeParser for JSON files
        - SentenceSplitter for generic text content
        """
        self.code_splitter = CodeSplitter(language="python")
        self.markdown_splitter = MarkdownNodeParser()
        self.json_splitter = JSONNodeParser()
        self.text_splitter = SentenceSplitter(chunk_size=1024, chunk_overlap=20)

    def split(self, document: Document) -> List[Document]:
        """Splits a document into chunks based on its file type.

        Determines the appropriate splitter based on the document's file extension
        and applies it to break the document into logical chunks. Different file types
        are handled with specialized splitters to maintain context and structure.

        Args:
            document (Document): The document to be split. Should have metadata containing
                                 file_path or similar information to determine its type.

        Returns:
            List[Document]: A list of Document objects representing the chunks of the
                            original document after splitting.

        Example:
            ```python
            splitter = Splitter()
            python_doc = Document(text="def hello():\n    print('world')",
                                  metadata={"file_path": "hello.py"})
            chunks = splitter.split(python_doc)
            ```
        """
        file_extension = self._get_file_extension(document)

        if file_extension == ".py":
            return self.code_splitter.get_nodes_from_documents([document])
        elif file_extension == ".md":
            return self.markdown_splitter.get_nodes_from_documents([document])
        elif file_extension == ".json":
            return self.json_splitter.get_nodes_from_documents([document])
        elif file_extension == ".ipynb":
            return self.code_splitter.get_nodes_from_documents([document])
        else:
            return self.text_splitter.get_nodes_from_documents([document])

    def _get_file_extension(self, document: Document) -> str:
        """Extracts the file extension from a document's metadata.

        Looks for the 'file_path' key in the document's metadata and extracts
        the file extension. If no file path is found, returns an empty string.

        Args:
            document (Document): The document whose file extension needs to be determined.
                                 Expected to have metadata with a 'file_path' key.

        Returns:
            str: The lowercase file extension including the dot (e.g., '.py', '.md'),
                 or an empty string if no file path is found.
        """
        file_path = document.metadata.get("file_path", "")
        _, extension = os.path.splitext(file_path)
        return extension.lower()
