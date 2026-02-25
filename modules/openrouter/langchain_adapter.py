"""
LangChain-compatible wrapper for OpenRouter API.

This module provides a ChatOpenRouter class that can be used as a drop-in
replacement for ChatOpenAI in existing LangChain-based agents.

Usage:
    from modules.openrouter.langchain_adapter import ChatOpenRouter

    # Replace ChatOpenAI with ChatOpenRouter
    llm = ChatOpenRouter(model="openai/gpt-5.1", temperature=0.7)

    # Use with LangChain chains
    chain = prompt | llm | output_parser
    result = await chain.ainvoke({"input": "Hello"})
"""

import os
import logging
from typing import Any, List, Optional, Dict, Iterator, AsyncIterator

import httpx
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    BaseMessage,
    AIMessage,
    HumanMessage,
    SystemMessage,
    AIMessageChunk
)
from langchain_core.outputs import ChatResult, ChatGeneration, ChatGenerationChunk
from langchain_core.callbacks import CallbackManagerForLLMRun, AsyncCallbackManagerForLLMRun
from pydantic import Field

logger = logging.getLogger(__name__)

# Configuration
OPENROUTER_API_KEY = os.getenv(
    "OPENROUTER_API_KEY",
    "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"
)
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_REASONING_MODEL = os.getenv("OPENROUTER_REASONING_MODEL", "openai/gpt-4o")


class ChatOpenRouter(BaseChatModel):
    """
    LangChain-compatible ChatModel that uses OpenRouter API.

    This is a drop-in replacement for ChatOpenAI that routes requests
    through OpenRouter's unified API.

    Attributes:
        model: The model to use (e.g., "openai/gpt-5.1", "anthropic/claude-3")
        temperature: Sampling temperature (0-2)
        max_tokens: Maximum tokens in response
        api_key: OpenRouter API key
        streaming: Whether to stream responses

    Example:
        llm = ChatOpenRouter(model="openai/gpt-5.1", temperature=0.7)
        response = llm.invoke([HumanMessage(content="Hello!")])
    """

    model: str = Field(default=OPENROUTER_REASONING_MODEL)
    temperature: float = Field(default=0.7)
    max_tokens: int = Field(default=4096)
    api_key: str = Field(default=OPENROUTER_API_KEY)
    streaming: bool = Field(default=False)
    base_url: str = Field(default=OPENROUTER_BASE_URL)

    class Config:
        """Pydantic config."""
        arbitrary_types_allowed = True

    @property
    def _llm_type(self) -> str:
        """Return type of LLM."""
        return "openrouter"

    @property
    def _identifying_params(self) -> Dict[str, Any]:
        """Return identifying parameters."""
        return {
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens
        }

    def _get_headers(self) -> Dict[str, str]:
        """Get headers for OpenRouter API requests."""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": "https://shopivell.com",
            "X-Title": "Shopivell AI Agents",
            "Content-Type": "application/json"
        }

    def _convert_message_to_dict(self, message: BaseMessage) -> Dict[str, str]:
        """Convert a LangChain message to OpenRouter format."""
        if isinstance(message, SystemMessage):
            return {"role": "system", "content": message.content}
        elif isinstance(message, HumanMessage):
            return {"role": "user", "content": message.content}
        elif isinstance(message, AIMessage):
            return {"role": "assistant", "content": message.content}
        else:
            # Default to user role for unknown message types
            return {"role": "user", "content": str(message.content)}

    def _create_payload(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        **kwargs: Any
    ) -> Dict[str, Any]:
        """Create the API request payload."""
        formatted_messages = [self._convert_message_to_dict(m) for m in messages]

        payload = {
            "model": self.model,
            "messages": formatted_messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": self.streaming
        }

        if stop:
            payload["stop"] = stop

        # Allow kwargs to override defaults
        payload.update(kwargs)

        return payload

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """
        Synchronous generation using OpenRouter API.

        Args:
            messages: List of LangChain messages
            stop: Optional stop sequences
            run_manager: Optional callback manager
            **kwargs: Additional arguments

        Returns:
            ChatResult with generated content
        """
        payload = self._create_payload(messages, stop, **kwargs)

        with httpx.Client(timeout=120.0) as client:
            try:
                response = client.post(
                    f"{self.base_url}/chat/completions",
                    headers=self._get_headers(),
                    json=payload
                )
                response.raise_for_status()
                data = response.json()

                content = data['choices'][0]['message']['content']
                generation = ChatGeneration(message=AIMessage(content=content))

                # Extract usage data from OpenRouter response
                usage = data.get('usage', {})
                llm_output = {
                    "model": self.model,
                    "prompt_tokens": usage.get('prompt_tokens', 0),
                    "completion_tokens": usage.get('completion_tokens', 0),
                    "total_tokens": usage.get('total_tokens', 0),
                }

                # Fire-and-forget usage tracking
                try:
                    from modules.openrouter.context import ai_context
                    from modules.openrouter.ai_usage_service import track_usage
                    ctx = ai_context.get()
                    track_usage(
                        model=self.model,
                        prompt_tokens=llm_output["prompt_tokens"],
                        completion_tokens=llm_output["completion_tokens"],
                        total_tokens=llm_output["total_tokens"],
                        agent_name=ctx.agent_name,
                        store_id=ctx.store_id,
                        user_id=ctx.user_id,
                        campaign_id=ctx.campaign_id,
                    )
                except Exception as e:
                    logger.warning(f"[ChatOpenRouter] Usage tracking failed: {e}")

                return ChatResult(generations=[generation], llm_output=llm_output)

            except httpx.HTTPStatusError as e:
                logger.error(f"[ChatOpenRouter] HTTP error: {e.response.status_code} - {e.response.text}")
                raise
            except Exception as e:
                logger.error(f"[ChatOpenRouter] Error: {str(e)}")
                raise

    async def _agenerate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """
        Async generation using OpenRouter API.

        Args:
            messages: List of LangChain messages
            stop: Optional stop sequences
            run_manager: Optional callback manager
            **kwargs: Additional arguments

        Returns:
            ChatResult with generated content
        """
        payload = self._create_payload(messages, stop, **kwargs)

        async with httpx.AsyncClient(timeout=120.0) as client:
            try:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=self._get_headers(),
                    json=payload
                )
                response.raise_for_status()
                data = response.json()

                content = data['choices'][0]['message']['content']
                generation = ChatGeneration(message=AIMessage(content=content))

                # Extract usage data from OpenRouter response
                usage = data.get('usage', {})
                llm_output = {
                    "model": self.model,
                    "prompt_tokens": usage.get('prompt_tokens', 0),
                    "completion_tokens": usage.get('completion_tokens', 0),
                    "total_tokens": usage.get('total_tokens', 0),
                }

                logger.info(f"[ChatOpenRouter] Generated response, model: {self.model}, tokens: {llm_output['total_tokens']}")

                # Fire-and-forget usage tracking
                try:
                    from modules.openrouter.context import ai_context
                    from modules.openrouter.ai_usage_service import track_usage
                    ctx = ai_context.get()
                    track_usage(
                        model=self.model,
                        prompt_tokens=llm_output["prompt_tokens"],
                        completion_tokens=llm_output["completion_tokens"],
                        total_tokens=llm_output["total_tokens"],
                        agent_name=ctx.agent_name,
                        store_id=ctx.store_id,
                        user_id=ctx.user_id,
                        campaign_id=ctx.campaign_id,
                    )
                except Exception as e:
                    logger.warning(f"[ChatOpenRouter] Usage tracking failed: {e}")

                return ChatResult(generations=[generation], llm_output=llm_output)

            except httpx.HTTPStatusError as e:
                logger.error(f"[ChatOpenRouter] HTTP error: {e.response.status_code} - {e.response.text}")
                raise
            except Exception as e:
                logger.error(f"[ChatOpenRouter] Error: {str(e)}")
                raise

    def _stream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        """
        Stream responses from OpenRouter API.

        Args:
            messages: List of LangChain messages
            stop: Optional stop sequences
            run_manager: Optional callback manager
            **kwargs: Additional arguments

        Yields:
            ChatGenerationChunk with streamed content
        """
        payload = self._create_payload(messages, stop, stream=True, **kwargs)

        with httpx.Client(timeout=120.0) as client:
            with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers=self._get_headers(),
                json=payload
            ) as response:
                response.raise_for_status()

                for line in response.iter_lines():
                    if line.startswith("data: "):
                        data = line[6:]
                        if data == "[DONE]":
                            break

                        try:
                            import json
                            chunk_data = json.loads(data)
                            delta = chunk_data['choices'][0].get('delta', {})
                            content = delta.get('content', '')

                            if content:
                                chunk = ChatGenerationChunk(
                                    message=AIMessageChunk(content=content)
                                )
                                if run_manager:
                                    run_manager.on_llm_new_token(content)
                                yield chunk

                        except json.JSONDecodeError:
                            continue

    async def _astream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        """
        Async stream responses from OpenRouter API.

        Args:
            messages: List of LangChain messages
            stop: Optional stop sequences
            run_manager: Optional callback manager
            **kwargs: Additional arguments

        Yields:
            ChatGenerationChunk with streamed content
        """
        payload = self._create_payload(messages, stop, stream=True, **kwargs)

        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers=self._get_headers(),
                json=payload
            ) as response:
                response.raise_for_status()

                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data = line[6:]
                        if data == "[DONE]":
                            break

                        try:
                            import json
                            chunk_data = json.loads(data)
                            delta = chunk_data['choices'][0].get('delta', {})
                            content = delta.get('content', '')

                            if content:
                                chunk = ChatGenerationChunk(
                                    message=AIMessageChunk(content=content)
                                )
                                if run_manager:
                                    await run_manager.on_llm_new_token(content)
                                yield chunk

                        except json.JSONDecodeError:
                            continue
