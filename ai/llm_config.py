"""
LLM Configuration Module with Hot-Reload Support

This module provides configuration management for LLM settings and prompts
with automatic reload capability when configuration files change.

Usage:
    from ai.llm_config import get_llm_config, reload_config

    # Get current configuration (automatically reloads if file changed)
    config = get_llm_config()

    # Force reload configuration
    reload_config()
"""

import os
import yaml
import time
import threading
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from pathlib import Path


CONFIG_FILE = Path(__file__).parent / "llm_config.yaml"
_RELOAD_INTERVAL = 2.0  # Check for file changes every 2 seconds


@dataclass
class EmbeddingConfig:
    """Embedding model configuration"""

    model: str = "baai/bge-m3"
    api_url: str = "https://openrouter.ai/api/v1/embeddings"


@dataclass
class ChatConfig:
    """Chat completion configuration"""

    model: str = "google/gemini-3-flash-preview"
    api_url: str = "https://openrouter.ai/api/v1/chat/completions"
    temperature: float = 0.1
    timeout: int = 60
    system_prompt: str = (
        "You are an expert QA engineer specializing in test case design."
    )


@dataclass
class PromptConfig:
    """Prompt template configuration"""

    template: str = ""
    similar_cases_count: int = 5
    similar_cases_max_length: int = 500


@dataclass
class WeightsConfig:
    """Weight configuration for combining search results"""

    test_cases: float = 0.7
    usm_nodes: float = 0.3


@dataclass
class LimitConfig:
    """Limit configuration for search results"""

    test_cases: int = 14
    usm_nodes: int = 6


@dataclass
class QdrantConfig:
    """Qdrant configuration"""

    url: str = "http://localhost:6333"
    collection_test_cases: str = "test_cases"
    collection_usm_nodes: str = "usm_nodes"
    weights: WeightsConfig = field(default_factory=WeightsConfig)
    limit: LimitConfig = field(default_factory=LimitConfig)


@dataclass
class JiraConfig:
    """JIRA configuration"""

    server_url: str = ""
    username: str = ""
    api_token: str = ""
    ca_cert_path: str = ""


@dataclass
class OutputConfig:
    """Output configuration"""

    default_language: str = "Traditional Chinese"
    languages: List[str] = field(
        default_factory=lambda: ["Traditional Chinese", "Simplified Chinese", "English"]
    )


@dataclass
class LLMConfig:
    """Main LLM configuration container"""

    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    chat: ChatConfig = field(default_factory=ChatConfig)
    prompt: PromptConfig = field(default_factory=PromptConfig)
    qdrant: QdrantConfig = field(default_factory=QdrantConfig)
    jira: JiraConfig = field(default_factory=JiraConfig)
    output: OutputConfig = field(default_factory=OutputConfig)

    def format_prompt(
        self,
        output_language: str,
        ticket_key: str,
        ticket_summary: str,
        ticket_description: str,
        ticket_components: str,
        similar_cases_text: str,
        initial_middle: str,
    ) -> str:
        """Format the prompt template with provided values"""
        # Calculate next middle numbers
        try:
            initial = int(initial_middle)
            next_middle_1 = str(initial + 10).zfill(3)
            next_middle_2 = str(initial + 20).zfill(3)
        except ValueError:
            next_middle_1 = "020"
            next_middle_2 = "030"

        # Extract project ID from ticket key (e.g., "PROJ-123" -> "123")
        ticket_project_id = ""
        if "-" in ticket_key:
            parts = ticket_key.split("-")
            if len(parts) >= 2:
                # Handle cases like "PROJ-123" -> "123" or "TCG-130078" -> "130078"
                ticket_project_id = parts[-1] if parts[-1].isdigit() else parts[1]

        # Replace placeholders
        formatted = self.prompt.template
        replacements = {
            "{output_language}": output_language,
            "{ticket_key}": ticket_key,
            "{ticket_summary}": ticket_summary,
            "{ticket_description}": ticket_description,
            "{ticket_components}": ticket_components or "N/A",
            "{similar_cases}": similar_cases_text,
            "{initial_middle}": initial_middle,
            "{next_middle_1}": next_middle_1,
            "{next_middle_2}": next_middle_2,
            "{ticket_project_id}": ticket_project_id or ticket_key.split("-")[-1]
            if "-" in ticket_key
            else ticket_key,
        }

        for placeholder, value in replacements.items():
            formatted = formatted.replace(placeholder, value)

        return formatted

    def get_similar_cases_for_prompt(self, similar_cases: List[Dict[str, Any]]) -> str:
        """Format similar cases for inclusion in prompt"""
        max_cases = self.prompt.similar_cases_count
        max_length = self.prompt.similar_cases_max_length

        formatted_cases = []
        for i, case in enumerate(similar_cases[:max_cases]):
            text = case.get("text", "")[:max_length]
            formatted_cases.append(f"Similar Case {i + 1}:\n{text}...")

        return "\n\n".join(formatted_cases)


class ConfigManager:
    """Configuration manager with hot-reload support"""

    _instance: Optional["ConfigManager"] = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._config: Optional[LLMConfig] = None
        self._last_modified: float = 0
        self._lock = threading.Lock()
        self._initialized = True

    def _load_config(self) -> LLMConfig:
        """Load configuration from YAML file"""
        if not CONFIG_FILE.exists():
            # Return default config if file doesn't exist
            return LLMConfig()

        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if data is None:
            return LLMConfig()

        # Parse embedding config
        embedding_data = data.get("llm", {}).get("embedding", {})
        embedding = EmbeddingConfig(
            model=embedding_data.get("model", "baai/bge-m3"),
            api_url=embedding_data.get(
                "api_url", "https://openrouter.ai/api/v1/embeddings"
            ),
        )

        # Parse chat config
        chat_data = data.get("llm", {}).get("chat", {})
        chat = ChatConfig(
            model=chat_data.get("model", "google/gemini-3-flash-preview"),
            api_url=chat_data.get(
                "api_url", "https://openrouter.ai/api/v1/chat/completions"
            ),
            temperature=chat_data.get("temperature", 0.1),
            timeout=chat_data.get("timeout", 60),
            system_prompt=chat_data.get(
                "system_prompt",
                "You are an expert QA engineer specializing in test case design.",
            ),
        )

        # Parse prompt config
        prompt_data = data.get("prompt", {})
        prompt = PromptConfig(
            template=prompt_data.get("template", ""),
            similar_cases_count=prompt_data.get("similar_cases_count", 5),
            similar_cases_max_length=prompt_data.get("similar_cases_max_length", 500),
        )

        # Parse Qdrant config
        qdrant_data = data.get("qdrant", {})
        weights_data = qdrant_data.get("weights", {})
        limit_data = qdrant_data.get("limit", {})
        qdrant = QdrantConfig(
            url=qdrant_data.get("url", "http://localhost:6333"),
            collection_test_cases=qdrant_data.get(
                "collection_test_cases", "test_cases"
            ),
            collection_usm_nodes=qdrant_data.get("collection_usm_nodes", "usm_nodes"),
            weights=WeightsConfig(
                test_cases=weights_data.get("test_cases", 0.7),
                usm_nodes=weights_data.get("usm_nodes", 0.3),
            ),
            limit=LimitConfig(
                test_cases=limit_data.get("test_cases", 14),
                usm_nodes=limit_data.get("usm_nodes", 6),
            ),
        )

        # Parse JIRA config
        jira_data = data.get("jira", {})
        jira = JiraConfig(
            server_url=jira_data.get("server_url", ""),
            username=jira_data.get("username", ""),
            api_token=jira_data.get("api_token", ""),
            ca_cert_path=jira_data.get("ca_cert_path", ""),
        )

        # Parse output config
        output_data = data.get("output", {})
        output = OutputConfig(
            default_language=output_data.get("default_language", "Traditional Chinese"),
            languages=output_data.get(
                "languages", ["Traditional Chinese", "Simplified Chinese", "English"]
            ),
        )

        return LLMConfig(
            embedding=embedding,
            chat=chat,
            prompt=prompt,
            qdrant=qdrant,
            jira=jira,
            output=output,
        )

    def get_config(self, force_reload: bool = False) -> LLMConfig:
        """Get current configuration, optionally forcing a reload"""
        if force_reload:
            return self._reload()

        # Check if file was modified
        try:
            current_mtime = os.path.getmtime(CONFIG_FILE)
        except (OSError, FileNotFoundError):
            current_mtime = 0

        # Reload if file was modified
        if current_mtime > self._last_modified:
            return self._reload()

        # Return cached config
        if self._config is None:
            return self._reload()

        return self._config

    def _reload(self) -> LLMConfig:
        """Reload configuration from file"""
        with self._lock:
            self._config = self._load_config()
            try:
                self._last_modified = os.path.getmtime(CONFIG_FILE)
            except (OSError, FileNotFoundError):
                self._last_modified = 0
            return self._config

    def reload(self) -> LLMConfig:
        """Public method to force reload configuration"""
        return self._reload()


def get_llm_config(force_reload: bool = False) -> LLMConfig:
    """
    Get the current LLM configuration.

    This function automatically reloads the configuration if the file
    has been modified since the last load.

    Args:
        force_reload: If True, always reload from file

    Returns:
        LLMConfig instance with current settings
    """
    manager = ConfigManager()
    return manager.get_config(force_reload=force_reload)


def reload_config() -> LLMConfig:
    """
    Force reload the configuration from file.

    Returns:
        LLMConfig instance with fresh settings
    """
    manager = ConfigManager()
    return manager.reload()


def format_prompt(
    output_language: str,
    ticket_key: str,
    ticket_summary: str,
    ticket_description: str,
    ticket_components: str,
    similar_cases: List[Dict[str, Any]],
    initial_middle: str = "010",
    force_reload: bool = False,
) -> str:
    """
    Format the prompt template with provided values.

    Args:
        output_language: Target language for test cases
        ticket_key: JIRA ticket key (e.g., "PROJ-123")
        ticket_summary: Ticket summary/title
        ticket_description: Full ticket description
        ticket_components: Comma-separated list of components
        similar_cases: List of similar test cases from Qdrant
        initial_middle: Starting middle number
        force_reload: Force reload config before formatting

    Returns:
        Formatted prompt string
    """
    config = get_llm_config(force_reload=force_reload)
    similar_cases_text = config.get_similar_cases_for_prompt(similar_cases)

    return config.format_prompt(
        output_language=output_language,
        ticket_key=ticket_key,
        ticket_summary=ticket_summary,
        ticket_description=ticket_description,
        ticket_components=ticket_components,
        similar_cases_text=similar_cases_text,
        initial_middle=initial_middle,
    )


def get_available_languages() -> List[str]:
    """Get list of available output languages"""
    config = get_llm_config()
    return config.output.languages


def get_default_language() -> str:
    """Get the default output language"""
    config = get_llm_config()
    return config.output.default_language


def get_qdrant_config() -> QdrantConfig:
    """Get Qdrant configuration"""
    config = get_llm_config()
    return config.qdrant


def get_chat_config() -> ChatConfig:
    """Get chat completion configuration"""
    config = get_llm_config()
    return config.chat


def get_embedding_config() -> EmbeddingConfig:
    """Get embedding configuration"""
    config = get_llm_config()
    return config.embedding
