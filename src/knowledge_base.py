"""
Knowledge Base - RAG implementation with ChromaDB
Vector search for relevant document retrieval
"""

import os
import json
import logging
from typing import List, Dict, Optional

import chromadb
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


def _is_placeholder(value: str) -> bool:
    """Detect placeholder API key values from .env.example"""
    if not value:
        return True
    return value.startswith("your_") or value in ("changeme", "CHANGE_ME", "xxx", "sk-xxx")


class KnowledgeBase:
    """Vector-based knowledge base for RAG"""

    def __init__(self):
        self.openai_api_key = os.getenv("OPENAI_API_KEY")
        if not self.openai_api_key or _is_placeholder(self.openai_api_key):
            logger.warning("OPENAI_API_KEY not set - knowledge base will use default embeddings")
            self.openai_api_key = None
            self.openai_client = None
        else:
            self.openai_client = AsyncOpenAI(api_key=self.openai_api_key)
        self.embedding_model = "text-embedding-3-small"

        # Initialize ChromaDB with persistent storage
        chroma_path = "./data/chroma"
        os.makedirs(chroma_path, exist_ok=True)
        self.chroma_client = chromadb.PersistentClient(path=chroma_path)

        self.collection_name = "voice_agent_kb"
        self.collection = None
        self.document_count = 0
        self.documents = []

        logger.info("KnowledgeBase initialized")

    async def initialize(self, kb_path: str):
        """
        Load knowledge base from JSON file and create embeddings
        """
        try:
            logger.info(f"Loading knowledge base from: {kb_path}")

            # Load documents
            with open(kb_path, 'r') as f:
                data = json.load(f)

            documents = data.get("documents", [])
            if not documents:
                raise ValueError("No documents found in knowledge base")

            self.document_count = len(documents)
            self.documents = documents
            logger.info(f"Loaded {self.document_count} documents")

            # Get or create collection
            self.collection = self.chroma_client.get_or_create_collection(
                name=self.collection_name,
                metadata={"description": "Voice agent knowledge base"}
            )
            logger.info(f"Using collection: {self.collection_name}")

            # Check if collection already has documents
            existing_count = self.collection.count()
            if existing_count > 0:
                logger.info(f"Collection already has {existing_count} documents - skipping embedding")
                return

            # Generate embeddings and store
            logger.info("Generating embeddings...")

            ids = []
            texts = []
            metadatas = []
            embeddings_list = []

            for doc in documents:
                doc_id = doc.get("id", f"doc_{len(ids)}")

                # Combine question and answer for better retrieval
                text = f"Q: {doc.get('question', '')}\nA: {doc.get('answer', '')}"

                ids.append(doc_id)
                texts.append(text)
                metadatas.append({
                    "category": doc.get("category", "general"),
                    "question": doc.get("question", ""),
                    "answer": doc.get("answer", "")
                })

                # Generate embedding
                if self.openai_client:
                    embedding = await self._generate_embedding(text)
                    embeddings_list.append(embedding)

            # Add to collection
            if embeddings_list:
                self.collection.add(
                    ids=ids,
                    documents=texts,
                    metadatas=metadatas,
                    embeddings=embeddings_list
                )
            else:
                # Fallback: use ChromaDB's default embedding function
                self.collection.add(
                    ids=ids,
                    documents=texts,
                    metadatas=metadatas
                )

            logger.info(f"Knowledge base initialized with {len(documents)} documents")

        except Exception as e:
            logger.error(f"Failed to initialize knowledge base: {e}", exc_info=True)
            raise

    async def _generate_embedding(self, text: str) -> List[float]:
        """Generate embedding using OpenAI"""
        try:
            response = await self.openai_client.embeddings.create(
                model=self.embedding_model,
                input=text
            )
            return response.data[0].embedding

        except Exception as e:
            logger.error(f"Embedding error: {e}")
            raise

    def get_all_documents_text(self) -> str:
        """
        Return all KB documents as formatted text for embedding in the system prompt.
        This eliminates the need for per-query embedding + vector search (~876ms saved).
        """
        if not self.documents:
            return ""

        categories = {}
        for doc in self.documents:
            cat = doc.get("category", "general")
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(doc)

        lines = ["\n\nCompany Knowledge Base (use this to answer customer questions):"]
        for cat in sorted(categories.keys()):
            lines.append(f"\n[{cat.upper()}]")
            for doc in categories[cat]:
                lines.append(f"Q: {doc.get('question', '')}")
                lines.append(f"A: {doc.get('answer', '')}")

        return "\n".join(lines)

    async def search(self, query: str, top_k: int = 3) -> List[Dict]:
        """
        Search knowledge base for relevant documents
        Returns list of matching documents with metadata
        """
        try:
            if not self.collection:
                logger.warning("Collection not initialized")
                return []

            # Generate query embedding
            query_embedding = None
            if self.openai_client:
                query_embedding = await self._generate_embedding(query)

            # Search collection
            if query_embedding:
                results = self.collection.query(
                    query_embeddings=[query_embedding],
                    n_results=top_k
                )
            else:
                # Fallback: use text search
                results = self.collection.query(
                    query_texts=[query],
                    n_results=top_k
                )

            # Format results
            documents = []
            if results and results["metadatas"]:
                for i, metadata in enumerate(results["metadatas"][0]):
                    documents.append({
                        "id": results["ids"][0][i],
                        "category": metadata.get("category", "general"),
                        "question": metadata.get("question", ""),
                        "answer": metadata.get("answer", ""),
                        "distance": results["distances"][0][i] if "distances" in results else 0
                    })

            logger.info(f"Found {len(documents)} relevant documents for: {query[:50]}...")
            return documents

        except Exception as e:
            logger.error(f"Search error: {e}", exc_info=True)
            return []
