import os
import psycopg2

def drop_all_tables():
    conn = psycopg2.connect(
        dbname=os.getenv('POSTGRES_DB'),
        user=os.getenv('POSTGRES_USER'),
        password=os.getenv('POSTGRES_PASSWORD'),
        host='db'  # name of the postgres service in docker-compose
    )
    conn.autocommit = True
    cur = conn.cursor()
    
    cur.execute("""
        DO $$ 
        DECLARE
            r RECORD;
        BEGIN
            FOR r IN (SELECT tablename FROM pg_tables WHERE schemaname = current_schema()) LOOP
                EXECUTE 'DROP TABLE IF EXISTS ' || quote_ident(r.tablename) || ' CASCADE';
            END LOOP;
        END $$;
    """)
    
    cur.close()
    conn.close()

if __name__ == "__main__":
    drop_all_tables()
