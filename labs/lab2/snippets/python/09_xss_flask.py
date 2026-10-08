from flask import Flask, request
app = Flask(__name__)
@app.route('/')
def i():
  name = request.args.get('name','')
  return f"<h1>{name}</h1>"  # CWE-79