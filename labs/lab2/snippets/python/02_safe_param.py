import sqlite3
user = input('u: ')
conn=sqlite3.connect('app.db')
print(conn.execute('SELECT * FROM users WHERE name = ?', (user,)).fetchall())