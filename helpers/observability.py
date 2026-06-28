"""
Langfuse observability integration for LLM workflow tracking.

This module provides:
- Automatic LLM call tracing (prompts, completions, costs)
- LangGraph workflow tracing (entire coder → QA → PR flow)
- Performance metrics (latency, tokens, errors)
- Cost tracking per ticket

Security:
- Secrets (API keys, tokens) are never logged in traces
- All credentials loaded from environment variables only
- .env file must be in .gitignore

Usage:
    from helpers.observability import init_langfuse, trace_workflow, get_traced_llm_client
    
    # Initialize once at startup
    init_langfuse()
    
    # Wrap LangGraph workflow
    @trace_workflow
    def coder_agent(state):
        ...
    
    # Get traced LLM client
    client = get_traced_llm_client()
"""

import os
from functools import wraps
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# Global Langfuse instance
_langfuse = None
_langfuse_enabled = False
_langfuse_trace_supported = False
_langfuse_trace_warning_logged = False


def init_langfuse():
    """Initialize Langfuse observability if credentials are provided."""
    global _langfuse, _langfuse_enabled, _langfuse_trace_supported, _langfuse_trace_warning_logged
    
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY")
    host = os.getenv("LANGFUSE_HOST", "http://192.168.0.146:3002")
    
    if not public_key or not secret_key:
        logger.warning("[Observability] Langfuse credentials not found. Observability disabled.")
        logger.warning("[Observability] Set LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY in .env to enable.")
        _langfuse_enabled = False
        return None
    
    try:
        from langfuse import Langfuse
        _langfuse = Langfuse(
            public_key=public_key,
            secret_key=secret_key,
            host=host
        )
        _langfuse_enabled = True
        _langfuse_trace_supported = hasattr(_langfuse, "trace")
        _langfuse_trace_warning_logged = False
        if not _langfuse_trace_supported:
            logger.warning(
                "[Observability] Langfuse client does not expose trace(); workflow tracing will be disabled, "
                "but LLM client wrapping may still work."
            )
        logger.info(f"[Observability] ✓ Langfuse initialized: {host}")
        return _langfuse
    except ImportError:
        logger.warning("[Observability] langfuse not installed. Run: pip install langfuse")
        _langfuse_enabled = False
        return None
    except Exception as e:
        logger.error(f"[Observability] Failed to initialize Langfuse: {e}")
        _langfuse_enabled = False
        return None


def get_langfuse():
    """Get the Langfuse instance (or None if disabled)."""
    return _langfuse if _langfuse_enabled else None


def is_enabled():
    """Check if Langfuse observability is enabled."""
    return _langfuse_enabled


def _workflow_tracing_available() -> bool:
    """Return True when the loaded Langfuse client supports trace() API."""
    return bool(_langfuse_enabled and _langfuse and _langfuse_trace_supported and hasattr(_langfuse, "trace"))


def get_traced_llm_client(provider: str = "ollama", model: str = None):
    """
    Get an OpenAI client wrapped with Langfuse tracing.
    
    Args:
        provider: "ollama" or "openrouter"
        model: Model name for metadata
    
    Returns:
        OpenAI client instance (traced if Langfuse is enabled)
    """
    from openai import OpenAI
    
    if not _langfuse_enabled:
        # Return regular client if observability is disabled
        if provider == "ollama":
            return OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")
        elif provider == "openrouter":
            return OpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=os.getenv("OPENROUTER_API_KEY")
            )
    
    # Langfuse OpenAI wrapper for automatic tracing
    try:
        from langfuse.openai import OpenAI as LangfuseOpenAI
        
        if provider == "ollama":
            client = LangfuseOpenAI(
                base_url="http://localhost:11434/v1",
                api_key="ollama"
            )
        elif provider == "openrouter":
            client = LangfuseOpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=os.getenv("OPENROUTER_API_KEY")
            )
        else:
            raise ValueError(f"Unknown provider: {provider}")
        
        logger.debug(f"[Observability] Created traced LLM client: {provider}/{model}")
        return client
        
    except ImportError:
        logger.warning("[Observability] langfuse.openai not available, using standard client")
        if provider == "ollama":
            return OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")
        elif provider == "openrouter":
            return OpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=os.getenv("OPENROUTER_API_KEY")
            )


def trace_workflow(agent_name: str = None):
    """
    Decorator to trace LangGraph workflow nodes with Langfuse.
    
    Usage:
        @trace_workflow("coder_agent")
        def coder_agent(state: TicketState):
            ...
    
    Captures:
        - Agent execution time
        - Input/output state
        - Errors and exceptions
        - Ticket metadata
    """
    def decorator(func):
        @wraps(func)
        def wrapper(state, *args, **kwargs):
            global _langfuse_trace_warning_logged

            if not _workflow_tracing_available():
                if _langfuse_enabled and _langfuse and not _langfuse_trace_warning_logged:
                    logger.warning(
                        "[Observability] Skipping workflow trace because this Langfuse SDK lacks trace(); "
                        "function will run without workflow spans."
                    )
                    _langfuse_trace_warning_logged = True
                # Just run the function normally if observability is disabled
                return func(state, *args, **kwargs)
            
            name = agent_name or func.__name__
            ticket_id = state.get("ticket_id", "unknown")
            
            # Create trace
            trace = _langfuse.trace(
                name=f"workflow_{ticket_id}",
                metadata={
                    "ticket_id": ticket_id,
                    "agent": name,
                    "status": state.get("status"),
                    "retry_count": state.get("qa_retry_count", 0)
                }
            )
            
            # Create span for this agent
            span = trace.span(
                name=name,
                input={
                    "ticket_id": ticket_id,
                    "status": state.get("status"),
                    "spec": state.get("spec", "")[:200] + "..." if state.get("spec") else None
                }
            )
            
            try:
                result = func(state, *args, **kwargs)
                
                # Log output
                span.end(
                    output={
                        "new_status": result.get("status") if isinstance(result, dict) else None,
                        "files_modified": result.get("file_paths") if isinstance(result, dict) else None
                    }
                )
                
                return result
                
            except Exception as e:
                # Log error
                span.end(
                    level="ERROR",
                    status_message=str(e)
                )
                raise
        
        return wrapper
    return decorator


def log_ticket_event(ticket_id: str, event: str, metadata: dict = None):
    """
    Log a custom event for a ticket (e.g., PR created, validation failed).
    
    Args:
        ticket_id: Ticket identifier
        event: Event name (e.g., "pr_created", "validation_failed")
        metadata: Additional event data
    """
    if not _langfuse_enabled:
        return
    
    try:
        _langfuse.score(
            name=event,
            trace_id=f"workflow_{ticket_id}",
            value=1,
            comment=metadata.get("comment") if metadata else None
        )
    except Exception as e:
        logger.warning(f"[Observability] Failed to log event: {e}")


def log_cost(ticket_id: str, cost: float, tokens: int, model: str):
    """
    Log cost metrics for a ticket.
    
    Args:
        ticket_id: Ticket identifier
        cost: Total cost in USD
        tokens: Total tokens used
        model: Model name
    """
    if not _langfuse_enabled:
        return
    
    try:
        _langfuse.score(
            name="cost",
            trace_id=f"workflow_{ticket_id}",
            value=cost,
            comment=f"{tokens} tokens, {model}"
        )
    except Exception as e:
        logger.warning(f"[Observability] Failed to log cost: {e}")


def flush():
    """Flush any pending observability data (call before shutdown)."""
    if _langfuse_enabled and _langfuse:
        try:
            _langfuse.flush()
            logger.info("[Observability] Flushed Langfuse data")
        except Exception as e:
            logger.warning(f"[Observability] Failed to flush: {e}")
