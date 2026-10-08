"""Loaded only by isolated Phase 1A subprocesses, never by live applications."""
import os
from pathlib import Path
import sys

def deny_external_access(event, args):
    if event in {'socket.connect', 'socket.getaddrinfo', 'socket.sendto'}:
        raise RuntimeError('Phase 1A forbids network access')
    if event == 'open' and isinstance(args[0], (str, bytes)):
        if Path(os.fsdecode(args[0])).name == '.env':
            raise PermissionError('Phase 1A forbids reading private .env files')

sys.addaudithook(deny_external_access)
