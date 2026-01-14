import os
import glob
import json

from pathlib import Path

def analyze_cards():
    # Determine project root relative to this script
    # script is in setup/table_card_analysis/
    project_root = Path(__file__).resolve().parent.parent.parent

    # Look at every schema directory under input/table_cards (e.g., ICSR, ICSR_LOOKUP, ICSR_EMA)
    table_cards_root = project_root / "input" / "table_cards"
    if not table_cards_root.exists() or not table_cards_root.is_dir():
        print(f"Table cards directory not found: {table_cards_root}")
        return

    directories = [d for d in table_cards_root.iterdir() if d.is_dir()]
    if not directories:
        print(f"No schema directories found in {table_cards_root}")
        return

    total_tables = 0
    tables_no_desc = 0
    table_desc_lengths = []

    total_columns = 0
    columns_no_desc = 0
    column_desc_lengths = []

    processed_files = set()

    for d in directories:
        if not os.path.exists(d):
            print(f"Directory not found: {d}")
            continue
        
        # glob .json files
        files = glob.glob(os.path.join(d, "*.json"))
        
        for f in files:
            # Avoid processing the same file twice if directories overlap or same file structure
            # But here they are distinct folders. Just in case, I'll use abs path
            abs_path = os.path.abspath(f)
            if abs_path in processed_files:
                continue
            processed_files.add(abs_path)

            try:
                with open(f, 'r', encoding='utf-8') as json_file:
                    data = json.load(json_file)
                
                total_tables += 1
                
                # Check table description
                meta = data.get("table_metadata", {})
                table_desc = meta.get("description")
                
                if not table_desc or not isinstance(table_desc, str) or not table_desc.strip():
                    tables_no_desc += 1
                else:
                    print(f"Table with description: {meta.get('name')}")
                    table_desc_lengths.append(len(table_desc))

                # Check columns
                columns = data.get("columns", [])
                for col in columns:
                    total_columns += 1
                    col_desc = col.get("description")
                    
                    if not col_desc or not isinstance(col_desc, str) or not col_desc.strip():
                        columns_no_desc += 1
                    else:
                        column_desc_lengths.append(len(col_desc))
            
            except Exception as e:
                print(f"Error processing {f}: {e}")

    # Calculate stats
    pct_tables_no_desc = (tables_no_desc / total_tables * 100) if total_tables > 0 else 0
    pct_columns_no_desc = (columns_no_desc / total_columns * 100) if total_columns > 0 else 0
    
    avg_table_desc_len = (sum(table_desc_lengths) / len(table_desc_lengths)) if table_desc_lengths else 0
    avg_col_desc_len = (sum(column_desc_lengths) / len(column_desc_lengths)) if column_desc_lengths else 0

    print(f"Total tables: {total_tables}")
    print(f"Tables with no description: {tables_no_desc}")
    print(f"Percentage tables no description: {pct_tables_no_desc:.2f}%")
    print(f"Average table description length: {avg_table_desc_len:.2f}")
    
    print("-" * 20)
    
    print(f"Total columns: {total_columns}")
    print(f"Columns with no description: {columns_no_desc}")
    print(f"Percentage columns no description: {pct_columns_no_desc:.2f}%")
    print(f"Average column description length: {avg_col_desc_len:.2f}")

if __name__ == "__main__":
    analyze_cards()
