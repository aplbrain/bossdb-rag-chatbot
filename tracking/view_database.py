from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from tabulate import tabulate
from database_models import Base, DATABASE_URL


def view_database():
    """
    View the contents of the database tables.

    This function connects to the database, retrieves the first 5 rows from each table,
    and prints them in a formatted table.
    """
    engine = create_engine(DATABASE_URL.replace("+aiosqlite", ""))
    Session = sessionmaker(bind=engine)
    session = Session()
    inspector = inspect(engine)

    print(f"\nDatabase: {DATABASE_URL}\n")

    for table_name in inspector.get_table_names():
        print(f"Table: {table_name}")

        columns = [column["name"] for column in inspector.get_columns(table_name)]

        result = session.execute(text(f"SELECT * FROM {table_name} LIMIT 5"))
        rows = result.fetchall()

        print(tabulate(rows, headers=columns, tablefmt="grid"))
        print("\n")

    session.close()


if __name__ == "__main__":
    try:
        view_database()
    except Exception as e:
        print(f"Error: Unable to view database. {str(e)}")
