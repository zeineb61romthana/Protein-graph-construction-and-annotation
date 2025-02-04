from flask import Flask, render_template, request, jsonify
from neo4j import GraphDatabase
from datetime import datetime
import logging

app = Flask(__name__)

# Neo4j connection details
NEO4J_URI = "bolt://neo4j-container:7687"
USERNAME = "neo4j"
PASSWORD = "12345678"

driver = GraphDatabase.driver(NEO4J_URI, auth=(USERNAME, PASSWORD))

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/query', methods=['POST'])
def query_protein():
    try:
        protein_id = request.form.get('protein_id')
        if not protein_id:
            return jsonify({'error': 'No protein ID provided'}), 400
        
        with driver.session() as session:
            result = session.run("""
                MATCH (p:Protein {id: $protein_id})
                OPTIONAL MATCH (p)-[r:SIMILAR]->(neighbor)
                OPTIONAL MATCH (p)-[:HAS_FUNCTION]->(e:EC)
                OPTIONAL MATCH (p)-[:PREDICTED_FUNCTION]->(pe:EC)
                RETURN 
                    p.id AS protein_id, 
                    p.name AS protein_name, 
                    collect(DISTINCT e.id) AS known_functions,
                    collect(DISTINCT pe.id) AS predicted_functions,
                    collect({id: neighbor.id, name: neighbor.name, similarity: r.similarity}) AS neighbors
            """, protein_id=protein_id)

            data = result.single()
            return jsonify({
                'protein_id': data.get('protein_id', 'Unknown'),
                'protein_name': data.get('protein_name', 'Unknown'),
                'known_functions': data.get('known_functions', []),
                'predicted_functions': data.get('predicted_functions', []),
                'neighbors': data.get('neighbors', []),
                'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)