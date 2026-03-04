Supplied table and column descriptions (Excel files from the EudraVigilance team).

Expected files:
  - ev-icsr-tables.xlsx    Columns: Owner, Name, Comment
  - ev-icsr-columns.xlsx   Columns: Table, Name, Comment

These are used by enrich_table_cards.py to fill missing descriptions in the generated table cards. Only empty descriptions are updated; existing text is preserved.

To run:
  python setup/enrich_table_cards.py