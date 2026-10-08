import sqlite3
user = input('u: ')
q = "SELECT * FROM users WHERE name = '" + user + "'"
conn=sqlite3.connect('app.db')
print(conn.execute(q).fetchall())  # CWE-89