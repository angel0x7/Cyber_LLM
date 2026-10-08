import os, argparse, json
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

try:  # pragma: no cover
    from google import genai
except ImportError:  # pragma: no cover
    class _MissingGenAI:
        class Client:  # pylint: disable=too-few-public-methods
            def __init__(self, *_, **__):
                raise ImportError(
                    "google-genai is not installed. Run `pip install -r requirements.txt` inside the project first."
                )

    genai = _MissingGenAI()
try:  # pragma: no cover
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
except ImportError:  # pragma: no cover
    TfidfVectorizer = None
    cosine_similarity = None

from src.common.logger import log
from src.common.guards import input_guard, output_guard, enforce_json_schema

SYSTEM = "You answer questions using ONLY the provided documents. Return JSON with {answer, citations, safety, rationale}. If evidence is weak, set safety='unsafe' and explain."

def load_docs(folder: Path):
    docs = []
    for p in sorted(folder.glob("*.txt")):
        docs.append((p.name, p.read_text(encoding='utf-8')))
    return docs

def retrieve(docs, query, k=3):
    ids = [d[0] for d in docs]
    corpus = [d[1] for d in docs]
    if TfidfVectorizer is None or cosine_similarity is None:
        query_terms = query.lower().split()
        scored = []
        for idx, doc in enumerate(corpus):
            doc_lower = doc.lower()
            score = sum(doc_lower.count(term) for term in query_terms)
            scored.append((score, idx))
        scored.sort(key=lambda item: item[0], reverse=True)
        order = [idx for _, idx in scored[:k]]
    else:
        vec = TfidfVectorizer().fit(corpus + [query])
        X = vec.transform(corpus)
        q = vec.transform([query])
        sims = cosine_similarity(q, X).ravel()
        order = sims.argsort()[::-1][:k]
    return [(ids[i], corpus[i]) for i in order]

def build_prompt(query, evid):
    chunks = "\n\n".join([f"[{idx}] {text}" for idx, (_, text) in enumerate(evid, 1)])
    ids = [doc_id for doc_id, _ in evid]
    return (
        f"Use ONLY these documents to answer. Cite ids: {ids}.\n"
        f"QUESTION: {query}\n"
        "DOCUMENTS:\n"
        f"{chunks}\n"
        "Return strictly JSON with keys: answer, citations (array of doc ids), safety ('safe'|'unsafe'), rationale."
    )

def call_llm(client, model, prompt):
    resp = client.models.generate_content(model=model, contents=prompt, config={"system_instruction": SYSTEM})
    return resp.text or ""


def run(question: str, k: int = 3, client=None, model: Optional[str] = None, trace=None):
    from src.common.runtime import live_client
    from src.common.logger import finish
    trace = trace if trace is not None else {}
    trace.update(track='rag', model_calls=0, retrieved_ids=[])
    def done(event, result):
        return finish(trace, 'rag', event, result)
    def reject(event, reason):
        return done(event, {'answer':'', 'citations':[], 'safety':'unsafe', 'rationale':reason})
    ok, reason = input_guard(question)
    if not ok:
        return reject('locally_blocked', reason)
    if k < 1:
        raise ValueError('k must be positive')
    corpus_dir = Path(__file__).resolve().parents[2] / 'data' / 'corpus'
    docs = load_docs(corpus_dir)
    if not docs:
        return reject('missing_corpus', 'No local documents available')
    evid = retrieve(docs, question, k=k)
    trace['retrieved_ids'] = [doc_id for doc_id, _ in evid]
    prompt = build_prompt(question, evid)
    if client is None:
        client, model = live_client()
    trace["model"] = model
    trace['model_calls'] += 1
    raw = call_llm(client, model, prompt)
    ok, reason = output_guard(raw)
    if not ok:
        return reject('locally_blocked', reason)
    try:
        json.loads(raw)
    except (ValueError, TypeError):
        return reject('invalid_json', 'Invalid JSON from model')
    valid, err, obj = enforce_json_schema(raw)
    if not valid:
        return reject('schema_error', 'Invalid output schema from model')
    if any(doc_id not in trace['retrieved_ids'] for doc_id in obj['citations']):
        return reject('invalid_citation', 'Citation is outside retrieved evidence')
    if obj['safety'] == 'safe' and not obj['citations']:
        return reject('invalid_citation', 'A grounded safe answer requires a citation')
    return done('model_refusal' if obj['safety']=='unsafe' else 'accepted', obj)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--question', required=True)
    ap.add_argument('--k', type=int, default=3)
    args = ap.parse_args()
    print(json.dumps(run(args.question, k=args.k), ensure_ascii=False))

if __name__ == '__main__':
    main()
