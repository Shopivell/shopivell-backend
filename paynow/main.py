from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import time
from paynow import Paynow
import uvicorn
import sys
import os

app = FastAPI(title="Paynow Payment Gateway")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Paynow Configuration
INTEGRATION_ID = "22701"
INTEGRATION_KEY = "34f9dddf-4012-4556-a7c6-5a32f0f537ca"

# Initialize Paynow with FastAPI endpoints
paynow = Paynow(
    INTEGRATION_ID,
    INTEGRATION_KEY,
    'http://localhost:8000/paynow-return',      # Return URL
    'http://localhost:8000/paynow-webhook'      # Webhook/Result URL
)

# Store payment sessions (in production, use Redis or database)
payment_sessions = {}

@app.get("/", response_class=HTMLResponse)
async def home():
    """Home page with payment form"""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Paynow Payment Gateway</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                max-width: 500px;
                margin: 50px auto;
                padding: 20px;
            }
            .form-group {
                margin-bottom: 15px;
            }
            label {
                display: block;
                margin-bottom: 5px;
                font-weight: bold;
            }
            input, select {
                width: 100%;
                padding: 8px;
                border: 1px solid #ddd;
                border-radius: 4px;
                box-sizing: border-box;
            }
            button {
                background-color: #4CAF50;
                color: white;
                padding: 12px 20px;
                border: none;
                border-radius: 4px;
                cursor: pointer;
                width: 100%;
                font-size: 16px;
            }
            button:hover {
                background-color: #45a049;
            }
            .container {
                background-color: #f9f9f9;
                padding: 20px;
                border-radius: 8px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            }
            small {
                color: #666;
                font-size: 12px;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Pay with EcoCash</h1>
            <form action="/initiate-payment" method="post">
                <div class="form-group">
                    <label for="email">Email:</label>
                    <input type="email" id="email" name="email" value="farairhato@gmail.com" required>
                </div>
                
                <div class="form-group">
                    <label for="phone">Phone Number:</label>
                    <input type="tel" id="phone" name="phone" value="0781276999" required>
                    <small>Format: 0781276999 (will be converted to 263781276999)</small>
                </div>
                
                <div class="form-group">
                    <label for="amount">Amount (USD):</label>
                    <input type="number" id="amount" name="amount" step="0.01" value="0.10" min="0.10" required>
                </div>
                
                <div class="form-group">
                    <label for="description">Description:</label>
                    <input type="text" id="description" name="description" value="Payment for products">
                </div>
                
                <button type="submit">Pay Now with EcoCash</button>
            </form>
            
            <div style="margin-top: 30px; padding-top: 20px; border-top: 1px solid #ddd;">
                <h3>Test Endpoints:</h3>
                <ul>
                    <li><a href="/test-payment">Quick Test Payment ($0.10)</a></li>
                    <li><a href="/payments">View All Payment Sessions</a></li>
                    <li><a href="/docs">API Documentation</a></li>
                </ul>
            </div>
        </div>
    </body>
    </html>
    """

@app.post("/initiate-payment", response_class=HTMLResponse)
async def initiate_payment(
    email: str = Form(...),
    phone: str = Form(...),
    amount: float = Form(...),
    description: str = Form("Payment for goods")
):
    """Initiate a mobile payment"""
    
    # Format phone number (remove leading zero, add country code if needed)
    formatted_phone = phone
    if phone.startswith('0'):
        formatted_phone = '263' + phone[1:]  # Zimbabwe format
    
    # Create payment
    payment = paynow.create_payment(f"Order-{int(time.time())}", email)
    payment.add(description, amount)
    
    # Send mobile payment (using EcoCash as default)
    response = paynow.send_mobile(payment, formatted_phone, 'ecocash')
    
    if response.success:
        # Store session
        session_id = response.poll_url.split('/')[-1]
        payment_sessions[session_id] = {
            "poll_url": response.poll_url,
            "email": email,
            "phone": formatted_phone,
            "amount": amount,
            "status": "initiated",
            "timestamp": time.time(),
            "original_phone": phone
        }
        
        # Return status page
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Payment Initiated</title>
            <style>
                body {{ font-family: Arial, sans-serif; max-width: 600px; margin: 50px auto; padding: 20px; }}
                .status {{ padding: 20px; background-color: #fff3cd; border: 1px solid #ffeaa7; border-radius: 5px; }}
                button {{ padding: 10px 20px; margin: 5px; cursor: pointer; }}
                .success {{ background-color: #d4edda; color: #155724; padding: 15px; border-radius: 5px; }}
                .pending {{ background-color: #fff3cd; color: #856404; padding: 15px; border-radius: 5px; }}
            </style>
        </head>
        <body>
            <h1>✅ Payment Initiated Successfully!</h1>
            
            <div class="status">
                <h2>Check Your Phone</h2>
                <p>A payment request of <strong>${amount:.2f}</strong> has been sent to:</p>
                <p><strong>Phone:</strong> {formatted_phone}</p>
                <p><strong>Email:</strong> {email}</p>
                <p><strong>Description:</strong> {description}</p>
                <p>Please check your EcoCash menu and authorize the payment.</p>
            </div>
            
            <div style="margin-top: 30px;">
                <button onclick="checkStatus()">Check Payment Status</button>
                <button onclick="window.location.href='/'">Make Another Payment</button>
            </div>
            
            <div id="status-result" style="margin-top: 20px; padding: 10px; display: none;"></div>
            
            <script>
                async function checkStatus() {{
                    try {{
                        const response = await fetch('/api/check-status/{session_id}');
                        const data = await response.json();
                        
                        const resultDiv = document.getElementById('status-result');
                        resultDiv.style.display = 'block';
                        
                        if(data.paid) {{
                            resultDiv.innerHTML = `
                                <div class="success">
                                    <h3>✅ Payment Successful!</h3>
                                    <p>Amount: $${data.amount}</p>
                                    <p>Status: ${data.status}</p>
                                    <p>Reference: ${data.reference}</p>
                                </div>
                            `;
                        }} else {{
                            resultDiv.innerHTML = `
                                <div class="pending">
                                    <h3>⏳ Waiting for Payment</h3>
                                    <p>Current Status: ${data.status}</p>
                                    <p>Please authorize the payment on your phone.</p>
                                    <button onclick="checkStatus()">Check Again</button>
                                </div>
                            `;
                        }}
                    }} catch (error) {{
                        console.error('Error checking status:', error);
                        resultDiv.innerHTML = '<div style="background-color: #f8d7da; padding: 15px; border-radius: 5px;">Error checking status. Please try again.</div>';
                    }}
                }}
                
                // Auto-check every 10 seconds
                setInterval(checkStatus, 10000);
            </script>
        </body>
        </html>
        """
    else:
        return f"""
        <html>
            <body style="font-family: Arial; margin: 50px;">
                <h2 style="color: #dc3545;">❌ Payment Failed</h2>
                <p>Error: {response.error}</p>
                <a href="/"><button>Try Again</button></a>
            </body>
        </html>
        """

@app.get("/payment-status/{session_id}", response_class=HTMLResponse)
async def payment_status(session_id: str):
    """Check payment status page"""
    if session_id not in payment_sessions:
        return """
        <html>
            <body style="font-family: Arial; margin: 50px;">
                <h2>Session Not Found</h2>
                <p>The payment session was not found or has expired.</p>
                <a href="/"><button>Back to Home</button></a>
            </body>
        </html>
        """
    
    session = payment_sessions[session_id]
    status = paynow.check_transaction_status(session["poll_url"])
    
    # Update session
    payment_sessions[session_id]["status"] = status.status
    payment_sessions[session_id]["paid"] = status.paid
    
    status_color = "#d4edda" if status.paid else "#fff3cd" if status.status == 'sent' else "#f8d7da"
    status_text = "✅ PAID" if status.paid else f"⏳ {status.status.upper()}"
    
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Payment Status</title>
        <style>
            body {{ font-family: Arial, sans-serif; max-width: 600px; margin: 50px auto; padding: 20px; }}
            .status {{ padding: 20px; border-radius: 5px; margin: 20px 0; }}
            button {{ padding: 10px 20px; margin: 5px; cursor: pointer; }}
        </style>
    </head>
    <body>
        <h1>Payment Status</h1>
        
        <div class="status" style="background-color: {status_color};">
            <h2>{status_text}</h2>
            <p><strong>Amount:</strong> ${session['amount']:.2f}</p>
            <p><strong>Phone:</strong> {session['original_phone']}</p>
            <p><strong>Email:</strong> {session['email']}</p>
            <p><strong>Status:</strong> {status.status}</p>
            <p><strong>Paid:</strong> {'Yes' if status.paid else 'No'}</p>
            <p><strong>Time:</strong> {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(session['timestamp']))}</p>
        </div>
        
        <div>
            <button onclick="window.location.href='/'">Back to Home</button>
            <button onclick="window.location.reload()">Refresh Status</button>
        </div>
        
        {"<script>setTimeout(() => { window.location.reload(); }, 10000);</script>" if not status.paid else ""}
    </body>
    </html>
    """

@app.get("/api/check-status/{session_id}")
async def api_check_status(session_id: str):
    """API endpoint to check payment status (for AJAX polling)"""
    if session_id not in payment_sessions:
        return JSONResponse({"error": "Session not found"}, status_code=404)
    
    session = payment_sessions[session_id]
    status = paynow.check_transaction_status(session["poll_url"])
    
    # Update session
    payment_sessions[session_id]["status"] = status.status
    payment_sessions[session_id]["paid"] = status.paid
    
    return {
        "session_id": session_id,
        "status": status.status,
        "paid": status.paid,
        "amount": float(status.amount) if hasattr(status, 'amount') else session["amount"],
        "reference": status.reference if hasattr(status, 'reference') else None,
        "message": "Payment successful!" if status.paid else "Waiting for payment authorization..."
    }

@app.get("/paynow-return")
async def paynow_return(
    status: str = None,
    reference: str = None,
    pollurl: str = None
):
    """Return URL where users are redirected after payment attempt"""
    session_id = pollurl.split('/')[-1] if pollurl else None
    
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Payment Return</title>
        <style>
            body {{ font-family: Arial, sans-serif; max-width: 600px; margin: 50px auto; padding: 20px; }}
        </style>
    </head>
    <body>
        <h1>Payment Return Page</h1>
        
        <div style="padding: 20px; border: 1px solid #ddd; margin: 20px 0; border-radius: 5px;">
            <h2>Payment Details</h2>
            <p><strong>Status:</strong> {status or "Unknown"}</p>
            <p><strong>Reference:</strong> {reference or "No reference"}</p>
    """
    
    if session_id:
        html_content += f'<p><a href="/payment-status/{session_id}"><button>Check Detailed Status</button></a></p>'
    
    html_content += """
        </div>
        
        <a href="/"><button>Back to Home</button></a>
    </body>
    </html>
    """
    
    return HTMLResponse(html_content)

@app.post("/paynow-webhook")
async def paynow_webhook(request: Request):
    """Webhook endpoint for Paynow to send payment updates"""
    try:
        # Parse form data from Paynow
        form_data = await request.form()
        data = dict(form_data)
        
        print(f"📥 Paynow Webhook Received: {data}")
        
        # Process webhook data
        # In production, verify the signature and update your database
        
        return JSONResponse({"status": "ok", "message": "Webhook received successfully"})
    except Exception as e:
        print(f"❌ Webhook error: {e}")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=400)

@app.get("/payments")
async def list_payments():
    """List all payment sessions (for testing)"""
    return {
        "total_sessions": len(payment_sessions),
        "sessions": payment_sessions
    }

@app.get("/test-payment")
async def test_payment():
    """Quick test endpoint"""
    test_phone = "263781276999"  # Replace with test number
    test_email = "farairhato@gmail.com"
    
    payment = paynow.create_payment(f"Test-Order-{int(time.time())}", test_email)
    payment.add("Test Product", 0.10)
    
    response = paynow.send_mobile(payment, test_phone, 'ecocash')
    
    if response.success:
        session_id = response.poll_url.split('/')[-1]
        payment_sessions[session_id] = {
            "poll_url": response.poll_url,
            "email": test_email,
            "phone": test_phone,
            "amount": 0.10,
            "status": "initiated",
            "timestamp": time.time(),
            "original_phone": "0781276999"
        }
        
        return {
            "success": True,
            "message": "Test payment initiated",
            "poll_url": response.poll_url,
            "instructions": "Check your phone to authorize payment of $0.10",
            "status_url": f"http://localhost:8000/payment-status/{session_id}",
            "api_status_url": f"http://localhost:8000/api/check-status/{session_id}"
        }
    else:
        return {"success": False, "error": response.error}

@app.get("/clear-sessions")
async def clear_sessions():
    """Clear all payment sessions (for testing)"""
    count = len(payment_sessions)
    payment_sessions.clear()
    return {"message": f"Cleared {count} payment sessions"}

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": time.time(),
        "service": "paynow-fastapi",
        "version": "1.0.0"
    }

# Run the application directly without uvicorn.run() for better compatibility
if __name__ == "__main__":
    print("🚀 Starting Paynow FastAPI Server...")
    print("📱 Access the application at: http://localhost:8000")
    print("📚 API Documentation at: http://localhost:8000/docs")
    print("🔧 Test Payment at: http://localhost:8000/test-payment")
    print("\nPress Ctrl+C to stop the server\n")
    
    # Run uvicorn programmatically without reload for now
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")