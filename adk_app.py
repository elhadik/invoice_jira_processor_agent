import os
import vertexai
from vertexai.agent_engines import AdkApp
from google.adk.apps import App
from .agent import root_agent

adk_app = AdkApp(
    app=App(name='ge_fileagent', root_agent=root_agent),
    enable_tracing=True,
)
