from neo4j import GraphDatabase

URI = "bolt://localhost:7687"
USER = "neo4j"
PASSWORD = "password"

driver = GraphDatabase.driver(
    URI,
    auth=(USER, PASSWORD)
)

query = """
CREATE (t:Test {name: "hello"})
RETURN t
"""

with driver.session() as session:
    result = session.run(query)
    result.consume()

print("Sikeres mentés!")

driver.close()