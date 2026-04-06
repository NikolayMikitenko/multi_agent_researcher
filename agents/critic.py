from config import Settings, CRITIC_SYSTEM_PROMPT 
from langchain_openai import ChatOpenAI
from langchain.agents import create_agent
from tools import web_search, read_url, knowledge_search
# from langgraph.checkpoint.memory import MemorySaver
from schemas import CritiqueResult

settings = Settings()

llm = ChatOpenAI(
        model=settings.openai_lm_model,
        temperature=settings.temperature,
        base_url=settings.openai_api_base,
        api_key=settings.openai_api_key
    )

# memory = MemorySaver()

critic = create_agent(
    model=llm,
    tools=[web_search, read_url, knowledge_search],
    system_prompt=CRITIC_SYSTEM_PROMPT,
    response_format=CritiqueResult,
    # checkpointer=memory
)