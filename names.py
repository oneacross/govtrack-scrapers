import re, unicodedata

import sqlalchemy
from sqlalchemy.sql import select, and_, or_

from util import warn

engine = sqlalchemy.create_engine(open("config.db", "r").read())

from sqlalchemy import Table, Column, Integer, String, Unicode, MetaData, ForeignKey
from sqlalchemy.dialects.mysql import DATE

metadata = MetaData()
people = Table("people", metadata,
	Column("id", Integer, primary_key=True),
	Column("firstname", Unicode),
	Column("middlename", Unicode),
	Column("nickname", Unicode),
	Column("lastname", Unicode),
	Column("lastnameenc", Unicode),
	Column("namemod", Unicode),
	)
people_roles = Table("people_roles", metadata,
	Column("personroleidid", Integer, primary_key=True),
	Column("personid", None, ForeignKey("people.id")),
	Column("type", String),
	Column("startdate", DATE),
	Column("enddate", DATE),
	Column("state", String),
	Column("district", Integer),
	)

def parse_name(name, pubdate, nameformat="firstlast", role_type=None, state=None, district=None):
	"""Returns the person id identified by the name.
	This function normalizes extended characters such as letters with accents."""
	
	global common_names
	load_common_names()

	name = normalize_extended_characters(name)

	# Concatenated abbreviations should be split to match the format in the
	# database, like C.W. Bil Young => C. W. Bill Young.
	name = re.sub(r'\.(\S)', lambda m : ". " + m.group(1), name)
	
	if nameformat == "lastfirst":
		names = name.split(",")
		lastname = names[0]
		firstnames = names[1].strip().split(" ")
	else:
		firstnames = name.split(" ")
		lastname = firstnames.pop(-1)
	
	# Normalize the first name strings.
	for i in xrange(len(firstnames)):
		# Remove quotes around nicknames. Sometimes the trailing quote is missing?
		firstnames[i] = re.sub(r'^"+(.*?)"*$', lambda m : m.group(1), firstnames[i])
	
	connection = engine.connect()
	
	# Filter on the last name (which has no extended characters, versus lastnameenc),
	# with space/dash variants...
	lastname_variants = set([lastname, lastname.replace(" ", "-"), lastname.replace("-", " ")])
	if len(lastname_variants) == 1:
		fltr = (people.c.lastname == lastname)
	else:
		fltr = people.c.lastname.in_(lastname_variants)
	
	# Filter on the role...
	fltr = and_(fltr, (people.c.id == people_roles.c.personid), (people_roles.c.startdate <= pubdate), (people_roles.c.enddate >= pubdate))
	if role_type != None:
		fltr = and_(fltr, people_roles.c.type==role_type)
	if state != None:
		fltr = and_(fltr, people_roles.c.state==state)
	if district != None:
		fltr = and_(fltr, people_roles.c.district==district)
	
	max_match_score = 0
	matches = []
	
	s = select([people], fltr)
	result = connection.execute(s)
	choices = ""
	for row in result:
		choices += "\n" + repr(row)
		
		# Expand out the list of first, middle, etc. names into an array where each element
		# has no spaces.
		fn_patterns = [
			(row["firstname"], row["middlename"], row["nickname"]),
			(row["firstname"], row["nickname"]),
			(row["middlename"], row["nickname"]),
			(row["nickname"],),
		]
	
		for fn_pattern in fn_patterns:
			fn = sum([
				normalize_extended_characters(n).split(" ")
				for n in fn_pattern if n not in (None, "")], [])
			
			match_score  = 0
			for a, bb in zip(firstnames, fn):
				# Do the names match? fn elements can be a pipe-delimited set of allowable names.
				
				for b in bb.split("|"):
					# Identity comparison.
					if a.lower() == b.lower(): break
					
					# If either is an abbreviation, test the first letters only for a match.
					#print repr(a), repr(b)
					if ("." in a or "." in b) and a[0] == b[0]: break
					
					# Check the common names list.
					if (a.lower(), b.lower()) in common_names or (b.lower(), a.lower()) in common_names: break
				else:
					# if we didn't break out, then the match fails. Inside the loop,
					# break is success. Outside the loop, break is failure.
					break
		
				match_score += 1
			else:
				# if we didn't break out, then each component matched.
				
				# If we found a better score than the previous set of matches, reset the list
				# of matches with just this match.
				if match_score > max_match_score:
					matches = [row["id"]]
					
				# Since we loop through different first name patterns (to find the one with the
				# best score), we might have already matched on this person. 
				elif row["id"] not in matches:
					matches.append(row["id"])

		
	connection.close()
	
	if len(matches) != 1:
		if choices == "":
			choices = " (none)"
	
		raise ValueError("%s matches for person %s on %s [role_type=%s, state=%s, district=%s]. Choices were:%s" % (len(matches), " ".join(firstnames) + " " + lastname, pubdate, role_type, state, district, choices))
		
	return matches[0]

def normalize_extended_characters(s):
	"""Removes accent marks from characters by decomposing characters into
	base and combining characters, and then removing combining characters."""
	return "".join([
		c for c in unicodedata.normalize("NFD", s)
		if not unicodedata.combining(c)])

common_names = None
def load_common_names():
	global common_names
	
	if common_names != None:
		return
	
	common_names = (
		('tom', 'thomas'),
		('dan', 'daniel'),
		('ken', 'kenneth'),
		('ted', 'theodore'),
		('ron', 'ronald'),
		('rob', 'robert'),
		('bob', 'robert'),
		('bill', 'william'),
		('tim', 'timothy'),
		('rick', 'richard'),
		('ric', 'richard'),
		('jim', 'james'),
		('russ', 'russell'),
		('mike', 'michael'),
		('les', 'leslie'),
		('doug', 'douglas'),
		('wm.', 'william'),
		('rod', 'rodney'),
		('geo.', 'george'),
		('chuck', 'charles'),
		('roy', 'royden'),
		('fred', 'frederick'),
		('vic', 'victor'),
		('newt', 'newton'),
		('joe', 'joseph'),
		('mel', 'melanie'),
		('dave', 'david'),
		('sid', 'sidney'),
		('stan', 'stanley'),
		('don', 'donald'),
		('marty', 'martin'),
		('gerry', 'gerald'),
		('jerry', 'gerald'),
		('jerry', 'jerald'),
		('al', 'allen'),
		('al', 'allan'),
		('vin', 'vincent'),
		('vince', 'vincent'),
		('pat', 'patrick'),
		('steve', 'steven'),
		('greg', 'gregory'),
		('frank', 'francis'),
		('stan', 'stanley'),
		('dick', 'richard'),
		('charlie', 'charles'),
		('sam', 'samuel'),
		('herb', 'herbert'),
		('max', 'maxwell'),
		('cathy', 'catherine'),
		('ray', 'raymond'),
		('ed', 'edwin'),
		)


#import datetime
#parse_name("Tim Ryan", datetime.datetime.now(), role_type="rep")


