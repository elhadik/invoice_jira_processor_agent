import os
print("MOCK SCRIPT INITIALIZING")
from dotenv import load_dotenv

# Load env file (located in parent folder)
current_dir = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(current_dir, "../.env")
load_dotenv(dotenv_path=env_path)

os.environ["GOOGLE_API_USE_CLIENT_CERTIFICATE"] = "false"
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "true"
os.environ["GOOGLE_CLOUD_PROJECT"] = "shade-sandbox"
os.environ["GOOGLE_CLOUD_LOCATION"] = "us-central1"

# Inject JIRA credentials from package .env
if "JIRA_API_TOKEN" not in os.environ:
    raise ValueError("JIRA_API_TOKEN must be configured in the .env file.")
os.environ["NESS_PROCESSED_DOCS_BUCKET"] = "gamestop-processed-docs-shade-sandbox"
os.environ["NESS_HUMAN_REVIEW_BUCKET"] = "gamestop-review-docs-shade-sandbox"

import asyncio
import json
from unittest.mock import patch
from google.adk.runners import Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.adk.artifacts.in_memory_artifact_service import InMemoryArtifactService
from google.adk.memory.in_memory_memory_service import InMemoryMemoryService
from google.genai import types
from ge_fileagent.agent import root_agent, route_document_tool

# Pre-defined mock responses
MOCK_EXTRACTION = {
    "document_type": "Receipt",
    "entities": [
        {"type": "supplier_name", "mention_text": "GROCERY MART"},
        {"type": "total_amount", "mention_text": "$47.08"}
    ],
    "line_items": [
        {"description": "GAL WHOLE MILK", "quantity": "1", "amount": "$4.29"}
    ],
    "raw_text_summary": "GROCERY MART TOTAL $47.08"
}

MOCK_VALIDATION_FAIL = {
    "confidence_score": 2,
    "criteria_met": "Auditor Alert: Total mismatch. Visual receipt displays Total $47.08, but Document AI extracted $4.29.",
    "extracted_values": {
        "Merchant": "GROCERY MART",
        "Date": "10/26/23",
        "Total": "47.08",
        "Tax": "1.45"
    }
}

async def main():
    # Setup the plain ADK Runner
    runner = Runner(
        app_name="GeFileAgent",
        agent=root_agent,
        artifact_service=InMemoryArtifactService(),
        session_service=InMemorySessionService(),
        memory_service=InMemoryMemoryService()
    )
    
    session = await runner.session_service.create_session(app_name=runner.app_name, user_id="test_user")
    
    # Save mock file into session artifact storage
    part = types.Part.from_bytes(data=b"mock_image_bytes", mime_type="image/png")
    await runner.artifact_service.save_artifact(
        app_name=runner.app_name,
        user_id="test_user",
        session_id=session.id,
        filename="sample_invoice.png",
        artifact=part
    )

    print("\n=== MOCK TEST: Simulating validation failure (Expected Score: 2) ===")
    print("[Test CLI] Mocking document parser and gemini validation client calls...")
    
    # Mock all slow Vertex AI and GCS network client dependencies!
    with patch("ge_fileagent.agent.parse_document", return_value=MOCK_EXTRACTION), \
         patch("ge_fileagent.agent.analyze_receipt_with_gemini", return_value=MOCK_VALIDATION_FAIL), \
         patch("ge_fileagent.agent.storage.Client"):
         
         new_message = types.Content(
             role="user",
             parts=[types.Part.from_text(text="Analyze the uploaded invoice and run audit pipeline")]
         )
         
         final_text_pieces = []
         async for event in runner.run_async(user_id="test_user", session_id=session.id, new_message=new_message):
             if event.get_function_calls():
                 for fc in event.get_function_calls():
                     print(f"\n⚡ Agent requested tool call: {fc.name}")
             if event.get_function_responses():
                 for fr in event.get_function_responses():
                     print(f"✅ Tool response received: {fr.name}")
             if event.is_final_response():
                 if event.content and event.content.parts:
                     final_text_pieces.extend([p.text for p in event.content.parts if p.text])
                     
         print("\n--- Final Orchestrator Report ---")
         print("".join(final_text_pieces))
         print("---------------------------------")

if __name__ == "__main__":
    asyncio.run(main())
