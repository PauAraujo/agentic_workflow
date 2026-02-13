from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

IMAGES_DIR = ROOT / "app" / "images"
STATE_DUMPS_DIR = ROOT / "output" / "state_dumps"

HEADER_IMG = IMAGES_DIR / "header_image.jpg"
FLOW_DIGRAM_IMG = IMAGES_DIR / "flow_diagram.png"
COMPACT_FLOW_DIGRAM_IMG =  IMAGES_DIR / "flow_diagram_compact.png"

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
.app-footer {{
    background-color: {PRIMARY_BLUE};
    color: #ffffff;
    text-align: center;
    padding: 10px 0;
    font-size: 0.85rem;
    margin-top: 2rem;
    border-radius: 4px;
}}
.app-footer a {{
    color: #ffffff;
    text-decoration: none;
}}
.app-footer a:hover {{
    text-decoration: underline;
}}
</style>
"""
