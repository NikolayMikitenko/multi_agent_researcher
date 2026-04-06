from config import Settings, PLANNER_SYSTEM_PROMPT 
from langchain_openai import ChatOpenAI
from langchain.agents import create_agent
from tools import web_search, knowledge_search
from schemas import ResearchPlan

settings = Settings()

llm = ChatOpenAI(
        model=settings.openai_lm_model,
        temperature=settings.temperature,
        base_url=settings.openai_api_base,
        api_key=settings.openai_api_key
    )

planner = create_agent(
    model=llm,
    tools=[web_search, knowledge_search],
    system_prompt=PLANNER_SYSTEM_PROMPT,
    response_format=ResearchPlan,
)