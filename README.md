# Multi-Agent Retail Invoice Auditor (Plain ADK)

This folder contains a flat, pure **Google Agent Development Kit (ADK)** agent workspace that implements a sequential multi-agent pipeline to automatically extract retail invoice details, audit them against original document images, score validation confidence, archive assets, and dynamically raise support tickets in Atlassian JIRA for failed validation checks.

---

## 🏗️ Multi-Agent Architecture

The agent workspace defines a nested parent-child relationship tree, modeled natively using ADK's `sub_agents` property.

![Agent Tree Architecture Diagram](./architecture_diagram.png)

### 1. `orchestrator_agent` (Root Coordinator)
*   **Model**: `gemini-2.5-flash`
*   **Role**: The primary store auditor. Coordinates the specialists sequentially and aggregates the final markdown report.
*   **Tools**: `load_artifacts`, `analyze_uploaded_invoice`
*   **Sub-Agents**: `data_extractor_agent`, `validator_agent`, `scoring_routing_agent`

### 2. `data_extractor_agent` (Specialist Extractor)
*   **Model**: `gemini-2.5-flash`
*   **Role**: Expert retail document parser. Identifies Merchant Name, Invoice Date, Tax, Total, and line-item entities.
*   **Tools**: `extract_data_tool` (drives `document_parser.py`)

### 3. `validator_agent` (Specialist Auditor)
*   **Model**: `gemini-2.5-flash`
*   **Role**: Validation auditor. Performs image-to-text comparisons to verify the accuracy of extracted fields directly against what is visually readable in the receipt.
*   **Tools**: `validate_data_tool` (drives `gemini_parser.py`)

### 4. `scoring_routing_agent` (Specialist Routing & Ticket Coordinator)
*   **Model**: `gemini-2.5-flash`
*   **Role**: Archives documents depending on validation score. If the score is below 3 (fail/discrepancy), it delegates the task to `jira_agent` to raise a support issue.
*   **Tools**: `route_document_tool` (GCS routing client)
*   **Sub-Agents**: `jira_agent`

### 5. `jira_agent` (Integration Support Agent)
*   **Model**: `gemini-2.5-flash`
*   **Role**: Specialist JIRA assistant. Connects via our thread-safe async ThreadPool MCP execution bridge to raise support tickets on the Atlassian cloud board.
*   **Tools**: `create_jira_ticket_tool` (Atlassian MCP integration)

---

## ⏱️ Multi-Agent Execution Sequence Diagram

This sequence diagram illustrates the step-by-step execution timeline of the JIRA-integrated multi-agent pipeline:

![Multi-Agent Execution Sequence Diagram](./sequence_diagram.png)

---

## 📁 Flat Package Structure

```text
ge_fileagent/
├── agent.py           # Main definitions (Orchestrator + Specialists + sub_agents)
├── document_parser.py # OCR & Entity extraction client
├── gemini_parser.py   # Image audit comparison & validation client
├── .env               # Configuration tokens (Vertex AI, GCS, JIRA)
├── requirements.txt   # Cloud container dependencies (mcp, Pillow, sse-starlette)
└── README.md          # Setup and Multi-Agent Architecture documentation
```

---

## ⚙️ JIRA MCP Configuration

The JIRA sub-agent (`jira_agent`) utilizes the Model Context Protocol (MCP) to interact with the Atlassian cloud. It supports two runtime transport modes natively:

### A. Local Stdio Mode (Default / Local Testing)
Spawns a local subprocess running the Atlassian JIRA MCP server. 
*   **Binary Path**: `/usr/local/google/home/elhadik/NESS_GEMINI/venv/bin/mcp-atlassian`
*   **Standard Environment Variables**:
    *   `JIRA_URL`: `https://google-team-vwhbosar.atlassian.net` (Atlassian cloud domain).
    *   `JIRA_USERNAME`: Derived automatically from your `JIRA_EMAIL` setting.
    *   `JIRA_API_TOKEN`: Your Atlassian Personal API Token.
    *   `TOOLSETS`: Set to `"all"`.

### B. SSE Cloud Mode (Production / Cloud Deploy)
Connects to a remotely hosted Atlassian MCP server using Server-Sent Events (SSE).
*   **Activation**: Set the `JIRA_MCP_URL` environment variable inside the `.env` file:
    ```env
    JIRA_MCP_URL=https://your-mcp-server.endpoints/sse
    ```
*   **Authentication**: The agent automatically extracts `JIRA_EMAIL` and `JIRA_API_TOKEN`, converts them to basic base64-encoded authorization headers, and performs secure tokenized handshake exchanges.

---

## 🚀 How to Run Locally

First, make sure you are in this directory:
```bash
cd /usr/local/google/home/elhadik/ge_fileagent
```

### Step 1: Stage the isolated copy
To satisfy ADK's strict security traversal checks, create an isolated staging copy in your local `/tmp/` directory:
```bash
rm -rf /tmp/adk_agents/ge_fileagent
mkdir -p /tmp/adk_agents/ge_fileagent
cp -r /usr/local/google/home/elhadik/ge_fileagent/* /tmp/adk_agents/ge_fileagent/
cp /usr/local/google/home/elhadik/ge_fileagent/.env /tmp/adk_agents/ge_fileagent/
```

### Step 2: Start the visual playground
Start the playground local server by running:
```bash
export GOOGLE_API_USE_CLIENT_CERTIFICATE=false
export GOOGLE_GENAI_USE_VERTEXAI=true
export GOOGLE_CLOUD_PROJECT=shade-sandbox
export GOOGLE_CLOUD_LOCATION=us-central1

/usr/local/google/home/elhadik/gamestop_invoice/venv/bin/adk web /tmp/adk_agents
```

Once launched, navigate to **`http://127.0.0.1:8000`**, select **`ge_fileagent`**, upload a receipt, and run your audit prompt!
