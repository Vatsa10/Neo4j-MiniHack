// Save My Tokens — codebase KG schema (AuraDB). Cypher comments use //.
CREATE CONSTRAINT file_path  IF NOT EXISTS FOR (f:File)    REQUIRE f.path IS UNIQUE;
CREATE CONSTRAINT module_name IF NOT EXISTS FOR (m:Module)  REQUIRE m.name IS UNIQUE;
CREATE CONSTRAINT symbol_key  IF NOT EXISTS FOR (s:Symbol)  REQUIRE s.key  IS UNIQUE;
CREATE CONSTRAINT concept_name IF NOT EXISTS FOR (c:Concept) REQUIRE c.name IS UNIQUE;
