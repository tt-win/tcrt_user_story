#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JIRA Ticket to Test Case PoC

A TUI-based proof of concept tool that generates test cases from JIRA tickets.

Usage:
    python ai/jira_to_test_case_poc.py

Features:
- Input JIRA ticket key (e.g., PROJ-123)
- Fetch ticket details from JIRA API
- Query Qdrant for similar test cases and user stories
- Generate test cases using OpenRouter LLM
- Display results in formatted TUI

Dependencies:
- textual
- qdrant-client
- requests
"""

import asyncio
import re
import sys
import os
import json
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, TYPE_CHECKING, cast
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.getcwd())

# Import LLM configuration with hot-reload support
from ai.llm_config import (
    get_llm_config,
    reload_config,
    format_prompt,
    get_qdrant_config,
    get_chat_config,
    get_embedding_config,
    get_available_languages,
    get_default_language,
)

# Debug logging to file
DEBUG_FILE = "/tmp/tcrt_debug.log"


def debug_log(msg: str):
    """Write debug message to file"""
    with open(DEBUG_FILE, "a") as f:
        f.write(f"[{datetime.now().strftime('%H:%M:%S.%f')}] {msg}\n")
        f.flush()


# Clear debug file on startup
with open(DEBUG_FILE, "w") as f:
    f.write("")


from textual.app import App, ComposeResult
from textual.widgets import Input, Button, Static, Markdown, Label
from textual.containers import Vertical, Horizontal, Center, VerticalScroll
from textual.screen import Screen
from textual.reactive import reactive

if TYPE_CHECKING:
    pass


@dataclass
class JiraTicket:
    """JIRA ticket data structure"""

    key: str
    summary: str
    description: str
    components: List[str]
    labels: List[str]
    status: str


class InputScreen(Screen):
    """Screen for inputting JIRA ticket key and initial middle number"""

    def compose(self) -> ComposeResult:
        with Center():
            with Vertical():
                yield Label("JIRA Ticket to Test Case Generator", id="title")
                yield Label(
                    "Enter JIRA ticket key (e.g., PROJ-123):", id="label-ticket"
                )
                yield Input(placeholder="PROJ-123", id="ticket-input")
                yield Label(
                    "Initial middle number (optional, default 010):", id="label-middle"
                )
                yield Input(placeholder="010", id="middle-input")
                yield Label("Output Language:", id="label-language")
                yield Input(placeholder="繁中 (default)", id="language-input")
                yield Button("Generate Test Cases", id="submit-btn", variant="primary")
                yield Static("", id="error-msg")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "submit-btn":
            ticket_input = self.query_one("#ticket-input", Input)
            middle_input = self.query_one("#middle-input", Input)
            language_input = self.query_one("#language-input", Input)

            ticket_key = ticket_input.value.strip().upper()
            middle_num = middle_input.value.strip()
            language = language_input.value.strip().lower()

            # Validate ticket key format
            if not re.match(r"^[A-Z]+-\d+$", ticket_key):
                self.query_one("#error-msg", Static).update(
                    "Invalid ticket format. Use format: PROJ-123"
                )
                return

            # Validate middle number if provided
            if middle_num and not re.match(r"^\d{3}$", middle_num):
                self.query_one("#error-msg", Static).update(
                    "Invalid middle number. Use format: 010, 020, etc."
                )
                return

            # Parse language selection
            language_map = {
                "en": "English",
                "english": "English",
                "eng": "English",
                "簡中": "Simplified Chinese",
                "簡": "Simplified Chinese",
                "sc": "Simplified Chinese",
                "simplified": "Simplified Chinese",
                "繁中": "Traditional Chinese",
                "繁": "Traditional Chinese",
                "tc": "Traditional Chinese",
                "traditional": "Traditional Chinese",
                "zh": "Traditional Chinese",
                "zh-tw": "Traditional Chinese",
                "zh-cn": "Simplified Chinese",
            }

            # Default to Traditional Chinese if not specified or not recognized
            selected_language = language_map.get(language, "Traditional Chinese")

            # Clear error and proceed
            self.query_one("#error-msg", Static).update("")
            app = cast("JiraToTestCaseApp", self.app)
            app.ticket_key = ticket_key
            app.initial_middle = middle_num if middle_num else "010"
            app.output_language = selected_language
            debug_log(f"InputScreen: Pushing loading screen for ticket {ticket_key}")
            app.push_screen(LoadingScreen())


class LoadingScreen(Screen):
    """Screen showing progress of operations"""

    current_step = reactive("")
    progress = reactive(0.0)

    def compose(self) -> ComposeResult:
        with Center():
            with Vertical(id="loading-container"):
                yield Label("Generating Test Cases", id="loading-title")
                yield Label("Initializing...", id="current-task")

                # Progress bar
                with Horizontal(id="progress-container"):
                    yield Static("▱" * 30, id="progress-bar")

                yield Label("0%", id="progress-percent")

                # Task list showing completed and pending tasks
                yield Label("Workflow Progress:", id="task-list-title")
                yield Static("", id="task-list")

                yield Button("Cancel", id="cancel-btn", variant="error")

    def on_mount(self) -> None:
        debug_log("LoadingScreen.on_mount() called - ENTER")
        # Start the workflow as a background task
        # This runs every time the screen is created (including after regenerate)
        self.run_worker(self.run_workflow())

    def on_show(self) -> None:
        debug_log("LoadingScreen.on_show() called - ENTER")
        # When screen becomes visible again (e.g., after regenerate)
        # Check if we need to run workflow (no results yet)
        app = cast("JiraToTestCaseApp", self.app)
        has_results = hasattr(app, "generated_test_cases") and app.generated_test_cases
        debug_log(
            f"on_show - has_results = {has_results}, generated_test_cases length = {len(app.generated_test_cases) if app.generated_test_cases else 0}"
        )
        if not has_results:
            debug_log("on_show - Will run workflow (no results)")
            # Reset UI and run workflow
            self.current_step = ""
            self.progress = 0.0
            self.query_one("#current-task", Label).update("Initializing...")
            self.query_one("#progress-bar", Static).update("▱" * 30)
            self.query_one("#progress-percent", Label).update("0%")
            self.query_one("#task-list", Static).update("")
            self.run_worker(self.run_workflow())
        else:
            debug_log("on_show - SKIPPING workflow (has results)")

    def update_progress(
        self, step: int, total: int, task_name: str, status: str = "running"
    ):
        """Update progress display

        Args:
            step: Current step number (0-indexed)
            total: Total number of steps
            task_name: Name of current task
            status: "running", "completed", or "pending"
        """
        progress_pct = int((step / total) * 100)
        self.progress = progress_pct

        # Update progress bar
        filled = int((step / total) * 30)
        empty = 30 - filled
        progress_bar = "▰" * filled + "▱" * empty
        self.query_one("#progress-bar", Static).update(progress_bar)

        # Update percentage
        self.query_one("#progress-percent", Label).update(f"{progress_pct}%")

        # Update current task
        self.query_one("#current-task", Label).update(f"⏳ {task_name}")

        # Update task list
        self.update_task_list(step, total)

    def update_task_list(self, current_step: int, total: int):
        """Update the visual task list"""
        tasks = [
            "Fetching JIRA ticket details",
            "Querying Qdrant for similar cases",
            "Generating embeddings",
            "Analyzing acceptance criteria",
            "Generating test cases with LLM",
            "Formatting results",
        ]

        # Adjust total steps
        display_tasks = tasks[:total] if total <= len(tasks) else tasks

        task_text = ""
        for i, task in enumerate(display_tasks):
            if i < current_step:
                task_text += f"✓ {task}\n"
            elif i == current_step:
                task_text += f"⏳ {task} (in progress...)\n"
            else:
                task_text += f"○ {task}\n"

        self.query_one("#task-list", Static).update(task_text.strip())

    async def run_workflow(self):
        """Run the main workflow with detailed progress tracking"""
        debug_log("run_workflow() STARTED")
        TOTAL_STEPS = 6
        app = cast("JiraToTestCaseApp", self.app)

        try:
            debug_log("Starting workflow steps...")
            # Step 1: Fetch JIRA ticket
            self.update_progress(0, TOTAL_STEPS, "Fetching JIRA ticket details...")
            await app.fetch_jira_data()
            debug_log("Step 1 complete - JIRA data fetched")

            # Step 2: Query Qdrant
            self.update_progress(1, TOTAL_STEPS, "Querying Qdrant for similar cases...")
            await app.query_qdrant()
            debug_log("Step 2 complete - Qdrant queried")

            # Step 3: Generate embeddings (sub-step)
            self.update_progress(2, TOTAL_STEPS, "Generating embeddings...")

            # Step 4: Analyze acceptance criteria
            self.update_progress(3, TOTAL_STEPS, "Analyzing acceptance criteria...")

            # Step 5: Generate test cases
            self.update_progress(4, TOTAL_STEPS, "Generating test cases with LLM...")
            await app.generate_test_cases()
            debug_log(
                f"Step 5 complete - Test cases generated, length={len(app.generated_test_cases)}"
            )

            # Step 6: Format results
            self.update_progress(5, TOTAL_STEPS, "Formatting results...")

            # Complete
            self.update_progress(6, TOTAL_STEPS, "Complete!")
            await asyncio.sleep(0.5)  # Brief pause to show 100%

            # Success - go to result screen
            debug_log("Workflow complete, pushing result screen")
            debug_log(
                f"app.generated_test_cases length before push: {len(app.generated_test_cases)}"
            )
            app.push_screen(ResultScreen())

        except Exception as e:
            debug_log(f"Workflow ERROR: {e}")
            import traceback

            traceback.print_exc()
            app.error_message = str(e)
            app.push_screen(ErrorScreen())

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel-btn":
            debug_log("LoadingScreen: Cancel button clicked")
            # Create fresh input screen
            from textual.app import App

            cast("JiraToTestCaseApp", self.app).push_screen(InputScreen())


class ResultScreen(Screen):
    """Screen displaying generated test cases"""

    def compose(self) -> ComposeResult:
        with Vertical(id="result-container"):
            yield Label("Generated Test Cases", id="result-title")
            with VerticalScroll(id="result-scroll-area"):
                yield Markdown("", id="test-cases-md")
            with Horizontal(id="result-buttons"):
                yield Button("Copy to Clipboard", id="copy-btn", variant="primary")
                yield Button("Regenerate", id="regenerate-btn")
                yield Button("New Ticket", id="new-btn")

    def on_mount(self) -> None:
        debug_log("ResultScreen.on_mount() called")
        # Display generated test cases
        app = cast("JiraToTestCaseApp", self.app)
        if hasattr(app, "generated_test_cases"):
            debug_log(
                f"ResultScreen - has generated_test_cases, len={len(app.generated_test_cases)}"
            )
            self.query_one("#test-cases-md", Markdown).update(app.generated_test_cases)
        else:
            debug_log("ResultScreen - NO generated_test_cases!")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        app = cast("JiraToTestCaseApp", self.app)
        debug_log(f"ResultScreen button pressed: {event.button.id}")
        if event.button.id == "copy-btn":
            # Copy to clipboard (platform dependent)
            if hasattr(app, "generated_test_cases"):
                self.copy_to_clipboard(app.generated_test_cases)
        elif event.button.id == "regenerate-btn":
            debug_log("Regenerate button clicked")
            # Clear previous results and regenerate
            app.generated_test_cases = ""
            app.similar_cases = []
            debug_log(
                f"After clear - generated_test_cases = '{app.generated_test_cases}'"
            )

            # Create a fresh LoadingScreen instance to ensure on_mount/on_show are called
            debug_log("Creating fresh LoadingScreen instance")
            fresh_loading_screen = LoadingScreen()
            app.push_screen(fresh_loading_screen)
            debug_log("Pushed fresh LoadingScreen instance")
        elif event.button.id == "new-btn":
            debug_log("New Ticket button clicked")
            # Create fresh input screen
            app.push_screen(InputScreen())

    def copy_to_clipboard(self, text: str):
        """Copy text to clipboard"""
        try:
            import pyperclip

            pyperclip.copy(text)
        except ImportError:
            # Fallback for systems without pyperclip
            import subprocess

            subprocess.run(["pbcopy"], input=text.encode(), check=True)


class ErrorScreen(Screen):
    """Screen for displaying errors"""

    def compose(self) -> ComposeResult:
        with Center():
            with Vertical():
                yield Label("Error", id="error-title")
                yield Static("", id="error-text")
                yield Button("Back", id="back-btn", variant="primary")

    def on_mount(self) -> None:
        app = cast("JiraToTestCaseApp", self.app)
        if hasattr(app, "error_message"):
            self.query_one("#error-text", Static).update(app.error_message)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back-btn":
            debug_log("ErrorScreen: Back button clicked")
            # Create fresh input screen
            cast("JiraToTestCaseApp", self.app).push_screen(InputScreen())


class JiraToTestCaseApp(App):
    """Main TUI Application"""

    CSS = """
    Screen {
        align: center middle;
    }
    
    #title {
        text-align: center;
        text-style: bold;
        padding: 1 0;
    }
    
    #label-ticket, #label-middle, #label-language {
        padding: 1 0 0 0;
    }
    
    #ticket-input, #middle-input {
        width: 40;
        margin: 1 0;
    }
    
    #submit-btn {
        margin: 2 0;
    }
    
    #error-msg {
        color: red;
        text-style: bold;
    }
    
    #loading-container {
        width: 60;
        padding: 2;
    }
    
    #loading-title {
        text-align: center;
        text-style: bold;
        padding: 1 0;
    }
    
    #current-task {
        text-align: center;
        text-style: bold;
        color: blue;
        padding: 1 0;
    }
    
    #progress-container {
        text-align: center;
        padding: 1 0;
    }
    
    #progress-bar {
        text-align: center;
        color: green;
        text-style: bold;
    }
    
    #progress-percent {
        text-align: center;
        text-style: bold;
        padding: 0 0 1 0;
    }
    
    #task-list-title {
        text-style: bold;
        padding: 1 0 0 0;
    }
    
    #task-list {
        padding: 1;
        height: auto;
    }
    
    #status-text {
        text-align: center;
        padding: 1 0;
    }
    
    #result-container {
        height: 100%;
        width: 100%;
    }
    
    #result-title {
        text-align: center;
        text-style: bold;
        padding: 1 0;
        height: auto;
    }
    
    #result-scroll-area {
        height: 1fr;
        width: 100%;
        border: solid green;
        padding: 1;
    }
    
    #test-cases-md {
        height: auto;
        width: 100%;
    }
    
    #result-buttons {
        height: auto;
        padding: 1 0;
        align: center middle;
    }
    
    #error-title {
        text-align: center;
        text-style: bold;
        color: red;
        padding: 1 0;
    }
    
    #error-text {
        text-align: center;
        padding: 1 0;
        color: red;
    }
    """

    def __init__(self):
        super().__init__()
        debug_log("JiraToTestCaseApp.__init__ called")
        self.ticket_key = ""
        self.initial_middle = "010"
        self.output_language = "Traditional Chinese"
        self.jira_ticket: Optional[JiraTicket] = None
        self.similar_cases: List[Dict[str, Any]] = []
        self.generated_test_cases = ""
        self.error_message = ""

    def on_mount(self):
        debug_log("JiraToTestCaseApp.on_mount() called")
        self.push_screen(InputScreen())

    def format_test_cases_markdown(self, data: Dict[str, Any]) -> str:
        """Convert JSON test cases into markdown for display"""
        summary = data.get("summary", {})
        ticket_key = summary.get("ticket_key", "")
        language = summary.get("language", "")
        sections = summary.get("sections", [])
        details = data.get("details", [])

        lines = []
        title = (
            f"# Test Case Summary for {ticket_key}"
            if ticket_key
            else "# Test Case Summary"
        )
        lines.append(title)
        if language:
            lines.append(f"\nLanguage: {language}")

        lines.append("\n## All Sections Overview")
        for section in sections:
            section_id = section.get("section", "")
            criteria = section.get("acceptance_criteria", "")
            count = section.get("count", "")
            count_text = f" - {count} test cases" if count != "" else ""
            criteria_text = f"{criteria}" if criteria else "[Acceptance Criteria]"
            lines.append(f"- Section {section_id}: {criteria_text}{count_text}")

        details_by_section = {item.get("section"): item for item in details}

        for section in sections:
            section_id = section.get("section", "")
            criteria = section.get("acceptance_criteria", "")
            lines.append("\n---")
            lines.append(
                f"\n## Section {section_id} - {criteria if criteria else '[Acceptance Criteria]'}"
            )

            lines.append("\n### Test Cases Overview")
            for tc in section.get("test_cases", []):
                tc_id = tc.get("id", "")
                tc_title = tc.get("title", "")
                lines.append(f"- {tc_id}: {tc_title}")

            section_details = details_by_section.get(section_id, {})
            section_test_cases = section_details.get("test_cases", [])
            lines.append("\n### Detailed Test Cases")
            for tc in section_test_cases:
                tc_id = tc.get("id", "")
                tc_title = tc.get("title", "")
                precondition = tc.get("precondition", [])
                steps = tc.get("steps", [])
                expected_result = tc.get("expected_result", [])

                lines.append(f"\n#### {tc_id}: {tc_title}")
                lines.append("Precondition:")
                if precondition:
                    for item in precondition:
                        lines.append(f"- {item}")
                else:
                    lines.append("- [Missing]")

                lines.append("\nSteps:")
                if steps:
                    for idx, step in enumerate(steps, start=1):
                        lines.append(f"{idx}. {step}")
                else:
                    lines.append("1. [Missing]")

                lines.append("\nExpected Result:")
                if expected_result:
                    for item in expected_result:
                        lines.append(f"- {item}")
                else:
                    lines.append("- [Missing]")

        return "\n".join(lines)

    async def fetch_jira_data(self):
        """Fetch JIRA ticket data"""
        from app.services.jira_client import JiraClient
        from app.config import settings

        try:
            jira_client = JiraClient()
            issue = jira_client.get_issue(self.ticket_key)

            if not issue:
                raise ValueError(f"Ticket {self.ticket_key} not found")

            fields = issue.get("fields", {})

            self.jira_ticket = JiraTicket(
                key=self.ticket_key,
                summary=fields.get("summary", ""),
                description=fields.get("description", ""),
                components=[c.get("name", "") for c in fields.get("components", [])],
                labels=fields.get("labels", []),
                status=fields.get("status", {}).get("name", ""),
            )
        except Exception as e:
            raise Exception(f"Failed to fetch JIRA ticket: {str(e)}")

    async def query_qdrant(self):
        """Query Qdrant for similar test cases"""
        from qdrant_client import QdrantClient
        import requests

        # Get Qdrant config with hot-reload
        qdrant_config = get_qdrant_config()

        if self.jira_ticket is None:
            raise Exception("JIRA ticket not loaded")

        try:
            # Generate embedding for ticket description
            embedding = await self.get_embeddings(self.jira_ticket.description)

            client = QdrantClient(url=qdrant_config.url)

            # Query test_cases collection
            tc_results = client.search(
                collection_name=qdrant_config.collection_test_cases,
                query_vector=embedding,
                limit=qdrant_config.limit.test_cases,
            )

            # Query usm_nodes collection
            usm_results = client.search(
                collection_name=qdrant_config.collection_usm_nodes,
                query_vector=embedding,
                limit=qdrant_config.limit.usm_nodes,
            )

            # Combine results
            self.similar_cases = []
            for result in tc_results:
                payload = result.payload or {}
                self.similar_cases.append(
                    {
                        "text": payload.get("text", ""),
                        "score": result.score,
                        "source": "test_case",
                    }
                )
            for result in usm_results:
                payload = result.payload or {}
                self.similar_cases.append(
                    {
                        "text": payload.get("text", ""),
                        "score": result.score,
                        "source": "usm_node",
                    }
                )

        except Exception as e:
            raise Exception(f"Failed to query Qdrant: {str(e)}")

    async def get_embeddings(self, text: str) -> List[float]:
        """Generate embedding using OpenRouter"""
        import requests
        from app.config import settings

        # Get embedding config with hot-reload
        embed_config = get_embedding_config()

        headers = {
            "Authorization": f"Bearer {settings.openrouter.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": settings.app.get_base_url(),
            "X-Title": "TCRT Test Case Generator",
        }

        payload = {"input": [text], "model": embed_config.model}

        response = requests.post(embed_config.api_url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()

        return data["data"][0]["embedding"]

    async def generate_test_cases(self):
        """Generate test cases using OpenRouter LLM"""
        import requests
        from app.config import settings

        # Get chat config with hot-reload
        chat_config = get_chat_config()

        headers = {
            "Authorization": f"Bearer {settings.openrouter.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": settings.app.get_base_url(),
            "X-Title": "TCRT Test Case Generator",
        }

        if self.jira_ticket is None:
            raise Exception("JIRA ticket not loaded")

        # Format similar cases for prompt
        similar_cases_text = "\n\n".join(
            [
                f"Similar Case {i + 1}:\n{case['text'][:500]}..."
                for i, case in enumerate(self.similar_cases[:5])
            ]
        )

        # Use format_prompt from config module (supports hot-reload)
        prompt = format_prompt(
            output_language=self.output_language,
            ticket_key=self.jira_ticket.key,
            ticket_summary=self.jira_ticket.summary,
            ticket_description=self.jira_ticket.description,
            ticket_components=", ".join(self.jira_ticket.components)
            if self.jira_ticket.components
            else "N/A",
            similar_cases=self.similar_cases,
            initial_middle=self.initial_middle,
        )

        payload = {
            "model": chat_config.model,
            "messages": [
                {
                    "role": "system",
                    "content": chat_config.system_prompt,
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": chat_config.temperature,
        }

        try:
            response = requests.post(
                chat_config.api_url,
                json=payload,
                headers=headers,
                timeout=chat_config.timeout,
            )
            response.raise_for_status()
            data = response.json()

            content = data["choices"][0]["message"]["content"]
            content = content.strip()
            if content.startswith("```"):
                content = content.strip("`")
                if content.startswith("json"):
                    content = content[4:].strip()

            parsed = json.loads(content)
            self.generated_test_cases = self.format_test_cases_markdown(parsed)
        except Exception as e:
            raise Exception(f"Failed to generate test cases: {str(e)}")


if __name__ == "__main__":
    # Load and display LLM configuration at startup
    debug_log("Loading LLM configuration...")
    config = get_llm_config()
    debug_log(f"  Embedding model: {config.embedding.model}")
    debug_log(f"  Chat model: {config.chat.model}")
    debug_log(f"  Temperature: {config.chat.temperature}")
    debug_log(f"  Prompt template loaded: {len(config.prompt.template)} chars")
    debug_log(f"  Qdrant URL: {config.qdrant.url}")
    debug_log(f"  Collection TC: {config.qdrant.collection_test_cases}")
    debug_log(f"  Collection USM: {config.qdrant.collection_usm_nodes}")
    debug_log("Configuration loaded successfully. Starting app...")

    app = JiraToTestCaseApp()
    app.run()
