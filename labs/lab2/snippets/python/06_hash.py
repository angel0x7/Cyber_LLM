import hashlib
pwd = input('pwd: ')
print(hashlib.md5(pwd.encode()).hexdigest())  # weak hash CWE-327