import psycopg2

DB_PARAMS = {
    'host': 'localhost',
    'database': 'testdb',
    'user': 'testuser',
    'password': 'mypassword',
    'port': 5432
}

def insert_n_rows(n=1_000_000):
    """
    Insert n rows into sample_data table using PostgreSQL's generate_series
    
    Args:
        n: Number of rows to insert (default 1 million)
    """
    conn = psycopg2.connect(**DB_PARAMS)
    cur = conn.cursor()
    
    print(f"Creating table and inserting {n:,} rows...")
    
    # Create table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sample_data (
            id BIGSERIAL PRIMARY KEY,
            value DOUBLE PRECISION,
            category VARCHAR(50),
            timestamp TIMESTAMP
        );
    """)
    
    # Insert data using generate_series
    cur.execute(f"""
        INSERT INTO sample_data (value, category, timestamp)
        SELECT 
            50 + (random() - 0.5) * 30 + (random() - 0.5) * 30,
            CHR(65 + floor(random() * 5)::int),
            NOW() - (random() * INTERVAL '365 days')
        FROM generate_series(1, {n});
    """)
    
    # Create index
    cur.execute("CREATE INDEX IF NOT EXISTS idx_value ON sample_data(value);")
    
    # Analyze table
    cur.execute("ANALYZE sample_data;")
    
    conn.commit()
    cur.close()
    conn.close()
    
    print(f"✓ Successfully inserted {n:,} rows")