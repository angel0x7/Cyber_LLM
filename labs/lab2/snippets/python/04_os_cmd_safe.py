import subprocess, shlex
path = input('p: ')
subprocess.run(['ls', '--', path])