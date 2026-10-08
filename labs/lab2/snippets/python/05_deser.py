import pickle
raw = input('data: ')
obj = pickle.loads(bytes.fromhex(raw))  # CWE-502