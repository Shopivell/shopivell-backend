import os
import json
from dotenv import load_dotenv
from typing import Annotated, TypedDict, Optional
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from database import SessionLocal
from modules.whatsapp.models import CompanyKnowledge
from sqlalchemy import select
from langgraph.checkpoint.memory import MemorySaver

load_dotenv()


class LeadScorer:
    """Score leads based on conversation content"""

    def __init__(self):
        self.llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

    def score_lead(self, conversation_history: str, last_message: str) -> dict:
        """
        Analyze conversation and return lead score with reasoning.
        Returns: {score: 0-100, status: str, interests: list, is_hot_lead: bool}
        """
        prompt = f"""Analyze this customer conversation and score the lead quality.

CONVERSATION:
{conversation_history}

LATEST MESSAGE FROM CUSTOMER:
{last_message}

Score the lead from 0-100 based on:
- 0-20: Just browsing, no real interest
- 21-40: Asking general questions
- 41-60: Showing interest, asking about prices/features
- 61-80: Serious interest, asking for quotes, comparing options
- 81-100: Ready to buy, scheduling site visit, requesting meeting, confirming purchase

HIGH INTENT SIGNALS (score 70+):
- Asking for quotation/quote
- Requesting site visit
- Wanting to schedule a meeting
- Asking about payment options
- Saying "looks good", "interested", "let's proceed"
- Providing their location/address
- Asking about installation dates

Return ONLY valid JSON (no markdown):
{{"score": <number>, "status": "<new|engaged|qualified|converted>", "interests": ["product1", "product2"], "reasoning": "<brief reason>"}}"""

        try:
            response = self.llm.invoke([("system", "You are a lead scoring assistant. Return only valid JSON."), ("user", prompt)])
            result = json.loads(response.content)
            result["is_hot_lead"] = result.get("score", 0) >= 70
            return result
        except Exception as e:
            print(f"Lead scoring error: {e}")
            return {"score": 30, "status": "engaged", "interests": [], "reasoning": "Default score", "is_hot_lead": False}

class SalesState(TypedDict):
    messages: Annotated[list, add_messages]
    context: str
    status: str

class SalesBot:
    def __init__(self, max_tokens: int = 300):
        # Limit response tokens to keep WhatsApp messages concise
        self.llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.3, max_tokens=max_tokens)
        self.embeddings = OpenAIEmbeddings()

    def retrieve(self, state: SalesState):
        query = state["messages"][-1].content
        print(f"Query: '{query}'")
        
        q_vector = self.embeddings.embed_query(query)
        
        with SessionLocal() as db:
            from sqlalchemy import text
            
            # Format embedding for PostgreSQL
            embedding_str = "[" + ",".join(str(x) for x in q_vector) + "]"
            
            # FIXED: Use proper CAST syntax and add similarity threshold
            stmt = text("""
                SELECT 
                    content, 
                    1 - (embedding <=> CAST(:embedding AS vector)) as similarity
                FROM company_knowledge 
                WHERE store_id = '36689cad-4b73-4fea-802b-d3a4fbfa23ec'
                AND embedding IS NOT NULL
                AND 1 - (embedding <=> CAST(:embedding AS vector)) > 0.3
                ORDER BY similarity DESC
                LIMIT 3
            """)
            
            try:
                results = db.execute(stmt, {"embedding": embedding_str}).all()
                
                if results:
                    print(f"Found {len(results)} matches")
                    for content, similarity in results:
                        print(f"   Similarity: {similarity:.4f}")
                    
                    # Extract only content
                    context = "\n".join([content for content, similarity in results])
                    return {"context": context, "status": "active"}
                else:
                    print("No matches above threshold 0.3")
                    
            except Exception as e:
                print(f"pgvector error: {e}")
                # Fallback to simpler query without threshold
                try:
                    stmt = text("""
                        SELECT content 
                        FROM company_knowledge 
                        WHERE store_id = '36689cad-4b73-4fea-802b-d3a4fbfa23ec'
                        ORDER BY embedding <=> CAST(:embedding AS vector)
                        LIMIT 3
                    """)
                    results = db.execute(stmt, {"embedding": embedding_str}).scalars().all()
                    
                    if results:
                        context = "\n".join(results)
                        return {"context": context, "status": "active"}
                except:
                    pass
            
            return {"context": "No relevant technical info found.", "status": "active"}
    
    def respond(self, state: SalesState):
        system_instructions = (
            "You are a Sales Rep at SecureSights. Be VERY brief and concise - max 2-3 sentences. "
            "Answer using CONTEXT below. Give key info only: product name, price, main feature. "
            "Only say 'WAITING' if context says 'No relevant technical info found'."
        )

        full_prompt = f"{system_instructions}\n\nCONTEXT:\n{state['context']}"
        response = self.llm.invoke([("system", full_prompt)] + state["messages"])

        if "WAITING" in response.content.upper():
            return {"messages": [response], "status": "human_required"}

        return {"messages": [response], "status": "active"}

    def get_graph(self):
        builder = StateGraph(SalesState)
        builder.add_node("retrieve", self.retrieve)
        builder.add_node("respond", self.respond)
        builder.add_edge(START, "retrieve")
        builder.add_edge("retrieve", "respond")
        builder.add_edge("respond", END)
        
        checkpointer = MemorySaver()
        return builder.compile(checkpointer=checkpointer)