"""Shared application dispatcher used by the CLI and the evaluation adapter."""
import argparse
import json
from src.rag.app import run as run_rag
from src.agent.app import run as run_agent


def run_application(track, question, *, k=3, max_steps=3, client=None, model=None, trace=None):
    if track == 'rag':
        return run_rag(question, k=k, client=client, model=model, trace=trace)
    if track == 'agent':
        return run_agent(question, max_steps=max_steps, client=client, model=model, trace=trace)
    raise ValueError('track must be rag or agent')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--track', choices=['rag','agent'], required=True)
    parser.add_argument('--question', required=True)
    parser.add_argument('--k', type=int, default=3)
    parser.add_argument('--max-steps', type=int, default=3)
    args = parser.parse_args()
    result = run_application(args.track, args.question, k=args.k, max_steps=args.max_steps)
    print(json.dumps(result, ensure_ascii=False))

if __name__ == '__main__':
    main()
