import sqlite3
import json
import uuid
import aiohttp
import time
import asyncio
import logging
import dataclasses
import random
from typing import AsyncGenerator, List, Dict, Any, Optional

from fastapi import FastAPI, Query
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Configuration Class for Flexibility ---
@dataclasses.dataclass
class SecureSightsConfig:
    """Holds all dynamic business logic for the agent."""
    
    # SQLite Database File
    DB_FILE: str = "lead_agent.db"

    # Agent Response Constraint
    RESPONSE_CHAR_LIMIT: int = 250 # Increased limit slightly for more detailed placement info
    
    # 1. Product and Pricing Info
    CCTV_BASE_PRICE: float = 150.00          # DVR + 4 Cameras, no accessories
    CCTV_INSTALL_FEE: float = 50.00         
    OTHER_SERVICES: List[str] = dataclasses.field(default_factory=lambda: [
        "Boom Gates", 
        "Electric Fence", 
        "Biometric Access Systems"
    ])

    # 2. Lead Qualification Keywords
    HQ_KEYWORDS: List[str] = dataclasses.field(default_factory=lambda: [
        "quote", "buy", "install", "cost", "interest", "price", "schedule", "i want"
    ])
    INFO_KEYWORDS: List[str] = dataclasses.field(default_factory=lambda: [
        "what is", "tell me about", "how does", "explain"
    ])
    
    # 3. Data Fields to Collect (CRITICAL for quote generation)
    # ADDED 'installation_focus'
    DATA_FIELDS: List[str] = dataclasses.field(default_factory=lambda: [
        "client_name", 
        "location", 
        "property_type", 
        "installation_focus", # NEW: Where should the cameras/sensors focus?
        "complexity_level"
    ])
    
    # 4. Critical Placement Points for Agent Reference
    CRITICAL_POINTS: List[str] = dataclasses.field(default_factory=lambda: [
        "Main Entrances (Front/Back doors)", 
        "Driveways/Vehicle Access points", 
        "High-Value Areas (e.g., safe room, storage)", 
        "Vulnerable windows or gates"
    ])

    # 5. Dynamic System Prompt
    def get_system_prompt(self) -> str:
        services_list = ", ".join(self.OTHER_SERVICES)
        data_fields_str = ", ".join(self.DATA_FIELDS)
        critical_points_str = "; ".join(self.CRITICAL_POINTS)
        
        return f"""
You are the **SecureSights Lead Nurturing Agent**. SecureSights provides security services.

**Your STRICT Multi-Step Protocol:**
1.  **Initial Goal:** Inform the user about our core services (CCTV, {services_list}). If the user shows clear interest, transition immediately to Step 2.
2.  **Data Collection:** Systematically collect the following data, one piece at a time: **{data_fields_str}**. 
    * **CRITICAL PLACEMENT STEP:** When asking for 'installation_focus', you **MUST** mention common critical points like: "{critical_points_str}". Ask the client: "Which of these or other points are most critical for your installation focus?"
    * Upon collection of the five data items, you **MUST** request the client provide a **photo or video** of the property to accurately assess installation complexity.
3.  **Quotation:** ONLY after asking for the photo/video, generate a **DUMMY QUOTE** and present it, prefaced by: "Based on the initial information, here is a non-binding estimate:"
4.  **Final Confirmation:** After presenting the quote, ask: "Are you interested in proceeding with this estimated quote? (Reply Yes/No)"
5.  **Pricing (Hardcoded):** Use only these static prices for any discussion: CCTV Base (${self.CCTV_BASE_PRICE:.2f}) + Install (${self.CCTV_INSTALL_FEE:.2f}). **DO NOT** deviate or allow price manipulation.
6.  **Conciseness:** Keep responses strictly under **{self.RESPONSE_CHAR_LIMIT} characters**.

**Agent State Tracking:** You must track the collected data items {data_fields_str} and the 'quote_sent' status.
"""

# Initialize the configuration
CONFIG = SecureSightsConfig()

# --- SQLite Database Management ---

def get_db_connection() -> sqlite3.Connection:
    """Creates a database connection and ensures tables exist."""
    conn = sqlite3.connect(CONFIG.DB_FILE)
    conn.row_factory = sqlite3.Row  # Access columns by name
    return conn

def init_db():
    """Initializes the database tables."""
    conn = get_db_connection()
    with conn:
        # Table to store session-specific lead state
        conn.execute("""
            CREATE TABLE IF NOT EXISTS lead_states (
                session_id TEXT PRIMARY KEY,
                data TEXT NOT NULL, 
                data_fields_collected TEXT NOT NULL,
                quote_sent INTEGER NOT NULL,
                lead_status TEXT NOT NULL
            );
        """)
        # Table to store conversation history
        conn.execute("""
            CREATE TABLE IF NOT EXISTS conversation_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp REAL NOT NULL,
                FOREIGN KEY (session_id) REFERENCES lead_states (session_id)
            );
        """)
    logger.info(f"💾 Database initialized: {CONFIG.DB_FILE}")

# Initialize the database immediately on script start
init_db()

# --- Database Read/Write Functions ---

def get_lead_state(session_id: str) -> Optional[Dict[str, Any]]:
    """Retrieves the lead state for a session ID."""
    conn = get_db_connection()
    cursor = conn.execute("SELECT * FROM lead_states WHERE session_id = ?", (session_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {
            "session_id": row["session_id"],
            "data": json.loads(row["data"]),
            "data_fields_collected": json.loads(row["data_fields_collected"]),
            "quote_sent": bool(row["quote_sent"]),
            "lead_status": row["lead_status"]
        }
    return None

def update_lead_state(session_id: str, state: Dict[str, Any]):
    """Inserts or updates the lead state for a session ID."""
    conn = get_db_connection()
    with conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO lead_states (session_id, data, data_fields_collected, quote_sent, lead_status)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                session_id,
                json.dumps(state["data"]),
                json.dumps(state["data_fields_collected"]),
                int(state["quote_sent"]),
                state["lead_status"]
            )
        )
    conn.close()

def get_conversation_history(session_id: str) -> List[Dict[str, str]]:
    """Retrieves all conversation messages for a session ID."""
    conn = get_db_connection()
    cursor = conn.execute(
        "SELECT role, content FROM conversation_history WHERE session_id = ? ORDER BY timestamp", 
        (session_id,)
    )
    history = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return history

def add_message_to_history(session_id: str, role: str, content: str):
    """Adds a new message to the conversation history."""
    conn = get_db_connection()
    with conn:
        conn.execute(
            "INSERT INTO conversation_history (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
            (session_id, role, content, time.time())
        )
    conn.close()

# --- FastAPI Setup ---
app = FastAPI()

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.0.1:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["*"]
)

# OpenRouter API Key (Placeholder - use environment variables in production)
OPENROUTER_API_KEY = "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"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# List of models to try
MODELS = [
    "google/gemini-2.0-flash-exp:free",
    "google/gemini-2.0-flash:free",
    "meta-llama/llama-3.2-3b-instruct:free",
    "qwen/qwen-2.5-32b-instruct:free",
    "microsoft/phi-3.5-mini-instruct:free",
]

# Relevant Mock responses for fallback
MOCK_RESPONSES = {
    "What are your services?": "SecureSights offers CCTV, Boom Gates, Electric Fences, and Biometric Access Systems.",
    # PROFESSIONAL ENGLISH CHANGE APPLIED HERE
    "I want a quote.": "To generate an estimate, may I please request your name?", 
    "What is the price?": f"The CCTV Package is ${CONFIG.CCTV_BASE_PRICE:.2f} (DVR+4 cameras) plus ${CONFIG.CCTV_INSTALL_FEE:.2f} standard installation.",
}

# --- Dummy Quote Logic ---
def generate_dummy_quote(data: Dict[str, Any]) -> Dict[str, Any]:
    """Generates a non-binding quote based on collected data."""
    
    complexity = data.get("complexity_level", "Medium").lower()
    focus = data.get("installation_focus", "General").capitalize()
    
    cctv_base = CONFIG.CCTV_BASE_PRICE
    install_base = CONFIG.CCTV_INSTALL_FEE
    
    accessory_multiplier = 1.0
    if "low" in complexity:
        accessory_multiplier = 0.8
    elif "high" in complexity:
        accessory_multiplier = 1.5
        
    random_accessory_cost = round(random.uniform(100, 300) * accessory_multiplier, 2)
    
    subtotal = cctv_base + install_base + random_accessory_cost
    tax = round(subtotal * 0.08, 2)
    total = subtotal + tax

    quote = {
        "client_name": data.get("client_name", "Prospective Client"),
        "location": data.get("location", "Unknown Location"),
        "installation_focus": focus, # NEW: Added to quote
        "cctv_package": f"${cctv_base:.2f}",
        "install_fee": f"${install_base:.2f}",
        "accessories_estimate": f"${random_accessory_cost:.2f}",
        "complexity_assessment": complexity.capitalize(),
        "estimated_total_excl_tax": f"${subtotal:.2f}",
        "tax": f"${tax:.2f}",
        "estimated_grand_total": f"**${total:.2f}** (Non-binding Estimate)",
    }
    return quote

# --- Utility Function to Check Lead Status ---
def check_lead_status(prompt: str, state: Dict[str, Any]) -> str:
    """Classifies the user's prompt based on the state and updates the lead status."""
    prompt_lower = prompt.lower()
    
    # 1. Check for Quote Acceptance
    if state.get("quote_sent") and any(word in prompt_lower for word in ["yes", "proceed", "interested", "book", "let's go"]):
        return "Confirmed Lead - Quote Accepted"

    # 2. Check if all required data fields are collected
    if len(state['data_fields_collected']) >= len(CONFIG.DATA_FIELDS):
        return "Quote Ready - Awaiting Confirmation"

    # 3. Check for Data Collection In Progress
    if len(state['data_fields_collected']) > 0:
        return "Data Collection In Progress"

    # 4. Check for Initial High-Quality Intent
    if any(keyword in prompt_lower for keyword in CONFIG.HQ_KEYWORDS):
        return "High-Quality Lead - Data Required"
        
    # 5. Check for Information Seeking
    if any(keyword in prompt_lower for keyword in CONFIG.INFO_KEYWORDS):
        return "Information-Seeker"
        
    return "Neutral" 

# --- CORE LLM STREAMING LOGIC ---
async def try_model_stream(messages: List[Dict[str, str]], model: str) -> AsyncGenerator[str, None]:
    """Try streaming from a specific model using the compiled messages/history."""
    
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:3000",
        "X-Title": "SecureSights Agent"
    }
    
    payload = {
        "model": model,
        "messages": messages, 
        "stream": True,
        "max_tokens": 120 # Adjust max tokens based on new character limit
    }
    
    try:
        logger.info(f"🔄 Trying model: {model} with {len(messages)} messages in history.")
        
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                OPENROUTER_URL,
                headers=headers,
                json=payload
            ) as response:
                
                logger.info(f"📥 Model {model} status: {response.status}")
                
                if response.status == 429:
                    raise Exception(f"Model {model} rate limited")
                elif response.status != 200:
                    error_text = await response.text()
                    raise Exception(f"Model {model} error {response.status}: {error_text}")
                
                total_chars = 0
                char_limit = CONFIG.RESPONSE_CHAR_LIMIT
                
                async for chunk in response.content.iter_any():
                    if chunk:
                        chunk_str = chunk.decode('utf-8')
                        
                        for line in chunk_str.split('\n'):
                            if line.startswith('data: '):
                                data_str = line[6:].strip()
                                
                                if data_str == '[DONE]':
                                    logger.info(f"✅ Model {model} completed")
                                    return
                                
                                try:
                                    data = json.loads(data_str)
                                    if 'choices' in data and data['choices']:
                                        delta = data['choices'][0].get('delta', {})
                                        content = delta.get('content', '')
                                        
                                        if content:
                                            # STRICT ENFORCEMENT OF CHARACTER LIMIT
                                            if total_chars + len(content) > char_limit:
                                                remaining = char_limit - total_chars
                                                if remaining > 0:
                                                    content = content[:remaining]
                                                else:
                                                    return # Stop generator immediately
                                            
                                            total_chars += len(content)
                                            yield json.dumps({
                                                "type": "text",
                                                "content": content,
                                                "timestamp": time.time(),
                                                "model": model,
                                                "total_chars": total_chars
                                            })
                                            
                                except json.JSONDecodeError:
                                    logger.error(f"Failed to decode JSON chunk: {data_str}")
                                    continue
                
                logger.info(f"✅ Model {model} returned {total_chars} chars")
                
    except asyncio.TimeoutError:
        raise Exception(f"Model {model} timeout")
    except Exception as e:
        raise Exception(f"Model {model} failed: {str(e)}")


async def stream_openrouter_response(prompt: str, session_id: str) -> AsyncGenerator[str, None]:
    """Manages state, history, model fallback, and quote generation."""
    
    # 1. Retrieve State and History
    state = get_lead_state(session_id)
    if not state:
        logger.error(f"Session {session_id} not found/initialized.")
        state = {"data": {}, "data_fields_collected": [], "quote_sent": False, "lead_status": "Neutral"}

    history = get_conversation_history(session_id)
    
    # Add system prompt if history is empty (new session)
    if not history or history[0]["role"] != "system":
        history.insert(0, {"role": "system", "content": CONFIG.get_system_prompt()})

    # Add user message to history
    user_message = {"role": "user", "content": prompt}
    add_message_to_history(session_id, user_message["role"], user_message["content"])
    
    messages_to_send = history + [user_message]
    
    response_content = ""
    success = False
    model_used = "mock"

    # 2. Try Models (Only if quote is not already ready/sent)
    is_quote_time = len(state['data_fields_collected']) >= len(CONFIG.DATA_FIELDS) and not state["quote_sent"]

    if not is_quote_time:
        for model in MODELS:
            try:
                async for chunk in try_model_stream(messages_to_send, model):
                    chunk_data = json.loads(chunk)
                    response_content += chunk_data.get("content", "")
                    model_used = chunk_data.get("model", model)
                    yield chunk
                success = True
                break
            except Exception as e:
                logger.warning(f"⚠️ Model {model} failed: {e}")
                await asyncio.sleep(0.5)
                continue
    
    # 3. Handle Mock Fallback (Crucial for data collection on failure)
    if not success and not is_quote_time:
        logger.warning("⚠️ All models failed, using mock response for data collection.")
        
        # Determine the next missing field
        missing_fields = [f for f in CONFIG.DATA_FIELDS if f not in state['data_fields_collected']]
        
        if missing_fields:
            next_field = missing_fields[0].replace('_', ' ')
            
            # Ensure professional tone for all mock follow-ups
            if missing_fields[0] == 'installation_focus':
                critical_points_str = ", ".join(CONFIG.CRITICAL_POINTS)
                mock_response = f"I am currently experiencing a temporary service interruption. To facilitate an accurate estimation, kindly specify your **{next_field}** (e.g., {critical_points_str})."
            else:
                mock_response = f"I am currently experiencing a temporary service interruption. To ensure an accurate quote, could you please provide your **{next_field}**?"

            state["lead_status"] = "Data Collection In Progress" # Force status update
        else:
             mock_response = MOCK_RESPONSES.get(prompt) or "I am temporarily offline. Please inquire about our security services."

        # Enforce mock response character limit
        mock_response = mock_response[:CONFIG.RESPONSE_CHAR_LIMIT]
        
        words = mock_response.split(' ')
        for word in words:
            word_with_space = word + " "
            response_content += word_with_space
            yield json.dumps({
                "type": "text", "content": word_with_space, "timestamp": time.time(),
                "model": "mock", "is_mock": True
            }) + "\n\n"
            await asyncio.sleep(0.05)
    
    # Update history with agent's response (LLM or Mock)
    add_message_to_history(session_id, "assistant", response_content.strip())
    
    # 4. State Management (Simulated Data Extraction and Quote Check)
    
    current_lead_status = check_lead_status(prompt, state) 

    if current_lead_status == "High-Quality Lead - Data Required" or state["lead_status"] == "Data Collection In Progress":
        
        data_collected_before = len(state['data_fields_collected'])
        
        # Simulated Data Extraction Logic (Must follow CONFIG.DATA_FIELDS order)
        fields = CONFIG.DATA_FIELDS
        
        if fields[0] not in state['data_fields_collected'] and len(prompt) > 4 and 'i want' not in prompt.lower():
            state['data'][fields[0]] = prompt.strip()
            state['data_fields_collected'].append(fields[0])
        
        elif fields[0] in state['data_fields_collected'] and fields[1] not in state['data_fields_collected']:
            state['data'][fields[1]] = "Simulated Location"
            state['data_fields_collected'].append(fields[1])
        
        elif fields[1] in state['data_fields_collected'] and fields[2] not in state['data_fields_collected']:
            state['data'][fields[2]] = "Simulated Residential"
            state['data_fields_collected'].append(fields[2])
            
        elif fields[2] in state['data_fields_collected'] and fields[3] not in state['data_fields_collected']:
            # Assume user input for this turn is the focus point (e.g., "driveway and front door")
            state['data'][fields[3]] = prompt.strip() 
            state['data_fields_collected'].append(fields[3])
            
        elif fields[3] in state['data_fields_collected'] and fields[4] not in state['data_fields_collected']:
            state['data'][fields[4]] = "Medium"
            state['data_fields_collected'].append(fields[4])
            
        # Update status if a field was just collected
        if len(state['data_fields_collected']) > data_collected_before:
            state['lead_status'] = "Data Collection In Progress"

    # 5. Quote Generation Check (If all required data is present)
    if len(state['data_fields_collected']) >= len(CONFIG.DATA_FIELDS) and not state["quote_sent"]:
        
        quote_data = generate_dummy_quote(state['data'])
        
        # Send the Quote as a structured event
        yield json.dumps({
            "type": "quote",
            "message": "Non-Binding Quote Estimate Ready",
            "quote_details": quote_data,
            "timestamp": time.time(),
            "model": "system"
        }) + "\n\n"
        
        state["quote_sent"] = True
        state["lead_status"] = "Quote Sent - Awaiting Confirmation"
        
        # Follow up question to confirm interest (PROFESSIONAL TONE)
        follow_up = "Are you interested in proceeding with this estimated quote? (Reply Yes/No)"
        
        # Stream the follow up question
        words = follow_up.split(' ')
        for word in words:
            yield json.dumps({
                "type": "text",
                "content": word + " ",
                "timestamp": time.time(),
                "model": "system_followup"
            }) + "\n\n"
            await asyncio.sleep(0.05)
        
        response_content += follow_up

    # 6. Final Status Check & Persistence
    final_status = check_lead_status(prompt, state)
    state["lead_status"] = final_status

    # Persist the final state for this turn
    update_lead_state(session_id, state)
    
    # Yield the final status check
    yield json.dumps({
        "type": "status_check",
        "lead_status": final_status,
        "message": f"Lead qualification: {final_status}",
        "data_collected": state["data"],
        "timestamp": time.time(),
        "model": model_used
    }) + "\n\n"


# --- FASTAPI ENDPOINTS (Unchanged) ---

@app.get("/")
async def root():
    logger.info("🌐 Root endpoint accessed")
    return JSONResponse(
        content={
            "status": "ready", 
            "message": "SecureSights Lead Nurturing Agent API",
            "persistence": "SQLite3",
            "db_file": CONFIG.DB_FILE
        }
    )

@app.get("/api/stream")
async def stream_response(
    prompt: str, 
    session_id: str = Query(None, description="Unique ID for the conversation session")
):
    """Main streaming endpoint with conversation tracking and lead qualification."""
    
    if not session_id or not get_lead_state(session_id):
        # Auto-create new session if ID is missing or not found in DB
        new_id = str(uuid.uuid4())
        initialize_new_session_state(new_id)
        session_id = new_id
        logger.info(f"🆕 Auto-generated and initialized new session: {session_id}")
    
    async def event_generator():
        # Send start message and session ID
        start_data = json.dumps({
            "type": "start", 
            "message": f"Processing: {prompt[:30]}...", 
            "session_id": session_id,
            "timestamp": time.time()
        })
        yield f"data: {start_data}\n\n"
        
        char_count = 0
        final_status = "Error"
        final_model = "system"

        try:
            # Stream actual response, quote, and status checks
            async for chunk in stream_openrouter_response(prompt, session_id):
                chunk_data = json.loads(chunk)
                
                if chunk_data.get("type") == "text":
                    content = chunk_data.get("content", "")
                    char_count += len(content)
                    final_model = chunk_data.get('model', final_model)
                elif chunk_data.get("type") == "status_check":
                    final_status = chunk_data.get("lead_status", final_status)
                    final_model = chunk_data.get('model', final_model)

                yield f"data: {chunk}\n\n"
            
            # Final Completion message
            complete_data = json.dumps({
                "type": "complete", 
                "message": f"Stream completed. Status: {final_status}", 
                "timestamp": time.time(),
                "model": final_model,
                "total_chars": char_count,
                "lead_status": final_status
            })
            yield f"data: {complete_data}\n\n"
                
        except Exception as e:
            error_data = json.dumps({
                "type": "error", 
                "message": str(e), 
                "timestamp": time.time()
            })
            logger.error(f"❌ Error in event_generator: {e}")
            yield f"data: {error_data}\n\n"
    
    # Return streaming response
    response = StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
    )
    
    # Add CORS/Streaming headers
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Cache-Control"] = "no-cache"
    response.headers["Connection"] = "keep-alive"
    response.headers["X-Accel-Buffering"] = "no"
    
    return response

def initialize_new_session_state(new_id: str):
    """Initializes and persists a new session's state and history."""
    
    initial_state = {
        "data": {}, 
        "data_fields_collected": [], 
        "quote_sent": False, 
        "lead_status": "Neutral"
    }
    update_lead_state(new_id, initial_state)
    
    # Add initial system prompt to history
    add_message_to_history(new_id, "system", CONFIG.get_system_prompt())

@app.get("/api/new_session")
async def new_session():
    """Generates a new session ID for a fresh start."""
    new_id = str(uuid.uuid4())
    initialize_new_session_state(new_id)
    
    logger.info(f"✨ Created and initialized new session: {new_id}")
    return {"session_id": new_id, "message": "New session created and persisted to SQLite."}

@app.get("/api/lead_data")
async def get_lead_data(session_id: str):
    """Retrieve the collected lead data and current status for a given session ID from SQLite."""
    state = get_lead_state(session_id)
    if not state:
        return JSONResponse(
            content={"message": "Session not found or expired.", "session_id": session_id},
            status_code=404
        )
        
    history = get_conversation_history(session_id)
    
    return JSONResponse(
        content={
            "session_id": session_id,
            "lead_state": state,
            "history_length": len(history),
            "timestamp": time.time()
        }
    )

if __name__ == "__main__":
    import uvicorn
    logger.info("🚀 Starting SecureSights Lead Nurturing Agent (SQLite Persistence) on http://localhost:8001")
    uvicorn.run(
        app, 
        host="0.0.0.0", 
        port=8001,
        log_level="info",
        access_log=True
    )