from config import Settings, SUPERVISOR_SYSTEM_PROMPT 
from langchain_openai import ChatOpenAI
from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware
from langgraph.checkpoint.memory import InMemorySaver
from langchain.tools import tool
from agents.planner import planner
from agents.research import researcher
from agents.critic import critic

from tools import save_report

settings = Settings()


llm = ChatOpenAI(
        model=settings.openai_lm_model,
        temperature=settings.temperature,
        base_url=settings.openai_api_base,
        api_key=settings.openai_api_key.get_secret_value()
    )

@tool
async def plan(request: str) -> str:
    """Create a structured research plan for the user request."""
    result = await planner.ainvoke(
    # result = planner.invoke(
        {"messages": [{"role": "user", "content": request}]}
    )
    return result["structured_response"].model_dump_json(indent=2, ensure_ascii=False)

@tool
async def research(request: str) -> str:
    """Execute research based on a plan or revision request."""
    # result = researcher.invoke(
    result = await researcher.ainvoke(
        {"messages": [{"role": "user", "content": request}]}
    )
    return result["messages"][-1].content

@tool
async def critique(findings: str) -> str:
    """Critique research findings and return a structured verdict."""
    # result = critic.invoke(
    result = await critic.ainvoke(
        {"messages": [{"role": "user", "content": findings}]}
    )
    return result["structured_response"].model_dump_json(indent=2, ensure_ascii=False)

supervisor = create_agent(
    model=llm,
    tools=[plan, research, critique, save_report],
    system_prompt=SUPERVISOR_SYSTEM_PROMPT,
    middleware=[
        HumanInTheLoopMiddleware(
            interrupt_on={"save_report": True}
        )
    ],
    checkpointer=InMemorySaver(),
)