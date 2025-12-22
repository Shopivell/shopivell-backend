import os
from dotenv import load_dotenv
from typing import Annotated, TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from database import SessionLocal
from modules.whatsapp.models import CompanyKnowledge
from sqlalchemy import select
from langgraph.checkpoint.memory import MemorySaver

load_dotenv()

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