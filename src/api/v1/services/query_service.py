from src.api.v1.agents.agents import run_search_agent, run_search_agent_stream


def query_documents(query: str):
    return run_search_agent(query)

async def query_documents_stream(query: str):
    # Just return the async generator
    return run_search_agent_stream(query)
