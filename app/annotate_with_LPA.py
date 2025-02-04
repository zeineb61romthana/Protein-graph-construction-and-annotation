from pyspark.sql import SparkSession
from pyspark.sql.functions import col, split, size, array_intersect, array_union, when, array
from neo4j import GraphDatabase

# ✅ Start Spark session (Optimized for Low-Resource Machine)
spark = SparkSession.builder \
    .appName("ProteinGraphOptimization") \
    .config("spark.driver.memory", "2g") \
    .config("spark.executor.memory", "2g") \
    .config("spark.sql.shuffle.partitions", "10") \
    .config("spark.default.parallelism", "2") \
    .getOrCreate()

# ✅ Start Spark session
spark = SparkSession.builder \
    .appName("ProteinGraphOptimization") \
    .getOrCreate()

# ✅ Load and preprocess dataset
data_path = "/app/data/3702_2025_01_06.tsv"
df = spark.read.option("delimiter", "\t").option("header", "true").csv(data_path)

# ✅ Connect to Neo4j
NEO4J_URI = "bolt://neo4j-container:7687"
USERNAME = "neo4j"
PASSWORD = "12345678"
driver = GraphDatabase.driver(NEO4J_URI, auth=(USERNAME, PASSWORD))

# ✅ Ensure data is loaded
print(f"🔹 Total Proteins: {df.count()}")

# ✅ Replace NULL `Protein names` with "Unknown"
df = df.withColumn("Protein names", when(col("Protein names").isNull(), "Unknown").otherwise(col("Protein names")))

# ✅ Keep necessary columns
df = df.select(
    col("Entry").alias("protein_id"),
    col("Protein names").alias("protein_name"),
    col("InterPro").alias("interpro"),
    col("EC number").alias("ec_number")
)

# ✅ Replace NULL `InterPro` values with empty array and create labeled flag
df = df.withColumn("is_labeled", col("interpro").isNotNull())  
df = df.withColumn("interpro", when(col("interpro").isNotNull(), split(col("interpro"), ";")).otherwise(array()))  

# ✅ Count labeled vs. unlabeled proteins
unlabeled_count = df.filter(~col("is_labeled")).count()
labeled_count = df.filter(col("is_labeled")).count()

print(f"🔹 Total Proteins: {df.count()}")
print(f"✅ Labeled Proteins: {labeled_count}")
print(f"⚠️ Unlabeled Proteins: {unlabeled_count}")

# ✅ Load ALL Proteins into Neo4j before computing similarity
all_proteins = df.select("protein_id", "protein_name", "is_labeled").distinct().toPandas().to_dict(orient="records")

# ✅ Connect to Neo4j
uri = "bolt://localhost:7687"
username = "neo4j"
password = "12345678"
driver = GraphDatabase.driver(uri, auth=(username, password))

def load_proteins_with_labels(tx, proteins):
    query = """
    UNWIND $proteins AS row
    MERGE (p:Protein {id: row.protein_id})
    SET p.name = COALESCE(row.protein_name, "Unknown")
    FOREACH (ec IN row.ec_numbers | MERGE (e:EC {id: ec}) MERGE (p)-[:HAS_FUNCTION]->(e))
    """
    tx.run(query, proteins=proteins)

df = df.withColumn("ec_numbers", when(col("ec_number").isNotNull(), split(col("ec_number"), ";")).otherwise(array()))

all_proteins_with_labels = df.select("protein_id", "protein_name", "ec_numbers").distinct().toPandas().to_dict(orient="records")

try:
    with driver.session() as session:
        session.write_transaction(load_proteins_with_labels, all_proteins_with_labels)
except Exception as e:
    print(f"Error loading proteins with EC numbers into Neo4j: {e}")

print("✅ All proteins loaded into Neo4j.")

# ✅ Compute Jaccard similarity only for labeled proteins
df1 = df.filter(col("is_labeled")).alias("p1").limit(500)
df2 = df.filter(col("is_labeled")).alias("p2").limit(500)

protein_pairs = df1.crossJoin(df2).filter(col("p1.protein_id") < col("p2.protein_id"))
protein_pairs = protein_pairs.withColumn("intersection", size(array_intersect(col("p1.interpro"), col("p2.interpro"))))
protein_pairs = protein_pairs.withColumn("union", size(array_union(col("p1.interpro"), col("p2.interpro"))))
protein_pairs = protein_pairs.withColumn("jaccard_similarity", col("intersection") / col("union"))

# ✅ Filter meaningful relationships
protein_graph = protein_pairs.filter(col("jaccard_similarity") > 0.1)

# ✅ Select columns for Neo4j insertion
protein_graph = protein_graph.select(
    col("p1.protein_id").alias("protein1"),
    col("p1.protein_name").alias("protein_name1"),
    col("p2.protein_id").alias("protein2"),
    col("p2.protein_name").alias("protein_name2"),
    col("jaccard_similarity")
)

# ✅ Function to load relationships into Neo4j
def load_relationships(tx, batch):
    query = """
    UNWIND $batch AS row
    MATCH (p1:Protein {id: row.protein1}), (p2:Protein {id: row.protein2})
    MERGE (p1)-[r:SIMILAR {similarity: row.jaccard_similarity}]->(p2)
    """
    tx.run(query, batch=batch)

# ✅ Insert Data into Neo4j in Batches
batch_size = 100
protein_data = protein_graph.toPandas().to_dict(orient="records")

for i in range(0, len(protein_data), batch_size):
    batch = protein_data[i:i + batch_size]
    try:
        with driver.session() as session:
            session.write_transaction(load_relationships, batch)
    except Exception as e:
        print(f"Error loading relationship batch: {e}")

print("✅ Data successfully imported into Neo4j.")

# ✅ Run Label Propagation Algorithm (LPA) in Neo4j
def run_label_propagation():
    try:
        with driver.session() as session:
            # ✅ Create Graph Projection
            session.run("""
            CALL gds.graph.project(
                'proteinGraph',
                'Protein',
                { SIMILAR: { properties: 'similarity' } }
            )
            """)

            # ✅ Run LPA
            session.run("""
            CALL gds.labelPropagation.write(
                'proteinGraph',
                { writeProperty: 'communityId' }
            )
            """)

            print("✅ Label propagation completed successfully.")

            # ✅ Retrieve Assigned Communities
            result = session.run("""
            MATCH (p:Protein) WHERE p.communityId IS NOT NULL
            RETURN p.id AS protein_id, p.communityId
            """)
            lpa_data = result.data()

            if not lpa_data:
                print("❌ No communityId was assigned. Check if the graph is connected.")
            else:
                print(f"🔹 {len(lpa_data)} proteins received a label.")
    
    except Exception as e:
        print(f"Error during label propagation: {e}")

run_label_propagation()

def assign_labels_from_lpa():
    try:
        with driver.session() as session:
            session.run("""
            MATCH (p1:Protein)-[:SIMILAR]->(p2:Protein)
            WHERE p1.communityId = p2.communityId 
              AND NOT EXISTS {(p1)-[:HAS_FUNCTION]->(:EC)}
            MATCH (p2)-[:HAS_FUNCTION]->(e:EC)
            MERGE (p1)-[:PREDICTED_FUNCTION]->(e)
            """)
        
        print("✅ EC numbers propagated to unlabeled proteins!")
    
    except Exception as e:
        print(f"Error during function propagation: {e}")

assign_labels_from_lpa()
