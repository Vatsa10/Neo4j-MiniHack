#!/usr/bin/env python3
"""Save My Tokens — add a semantic layer to the codebase KG.

Embeds Concept nodes (text-embedding-3-small) and creates a Neo4j vector index,
so retrieval can match a task by *meaning* ("how is config loaded" -> concept
"flask config") instead of substring, then traverse ABOUT edges to the files.

Run once after ingest.py --llm:  python3 save-my-tokens/embed.py
Needs OPENAI_API_KEY + NEO4J_* in env.
"""
import os

from dotenv import load_dotenv
from neo4j import GraphDatabase
from openai import OpenAI

load_dotenv()
EMBED_MODEL = "text-embedding-3-small"  # 1536 dims, cheap
DIMS = 1536


def embed(texts, client):
    out = client.embeddings.create(model=EMBED_MODEL, input=texts)
    return [d.embedding for d in out.data]


def main():
    driver = GraphDatabase.driver(
        os.environ["NEO4J_URI"],
        auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"]),
    )
    db = os.environ.get("NEO4J_DATABASE", "neo4j")
    client = OpenAI()

    with driver, driver.session(database=db) as s:
        s.run(f"""
            CREATE VECTOR INDEX concept_vec IF NOT EXISTS FOR (c:Concept) ON c.embedding
            OPTIONS {{indexConfig: {{`vector.dimensions`: {DIMS}, `vector.similarity_function`: 'cosine'}}}}
        """)
        # Embed each concept with its connected file names for context.
        rows = s.run("""
            MATCH (c:Concept) OPTIONAL MATCH (c)<-[:ABOUT]-(f:File)
            RETURN c.name AS name, collect(f.name)[..6] AS files
        """).data()
        if not rows:
            print("no Concept nodes — run ingest.py --llm first")
            return
        texts = [f"{r['name']} — files: {', '.join(r['files'])}" for r in rows]
        vecs = embed(texts, client)
        s.run("""
            UNWIND $rows AS row
            MATCH (c:Concept {name: row.name})
            CALL db.create.setNodeVectorProperty(c, 'embedding', row.vec)
        """, rows=[{"name": r["name"], "vec": v} for r, v in zip(rows, vecs)])
        print(f"embedded {len(rows)} concepts, vector index concept_vec ready")


if __name__ == "__main__":
    main()
