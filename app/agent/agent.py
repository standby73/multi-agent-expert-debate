import os
import sys
from typing import Any, Dict
from google.adk.models.lite_llm import LiteLlm
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from google.adk.agents import LlmAgent, SequentialAgent, ParallelAgent, LoopAgent
from google.adk.tools.tool_context import ToolContext
from google.adk.agents.callback_context import CallbackContext
from pydantic import BaseModel, Field
from mcp import StdioServerParameters

from maikol_utils.print_utils import print_warn, print_color

from config import DEBATES, Configuration


# The agent.py file has been temporarily converted to use the functional approach
# Import the function from debate.py
from debate import create_debate_agent

CONFIG = Configuration()
agents_config = DEBATES[10]['agents']  

# Create the agent using the function
root_agent = create_debate_agent(CONFIG, agents_config)