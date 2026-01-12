from pathlib import Path

# Path configuration
ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output"
STATE_DUMPS_DIR = OUTPUT_DIR / "state_dumps"

# Graph paths
MAIN_GRAPH_PATH = OUTPUT_DIR / "graphs" / "main_graph.png"
HEADER_GRAPH_PATH = OUTPUT_DIR / "graphs" / "header.jpg"
INTERPRETER_GRAPH_PATH = OUTPUT_DIR / "graphs" / "interpreter_subgraph.png"
SQL_DRAFTER_GRAPH_PATH = OUTPUT_DIR / "graphs" / "sql_drafter_subgraph.png"
EXECUTOR_GRAPH_PATH = OUTPUT_DIR / "graphs" / "executor_subgraph.png"

# UI Constants
PRIMARY_BLUE = "#0b2d59"

# Page configuration
PAGE_TITLE = "SQL Query Assistant"
LAYOUT = "wide"

# Custom CSS styling
CUSTOM_CSS = f"""
<style>
div.stButton > button:first-child {{
    background-color: {PRIMARY_BLUE};
    color: #ffffff;
    border: 1px solid {PRIMARY_BLUE};
}}
div.stButton > button:first-child:hover {{
    background-color: #0d3568;
    border-color: #0d3568;
}}
div.stCheckbox input[type="checkbox"] {{
    accent-color: {PRIMARY_BLUE};
}}
</style>
"""
