import os
import json
import base64
import asyncio
from google.adk.agents import Agent
from google.adk.tools import FunctionTool
from google.adk.tools import load_artifacts
from google.cloud import storage
from ge_fileagent.document_parser import parse_document
from ge_fileagent.gemini_parser import analyze_receipt_with_gemini

# --- JIRA MCP Core Integration ---

def create_jira_ticket_mcp(summary: str, description: str) -> str:
    """Creates a JIRA support ticket using the local mcp-atlassian server or SSE transport."""
    email = os.environ.get("JIRA_EMAIL", "elhadik@google.com")
    api_token = os.environ.get("JIRA_API_TOKEN")
    jira_url = "https://google-team-vwhbosar.atlassian.net"
    
    if not api_token:
        return "Error: JIRA_API_TOKEN environment variable is not set."

    mcp_url = os.environ.get("JIRA_MCP_URL")
    
    from mcp.client.session import ClientSession

    # CASE A: Connect via SSE
    if mcp_url:
        from mcp.client.sse import sse_client
        credentials = f"{email}:{api_token}"
        encoded_credentials = base64.b64encode(credentials.encode()).decode()
        headers = {
            "Authorization": f"Basic {encoded_credentials}",
            "Content-Type": "application/json"
        }

        async def _call_sse():
            async with sse_client(mcp_url, headers=headers) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    result = await session.call_tool("jira_create_issue", {
                        "project_key": "KAN",
                        "summary": summary,
                        "description": description,
                        "issue_type": "Task"
                    })
                    return "\n".join([item.text if hasattr(item, 'text') else str(item) for item in result.content])
        try:
            try:
                loop = asyncio.get_running_loop()
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, _call_sse())
                    return future.result()
            except RuntimeError:
                return asyncio.run(_call_sse())
        except Exception as err:
            return f"Error calling SSE JIRA MCP: {err}"

    # CASE B: Connect via local stdio (Default)
    else:
        from mcp.client.stdio import StdioServerParameters, stdio_client
        binary_path = "/usr/local/google/home/elhadik/NESS_GEMINI/venv/bin/mcp-atlassian"
        if not os.path.exists(binary_path):
            return f"Error: Local mcp-atlassian binary not found at {binary_path}."

        server_params = StdioServerParameters(
            command=binary_path,
            args=[],
            env={
                "JIRA_URL": jira_url,
                "JIRA_USERNAME": email,
                "JIRA_API_TOKEN": api_token,
                "TOOLSETS": "all",
                "PATH": os.environ.get("PATH", "")
            }
        )

        async def _call_stdio():
            async with stdio_client(server_params) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    result = await session.call_tool("jira_create_issue", {
                        "project_key": "KAN",
                        "summary": summary,
                        "description": description,
                        "issue_type": "Task"
                    })
                    return "\n".join([item.text if hasattr(item, 'text') else str(item) for item in result.content])
        try:
            try:
                loop = asyncio.get_running_loop()
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, _call_stdio())
                    return future.result()
            except RuntimeError:
                return asyncio.run(_call_stdio())
        except Exception as err:
            return f"Error calling local STDIO JIRA MCP: {err}"

def create_jira_ticket_tool(summary: str, description: str) -> str:
    """Creates a support ticket in JIRA via Atlassian MCP integration.
    
    Args:
        summary: Brief title of the JIRA ticket.
        description: Detailed description of the issue/discrepancy.
    """
    return create_jira_ticket_mcp(summary, description)

# --- ADK Specialist Agent Definitions ---

# 1. JIRA Support Sub-Agent
jira_agent = Agent(
    name="jira_agent",
    model=os.environ.get("GEMINI_MODEL_NAME", "gemini-2.5-flash"),
    instruction="""You are an expert JIRA support assistant. 
    Your sole task is to use your `create_jira_ticket_tool` to automatically create support tickets in JIRA 
    when requested by other agents, and return the resulting ticket confirmation details.""",
    tools=[FunctionTool(create_jira_ticket_tool)]
)

# --- Specialist Document Routing & Ticketing Tool ---

def route_document_tool(filename: str, mime_type: str, score: int, data_bytes: bytes = None, file_path: str = None) -> str:
    """Routes the processed document to the GCS bucket depending on the score."""
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("PROJECT_ID")
    processed_bucket_name = os.environ.get("NESS_PROCESSED_DOCS_BUCKET") or "shade-sandbox-processed"
    review_bucket_name = os.environ.get("NESS_HUMAN_REVIEW_BUCKET") or "shade-sandbox-review"
    
    routing_status = "Skipped"
    bucket_name = None
    
    if project_id and processed_bucket_name and review_bucket_name:
        try:
            client = storage.Client(project=project_id)
            bucket_name = processed_bucket_name if score == 3 else review_bucket_name
            bucket = client.bucket(bucket_name)
            
            blob = bucket.blob(filename)
            if data_bytes:
                blob.upload_from_string(data_bytes, content_type=mime_type)
            elif file_path:
                blob.upload_from_filename(file_path, content_type=mime_type)
            
            routing_status = "Success"
            print(f"Routed {filename} to GCS bucket: {bucket_name}")
        except Exception as gcs_e:
            print(f"GCS Routing Error: {gcs_e}")
            routing_status = f"Error: {gcs_e}"
    else:
        print("Warning: Missing GCS Env Variables. Routing skipped.")
        routing_status = "Missing Config"
        
    return json.dumps({
        "status": routing_status,
        "bucket": bucket_name,
        "score": score
    })

# --- Rest of Multi-Agent Pipeline ---

def extract_data_tool(file_path: str = None, data_bytes: bytes = None, mime_type: str = "application/pdf") -> str:
    """Parses the invoice/receipt document to extract key entities and line items."""
    data = parse_document(file_path=file_path, data_bytes=data_bytes, mime_type=mime_type)
    return json.dumps(data)

def validate_data_tool(file_path: str = None, data_bytes: bytes = None, mime_type: str = "application/pdf", extraction_results_json: str = "{}") -> str:
    """Validates the extracted entities against the original document image/PDF."""
    extraction_results = json.loads(extraction_results_json)
    data = analyze_receipt_with_gemini(file_path=file_path, data_bytes=data_bytes, document_ai_result=extraction_results, mime_type=mime_type)
    return json.dumps(data)

def run_adk_orchestrator(filename: str, mime_type: str, data_bytes: bytes = None, file_path: str = None) -> dict:
    """Triggers the sequential multi-agent pipeline to analyze, audit, and route the invoice."""
    # 1. Extract Data
    print("[Orchestrator] Delegating to Data Extraction logic...")
    extracted_json = extract_data_tool(file_path=file_path, data_bytes=data_bytes, mime_type=mime_type)
    extracted_data = json.loads(extracted_json)
    
    # 2. Validate Data
    print("[Orchestrator] Delegating to Validation logic...")
    validation_json = validate_data_tool(file_path=file_path, data_bytes=data_bytes, mime_type=mime_type, extraction_results_json=extracted_json)
    validation_data = json.loads(validation_json)
    
    # 3. Score & Route Document
    print("[Orchestrator] Delegating to Routing logic...")
    score = validation_data.get("confidence_score", 0)
    routing_json = route_document_tool(filename=filename, mime_type=mime_type, score=score, data_bytes=data_bytes, file_path=file_path)
    routing_data = json.loads(routing_json)
    
    # 4. Synthesize final payload
    payload = extracted_data
    payload["gemini_analysis"] = validation_data
    payload["gcs_routing"] = routing_data
    
    return payload

# --- ADK Tool for File Artifact Processing ---

async def analyze_uploaded_invoice(tool_context=None) -> str:
    """Finds the user's uploaded invoice or receipt file and runs the full multi-agent extraction, audit, and routing pipeline on it completely in-memory."""
    if not tool_context:
        return "Error: No tool context available."
        
    part = None
    filename = None
    
    # 1. Try listing formal artifacts (staged uploads)
    artifact_keys = await tool_context.list_artifacts()
    if artifact_keys:
        filename = artifact_keys[-1]
        part = await tool_context.load_artifact(filename)
    
    # 2. Fallback: Search the session history events for any file part sent by the user
    if not part:
        session_events = tool_context.session.events
        for event in reversed(session_events):
            if event.author == "user" and event.content and event.content.parts:
                for p in event.content.parts:
                    if p.inline_data or p.file_data:
                        part = p
                        filename = "uploaded_document"
                        print(f"[Orchestrator Tool] Found file part in user message history: {filename}")
                        break
            if part:
                break
                
    if not part:
        return "Error: No invoice uploaded yet. Please upload or drag-and-drop a file or image first."
        
    mime_type = "application/pdf"
    data_bytes = None
    
    if part.inline_data:
        mime_type = part.inline_data.mime_type
        data_bytes = part.inline_data.data
    elif part.file_data and part.file_data.file_uri:
        mime_type = part.file_data.mime_type
        file_uri = part.file_data.file_uri
        print(f"[Orchestrator Tool] Loading GCS artifact: {file_uri}")
        
        from google.cloud import storage
        try:
            client = storage.Client()
            if file_uri.startswith("gs://"):
                path_parts = file_uri[5:].split("/", 1)
                bucket_name = path_parts[0]
                blob_name = path_parts[1]
                bucket = client.bucket(bucket_name)
                blob = bucket.blob(blob_name)
                data_bytes = blob.download_as_bytes()
        except Exception as gcs_read_e:
            return f"Error: Failed to download artifact from GCS: {gcs_read_e}"
    
    if not data_bytes:
        return f"Error: Failed to load data content for file {filename}."
        
    # 3. Run the orchestrator pipeline completely in-memory (No temporary files!)
    print(f"[Orchestrator Tool] Analyzing uploaded file in-memory: {filename} ({mime_type})")
    result = run_adk_orchestrator(filename=filename, mime_type=mime_type, data_bytes=data_bytes)
    return json.dumps(result, indent=4)

# --- ADK Specialist Agent Definitions ---

# Specialist Data Extractor Agent
data_extractor_agent = Agent(
    name="data_extractor",
    model=os.environ.get("GEMINI_MODEL_NAME", "gemini-2.5-flash"),
    instruction="""You are an expert retail document parser. 
    Use the extract_data_tool to parse receipt or invoice documents, 
    identifying store name, date, tax, total, and detailed line items.""",
    tools=[FunctionTool(extract_data_tool)]
)

# Specialist Validation Agent
validator_agent = Agent(
    name="validator",
    model=os.environ.get("GEMINI_MODEL_NAME", "gemini-2.5-flash"),
    instruction="""You are a retail receipt validation auditor. 
    Use the validate_data_tool to audit extracted invoice text directly 
    against what is visually readable from the receipt.""",
    tools=[FunctionTool(validate_data_tool)]
)

# Specialist Scoring and Routing Agent
scoring_routing_agent = Agent(
    name="scoring_router",
    model=os.environ.get("GEMINI_MODEL_NAME", "gemini-2.5-flash"),
    instruction="""You are a retail scoring and document routing agent. 
    Use the route_document_tool to archive receipts to the correct GCS bucket.
    If the validation confidence score is below 3 (i.e. 1 or 2), you must delegate the task to your sub-agent `jira_agent` 
    to automatically create a support ticket in JIRA with the summary and description of the validation discrepancy.
    Return both the GCS routing status and the JIRA ticket status in your final response.""",
    tools=[FunctionTool(route_document_tool)],
    sub_agents=[jira_agent]
)

# Lead Orchestrator Agent
orchestrator_agent = Agent(
    name="orchestrator",
    model=os.environ.get("GEMINI_MODEL_NAME", "gemini-2.5-flash"),
    instruction="""You are the lead store auditor coordinating the multi-agent pipeline.
    When the user uploads an invoice or receipt file, you must call the `analyze_uploaded_invoice` tool 
    to trigger the specialists sequentially and synthesize the final audit payload.
    Explain each step of the pipeline (Extraction, Audit validation, GCS routing, and JIRA support ticketing if applicable) 
    in your final response, presenting the structured JSON results clearly in markdown.""",
    tools=[load_artifacts, FunctionTool(analyze_uploaded_invoice)],
    sub_agents=[data_extractor_agent, validator_agent, scoring_routing_agent]
)

# The root agent exported to ADK
root_agent = orchestrator_agent
