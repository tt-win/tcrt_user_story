## Architecture

The PoC script follows a linear workflow with clear UI state transitions:

```
┌─────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   Input     │────▶│    Fetch     │────▶│    Query     │────▶│   Generate   │────▶│   Display    │
│   Screen    │     │   JIRA API   │     │   Qdrant     │     │     LLM      │     │   Results    │
│             │     │              │     │              │     │              │     │              │
│ [Text Input]│     │ Get ticket   │     │ Vector search│     │ OpenRouter   │     │ Markdown     │
│ [Validate]  │     │ details      │     │ for similar  │     │ API          │     │ formatted    │
│ [Submit]    │     │              │     │ test cases   │     │              │     │ display      │
└─────────────┘     └──────────────┘     └──────────────┘     └──────────────┘     └──────────────┘
                           │                    │                    │                    │
                           ▼                    ▼                    ▼                    ▼
                    ┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
                    │ Error Handler│     │ Error Handler│     │ Error Handler│     │   Actions    │
                    │ Invalid key  │     │ Connection   │     │ Timeout/Error│     │ [Copy]       │
                    │              │     │ failed       │     │              │     │ [Regenerate] │
                    └──────────────┘     └──────────────┘     └──────────────┘     └──────────────┘
```

## Key Components

### 1. TUI App Structure (textual)

```python
class JiraToTestCaseApp(App):
    """Main TUI Application"""
    
    CSS = """
    /* Screen layouts */
    """
    
    def compose(self) -> ComposeResult:
        # Input screen with ticket key input
        # Loading screen with progress indicators
        # Results screen with generated test cases
        pass
```

**Screens:**
- `InputScreen`: Input field for JIRA ticket key, submit button
- `LoadingScreen`: Shows progress: "Fetching JIRA..." → "Querying Qdrant..." → "Generating with LLM..."
- `ResultScreen`: Displays generated test cases in markdown format with action buttons

### 2. JIRA Integration

```python
async def fetch_jira_ticket(ticket_key: str) -> Dict[str, Any]:
    """Fetch ticket details from JIRA API"""
    # Use existing JiraClient from app.services.jira_client
    # Extract: summary, description, components, labels, status
    # Return structured data
```

**Data Structure:**
```python
@dataclass
class JiraTicket:
    key: str
    summary: str
    description: str
    components: List[str]
    labels: List[str]
    status: str
```

### 3. Qdrant Vector Search

```python
# Configuration
QDRANT_HOST = "localhost:6333"
COLLECTION_TEST_CASES = "test_cases"  # 70% weight
COLLECTION_USM_NODES = "usm_nodes"    # 30% weight

async def search_similar_items(
    ticket_description: str,
    component: str,
    limit: int = 5
) -> List[Dict[str, Any]]:
    """Query Qdrant for similar test cases and user stories"""
    # Generate embedding for ticket description
    # Query both collections with weighted results
    # test_cases: 70% weight, usm_nodes: 30% weight
    # Return combined top N results with metadata
```

**Implementation Notes:**
- Use existing `get_embeddings()` function from `ai/etl_all_teams.py` pattern
- Qdrant Host: `localhost:6333`
- Collections: `test_cases` (70%), `usm_nodes` (30%)
- Search using cosine similarity
- Combine results from both collections with specified weights

### 4. LLM Test Case Generation

```python
async def generate_test_cases(
    ticket: JiraTicket,
    similar_cases: List[Dict[str, Any]]
) -> str:
    """Generate test cases using OpenRouter"""
    # Build prompt with:
    #   - Ticket details (summary, description, component)
    #   - Similar test cases as examples (reference only)
    #   - Instructions for output format
    # Call OpenRouter API (openrouter/free)
    # Return generated test cases
```

**Prompt Template:**
```
You are a QA engineer. Generate comprehensive test cases for the following JIRA ticket:

Ticket: {ticket_key}
Summary: {summary}
Description: {description}
Component: {component}

Here are some similar test cases from our history for reference:
{similar_cases_formatted}

Generate 3-5 test cases in the following format:

Test Case ID: [TCG-123.010.010]
Test Case Title: [Title]
Precondition:
- 

Steps:
1. 
2. 

Expected Result:
- 

Make sure to cover:
- Happy path scenarios
- Edge cases
- Error scenarios (if applicable)
```

## Data Flow

1. **User Input** → `InputScreen` validates JIRA key format (PROJECT-123)
2. **Fetch JIRA** → `fetch_jira_ticket()` retrieves ticket details
3. **Query Qdrant** → `search_similar_items()` queries both collections:
   - `test_cases` collection (70% weight)
   - `usm_nodes` collection (30% weight)
4. **Generate** → `generate_test_cases()` calls OpenRouter LLM
5. **Display** → `ResultScreen` shows formatted output

## Dependencies

```python
# Required imports
import asyncio
from textual.app import App, ComposeResult
from textual.widgets import Input, Button, Static, Markdown
from textual.containers import Vertical, Horizontal
from dataclasses import dataclass
from typing import List, Dict, Any

# Internal project imports
from app.services.jira_client import JiraClient
from app.config import settings

# External dependencies (ensure installed)
# pip install textual qdrant-client requests
```

## Error Handling Strategy

Each external call wrapped in try-except with user-friendly messages:

```python
async def safe_operation(operation_name: str, coro):
    try:
        return await asyncio.wait_for(coro, timeout=30)
    except asyncio.TimeoutError:
        show_error(f"{operation_name} timed out")
    except Exception as e:
        show_error(f"{operation_name} failed: {str(e)}")
```

## UI/UX Design

**Color Scheme:**
- Primary: Blue (#2563eb)
- Success: Green (#22c55e)
- Error: Red (#ef4444)
- Background: Dark theme (textual default)

**Layout:**
- Centered input on InputScreen
- Full-width markdown display on ResultScreen
- Each test case shows a Test Case ID field before the title
- Test Case ID format follows `[TCG單號].[中間號].[尾號]` with 10-step increments
- Fixed footer with action buttons

## Testing Strategy

1. **Manual Testing**: Test with real JIRA tickets
2. **Mock Mode**: Add `--mock` flag for development without external APIs
3. **Error Testing**: Test each error scenario (invalid key, API failures)
