
import asyncio
import json
import logging
import sys
import httpx
import websockets

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

API_URL = "http://localhost:8000/api"
WS_URL = "ws://localhost:8000/ws"
USER_ID = "console_user_test"

async def main():
    async with httpx.AsyncClient() as client:
        # 1. Login
        logger.info("Logging in...")
        resp = await client.post(f"{API_URL}/user/login", json={"user_id": USER_ID})
        if resp.status_code != 200:
            logger.error(f"Login failed: {resp.text}")
            return

        data = resp.json()
        session_id = data["session"]["session_id"]
        logger.info(f"Logged in. Session ID: {session_id}")
        
        # 2. Connect WebSocket
        ws_url = f"{WS_URL}?user_id={USER_ID}&session_id={session_id}"
        logger.info(f"Connecting to {ws_url}...")
        
        async with websockets.connect(ws_url) as ws:
            logger.info("Connected to WebSocket.")
            
            # 3. Send message to trigger assessment
            logger.info("Sending trigger message...")
            await ws.send(json.dumps({
                "type": "chat_message",
                "content": "Please generate the assessment."
            }))
            
            # 4. Wait for response
            while True:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=60.0)
                    data = json.loads(msg)
                    logger.info(f"Received: {data['type']}")
                    if data['type'] == 'assessment_recommendations':
                        logger.info("SUCCESS: Received recommendations!")
                        break
                    if data['type'] == 'error':
                        logger.error(f"Error: {data}")
                        break
                except asyncio.TimeoutError:
                    logger.error("Timeout waiting for response.")
                    break

if __name__ == "__main__":
    asyncio.run(main())
