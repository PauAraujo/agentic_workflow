SQL function definitions that must exist before running the generated DDL.

Some virtual columns in the ICSR schema reference schema-qualified functions (e.g. "ICSR"."FUNCTION_REGEXP_REPLACE").
These functions must be created in the target Oracle instance before executing the DDL scripts in setup/generated_ddl/.

Run these manually in the target Oracle instance before the DDL.
