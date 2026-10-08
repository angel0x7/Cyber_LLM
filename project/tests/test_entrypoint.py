import unittest
from types import SimpleNamespace
from unittest import mock
from src import app

class EntrypointTests(unittest.TestCase):
    def test_main_routes_to_rag_track(self):
        args=SimpleNamespace(track='rag',question='What is LLM01?',k=2,max_steps=3)
        with mock.patch('argparse.ArgumentParser.parse_args',return_value=args), mock.patch('src.app.run_rag',return_value={'answer':'ok'}) as run, mock.patch('builtins.print'):
            app.main()
        run.assert_called_once_with(args.question,k=2,client=None,model=None,trace=None)

    def test_main_routes_to_agent_track(self):
        args=SimpleNamespace(track='agent',question='Add numbers',k=3,max_steps=5)
        with mock.patch('argparse.ArgumentParser.parse_args',return_value=args), mock.patch('src.app.run_agent',return_value={'answer':'ok'}) as run, mock.patch('builtins.print'):
            app.main()
        run.assert_called_once_with(args.question,max_steps=5,client=None,model=None,trace=None)
