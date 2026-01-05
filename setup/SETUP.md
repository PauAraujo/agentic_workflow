## Setup
The setup process involves two main steps:

1. Export - Extract data and metadata from Oracle database (get_oracle_exports.py)
2. Build - Convert exported data into SQLite database (build_db.py)

### Export from Oracle
Use `get_oracle_exports.py` to export both data and metadata from an Oracle database schema to local files that can be used for development, testing, or analysis without requiring direct Oracle database access.

1. Connects to Oracle database 
2. Exports table data, saving the first 1000 rows of each table as CSV files
3. Exports schema metadata, capturing complete schema structure in a JSON file

#### Configuration
Edit these constants at the top of the `get_oracle_exports.py` file:
``` 
# Oracle connection details
DB_HOST = 'your-oracle-host'
DB_PORT = 1571
DB_SERVICE = 'your-service-name'
DB_USER = 'your-username'
DB_PASSWORD = 'your-password'

# What to export
TARGET_SCHEMA = 'ICSR_LOOKUP'           # Schema name you want to export
BASE_OUTPUT_DIRECTORY = '../input/db_exports'  # Output location
CSV_ROW_LIMIT = 1000                    # Max rows per table to export
```
#### Usage
```
# Export both data and metadata (default)
python setup/get_oracle_exports.py

# Export only table data
python setup/get_oracle_exports.py --export-data

# Export only schema metadata
python setup/get_oracle_exports.py --export-metadata
``` 
The script will gracefully handle common issues, such as skipping tables you don't have permissions for, and logging warnings for any export failures.

#### Output structure
``` 
  input/db_exports/
  └── ICSR_LOOKUP/                    # Schema name (uppercase)
      ├── COUNTRY.csv            # Table data (1000 rows max)
      ├── DOSE_FORM.csv
      ├── ...
      └── _metadata.json              # Complete schema metadata
```
The newly created metadata file (_metadata.json) will then contain comprehensive schema information:

- Tables - names, row counts, partitioning, compression settings
- Columns - names, data types, lengths, precision, nullability, defaults
- Comments - table and column descriptions
- Constraints - primary keys, unique constraints, check constraints
- Foreign keys - relationships between tables with column mappings
- Indexes - index definitions and column ordering
- Triggers - database triggers and their conditions
- Grants - user permissions
- Synonyms - table aliases

### Build SQLite database
Use `build_db.py` to convert the exported Oracle data and metadata into a local SQLite database for development and testing.

1. Finds all schema folders in input/db_exports/
2. Creates SQLite databases (one .db file per schema)
3. Imports CSV data (each CSV becomes a table in the database)
4. Preserves structure, maintaining the same table and column names

#### Input/Output flow
``` 
  INPUT:                                 OUTPUT:
  input/db_exports/                      input/db/
  └── ICSR_LOOKUP/                       └── ICSR_LOOKUP.db
      ├── ACCESS_RIGHT.csv          →        └── Tables:
      ├── ACCESS_LEVEL.csv          →            ├── ACCESS_RIGHT
      └── PATIENT.csv               →            ├── ACCESS_LEVEL
                                                 └── PATIENT
``` 

#### Usage
```
# Build all schemas found in input/db_exports/
python setup/build_db.py
``` 
First CSV in a schema:
  - Deletes existing .db file (if any)
  - Creates fresh database
  - Imports table

Subsequent CSVs in same schema:
  - Opens existing database
  - Adds new table
  - Preserves existing tables

### Typical workflow

Step 1: Export from Oracle
```
# Run export (usually takes 1-5 minutes depending on schema size)
python setup/get_oracle_exports.py

Output:
- CSV files in input/db_exports/ICSR_LOOKUP/
- _metadata.json with schema structure
```

Step 2: Build SQLite database
```
  # Import all CSVs into SQLite (usually takes seconds)
  python setup/build_db.py
``` 
Output: `input/db/ICSR_LOOKUP.db` ready to query

Step 3: Use the database
``` 
  import sqlite3

  conn = sqlite3.connect('input/db/ICSR_LOOKUP.db')
  cursor = conn.cursor()

  # Query your data
  cursor.execute('SELECT * FROM ACCESS_RIGHT LIMIT 10')
  results = cursor.fetchall()

  conn.close()
``` 


### Common scenarios

Scenario 1: refreshing data

Oracle schema changed and you need fresh exports:
```
  # Re-export from Oracle
  python setup/get_oracle_exports.py

  # Rebuild database (automatically deletes old .db file)
  python setup/build_db.py
``` 

Scenario 2: multiple schemas

 Export and build multiple schemas:
```
  # Edit get_oracle_exports.py and change TARGET_SCHEMA
  # Run for first schema
  python setup/get_oracle_exports.py  # Creates db_exports/SCHEMA1/

  # Change TARGET_SCHEMA again
  # Run for second schema
  python setup/get_oracle_exports.py  # Creates db_exports/SCHEMA2/

  # Build both at once
  python setup/build_db.py  # Creates SCHEMA1.db and SCHEMA2.db
``` 
Scenario 3: Metadata only

You only need schema structure, not data:
```
  python setup/get_oracle_exports.py --export-metadata
``` 
This creates _metadata.json without exporting CSV files. Useful for:
  - Understanding schema structure
  - Generating documentation
  - Planning queries

Scenario 4: Incremental updates

Add more tables without re-exporting everything:
  1. Manually add CSV files to input/db_exports/SCHEMA_NAME/
  2. Run python setup/build_db.py
  3. New tables are added to existing database
