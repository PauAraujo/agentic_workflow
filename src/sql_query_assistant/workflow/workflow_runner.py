import logging

from dataclasses import dataclass
from typing import Callable

from langgraph.graph.state import CompiledStateGraph

from ..config import Settings
from ..llm_client import LLMClient, create_llm_client
from ..state import WorkflowState
from ..utils import get_available_schemas
from .main_graph import build_main_graph


logger = logging.getLogger(__name__)


# Human-readable descriptions for each workflow node
NODE_DESCRIPTIONS = {
    "table_card_retriever": "Retrieving relevant tables",
    "table_selector": "Selecting tables for query",
    "sql_drafter": "Generating SQL query",
    "sql_validator": "Validating SQL syntax",
    "sql_repairer": "Repairing SQL errors",
    "sql_executor": "Executing SQL query",
    "validation_failed": "Handling validation failure",
    "persistence": "Saving results",
}


@dataclass
class NodeEvent:
    """Event emitted when a workflow node completes."""
    node_name: str
    description: str
    state_update: dict


# Type alias for progress callback
ProgressCallback = Callable[[NodeEvent], None]


class WorkflowRunner:
    """
    Runs the text-to-SQL workflow.
    """

    def __init__(self, settings: Settings):
        """
        Initialize the workflow runner.

        Args:
            settings: Application settings for LLM, persistence, and search.
        """
        self.settings = settings
        self._llm_client: LLMClient | None = None

    @property
    def llm_client(self) -> LLMClient:
        """Get or create the LLM client (cached)."""
        if self._llm_client is None:
            self._llm_client = create_llm_client(self.settings)
        return self._llm_client

    def run(
        self,
        query: str,
        schemas: list[str] | None = None,
        enable_persistence: bool = True,
        on_progress: ProgressCallback | None = None,
    ) -> WorkflowState:
        """
        Run the text-to-SQL workflow.

        Args:
            query: Natural language query to convert to SQL.
            schemas: Optional list of schema names to filter tables.
                     If None, uses all available schemas.
            enable_persistence: Whether to save results to disk.
            on_progress: Optional callback invoked after each node completes.

        Returns:
            Final workflow state with SQL draft and execution results.

        Raises:
            ValueError: If schemas list is empty or contains invalid names.
        """
        self._validate_schemas(schemas)

        graph = self._build_graph(enable_persistence)
        initial_state = self._create_initial_state(query, schemas)

        logger.info("Processing query: %s", query)

        if on_progress:
            return self._run_with_progress(graph, initial_state, on_progress)
        return graph.invoke(initial_state)

    def _validate_schemas(self, schemas: list[str] | None) -> None:
        """Validate schema names if provided."""
        if schemas is None:
            logger.info("Workflow using all available schemas")
            return

        if len(schemas) == 0:
            raise ValueError(
                "schemas list cannot be empty. Use None to query all schemas "
                "or provide at least one schema name."
            )

        available_schemas = get_available_schemas(self.settings)
        invalid_schemas = [s for s in schemas if s not in available_schemas]
        if invalid_schemas:
            raise ValueError(
                f"Invalid schema(s): {invalid_schemas}. "
                f"Available schemas: {list(available_schemas.keys())}"
            )

        logger.info("Workflow restricted to schemas: %s", schemas)

    def _build_graph(self, enable_persistence: bool) -> CompiledStateGraph:
        """Build and compile the workflow graph."""
        logger.info("Building workflow graph...")
        return build_main_graph(
            self.llm_client,
            self.settings,
            enable_persistence=enable_persistence,
        )

    def _create_initial_state(
        self,
        query: str,
        schemas: list[str] | None,
    ) -> WorkflowState:
        """Create the initial workflow state."""
        return {
            "user_query": query,
            "table_cards": [],
            "allowed_schemas": schemas,
        }

    def _run_with_progress(
        self,
        graph: CompiledStateGraph,
        initial_state: WorkflowState,
        on_progress: ProgressCallback,
    ) -> WorkflowState:
        """Run workflow with progress callbacks."""
        final_state = dict(initial_state)

        for event in graph.stream(initial_state):
            for node_name, state_update in event.items():
                description = NODE_DESCRIPTIONS.get(node_name, f"Running {node_name}")
                on_progress(NodeEvent(node_name, description, state_update))

                if isinstance(state_update, dict):
                    final_state.update(state_update)

        return final_state
