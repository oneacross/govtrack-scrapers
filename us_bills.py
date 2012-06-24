import re, datetime
from lxml import etree
from lxml.html import fragment_fromstring
import os, os.path

from util import download, warn, md5_base64, format_datetime

from names import parse_name

thomas_bill_type_codes = (('HC', 'hc'), ('HE', 'hr'), ('HJ', 'hj'), ('HR', 'h'), ('HZ', 'hz'), ('SC', 'sc'), ('SE', 'sr'), ('SJ', 'sj'), ('SN', 's'), ('SP', 'sp'))

def update_bills(congress, force_update):
	"""Scans THOMAS search results for the indicated Congress updating bill
	XML data (bills/*.xml) for any changed records. Or re-parses all files if
	force_update == True."""	
	
	# Make the output directory.
	try:
		os.makedirs("../data/us/%d" % congress)
	except:
		pass
	
	# Store md5sums of the search result records in this file to detect changes.
	# Load in the contents of the file.
	changefile = ("../data/us/%d/bills.bsshash" % congress);
	changehash = {}
	if os.path.exists(changefile):
		with open(changefile, "r") as fchanges:
			for line in fchanges:
				bill_code, status_hash = line.strip().split(" ")
				changehash[bill_code] = status_hash
	newchangehash = {} # store new hashes to write here
	
	# Load results for each bill type (and two amendment types).
	for tbt, bt in thomas_bill_type_codes:
		# Loop through the paginated responses.
		lastseq = None
		offset = 0
		rec = None
	
		while True:
			# download file
			url = "http://thomas.loc.gov/cgi-bin/bdquery/d?d%03d:%d:./list/bss/d%03d%s.lst:[[o]]" \
				% (congress, offset, congress, tbt)
			content, mtime = download(url)
			if not content:
				warn("Failed to download %s" % url)
				break
			
			# Read file by line, grouping lines together into "rec" until we hit an <hr>, at which point
			# we handle the record.
			for line in content.split("\n"):
				hr = line.find("<hr")
				if hr >= 0 and rec != None:
					# process the record ending here
					rec += line[0:hr]
					update_bills_2(congress, bt, bn, rec, changehash, newchangehash, force_update)
					rec = None
				
				# check if a record begins here
				m = re.search(r'<b>\s*(\d+)\.</b> <a href="/cgi-bin/bdquery/d\?d\d+:\d+:./list/bss/d\d+[a-z]+.lst::">\s*[a-z\.]+(\d+)\s*</a>(: )?(.*)', line.lower())
				if m != None:
					# if we have an open record, process it; shouldn't occur since records end on <hr>'s.
					if rec != None:
						update_bills_2(congress, bt, bn, rec, changehash, newchangehash, force_update)
					
					seq = int(m.group(1)) # index in the search result
					bn = int(m.group(2)) # bill number
					rec = m.group(4) + "\n" # start record with the rest of the text on the line
					
					# check that we didn't miss a record
					if lastseq != None and lastseq != seq-1:
						warn("Skipped a sequence number %d to %d." % (lastseq, seq))
						
					lastseq = seq
				
				# add line to existing record
				elif rec != None:
					rec += line + "\n"
				
				# check if there are more results (i.e. continue onto next page)
				elif "&\">NEXT PAGE" in line and lastseq != None:
					offset = lastseq
			
			# if we hit a NEXT PAGE, continue the loop
			if lastseq == None or offset < lastseq:
				break
		
		if lastseq == None:
			warn("No %s bills" % tbt)

		# If there was an open record when we ended, process it, but it shouldn't happen.
		if rec != None:
			update_bills_2(congress, bt, bn, rec, changehash, newchangehash, force_update)
				
	# Write out current record md5s to the hash file.
	with open(changefile, "w") as fchanges:
		items = sorted(newchangehash.items())
		for item in items:
			fchanges.write("%s %s\n" % item)

def update_bills_2(congress, bill_type, bill_number, recordtext, changehash, newchangehash, force_update):
	"""Compares a THOMAS search result record to the hash file to see if anything
	changed, and if so, or if force_update == True, re-parses the bill or amendment."""
	
	key = bill_type + str(bill_number)
	rec = md5_base64(recordtext)

	if not force_update and key in changehash and changehash[key] == rec:
		newchangehash[key] = changehash[key]
		return
	
	if not force_update:
		warn("Detected Update to %d %s %d." % (congress, bill_type, bill_number))
	
	try:
		if bill_type == 'hz':
			#if (!ParseAmendment($bs, 'h', 'Z', $bn)) { return; }
			pass
		elif bill_type == 'sp':
			#if (!ParseAmendment($bs, 's', 'P', $bn)) { return; }
			pass
		else:
			parse_bill(congress, bill_type, bill_number)
	
		newchangehash[key] = rec
	except Exception as e:
		import traceback
		warn("Parsing bill %d %s %d: " % (congress, bill_type, bill_number) + unicode(e) + "\n" + traceback.format_exc())

def parse_bill(congress, bill_type, bill_number):
	"""Downloads and parses THOMAS bill status and summary files."""
	
	# map our bill type code to the THOMAS bill type code (namely, hr is confused with H.R.
	# so make it hres).
	bill_type2 = bill_type
	if bill_type2 == "hr": bill_type2 = "hres"
	
	# Start with the All Actions page, from which we'll also grab basic metadata.
	
	url = "http://thomas.loc.gov/cgi-bin/bdquery/z?d%03d:%s%s:@@@X" % (congress, bill_type2, bill_number)
	content, mtime = download(url)
	if not content:
		raise Exception("Failed to download bill status page: " + url)
	
	root = etree.Element("bill")
	root.set("session", str(congress))
	root.set("type", bill_type)
	root.set("number", str(bill_number))
	root.set("updated", format_datetime(mtime))
	
	sponsor = None
	introduced_date = None
	title = None
	actions = []
	action_indentation = 0
	state_name, state_date = None, None
	
	for line in content.split("\n"):
		# Match Sponsor line, which can be either No Sponsor or a name/state/district.
		# Parse the name later, after we find the introduced date.
		m = re.search(r"<b>Sponsor: </b>(No Sponsor|<a [^>]+>(.*)</a>\s+\[((\w\w)(-(\d+))?)\])", line, re.I)
		if m != None:
			if m.group(1) == "No Sponsor":
				sponsor = (None, None, None, None)
			else:
				name = m.group(2)
				if name.startswith("Sen "):
					senrep = "sen"
					name = name[4:]
				elif name.startswith("Rep "):
					senrep = "rep"
					name = name[4:]
				else:
					raise Exception("Invalid name: missing title: " + name)
				sponsor = (name, senrep, m.group(4), m.group(6)) # name, type, state, district
			
		# Match the line giving the date of introduction.
		m = re.search(r"\(introduced ([\d\/]+)\)", line, re.I)
		if m != None:
			introduced_date = datetime.datetime.strptime(m.group(1), "%m/%d/%Y").date()
			state_name, state_date = ("INTRODUCED", introduced_date)

		# Match the Title line, which we use 1) to check if this is a bill number reserved for the speaker,
		# 2) for determining whether this is a proposal for a constitutional amendment for parsing
		# vote status, and 3) as a backup in case the THOMAS Titles page cannot be parsed.
		m = re.search(r"<B>(Latest )?Title:</B> (.+)", line, re.I)
		if m != None:
			title = m.group(2)
		
		# Match action lines.
		m = re.search(r"<dt><strong>([\d/ :apm]+):</strong><dd>(.+)", line, re.I)
		if m != None:
			# Indentation indicates committee action.
			if line.startswith("<dl>"): action_indentation += 1
			if line.startswith("</dl>"): action_indentation -= 1
			
			text = re.sub(r"</?[Aa]( \S.*?)?>", "", m.group(2))
	
			# The date can be either a date or a date and time.
			try:
				action_date = datetime.datetime.strptime(m.group(1), "%m/%d/%Y %I:%M%p")
			except:
				#print repr(m.group(1))
				try:
					action_date = datetime.datetime.strptime(m.group(1), "%m/%d/%Y").date()
				except:
					raise ValueError("Could not parse date: " + m.group(1))
			
			# references are given in parentheses at the end
			considerations = []
			m = re.search("\s+\((.*)\)\s*$", text)
			if m:
				text = text[0:m.start()] + text[m.end():]
				for con in m.group(1).split("; "):
					if ": " not in con:
						considerations.append( ("", con) )
					else:
						considerations.append( con.split(": ") )
			
			# Parse the actual action line.
			attrs = parse_bill_action(text, bill_type, state_name, title)
			if "state" in attrs:
				state_name, state_date = attrs["state"], action_date
			actions.append((action_date, action_indentation, text, attrs, considerations))
			
	if introduced_date == None:
		raise Exception("No introduced date.")
			
	if sponsor == None:
		raise Exception("No sponsor line.")
	elif sponsor[0] == None:
		sponsor = 0
	else:
		sponsor = parse_name(sponsor[0], introduced_date, nameformat="lastfirst", role_type=sponsor[1], state=sponsor[2], district=sponsor[3])
		
	if "Reserved for the" in title:
		raise Exception("Skipping bill " + title.lower())
	
	# Start building the XML
	
	state = etree.Element("state")
	state.set("datetime", format_datetime(state_date))
	state.text = state_name
	root.append(state)
	
	intronode = etree.Element("introduced")
	intronode.set("datetime", introduced_date.isoformat())
	root.append(intronode)
	
	if sponsor != 0:
		sponsornode = etree.Element("sponsor")
		sponsornode.set("id", str(sponsor))
		root.append(sponsornode)
	
	# Download and parse the cosponsors page.

	cosponsors = etree.Element("cosponsors")
	root.append(cosponsors)

	url = url.replace("@@@X", "@@@P")
	content, mtime = download(url)
	if not content:
		raise Exception("Failed to download cosponsors page: " + url)
	
	content = re.sub(r"(\[[A-Z\d\-]+\])\n( - \d\d?\/)", lambda m : m.group(1) + m.group(2), content) # bring cosponsorship date onto previous line
	content = re.sub(r"</br>", "\n", content)
	
	for line in content.split("\n"):
		m = re.search(r"(<br ?/>)?<a href=[^>]+>(Rep|Sen) (.+)</a> \[([A-Z\d\-]+)\] - (\d\d?/\d\d?/\d\d\d\d)(\(withdrawn - (\d\d?/\d\d?/\d\d\d\d)\))?", line, re.I)
		if m:
			title, name, state_district, join_date, withdrawn_date = m.group(2), m.group(3), m.group(4), m.group(5), m.group(7)
			
			join_date = datetime.datetime.strptime(join_date, "%m/%d/%Y").date()
			if withdrawn_date != None:
				withdrawn_date = datetime.datetime.strptime(withdrawn_date, "%m/%d/%Y").date()
			
			name = name.replace("Colordao", "Colorado") # typo
			
			if not "-" in state_district:
				state = state_district
				district = None
			else:
				state, district = state_district.split("-")
			
			person = parse_name(name, join_date, nameformat="lastfirst", role_type=title.lower(), state=state, district=district)
			
			csp = etree.Element("cosponsor")
			csp.set("id", str(person))
			csp.set("joined", join_date.isoformat())
			if withdrawn_date: csp.set("withdrawn", withdrawn_date.isoformat())
			cosponsors.append(csp)


	# Download and parse the titles page.
	
	
	titles = etree.Element("titles")
	root.append(titles)

	url = url.replace("@@@P", "@@@T")
	content, mtime = download(url)
	if not content:
		raise Exception("Failed to download titles page: " + url)
	
	content = re.sub(r"(<I>)?(<br/>|<p>)", lambda m : "\n" + ("" if not m.group(1) else m.group(1)), content)
	
	title_type, title_as = None, None
	for line in content.split("\n"):
		if line == "</ul>":
			break
		
		m = re.search(r"<li>(.*) title(\(s\))?( as ([\w ]*))?:", line, re.I)
		if m:
			title_type, title_as = m.group(1).lower(), m.group(4).lower()
		
		elif title_type != None and line.strip() != "":
			partial = False
			if line.startswith("<I>"):
				partial = True
				line = line[3:]
			
			line = line.replace("<I>", "")
			line = line.replace("</I>", "")
			line = line.replace(" (identified by CRS)", "")
				
			t = etree.Element("title")
			t.set("type", title_type)
			t.set("as", title_as)
			t.set("partial", "yes" if partial else "no")
			t.text = line.strip()
			titles.append(t)
	
	if len(titles) == 0:
		# Sometimes titles aren't available.
		t = etree.Element("title")
		t.set("type", "official")
		t.set("as", "introduced")
		t.set("partial", "no")
		t.text = title
		titles.append(t)
	
	
	# Download and parse the committees page.
	
	
	committees = etree.Element("committees")
	root.append(committees)

	url = url.replace("@@@T", "@@@C")
	content, mtime = download(url)
	if not content:
		raise Exception("Failed to download committees page: " + url)
	
	last_committee = None
	for line in content.split("\n"):
		m = re.search(r'<a href="/cgi-bin/bdquery(tr)?/R\?[^"]+">(.*)</a>\s*</td><td width="65\%">(.+)</td></tr>', line, re.I)
		if m:
			committee = m.group(2)
			activity = m.group(3)
			
			committee = re.sub(r"\s+", " ", committee).strip()
	
			if not committee.startswith("Subcommittee on "):
				last_committee = committee
				committee = find_committee(committee, None, congress)
			else:
				committee = committee[len("Subcommittee on "):]
				committee = find_committee(last_committee, committee, congress)
			
			cx = etree.Element("committee")
			cx.set("code", committee)
			cx.set("activity", activity)
			committees.append(cx)


	# Download and parse related bills page.
	
	related_bill_type_map = { }
	for a, b in thomas_bill_type_codes:
		related_bill_type_map[a] = b
	related_bill_relationship_map = {
		"Identical bill identified by CRS": "identical",
		"Related bill identified by CRS": "related",
		"Related bill as identified by the House Clerk's office": "related",
		"passed in House in lieu of this bill": "supersedes",
		"passed in Senate in lieu of this bill": "supersedes",
		}
		
	related_bills = etree.Element("relatedbills")
	root.append(related_bills)

	url = url.replace("@@@C", "@@@K")
	content, mtime = download(url)
	if not content:
		raise Exception("Failed to download related bills page: " + url)
	
	for line in content.split("\n"):
		m = re.search(r'<a href="/cgi-bin/bdquery(tr)?/z\?d(\d\d\d):(\w+)(\d\d\d\d\d):">.*</a></td><td>(.*)</td></tr>', line, re.I)
		if m:
			related_bill_congress = int(m.group(2))
			related_bill_type = related_bill_type_map[m.group(3)]
			related_bill_number = int(m.group(4))
			if re.search("Rule related to", m.group(5)):
				related_bill_relationship = "rule"
			else:
				related_bill_relationship = related_bill_relationship_map[m.group(5)]
			
			rb = etree.Element("bill")
			rb.set("relation", related_bill_relationship)
			rb.set("session", str(related_bill_congress))
			rb.set("type", related_bill_type)
			rb.set("number", str(related_bill_number))
			related_bills.append(rb)
			
	
	# Download and parse CRS subject terms page.
	
	
	subjects = etree.Element("subjects")
	root.append(subjects)

	url = url.replace("@@@K", "@@@J")
	content, mtime = download(url)
	if not content:
		raise Exception("Failed to download subject terms page: " + url)
	
	for line in content.split("\n"):
		m = re.search(r'<a href="/cgi-bin/bdquery/\?.*@FIELD\(FLD001.*\)">(.*)</a> ', line, re.I)
		if m:
			term = m.group(1)
			term = re.sub(r"\s+", " ", term).strip()
			
			s = etree.Element("term")
			s.set("name", term)
			subjects.append(s)
			
	
	# Download and parse amendments page.
	
	
	amendments = etree.Element("amendments")
	root.append(amendments)

	url = url.replace("@@@J", "@@@A")
	content, mtime = download(url)
	if not content:
		raise Exception("Failed to download amendments page: " + url)
	
	for m in re.finditer(r'<a href="/cgi-bin/bdquery/z\?d\d+:([HS])([ZP])(\d+):">[HS]\.AMDT\.\d+</a>', content, re.I):
		amendment_chamber = m.group(1).lower()
		amendment_number = int(m.group(3))
		
		a = etree.Element("amendment")
		a.set("number", amendment_chamber + str(amendment_number))
		amendments.append(a)


	# Put the actions in here.

	actionsnode = etree.Element("actions")
	root.append(actionsnode)
	for adate, aindent, text, attrs, considerations in actions:
		nodename = "action"
		if "nodename" in attrs:
			nodename = attrs["nodename"]
			del attrs["nodename"]
			
		node = etree.Element(nodename)
		actionsnode.append(node)
		
		node.set("datetime", format_datetime(adate))
		
		for k, v in sorted(attrs.items()):
			if v == None:
				continue
			node.set(k, v)
		
		n = etree.Element("text")
		n.text = text
		node.append(n)
		
		for c in considerations:
			n = etree.Element("reference")
			n.set("label", c[0])
			n.set("ref", c[1])
			node.append(n)
	
	
	# Download the CRS summary text.


	url = url.replace("@@@A", "@@@D&summ2=m&")
	content, mtime = download(url)
	if not content:
		raise Exception("Failed to download summary page: " + url)
	
	mode = 0
	summary = ""
	for line in content.split("\n"):
		if mode == 1:
			if "<hr" in line:
				mode = 0
			elif "THOMAS Home" in line or "id=\"footer\"" in line:
				break
			else:
				line = re.sub(r"<a.*?>(.*?)</a>", lambda m : m.group(1), line, re.I)
				summary += line + "\n"
		elif "SUMMARY AS OF" in line:
			mode = 1
	
	summary = re.sub(r"\(There (is|are) \d+ other summar(y|ies)\)", "", summary, re.I)
	root.append(fragment_fromstring(summary, create_parent="summary"))

	try:
		os.makedirs("../data/us/%d/bills" % congress)
	except:
		pass

	return etree.tostring(root, pretty_print=True)


def parse_bill_action(line, bill_type, prev_state, title):
	"""Parse a THOMAS bill action line. Returns attributes to be set in the XML file on the action line."""
	
	attrs = { }
	
	# If a line starts with an amendment number, this action is on the amendment and cannot
	# be parsed yet.
	m = re.match("r^(H|S)\.Amdt\.(\d+)", line, re.I)
	if m != None:
		# Process actions specific to amendments separately.
		attrs["amendment"] = m.group(1).lower() + m.group(2)
	
	# Otherwise, parse the action line for key actions.
	else:
			# A House Vote.
			line = re.sub(", the Passed", ", Passed", line); # 106 h4733 and others
			m = re.search(r"(On passage|On motion to suspend the rules and pass the bill|On motion to suspend the rules and agree to the resolution|On motion to suspend the rules and pass the resolution|On agreeing to the resolution|On agreeing to the conference report|Two-thirds of the Members present having voted in the affirmative the bill is passed,?|On motion that the House agree to the Senate amendments?|On motion that the House suspend the rules and concur in the Senate amendments?|On motion that the House suspend the rules and agree to the Senate amendments?|On motion that the House agree with an amendment to the Senate amendments?|House Agreed to Senate Amendments.*?|Passed House)(, the objections of the President to the contrary notwithstanding.?)?(, as amended| \(Amended\))? (Passed|Failed|Agreed to|Rejected)? ?(by voice vote|without objection|by (the Yeas and Nays|Yea-Nay Vote|recorded vote)((:)? \(2/3 required\))?: \d+ - \d+(, \d+ Present)? [ \)]*\((Roll no\.|Record Vote No:) \d+\))", line, re.I)
			if m != None:
				motion, isoverride, asamended, passfail, how = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)
				
				if re.search(r"Passed House|House Agreed to", motion, re.I):
					passfail = 'pass'
				elif re.search(r"Pass|Agreed", passfail, re.I):
					passfail = 'pass'
				else:
					passfail = 'fail'
				
				if "Two-thirds of the Members present" in motion:
					isoverride = True
				
				if isoverride:
					votetype = "override"
				elif re.search(r"(agree (with an amendment )?to|concur in) the Senate amendment", line, re.I):
					votetype = "pingpong"
				elif re.search("conference report", line, re.I):
					votetype = "conference"
				elif bill_type[0] == "h":
					votetype = "vote"
				else:
					votetype = "vote2"
				
				roll = None
				m = re.search(r"\((Roll no\.|Record Vote No:) (\d+)\)", how, re.I)
				if m != None:
					roll = m.group(2)

				suspension = None
				if roll and "On motion to suspend the rules" in motion:
					suspension = True

				attrs["nodename"] = "vote"
				attrs["votetype"] = votetype
				attrs["how"] = how
				if roll:
					attrs["roll"] = roll

				# get the new state of the bill after this vote
				new_state = get_vote_resulting_state(votetype, "h", passfail=="pass", bill_type, suspension, asamended, title, prev_state)
				if new_state:
					attrs["state"] = new_state
					
			m = re.search(r"Passed House pursuant to", line, re.I)
			if m != None:
				votetype = "vote" if (bill_type[0] == "h") else "vote2"
				attrs["nodename"] = "vote"
				attrs["votetype"] = votetype
				attrs["how"] = "by special rule"

				# get the new state of the bill after this vote
				new_state = get_vote_resulting_state(votetype, "h", passfail=="pass", bill_type, False, False, title, prev_state)
				
				if new_state:
					attrs["state"] = new_state
			
			# A Senate Vote
			m = re.search(r"(Passed Senate|Failed of passage in Senate|Resolution agreed to in Senate|Received in the Senate, considered, and agreed to|Submitted in the Senate, considered, and agreed to|Introduced in the Senate, read twice, considered, read the third time, and passed|Received in the Senate, read twice, considered, read the third time, and passed|Senate agreed to conference report|Cloture \S*\s?on the motion to proceed .*?not invoked in Senate|Cloture on the bill not invoked in Senate|Cloture on the bill invoked in Senate|Cloture on the motion to proceed to the bill invoked in Senate|Cloture on the motion to proceed to the bill not invoked in Senate|Senate agreed to House amendment|Senate concurred in the House amendment)(,?.*,?) (without objection|by Unanimous Consent|by Voice Vote|by Yea-Nay( Vote)?\. \d+\s*-\s*\d+\. Record Vote (No|Number): \d+)", line, re.I)
			if m != None:
				motion, extra, how = m.group(1), m.group(2), m.group(3)
				roll = None
				
				if re.search("passed|agreed|concurred|bill invoked", motion, re.I):
					passfail = "pass"
				else:
					passfail = "fail"
					
				votenodename = "vote"
				if re.search("over veto", extra, re.I):
					votetype = "override"
				elif re.search("conference report", motion, re.I):
					votetype = "conference"
				elif re.search("cloture", motion, re.I):
					votetype = "cloture"
					votenodename = "vote-aux" # because it is not a vote on passage
				elif re.search("Senate agreed to House amendment|Senate concurred in the House amendment", motion, re.I):
					votetype = "pingpong"
				elif bill_type[0] == "s":
					votetype = "vote"
				else:
					votetype = "vote2"
					
				m = re.search(r"Record Vote (No|Number): (\d+)", how, re.I)
				if m != None:
					roll = m.group(2)
					how = "roll"
					
				asamended = False
				if re.search(r"with amendments|with an amendment", extra, re.I):
					asamended = True
					
				attrs["nodename"] = votenodename
				attrs["votetype"] = votetype
				attrs["how"] = how
				if roll:
					attrs["roll"] = roll

				# get the new state of the bill after this vote
				new_state = get_vote_resulting_state(votetype, "s", passfail=="pass", bill_type, False, asamended, title, prev_state)
				
				if new_state:
					attrs["state"] = new_state
					
			# TODO: Make a new state for this as pre-reported.
			m = re.search(r"Placed on (the )?([\w ]+) Calendar( under ([\w ]+))?[,\.] Calendar No\. (\d+)\.|Committee Agreed to Seek Consideration Under Suspension of the Rules|Ordered to be Reported", line, re.I)
			if m != None:
				# TODO: This makes no sense.
				if prev_state in ("INTRODUCED", "REFERRED"):
					attrs["state"] = "REPORTED"
				
				attrs["nodename"] = "calendar"
				
				# TODO: Useless.
				attrs["calendar"] = m.group(2)
				attrs["under"] = m.group(4)
				attrs["number"] = m.group(5)
			
			m = re.search(r"Committee on (.*)\. Reported by", line, re.I)
			if m != None:
				attrs["nodename"] = "reported"
				attrs["committee"] = m.group(1)
				if prev_state in ("INTRODUCED", "REFERRED"):
					attrs["state"] = "REPORTED"
				
			m = re.search(r"Committee on (.*)\. Discharged (by Unanimous Consent)?", line, re.I)
			if m != None:
				attrs["committee"] = m.group(1)
				attrs["nodename"] = "discharged"
				if prev_state in ("INTRODUCED", "REFERRED"):
					attrs["state"] = "REPORTED"
					
			m = re.search("Cleared for White House|Presented to President", line, re.I)
			if m != None:
				attrs["nodename"] = "topresident"
				
			m = re.search("Signed by President", line, re.I)
			if m != None:
				attrs["nodename"] = "signed"
				
			m = re.search("Pocket Vetoed by President", line, re.I)
			if m != None:
				attrs["nodename"] = "vetoed"
				attrs["pocket"] = "1"
				attrs["state"] = "VETOED:POCKET"
				
			m = re.search("Vetoed by President", line, re.I)
			if m != None:
				attrs["nodename"] = "vetod"
				attrs["state"] = "PROV_KILL:VETO'"
				
			m = re.search("Became (Public|Private) Law No: ([\d\-]+)\.", line, re.I)
			if m != None:
				attrs["nodename"] = "enacted"
				if prev_state != "PROV_KILL:VETO" and not prev_state.startswith("VETOED:"):				
					attrs["state"] = "ENACTED:SIGNED"
				else:
					attrs["state"] = "ENACTED:VETO_OVERRIDE"
				
			m = re.search(r"Referred to (the )?((House|Senate|Committee) [^\.]+).?", line, re.I)
			if m != None:
				attrs["nodename"] = "referral"
				attrs["committee"] = m.group(2)
				if prev_state == "INTRODUCED":
					attrs["state"] = "REFERRED"
				
			m = re.search(r"Referred to the Subcommittee on (.*[^\.]).?", line, re.I)
			if m != None:
				attrs["nodename"] = "referral"
				attrs["subcommittee"] = m.group(1)
				if prev_state == "INTRODUCED":
					attrs["state"] = "REFERRED"
				
			m = re.search(r"Received in the Senate and referred to (the )?(.*[^\.]).?", line, re.I)
			if m != None:
				attrs["nodename"] = "referral"
				attrs["committee"] = m.group(2)
				
	return attrs

	# # REFORMAT
# 
	# my @ti;
	# my $ti2;
	# foreach $c (@TITLES) {
		# my @cc = @{ $c };
		# push @ti, "\t\t<title type=\"$cc[0]\" as=\"$cc[1]\">$cc[2]</title>";
	# }
	# $ti2 = join("\n", @ti);
# 
	# my @cos;
	# my $cos2;
	# foreach $c (keys(%COSPONSORS)) {
		# my $j = "joined=\"$COSPONSORS{$c}{added}\"";
		# my $r = ($COSPONSORS{$c}{removed} ? " withdrawn=\"$COSPONSORS{$c}{removed}\"" : '');
		# push @cos, "\t\t<cosponsor id=\"$c\" $j$r/>";
	# }
	# $cos2 = join("\n", @cos);
	# if ($COSPONSORS_MISSING) { $COSPONSORS_MISSING = ' missing-unrecognized-person="1"'; } else { $COSPONSORS_MISSING = ''; }
# 
	# my @act;
	# my $act2;
	# my $laststate = '';
	# foreach $c (sort( { CompareDates($$a[0][0], $$b[0][0]); }  @ACTIONS)) {
		# my @cc = @{ $c };
		# my $ccstate = shift(@cc);
		# my $ccc = shift(@cc);
		# my ($ccdate, $cccommittee, $ccsubcommittee) = @{ $ccstate };
		# my $axncom;
		# if (defined($cccommittee)) {
			# $axncom = "<committee name=\"" . htmlify($cccommittee) . "\"";
			# if (defined($ccsubcommittee)) {
				# $axncom .= " subcommittee=\"" . htmlify($ccsubcommittee) . "\"";
			# }
			# $axncom .= "/>";
		# }
		# if ($ccc == 1) {
			# $cc[2] =~ s/<\/?[^>]+>//g;
			# push @act, "\t\t<action $cc[0]>$axncom" . ParseActionText($cc[1]) . "</action>";
		# } else {
			# my $s = "<$cc[0] ";
			# my %sk = %{ $cc[2] };
			# foreach my $k (keys(%sk)) { if ($sk{$k} eq "") { next; } $s .= "$k=\"$sk{$k}\" "; }
			# if ($cc[3] ne '' && $cc[3][0] ne $laststate) { $s .= " state=\"" . $cc[3][0] . "\""; $laststate = $cc[3][0]; }
			# $s .= ">$axncom" . ParseActionText($cc[1]) . "</$cc[0]>";
			# push @act, "\t\t$s";
		# }
	# }
	# $act2 = join("\n", @act);
	# 
	# # Load master committee XML file.
	# if (!$committee_xml_master) { $committee_xml_master = $XMLPARSER->parse_file('../data/us/committees.xml'); }
	# my @com;
	# my $com2;
	# foreach $c (@COMMITTEES) {
		# my @cc = @{ $c };
		# my $ccode;
		# my ($cnode) = $committee_xml_master->findnodes("committees/committee[thomas-names/name[\@session=$SESSION] = \"$cc[0]\"]");
		# if (!$cnode) {
			# warn "Committee not found: $cc[0]";
		# } else {
			# if ($cc[1] eq '') {
				# $ccode = $cnode->getAttribute('code');
			# } else {
				# my ($csnode) = $cnode->findnodes("subcommittee[thomas-names/name[\@session=$SESSION] = \"$cc[1]\"]");
				# if (!$csnode) {
					# #warn "Subcommittee not found: $cc[0] -- $cc[1]";
				# } else {
					# $ccode = $cnode->getAttribute('code') . '-' . $csnode->getAttribute('code');
				# }
			# }
		# }
		# $cc[0] = htmlify($cc[0]);
		# $cc[1] = htmlify($cc[1]);
		# my $s = "";
		# if ($cc[1] ne "") {
			# $s = " subcommittee=\"$cc[1]\"";
		# }
		# push @com, "\t\t<committee code=\"$ccode\" name=\"$cc[0]\"$s activity=\"$cc[2]\" />";
	# }
	# $com2 = join("\n", @com);
# 
	# my @rb;
	# my $rb2;
	# foreach $c (@RELATEDBILLS) {
		# my @cc = @{ $c };
		# push @rb, "\t\t<bill relation=\"$cc[0]\" session=\"$cc[1]\" type=\"$cc[2]\" number=\"$cc[3]\" />";
	# }
	# $rb2 = join("\n", @rb);
# 
	# my @crs;
	# my $crs2;
	# foreach $c (@CRS) {
		# push @crs, "\t\t<term name=\"$c\"/>";
	# }
	# $crs2 = join("\n", @crs);
	# 
	# my @amdts;
	# my $amdts;
	# foreach my $a (@AMENDMENTS) {
		# push @amdts, "\t\t<amendment number=\"$a\"/>";
	# }
	# $amdts = join("\n", @amdts);
# 
	# # reformat summary	
	# $SUMMARY =~ s/\(There (is|are) \d+ other summar(y|ies)\)//;
	# $SUMMARY =~ s/<p>/\n/ig;
	# $SUMMARY =~ s/<br\/?>/\n/ig;
	# $SUMMARY =~ s/<\/ul>/\n/ig;
	# $SUMMARY =~ s/<li>/\n-/ig;
	# $SUMMARY =~ s/<[^>]+?>//g;
	# $SUMMARY =~ s/\&nbsp;/ /g;
	# my $SUMMARY2 = HTMLify($SUMMARY);
# 
	# mkdir "../data/us/$SESSION/bills";
	# mkdir "../data/us/$SESSION/bills.summary";
# 
	# open XML, ">$xfn";
	# binmode(XML, ":utf8");
	# print XML <<EOF;
# 
# EOF
	# close XML;
# 
	# open SUMMARY, ">", "../data/us/$SESSION/bills.summary/$BILLTYPE$BILLNUMBER.summary.xml";
	# binmode(SUMMARY, ":utf8");
	# print SUMMARY FormatBillSummary($SUMMARY2);
	# close SUMMARY;
	# 
	# IndexBill($SESSION, $BILLTYPE, $BILLNUMBER);
	# 
	# return 1;
# }
# 
# sub ParseAmendment {
	# my $session = shift;
	# my $chamber = shift;
	# my $char = shift;
	# my $number = shift;
	# 
	# if ($ENV{SKIP_AMENDMENTS}) { return; }
# 
	# `mkdir -p ../data/us/$session/bills.amdt`;
	# my $fn = "../data/us/$session/bills.amdt/$chamber$number.xml";
# 
	# print "Fetching amendment $session:$chamber$number\n" if (!$OUTPUT_ERRORS_ONLY);
# 
	# my $session2 = sprintf("%03d", $session);
# 
	# my $URL = "http://thomas.loc.gov/cgi-bin/bdquery/z?d$session2:$chamber$char$number:";
# 
	# my ($content, $mtime) = Download($URL);
	# if (!$content) { return; }
	# my $updated = DateToISOString($mtime);
# 
	# $content =~ s/\r//g;
	# 
	# my $billtype;
	# my $billnumber;	
	# my $sequence = '';
	# my $sponsor;
	# my $offered;
	# my $description;
	# my $purpose;
	# my $status = 'offered';
	# my $statusdate;
	# my $actions = '';
	# 
	# my ($sptitle, $spname, $spstate, $spcommittee);
	# 
	# foreach my $line (split(/\n/, $content)) {
		# $line =~ s/<\/?font[^>]*>//g;
	# 
		# if ($line =~ /(<br \/>)?Amends: [^>]*>\s*$BillPattern/i) {
			# $billtype = $BillTypeMap{lc($2)};
			# $billnumber = $3;
		# } elsif ($line =~ /^ \(A(\d\d\d)\)/) {
			# $sequence = int($1);
		# } elsif ($line =~ /(<br \/>)?Sponsor: <a [^>]*>(Rep|Sen) ([^<]*)<\/a> \[(\w\w(-\d+)?)\]/) {
			# ($sptitle, $spname, $spstate) = ($2, $3, $4);
		# } elsif ($line =~ /(<br \/>)?Sponsor: <a [^>]*>((House|Senate) [^<]*)<\/a>/) {
			# ($spcommittee) = ($2);
		# } elsif ($line =~ /\((submitted|offered) (\d+\/\d+\/\d\d\d\d)\)/) {
			# $offered = $2;
			# if ($sptitle eq "") { next; }
			# $sponsor = PersonDBGetID(
				# title => $sptitle,
				# name => $spname,
				# state => $spstate,
				# when => ParseTime($offered));
			# if (!defined($sponsor)) { warn "parsing amendment $session:$chamber$number: Unknown sponsor: $sptitle, $spname, $spstate (bill not fetched)"; return; }
		# } elsif ($line =~ s/^<p>AMENDMENT DESCRIPTION:(<br \/>)?//) {
			# $description = $line;
		# } elsif ($line =~ s/^<p>AMENDMENT PURPOSE:(<br \/>)?//) {
			# $purpose = $line;
			# if ($description eq "") { $description = $purpose; }
		# } elsif ($line =~ /<dt><strong>(\d+\/\d+\/\d\d\d\d( \d+:\d\d(am|pm))?):<\/strong><dd>([\w\W]*)/) {
			# my ($when, $axn) = ($1, $4);
			# $axn = HTMLify($axn);
			# my $axnxml = ParseActionText($axn);
# 
			# my $statusdateattrs = "datetime=\"" . ParseDateTime($when) . "\"";
			# 
			# if ($axn =~ /On agreeing to the .* amendment (\(.*\) )?(Agreed to|Failed) (without objection|by [^\.:]+|by recorded vote: (\d+) - (\d+)(, \d+ Present)? \(Roll no. (\d+)\))\./) {
				# my ($passfail, $method) = ($2, $3);
				# if ($passfail =~ /Agree/) { $passfail = "pass"; } else { $passfail = "fail"; }
				# my $rollattr = "";
				# if ($method =~ /recorded vote/) {
					# $method =~ /\(Roll no. (\d+)\)/;
					# my $roll = $1;
					# $method = "roll";
					# $rollattr = " roll=\"$roll\"";
					# 
					# if (lc($chamber) eq "h") { GetHouseVote(YearFromDate(ParseTime($when)), $roll, 1); }
					# else { warn "parsing amendment $session:$chamber$number: House-style vote on Senate amendment?"; }
				# }
				# $actions .= "\t\t<vote $statusdateattrs result=\"$passfail\" how=\"$method\"$rollattr>$axnxml</vote>\n";
				# $status = $passfail;
				# $statusdate = $statusdateattrs;
			# } elsif ($axn =~ /(Motion to table )?Amendment SA \d+ (as modified )?(agreed to|not agreed to) in Senate by ([^\.:\-]+|Yea-Nay( Vote)?. (\d+) - (\d+)(, \d+ Present)?. Record Vote Number: (\d+))\./i) {
				# my ($totable, $passfail, $method) = ($1, $3, $4);
				# if ($passfail !~ /not/) { $passfail = "pass"; } else { $passfail = "fail"; }
# 
				# if ($totable) {
					# if ($passfail eq 'fail') { next; }
					# $passfail = 'fail'; # i.e. treat a passed motion to table as a failed vote on accepting the amendment
				# }
# 
				# my $rollattr = "";
				# if ($method =~ /Yea-Nay/) {
					# $method =~ /Record Vote Number: (\d+)/;
					# my $roll = $1;
					# $method = "roll";
					# $rollattr = " roll=\"$roll\"";
					# 
					# if (lc($chamber) eq "s") { GetSenateVote($session, SubSessionFromDateTime(ParseDateTime($when)), YearFromDate(ParseTime($when)), $roll, 1); }
					# else { warn "parsing amendment $session:$chamber$number: Senate-style vote on House amendment?"; }
				# }
				# $actions .= "\t\t<vote $statusdateattrs result=\"$passfail\" how=\"$method\"$rollattr>$axnxml</vote>\n";
				# $status = $passfail;
				# $statusdate = $statusdateattrs;
			# } elsif ($axn =~ /Proposed amendment SA \d+ withdrawn in Senate./
				# || $axn =~ /the [\w\W]+ amendment was withdrawn./) {
				# $actions .= "\t\t<withdrawn $statusdateattrs>$axnxml</withdrawn>\n";
				# $status = "withdrawn";
				# $statusdate = $statusdateattrs;
			# } else {
				# $actions .= "\t\t<action $statusdateattrs>$axnxml</action>\n";
			# }
		# }
	# }
	# 
	# if (!defined($purpose)) { $purpose = "Amendment information not available."; $description = $purpose; }
	# 
	# if (!defined($billtype) || (!defined($sponsor) && !defined($spcommittee)) || !defined($offered)) {
		# print "Parse failed on amendment: $URL\n";
		# return;
	# }
	# 
	# $description = HTMLify(ToUTF8($description));
	# $purpose = HTMLify(ToUTF8($purpose));
	# 
	# $offered = "datetime=\"" . ParseDateTime($offered) . "\"";
	# if ($status eq "offered") { $statusdate = $offered; }
# 
	# my $sponsorxml;
	# if (defined($sponsor)) { $sponsorxml = "id=\"$sponsor\""; }
	# else { $sponsorxml = "committee=\"" . htmlify($spcommittee) . "\""; }
# 
	# open XML, ">", "$fn";
	# print XML <<EOF;
# <amendment session="$session" chamber="$chamber" number="$number" updated="$updated">
	# <amends type="$billtype" number="$billnumber" sequence="$sequence"/>
	# <status $statusdate>$status</status>
	# <sponsor $sponsorxml/>
	# <offered $offered/>
	# <description>$description</description>
	# <purpose>$purpose</purpose>
	# <actions>
# $actions
	# </actions>
# </amendment>
# EOF
	# close XML;
	# 
	# return 1;
# }
# 
# sub HTMLify {
	# my $t = $_[0];
# 
	# $t =~ s/<\/?P>/\n/gi;
	# $t =~ s/<BR\s*\/?>/\n/gi;
	# $t =~ s/<\/?[^>]+>//gi;
# 
	# $t =~ s/&nbsp;/ /gi;
# 
	# return htmlify(decode_entities($t), 0, 1);
# }
# 
# sub FormatBillSummary {
	# my $summary = shift;
	# 
	# my @splits = split(/(Division|Title|Subtitle|Part|Chapter)\s+([^:\n]+)\s*: (.*?) - |\((Sec)\. (\d+)\)|(\n)/, $summary);
	# 
	# my %secorder = (Division => 1, Title => 2, Subtitle => 3, Part 
	# => 4, Chapter => 5, Section => 6, Paragraph => 7);
	# 
	# my $ret;
	# my @stack;
	# my @idstack;
	# 
	# $ret .= "<Paragraph type=\"Overview\">";
	# push @stack, "Paragraph";
	# 
	# my $lastisbullet;
	# 
	# while (scalar(@splits) > 0) {
		# my $s = shift(@splits);
		# 
		# if ($s eq "") {
		# } elsif ($s =~ /^(Division|Title|Subtitle|Part|Chapter)$/ or $s eq "Sec") {
			# my $sid = shift(@splits);
			# my $sname;
			# if ($s eq "Sec") {
				# $s = "Section";
				# $sname = "";
				# if ($lastisbullet) { unshift @splits, "$s $sid"; next; }
			# } else {
				# $sname = shift(@splits);
				# if ($lastisbullet) { unshift @splits, "$s $sid: $sname"; next; }
			# }
			# 
			# while (scalar(@stack) > 0 && $secorder{$s} <= $secorder{$stack[scalar(@stack)-1]}) {
				# $ret .= "</" . pop(@stack) . ">"; 
				# pop @idstack;
			# }
# 
			# if ($sname ne "") { $sname = "name=\"$sname\""; }
# 
			# my $id = "$s-$sid";
			# my $id2 = join(":", @idstack);
# 
			# $ret .= "<$s number=\"$sid\" $sname id=\"$id2\">";
# 
			# push @stack, $s;
			# push @idstack, $id;
# 
		# } elsif ($s eq "\n") {
		# } else {
			# while (scalar(@stack) > 0 && $secorder{Paragraph} <= $secorder{$stack[scalar(@stack)-1]}) { $ret .= "</" . pop(@stack) . ">"; }
			# 
			# $ret .= "<Paragraph>$s";
			# push @stack, 'Paragraph';
			# 
			# $lastisbullet = ($s =~ /<br\/>- $/);
		# }
	# }
# 
	# while (scalar(@stack) > 0) { $ret .= "</" . pop(@stack) . ">"; }
	# 
	# $ret = "<summary>$ret</summary>";
	# return ToUTF8($ret);
# 
	# #return $XMLPARSER->parse_string($ret)->findnodes('.');
# }
# 

# sub CompareDates {
	# my ($a, $b) = @_;
	# # Compare two dates, but if one doesn't have a time,
	# # then only compare the date portions.
	# if ($a !~ /T/) { $b =~ s/T.*//; }
	# if ($b !~ /T/) { $a =~ s/T.*//; }
	# return $a cmp $b;
# }

def get_vote_resulting_state(votetype, chamber, passed, bill_type, suspension, amended, title, prev_state):
	if votetype == "vote": # vote in originating chamber
		if passed:
			if bill_type in ("hr", "sr"):
				return 'PASSED:SIMPLERES' # end of life for a simple resolution
			if chamber == "h":
				return 'PASS_OVER:HOUSE' # passed by originating chamber, now in second chamber
			else:
				return 'PASS_OVER:SENATE' # passed by originating chamber, now in second chamber
		if suspension:
			return 'PROV_KILL:SUSPENSIONFAILED' # provisionally killed by failure to pass under suspension of the rules
		if chamber == "h":
			return 'FAIL:ORIGINATING:HOUSE' # outright failure
		else:
			return 'FAIL:ORIGINATING:SENATE' # outright failure
	if votetype == "vote2": # vote in second chamber
		if passed:
			if bill_type in ("hj", "sj") and title.startswith("Proposing an amendment to the Constitution of the United States"):
				return 'PASSED:CONSTAMEND' # joint resolution that looks like an amendment to the constitution
			if bill_type in ("hc", "sc"):
				return 'PASSED:CONCURRENTRES' # end of life for concurrent resolutions
			if amended:
				# bills and joint resolutions not constitutional amendments, amended from Senate version.
				# can go back to Senate, or conference committee
				if chamber == "h":
					return 'PASS_BACK:HOUSE' # passed by originating chamber, now in second chamber
				else:
					return 'PASS_BACK:SENATE' # passed by originating chamber, now in second chamber
			else:
				# bills and joint resolutions not constitutional amendments, not amended from Senate version
				return 'PASSED:BILL' # passed by second chamber, now on to president
		if suspension:
			return 'PROV_KILL:SUSPENSIONFAILED' # provisionally killed by failure to pass under suspension of the rules
		if chamber == "h":
			return 'FAIL:SECOND:HOUSE' # outright failure
		else:
			return 'FAIL:SECOND:SENATE' # outright failure
	if votetype == "cloture":
		if not passed:
			return "PROV_KILL:CLOTUREFAILED"
		else:
			return None
	if votetype == "override":
		if not passed:
			if bill_type[0] == chamber:
				if chamber == "h":
					return 'VETOED:OVERRIDE_FAIL_ORIGINATING:HOUSE'
				else:
					return 'VETOED:OVERRIDE_FAIL_ORIGINATING:SENATE'
			else:
				if chamber == "h":
					return 'VETOED:OVERRIDE_FAIL_SECOND:HOUSE'
				else:
					return 'VETOED:OVERRIDE_FAIL_SECOND:SENATE'
		else:
			if bill_type[0] == chamber:
				if chamber == "h":
					return 'VETOED:OVERRIDE_PASS_OVER:HOUSE'
				else:
					return 'VETOED:OVERRIDE_PASS_OVER:SENATE'
			else:
				return None # just wait for the enacted line
	if votetype == "pingpong":
		# This is a motion to accept Senate amendments to the House's original bill
		# or vice versa. If the motion fails, I suppose it is a provisional kill. If it passes,
		# then pingpong is over and the bill has passed both chambers.
		if passed:
			return 'PASSED:BILL'
		else:
			return 'PROV_KILL:PINGPONGFAIL'
	if votetype == "conference":
		# This is tricky to integrate into state because we have to wait for both
		# chambers to pass the conference report.
		if passed:
			if prev_state.startswith("CONFERENCE:PASSED:"):
				return 'PASSED:BILL'
			else:
				if chamber == "h":
					return 'CONFERENCE:PASSED:HOUSE'
				else:
					return 'CONFERENCE:PASSED:SENATE'
			
	return None
	
committee_map = None
def find_committee(committee, subcommittee, congress):
	global committee_map
	if committee_map == None:
		committee_map = { }
		root = etree.parse("../data/us/committees.xml")
		for c in root.xpath("committee"):
			for d in c.xpath("thomas-names/name"):
				committee_map[d.get("session") + ":" + d.text] = c.get("code")
				for s in c.xpath("subcommittee"):
					for e in c.xpath("thomas-names/name"):
						committee_map[d.get("session") + ":" + d.text + ":" + e.text] = c.get("code") + s.get("code")
	return committee_map[str(congress) + ":" + committee + (": " + subcommittee if subcommittee else "")]

if __name__ == "__main__":
	#update_bills(112, True)
	print parse_bill(112, "h", 1)
	
