import requests
from pprint import pprint
s = requests.Session()
ret = s.get('http://127.0.0.1:5000/config')
pprint(ret.text)