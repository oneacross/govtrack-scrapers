import os, os.path
import base64, hashlib
from pytz import timezone
import datetime, time
import urllib, urllib2, urlparse

# based on http://effbot.org/zone/re-sub.htm#unescape-html, with changes
#
# Removes HTML or XML numeric character references and named entities from
# a text string, replacing them with their unicode equivalent, except for the XML
# special characters &, <, >, ", and ' which are normalized to their standard named
# entity form (amp, lt, gt, quot, and apos).
#
# Accept a charset argument with which to decode numeric entities since the code
# points are relative to the character set.
def unescape(text, charset="utf-8"):
	import re, htmlentitydefs
	
	if charset.lower() in ("iso-8859-1", "windows-1252"):
		def decode_char(num):
			return chr(num).decode(charset)
	else:
		decode_char = unichr
	
	def fixup(m):
		text = m.group(0)
		if text[:2] == "&#":
			# numeric character reference
			try:
				if text[:3] == "&#x":
					text = decode_char(int(text[3:-1], 16))
				else:
					text = decode_char(int(text[2:-1]))
			except ValueError:
				pass # leave as is
		else:
			# named entity
			try:
				text = unichr(htmlentitydefs.name2codepoint[text[1:-1]])
			except KeyError:
				pass # leave as is
		
		# re-encode XML special characters
		if text == "&": text = "&amp;"
		if text == "<": text = "&lt;"
		if text == ">": text = "&gt;"
		if text == "\"": text = "&quot;"
		if text == "'": text = "&apos;"
		
		return text
	return re.sub("&#?\w+;", fixup, text)


def download(url, args=None, method="GET", binary=False, default_charset="iso-8859-1", mirror_key=None, mirror_base=None):
	# Try to load from our local mirror directory.
	if mirror_key == None:
		mirror_key = md5_base64(url + ("?" + urllib.urlencode(args).encode("utf8") if args != None else ""))
	if mirror_base == None:
		mirror_base = urlparse.urlparse(url).hostname
	mirror_file = "../mirror/%s/%s" % (mirror_base, mirror_key)
	try:
		os.makedirs(os.path.dirname(mirror_file))
	except:
		pass
	if os.path.exists(mirror_file):
		with open(mirror_file, "r") as f:
			format = f.readline().strip()
			content = f.read()
		if format == "utf8":
			content = content.decode("utf8")
		st = os.stat(mirror_file)
		return content, datetime.datetime.fromtimestamp(st.st_mtime) # return content and last modified time of file
	
	# Form URL.
	if method == "GET" and args != None:
		url += "?" + urllib.urlencode(args).encode("utf8")
	
	req = urllib2.Request(url)
	r = urllib2.urlopen(req)
	
	content = r.read()
	
	# Decode the bytes into unicode according to whatever charset information
	# we have. For HTML, normalize entity references into plain unicode.
	if r.info().gettype() in ("text/plain", "text/html") and not binary:
		charset = r.info().getparam("charset")
		if charset == None:
			charset = default_charset
		content = content.decode(charset)
		if r.info().gettype() == "text/html":
			content = unescape(content, charset.lower())
	
	# normalize line endings
	content = content.replace("\r\n", "\n")
	content = content.replace("\r", "\n")
	
	modified_time = time.time()

	f = open(mirror_file, "w")
	if type(content) == str:
		f.write("binary\n")
		f.write(content)
	else:
		f.write("utf8\n")
		f.write(content.encode("utf8"))
	f.close()
	os.utime(mirror_file, (modified_time, modified_time))

	return content, datetime.datetime.fromtimestamp(modified_time)

def warn(text):
	print text.encode("utf8")

def md5_base64(text):
	m = hashlib.md5()
	m.update(text.encode("utf-8"))
	return base64.b64encode(m.digest())

def format_datetime(v):
	if type(v) == datetime.datetime:
		v = v.replace(microsecond=0, tzinfo=timezone("US/Eastern"))
	return v.isoformat()

