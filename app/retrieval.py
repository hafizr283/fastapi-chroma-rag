import os
import re
import logging
from typing import List, Optional, Dict, Any

from app.config import settings
from app.vectorstore import vector_store
from app.models import QueryResponse, SourceChunk

logger = logging.getLogger(__name__)


class RetrievalQAPipeline:
    """
    Retrieval-Augmented Generation (RAG) QA Pipeline.
    1. Embeds question & retrieves top-K candidate chunks.
    2. Builds grounded context prompt.
    3. Queries LLM (Gemini / OpenAI) or runs Smart Entity Extraction Synthesizer.
    4. Formats answer + source citations.
    """

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

    def synthesize_answer(self, question: str, context_chunks: List[Dict[str, Any]]) -> str:
        """
        Synthesizes a grounded answer based strictly on retrieved context.
        Priority order:
          1. Google Gemini API (configured via GEMINI_MODEL)
          2. OpenAI API (gpt-4o-mini)
          3. Intelligent local entity extractor (offline)
        """
        if not context_chunks:
            return (
                "I could not find any relevant information in the uploaded documents "
                "to answer your question. Please make sure the document has been uploaded "
                "and try rephrasing your question."
            )

        context_str = "\n\n---\n\n".join([c["text"] for c in context_chunks])

        # 1. Try Google Gemini API
        gemini_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if gemini_key:
            try:
                from google import genai
                client = genai.Client(api_key=gemini_key)
                prompt = self._build_prompt(question, context_str)
                response = client.models.generate_content(
                    model=settings.GEMINI_MODEL,
                    contents=prompt,
                )
                if response.text:
                    return response.text.strip()
            except Exception as e:
                logger.warning(f"Gemini API call failed, attempting fallback: {e}")

        # 2. Try OpenAI API
        openai_key = os.environ.get("OPENAI_API_KEY")
        if openai_key:
            try:
                import openai
                client = openai.OpenAI(api_key=openai_key)
                prompt = self._build_prompt(question, context_str)
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1
                )
                return response.choices[0].message.content.strip()
            except Exception as e:
                logger.warning(f"OpenAI API call failed, attempting local fallback: {e}")

        # 3. Smart Local Entity Extractor (Offline Fallback)
        return self._local_extractor(question, context_str, context_chunks)

    # ------------------------------------------------------------------ #
    #  OFFLINE ENTITY EXTRACTOR — covers 15+ field types                  #
    # ------------------------------------------------------------------ #

    def _local_extractor(
        self, question: str, context_str: str, context_chunks: List[Dict[str, Any]]
    ) -> str:
        q = question.lower()

        # ── Father / Mother / Parent (MUST come before generic name check) ──
        if any(w in q for w in ["father", "mother", "parent", "বাবা", "মা", "পিতা", "মাতা"]):
            parents = re.findall(
                r"(?:Father'?s? Name|Mother'?s? Name|পিতার নাম|মাতার নাম)[^\n:]*[:\*\s]+\n*([^\n]+)",
                context_str, re.IGNORECASE
            )
            if parents:
                unique = list(dict.fromkeys([p.strip() for p in parents if p.strip()]))
                return "Parent name(s) found in the document:\n- " + "\n- ".join(unique[:2])

        # ── Applicant Name (only for applicant-specific keywords) ──────────
        # NOTE: bare 'name' alone is intentionally NOT here — too ambiguous
        if any(w in q for w in ["applicant", "who", "person", "candidate", "full name", "your name", "আবেদনকারী", "নিজের নাম"]):
            matches = re.findall(
                r'(?:Full Name|বাংলায় সম্পূর্ণ নাম|Nick Name|Applicant Name)[^\n:]*[\*\s]*\n+([^\n]+)',
                context_str, re.IGNORECASE
            )
            valid = [
                m.strip() for m in matches
                if m.strip() and not re.match(
                    r'^(?:Example|Institute|Department|Father|Mother|College|Branch|HSC|BDS|MBBS|Engineering|Admitted|\d+)',
                    m.strip(), re.IGNORECASE
                )
            ]
            if valid:
                unique = list(dict.fromkeys(valid))
                return "The applicant's name found in the document:\n- " + "\n- ".join(unique)

        # ── Phone / Mobile ────────────────────────────────────────────────
        if any(w in q for w in ["mobile", "phone", "number", "contact", "মোবাইল", "ফোন"]):
            mobiles = re.findall(
                r"(?:Mobile Number|Alternate Mobile|Father'?s? Mobile|Contact)[^\n:]*[\*\s]*\n+(\d{10,11})",
                context_str, re.IGNORECASE
            )
            if not mobiles:
                mobiles = re.findall(r'\b(01\d{9})\b', context_str)
            if mobiles:
                unique = list(dict.fromkeys(mobiles))
                return "Contact mobile number(s) found in the document:\n- " + "\n- ".join(unique)

        # ── Email ─────────────────────────────────────────────────────────
        if any(w in q for w in ["email", "mail", "ইমেইল"]):
            emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', context_str)
            if emails:
                return f"Email address found in the document: {emails[0]}"

        # ── Date of Birth ─────────────────────────────────────────────────
        if any(w in q for w in ["birth", "dob", "born", "age", "জন্ম"]):
            dob = re.findall(
                r'(?:Date of Birth|DOB|জন্ম তারিখ)[^\n:]*[:\*\s]+\n*([^\n]+)',
                context_str, re.IGNORECASE
            )
            # Also look for dd/mm/yyyy or dd-mm-yyyy patterns
            if not dob:
                dob = re.findall(r'\b(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})\b', context_str)
            if dob:
                return f"Date of birth found in the document: {dob[0].strip()}"

        # ── Address ───────────────────────────────────────────────────────
        if any(w in q for w in ["address", "village", "district", "upazila", "ঠিকানা", "গ্রাম", "জেলা"]):
            addr = re.findall(
                r'(?:Present Address|Permanent Address|Village|District|Upazila|ঠিকানা|গ্রাম|জেলা)[^\n:]*[:\*\s]+\n*([^\n]+)',
                context_str, re.IGNORECASE
            )
            if addr:
                unique = list(dict.fromkeys([a.strip() for a in addr if a.strip()]))
                return "Address information found in the document:\n- " + "\n- ".join(unique[:4])

        # ── Institute / School / College ──────────────────────────────────
        if any(w in q for w in ["institute", "school", "college", "university", "institution", "প্রতিষ্ঠান", "বিশ্ববিদ্যালয়"]):
            inst = re.findall(
                r'(?:Institute Name|School Name|College Name|University|Institution)[^\n:]*[:\*\s]+\n*([^\n]+)',
                context_str, re.IGNORECASE
            )
            if inst:
                unique = list(dict.fromkeys([i.strip() for i in inst if i.strip()]))
                return "Institute/School/College found in the document:\n- " + "\n- ".join(unique[:3])

        # ── Roll Number ───────────────────────────────────────────────────
        if any(w in q for w in ["roll", "registration", "রোল", "রেজিস্ট্রেশন"]):
            roll = re.findall(
                r'(?:Roll No|Roll Number|Registration No|রোল নং)[^\n:]*[:\*\s]+\n*([^\n]+)',
                context_str, re.IGNORECASE
            )
            if not roll:
                roll = re.findall(r'\b(\d{6,10})\b', context_str)
            if roll:
                return f"Roll/Registration number found in the document: {roll[0].strip()}"

        # ── Course / Program ──────────────────────────────────────────────
        if any(w in q for w in ["course", "program", "class", "subject", "কোর্স", "বিভাগ", "শ্রেণি"]):
            course = re.findall(
                r'(?:Course Name|Program|Class|Subject|Batch|কোর্স|বিভাগ)[^\n:]*[:\*\s]+\n*([^\n]+)',
                context_str, re.IGNORECASE
            )
            if course:
                unique = list(dict.fromkeys([c.strip() for c in course if c.strip()]))
                return "Course/Program information found in the document:\n- " + "\n- ".join(unique[:3])

        # ── Fee / Payment ─────────────────────────────────────────────────
        if any(w in q for w in ["fee", "fees", "payment", "cost", "amount", "ফি", "টাকা"]):
            fees = re.findall(
                r'(?:Fee|Fees|Amount|Payment|Total)[^\n:]*[:\*\s]+\n*([^\n]+)',
                context_str, re.IGNORECASE
            )
            # Also look for currency patterns (BDT or ৳)
            if not fees:
                fees = re.findall(r'(?:BDT|Tk\.?|৳)\s*[\d,]+', context_str)
            if fees:
                unique = list(dict.fromkeys([f.strip() for f in fees if f.strip()]))
                return "Fee/payment information found in the document:\n- " + "\n- ".join(unique[:3])

        # ── Father's / Mother's Name ──────────────────────────────────────
        if any(w in q for w in ["father", "mother", "parent", "বাবা", "মা", "পিতা", "মাতা"]):
            parents = re.findall(
                r"(?:Father'?s? Name|Mother'?s? Name|পিতার নাম|মাতার নাম)[^\n:]*[:\*\s]+\n*([^\n]+)",
                context_str, re.IGNORECASE
            )
            if parents:
                unique = list(dict.fromkeys([p.strip() for p in parents if p.strip()]))
                return "Parent name(s) found in the document:\n- " + "\n- ".join(unique[:2])

        # ── NID / National ID ────────────────────────────────────────────
        if any(w in q for w in ["nid", "national id", "identity", "জাতীয় পরিচয়"]):
            nid = re.findall(
                r'(?:NID|National ID|Voter ID|জাতীয় পরিচয়)[^\n:]*[:\*\s]+\n*(\d[\d\s]{9,20})',
                context_str, re.IGNORECASE
            )
            if not nid:
                nid = re.findall(r'\b(\d{13,17})\b', context_str)
            if nid:
                return f"National ID (NID) found in the document: {nid[0].strip()}"

        # ── Gender ────────────────────────────────────────────────────────
        if any(w in q for w in ["gender", "sex", "male", "female", "লিঙ্গ"]):
            gender = re.findall(
                r'(?:Gender|Sex|লিঙ্গ)[^\n:]*[:\*\s]+\n*([^\n]+)',
                context_str, re.IGNORECASE
            )
            if not gender:
                if re.search(r'\b(?:Male|পুরুষ)\b', context_str, re.IGNORECASE):
                    gender = ["Male"]
                elif re.search(r'\b(?:Female|মহিলা|নারী)\b', context_str, re.IGNORECASE):
                    gender = ["Female"]
            if gender:
                return f"Gender found in the document: {gender[0].strip()}"

        # ── Blood Group ───────────────────────────────────────────────────
        if any(w in q for w in ["blood", "blood group", "রক্তের গ্রুপ"]):
            blood = re.findall(r'\b(A\+|A-|B\+|B-|AB\+|AB-|O\+|O-)\b', context_str)
            if blood:
                return f"Blood group found in the document: {blood[0]}"

        # ─────────────────────────────────────────────────────────────────
        # DEFAULT: Smart summary fallback — much better than raw chunk dump
        # ─────────────────────────────────────────────────────────────────
        # Extract the most informative non-label lines from each chunk
        summary_lines = []
        seen = set()
        for chunk in context_chunks:
            for line in chunk["text"].split("\n"):
                line = line.strip()
                # Skip very short lines, pure field labels, and duplicate lines
                if len(line) < 8 or line in seen:
                    continue
                # Skip lines that look like bare form labels (no value)
                if re.match(r'^[A-Za-z\u0980-\u09FF\s]{2,40}[:\*]?\s*$', line) and len(line) < 30:
                    continue
                summary_lines.append(f"  • {line}")
                seen.add(line)
                if len(summary_lines) >= 12:
                    break
            if len(summary_lines) >= 12:
                break

        if summary_lines:
            return (
                f"Based on the retrieved document sections, here is the most relevant information "
                f"related to your question:\n\n" + "\n".join(summary_lines) +
                "\n\n[Tip]: Set GEMINI_API_KEY in your .env file for full natural language answers."
            )

        return (
            "The document was retrieved but the answer could not be precisely extracted offline. "
            "Please set GEMINI_API_KEY in your .env file to enable full AI-powered answers."
        )

    # ------------------------------------------------------------------ #
    #  MAIN ENTRY POINT                                                    #
    # ------------------------------------------------------------------ #

    def answer_question(
        self, question: str, top_k: Optional[int] = None, doc_id: Optional[str] = None
    ) -> QueryResponse:
        """
        Main RAG query entry point.
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

        # Step 3: Synthesize Answer
        answer_text = self.synthesize_answer(question, matched_chunks)

        return QueryResponse(
            question=question,
            answer=answer_text,
            sources=sources,
            doc_id_filter=doc_id
        )


retrieval_pipeline = RetrievalQAPipeline()
