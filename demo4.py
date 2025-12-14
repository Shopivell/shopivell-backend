from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import json
import aiohttp
import time
import asyncio
from typing import AsyncGenerator, List
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["*"]
)

# Your OpenRouter API Key
OPENROUTER_API_KEY = "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"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# List of models to try (free models that are less likely to be rate-limited)
MODELS = [
    "google/gemini-2.0-flash-exp:free",  # Try first
    "google/gemini-2.0-flash:free",      # Alternative Gemini
    "meta-llama/llama-3.2-3b-instruct:free",  # Llama as fallback
    "qwen/qwen-2.5-32b-instruct:free",   # Another free option
    "microsoft/phi-3.5-mini-instruct:free",  # Lightweight option
]

# Mock responses for testing when all models fail
MOCK_RESPONSES = {
    "What is life?": "Life is the condition that distinguishes organisms from inorganic matter, including growth, reproduction, functional activity, and continual change preceding death.",
    "What is food?": "Food is any substance consumed to provide nutritional support for an organism, usually of plant or animal origin.",
    "Explain quantum physics simply": "Quantum physics is the study of very small particles where things can be in multiple states at once until observed.",
    "Tell me a joke": "Why don't scientists trust atoms? Because they make up everything!",
    "What is artificial intelligence?": "AI is the simulation of human intelligence in machines that are programmed to think and learn.",
    "How to make coffee?": "1. Boil water 2. Add coffee grounds to filter 3. Pour hot water over grounds 4. Enjoy!"
}

async def try_model_stream(prompt: str, model: str) -> AsyncGenerator[str, None]:
    """Try streaming from a specific model"""
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:3000",
        "X-Title": "Streaming Test"
    }
    
    # System prompt to limit response length
    system_prompt = "Keep your response concise and under 200 characters."
    
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ],
        "stream": True,
        "max_tokens": 100  # Very short responses to avoid rate limits
    }
    
    try:
        logger.info(f"🔄 Trying model: {model}")
        
        timeout = aiohttp.ClientTimeout(total=15)  # Shorter timeout
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
                    raise Exception(f"Model {model} error {response.status}")
                
                total_chars = 0
                char_limit = 200
                
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
                                            if total_chars + len(content) > char_limit:
                                                remaining = char_limit - total_chars
                                                if remaining > 0:
                                                    content = content[:remaining]
                                                else:
                                                    return
                                            
                                            total_chars += len(content)
                                            yield json.dumps({
                                                "type": "text",
                                                "content": content,
                                                "timestamp": time.time(),
                                                "model": model,
                                                "total_chars": total_chars
                                            })
                                            
                                except:
                                    continue
                
                logger.info(f"✅ Model {model} returned {total_chars} chars")
                
    except asyncio.TimeoutError:
        raise Exception(f"Model {model} timeout")
    except Exception as e:
        raise Exception(f"Model {model} failed: {str(e)}")

async def stream_openrouter_response(prompt: str) -> AsyncGenerator[str, None]:
    """Try multiple models with fallback"""
    logger.info(f"🔍 Trying to stream response for: '{prompt[:50]}...'")
    
    # Try each model in order
    for model in MODELS:
        try:
            logger.info(f"🎯 Attempting with model: {model}")
            
            async for chunk in try_model_stream(prompt, model):
                yield chunk
                return  # Success, stop trying other models
            
        except Exception as e:
            logger.warning(f"⚠️ Model {model} failed: {e}")
            await asyncio.sleep(0.5)  # Small delay between attempts
            continue
    
    # If all models fail, use mock response
    logger.warning("⚠️ All models failed, using mock response")
    
    # Find closest mock response
    mock_response = MOCK_RESPONSES.get(prompt)
    if not mock_response:
        # Find a similar question
        for key in MOCK_RESPONSES:
            if any(word in prompt.lower() for word in key.lower().split()):
                mock_response = MOCK_RESPONSES[key]
                break
    
    if not mock_response:
        mock_response = "I'm currently experiencing high demand. Please try again in a moment."
    
    # Stream mock response character by character
    logger.info(f"🤖 Streaming mock response: {mock_response[:50]}...")
    
    words = mock_response.split(' ')
    current_text = ""
    
    for word in words:
        current_text += (" " if current_text else "") + word
        yield json.dumps({
            "type": "text",
            "content": word + " ",
            "timestamp": time.time(),
            "model": "mock",
            "is_mock": True
        })
        await asyncio.sleep(0.05)  # Simulate streaming
    
    logger.info("✅ Mock response completed")

@app.get("/")
async def root():
    logger.info("🌐 Root endpoint accessed")
    return JSONResponse(
        content={
            "status": "ready", 
            "message": "OpenRouter Streaming API",
            "available_models": MODELS,
            "note": "System will try multiple models with fallback"
        },
        headers={
            "Access-Control-Allow-Origin": "http://localhost:3000",
            "Access-Control-Allow-Credentials": "true"
        }
    )

@app.get("/api/stream")
async def stream_response(prompt: str):
    """Main streaming endpoint"""
    logger.info(f"🎯 Stream endpoint called with prompt: '{prompt}'")
    
    async def event_generator():
        # Send start message
        start_data = json.dumps({
            "type": "start", 
            "message": f"Processing: {prompt[:30]}...", 
            "timestamp": time.time()
        })
        logger.info("🚀 Sending start event")
        yield f"data: {start_data}\n\n"
        
        try:
            char_count = 0
            model_used = "unknown"
            
            # Stream actual response
            async for chunk in stream_openrouter_response(prompt):
                chunk_data = json.loads(chunk)
                
                if chunk_data.get("type") == "text":
                    content = chunk_data.get("content", "")
                    char_count += len(content)
                    model_used = chunk_data.get("model", "unknown")
                    
                    if char_count > 250:  # Safety limit
                        logger.warning(f"⚠️ Character limit reached: {char_count}")
                        break
                
                yield f"data: {chunk}\n\n"
            
            # Send completion
            complete_data = json.dumps({
                "type": "complete", 
                "message": f"Stream completed. Model: {model_used}, Chars: {char_count}", 
                "timestamp": time.time(),
                "model": model_used,
                "total_chars": char_count
            })
            logger.info(f"✅ Stream completed. Model: {model_used}, Chars: {char_count}")
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
    
    # Add CORS headers
    response.headers["Access-Control-Allow-Origin"] = "http://localhost:3000"
    response.headers["Access-Control-Allow-Credentials"] = "true"
    response.headers["Cache-Control"] = "no-cache"
    response.headers["Connection"] = "keep-alive"
    response.headers["X-Accel-Buffering"] = "no"
    
    return response

@app.get("/api/status")
async def status():
    """Check API status and available models"""
    return {
        "status": "operational",
        "backend": "running",
        "models_available": MODELS,
        "fallback_enabled": True,
        "timestamp": time.time()
    }

@app.get("/api/test")
async def test_stream():
    """Simple test endpoint that returns mock data immediately"""
    async def test_generator():
        yield f"data: {json.dumps({'type': 'start', 'message': 'Test stream', 'timestamp': time.time()})}\n\n"
        
        test_response = "This is a test response from the streaming API. If you can see this text appearing word by word, your streaming setup is working correctly!"
        
        words = test_response.split(' ')
        for word in words:
            yield f"data: {json.dumps({'type': 'text', 'content': word + ' ', 'timestamp': time.time()})}\n\n"
            await asyncio.sleep(0.05)
        
        yield f"data: {json.dumps({'type': 'complete', 'message': 'Test completed', 'timestamp': time.time()})}\n\n"
    
    response = StreamingResponse(
        test_generator(),
        media_type="text/event-stream",
    )
    
    response.headers["Access-Control-Allow-Origin"] = "http://localhost:3000"
    response.headers["Access-Control-Allow-Credentials"] = "true"
    
    return response

if __name__ == "__main__":
    import uvicorn
    logger.info("🚀 Starting FastAPI server on http://localhost:8001")
    logger.info(f"📋 Available models: {MODELS}")
    logger.info("🔄 System will try models in order with mock fallback")
    
    uvicorn.run(
        app, 
        host="0.0.0.0", 
        port=8001,
        log_level="info",
        access_log=True
    )