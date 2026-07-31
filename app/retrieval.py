import os
import logging
from typing import List, Optional, Dict, Any

from app.config import settings
from app.vectorstore import vector_store
from app.models import QueryResponse, SourceChunk

logger = logging.getLogger(__name__)


class LLMUnavailableError(RuntimeError):
    """No LLM backend could synthesise an answer.

    Raised instead of degrading to a non-LLM answer: an ungrounded regex dump
    is indistinguishable from a real answer to the caller, which is worse than
    an explicit failure. Surfaced to clients as HTTP 503.
    """


class RetrievalQAPipeline:
    """
    Retrieval-Augmented Generation (RAG) QA Pipeline.
    1. Embeds question & retrieves top-K candidate chunks.
    2. Builds grounded context prompt.
    3. Queries an LLM backend (Gemini, then OpenAI).
    4. Formats answer + source citations.

    There is deliberately no offline synthesiser. If every backend fails the
    request errors out rather than returning an unsynthesised answer.
    """

    # Returned when retrieval itself finds nothing. This is a statement about
    # the index, not a synthesised answer, so it does not need an LLM.
    NO_CONTEXT_MESSAGE = (
        "I could not find any relevant information in the uploaded documents "
        "to answer your question. Please make sure the document has been uploaded "
        "and try rephrasing your question."
    )

    # ------------------------------------------------------------------ #
    #  LLM SYNTHESIS                                                       #
    # ------------------------------------------------------------------ #

    def _build_prompt(self, question: str, context_str: str) -> str:
        return (
            "You are a precise, helpful document Q&A assistant. "
            "Answer the user's question clearly and directly using ONLY the document context provided below. "
            "If the context is in Bengali, answer in Bengali or English depending on what the question language is. "
            "Do NOT guess, hallucinate, or use any knowledge outside of the provided context. "
            "If the answer is not present in the context, say so honestly.\n\n"
            f"=== DOCUMENT CONTEXT ===\n{context_str}\n\n"
            f"=== QUESTION ===\n{question}\n\n"
            "=== ANSWER ==="
        )

    def _try_gemini(self, prompt: str) -> Optional[str]:
        key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not key:
            logger.info("Gemini skipped: no GEMINI_API_KEY/GOOGLE_API_KEY set.")
            return None
        try:
            from google import genai
            client = genai.Client(api_key=key)
            response = client.models.generate_content(
                model=settings.GEMINI_MODEL,
                contents=prompt,
            )
            text = (response.text or "").strip()
            if text:
                return text
            logger.warning("Gemini returned an empty response body.")
        except Exception as e:
            logger.warning(f"Gemini API call failed: {e}")
        return None

    def _try_openai(self, prompt: str) -> Optional[str]:
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            logger.info("OpenAI skipped: no OPENAI_API_KEY set.")
            return None
        try:
            import openai
            client = openai.OpenAI(api_key=key)
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
            )
            text = (response.choices[0].message.content or "").strip()
            if text:
                return text
            logger.warning("OpenAI returned an empty response body.")
        except Exception as e:
            logger.warning(f"OpenAI API call failed: {e}")
        return None

    def synthesize_answer(self, question: str, context_chunks: List[Dict[str, Any]]) -> str:
        """
        Synthesises a grounded answer strictly from retrieved context.

        Backend order: Gemini -> OpenAI. If both are unavailable or fail,
        raises LLMUnavailableError. No offline fallback.
        """
        if not context_chunks:
            return self.NO_CONTEXT_MESSAGE

        context_str = "\n\n---\n\n".join([c["text"] for c in context_chunks])
        prompt = self._build_prompt(question, context_str)

        for name, backend in (("Gemini", self._try_gemini), ("OpenAI", self._try_openai)):
            answer = backend(prompt)
            if answer:
                logger.info(f"Answer synthesised by {name}.")
                return answer

        raise LLMUnavailableError(
            "No LLM backend is currently available to generate an answer. "
            "Relevant document context was retrieved successfully, but answer "
            "synthesis requires a working Gemini or OpenAI API key with "
            "available quota. Check the server logs for the specific backend error."
        )

    # ------------------------------------------------------------------ #
    #  MAIN ENTRY POINT                                                    #
    # ------------------------------------------------------------------ #

    def answer_question(
        self, question: str, top_k: Optional[int] = None, doc_id: Optional[str] = None
    ) -> QueryResponse:
        """
        Main RAG query entry point.

        Propagates LLMUnavailableError so the API layer can return 503 rather
        than presenting an unsynthesised answer as a successful result.
        """
        k = top_k or settings.DEFAULT_TOP_K

        # Step 1: Vector Search in ChromaDB
        matched_chunks = vector_store.search_similar(
            query=question,
            top_k=k,
            doc_id=doc_id
        )

        # Step 2: Format Source Chunks
        sources: List[SourceChunk] = []
        for c in matched_chunks:
            meta = c["metadata"]
            sources.append(SourceChunk(
                chunk_id=c["chunk_id"],
                doc_id=meta["doc_id"],
                filename=meta["filename"],
                text=c["text"],
                page_number=meta["page_number"]
            ))

        # Step 3: Synthesize Answer (raises if no backend is usable)
        answer_text = self.synthesize_answer(question, matched_chunks)

        return QueryResponse(
            question=question,
            answer=answer_text,
            sources=sources,
            doc_id_filter=doc_id
        )


retrieval_pipeline = RetrievalQAPipeline()
