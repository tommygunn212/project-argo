#!/usr/bin/env python3
"""
Test FastAPI app to verify server infrastructure
"""

from fastapi import FastAPI
import uvicorn

app = FastAPI(title="Test Server")

@app.get("/")
async def root():
    """Simple test endpoint"""
    return {"status": "ok", "message": "Server is running"}

@app.get("/ping")
async def ping():
    """Ping endpoint"""
    return {"pong": True}

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8001, log_level="info")
