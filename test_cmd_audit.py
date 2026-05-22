import os
os.environ["GOOGLE_API_USE_CLIENT_CERTIFICATE"] = "false"
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "true"
os.environ["GOOGLE_CLOUD_PROJECT"] = "shade-sandbox"
os.environ["GOOGLE_CLOUD_LOCATION"] = "us-central1"

import asyncio
import json
from google.adk.runners import Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.adk.artifacts.in_memory_artifact_service import InMemoryArtifactService
from google.adk.memory.in_memory_memory_service import InMemoryMemoryService
from google.genai import types
from dotenv import load_dotenv

# Load package environment variables
load_dotenv()

from ge_fileagent.agent import root_agent, route_document_tool

async def main():
    
    # Inject JIRA credentials from package .env
    if "JIRA_API_TOKEN" not in os.environ:
        raise ValueError("JIRA_API_TOKEN must be configured in the .env file.")
        
    # Inject GCS buckets if not set
    if "NESS_PROCESSED_DOCS_BUCKET" not in os.environ:
        os.environ["NESS_PROCESSED_DOCS_BUCKET"] = "gamestop-processed-docs-shade-sandbox"
        os.environ["NESS_HUMAN_REVIEW_BUCKET"] = "gamestop-review-docs-shade-sandbox"
        
    # Setup the plain ADK Runner
    runner = Runner(
        app_name="GeFileAgent",
        agent=root_agent,
        artifact_service=InMemoryArtifactService(),
        session_service=InMemorySessionService(),
        memory_service=InMemoryMemoryService()
    )
    
    # Create the test session
    session = await runner.session_service.create_session(app_name=runner.app_name, user_id="test_user")
    
    # Load the sample receipt image file
    sample_filepath = "/usr/local/google/home/elhadik/gamestop_invoice/sample_receipt.png"
    print(f"[Test CLI] Loading local sample receipt file: {sample_filepath}")
    with open(sample_filepath, "rb") as f:
        img_bytes = f.read()
        
    # Save the file into the session's artifact service
    part = types.Part.from_bytes(data=img_bytes, mime_type="image/png")
    await runner.artifact_service.save_artifact(
        app_name=runner.app_name,
        user_id="test_user",
        session_id=session.id,
        filename="sample_receipt.png",
        artifact=part
    )
    print("[Test CLI] Sample receipt successfully saved to session artifact storage.")

    print("\n=== CASE 1: Running complete in-memory audit pipeline (Expected Score: 3) ===")
    new_message = types.Content(
        role="user",
        parts=[types.Part.from_text(text="Analyze the uploaded invoice and run audit pipeline")]
    )
    
    final_text_pieces = []
    async for event in runner.run_async(user_id="test_user", session_id=session.id, new_message=new_message):
        if event.is_final_response():
            if event.content and event.content.parts:
                final_text_pieces.extend([p.text for p in event.content.parts if p.text])
                
    print("--- CASE 1 Result Report ---")
    print("".join(final_text_pieces))
    print("----------------------------")

    print("\n=== CASE 2: Simulating Validation Audit Failure (Score: 2) ===")
    print("[Test CLI] Triggering route_document_tool programmatically with validation failure score 2...")
    
    discrepancy_criteria = "Auditor Alert: Store total total mismatch. Visual receipt displays Total $47.08, but Document AI extracted $4.29."
    routing_res_json = await route_document_tool(
        filename="sample_receipt.png",
        mime_type="image/png",
        score=2,
        criteria=discrepancy_criteria,
        data_bytes=img_bytes
    )
    
    print("\n--- CASE 2 Result (JIRA Routing Payload) ---")
    print(json.dumps(json.loads(routing_res_json), indent=4))
    print("---------------------------------------------")

if __name__ == "__main__":
    asyncio.run(main())
