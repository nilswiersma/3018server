import re

STATUS_REGEX = r'<(?P<state>[a-zA-Z]+)\|MPos:(?P<X>-?[0-9]+\.[0-9]{3}),(?P<Y>-?[0-9]+\.[0-9]{3}),(?P<Z>-?[0-9]+\.[0-9]{3})\|(.*?)>'

ret = 'ok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\nok\r\n<Idle|MPos:96.599,84.813,0.000|FS:0,0|Ov:100,100,100>\r\n'

m = re.search(STATUS_REGEX, ret, re.MULTILINE)

print(m)