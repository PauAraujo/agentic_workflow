from langchain_core.prompts import ChatPromptTemplate

def prompt_factory(system_prompt: str, user_prompt: str) -> ChatPromptTemplate:
    """
    Construct a ChatPromptTemplate with system and human messages.

    Args:
        system_prompt: The system prompt string.
        user_prompt: The user prompt string.

    Returns:
        ChatPromptTemplate object combining the prompts.
    """
    return ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("human", user_prompt),
    ])