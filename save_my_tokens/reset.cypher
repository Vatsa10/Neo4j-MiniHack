// Wipe the codebase KG (keep constraints). Cypher comments use //.
MATCH (n) WHERE n:File OR n:Module OR n:Symbol OR n:Concept DETACH DELETE n;
