import argparse
import dataclasses
import dotenv
import asyncio
import warnings
from google.adk import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from debate import create_debate_agent

from maikol_utils.print_utils import print_separator
from maikol_utils.other_utils import args_to_dataclass

from config import DEBATES, Configuration

async def run_agent_with_message(CONFIG, message_text: str, agents_config: list):
    """Run the agent with a specific message and agents configuration."""
    # Create the agent dynamically with the provided agents configuration
    root_agent = create_debate_agent(CONFIG, agents_config)
    
    # =================== Create a runner and session ===================
    runner = Runner(
        agent=root_agent, 
        app_name="simple_agent", 
        session_service=InMemorySessionService()
    )
    await runner.session_service.create_session(
        user_id="user1", 
        session_id="session1", 
        app_name="simple_agent"
    )
    
    # =================== Create the message ===================
    message = types.Content(
        role="user", 
        parts=[types.Part(text=message_text)]
    )
    
    # =================== Execute ===================
    current_agent = None
    try:
        async for event in runner.run_async(
            user_id="user1", 
            session_id="session1", 
            new_message=message
        ):
            agent_name = getattr(event, 'author', None) or 'Unknown Agent'
            
            if agent_name != current_agent:
                current_agent = agent_name
                print("\n")
                print_separator(current_agent, sep_type="SUPER")

            for part in event.content.parts:
                print(part.text, end="")
    except Exception as e:
        print(f"\n\nError durante la ejecución del agente: {e}", flush=True)
        raise
    finally:
        # Give a small delay to allow MCP connections to clean up properly
        await asyncio.sleep(1)



# ============================================================================
#                           MAIN FUNCTION
# ============================================================================
async def main(CONFIG: Configuration):
    global DEBATES
    # Execute all debates or a specific one based on CONFIG
    if CONFIG.debate is not None:
        DEBATES = [DEBATES[CONFIG.debate]]

    for debate in DEBATES:
        CONFIG_AUX = dataclasses.replace(CONFIG, exp_name=debate['exp_name'])
        
        print_separator(f"Starting debate: {debate['exp_name']}", sep_type="START")
        print(f"- Question: {debate['question']}")

        await run_agent_with_message(CONFIG_AUX, debate['question'], debate['agents'])

if __name__ == "__main__":
    dotenv.load_dotenv()

    # ======================== HELP TEXT =========================
    # Build the help text with the list of available debates
    debate_list = "\n".join([f"    - {i}: {debate['exp_name']}" for i, debate in enumerate(DEBATES)])
    debate_help = f"Debate index to run (default: None for all)\n  Indices:\n{debate_list}"

    # ======================== PARSER =========================
    parser = argparse.ArgumentParser(
        prog="run_agent", 
        description="Expert Debate Agent Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("-d", "--debate", type=int, default=None, help=debate_help)

    # ======================== CONFIG =========================
    args = parser.parse_args()
    CONFIG = args_to_dataclass(args, Configuration)

    # Suppress specific async cleanup warnings from MCP
    warnings.filterwarnings("ignore", category=RuntimeWarning, message=".*coroutine.*was never awaited.*")
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    
    # ======================== CALL =========================
    try:
        asyncio.run(main(CONFIG))
    except KeyboardInterrupt:
        print("\n\nEjecución interrumpida por el usuario.", flush=True)
    except Exception as e:
        print(f"\n\nError fatal: {e}", flush=True)
        # raise

    print_separator("DEBATES TERMINADOS", sep_type="START")
