import os
import unittest
from unittest.mock import patch
from src import app

class OfflineBoundaryTests(unittest.TestCase):
    def test_offline_cli_never_reads_dotenv_or_constructs_client(self):
        with patch.dict(os.environ, {'LLM_OFFLINE':'1'}), patch('src.app.load_dotenv') as env, patch('src.app.genai.Client') as client:
            with self.assertRaises(RuntimeError): app.main()
        env.assert_not_called()
        client.assert_not_called()

    def test_stub_notebook_code_cells_run_without_client_or_dotenv(self):
        import json
        from pathlib import Path
        root=Path(__file__).resolve().parents[1]
        notebook=json.loads((root/'notebooks/lab1_stub_validation.ipynb').read_text())
        namespace={}
        with patch('src.app.load_dotenv') as env:
            for index, cell in enumerate(notebook['cells']):
                if cell['cell_type']=='code':
                    exec(compile(''.join(cell['source']),f'stub-notebook-cell-{index}','exec'),namespace)
        env.assert_not_called()
        self.assertTrue(namespace['results'])
        self.assertTrue(all('error' not in row['result'] for row in namespace['results']))
