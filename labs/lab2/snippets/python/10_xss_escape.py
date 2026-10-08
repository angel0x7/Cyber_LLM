from flask import Flask, request
from markupsafe import escape
app = Flask(__name__)
@app.route('/')
def i():
  name = request.args.get('name','')
  return f"<h1>{escape(name)}</h1>"