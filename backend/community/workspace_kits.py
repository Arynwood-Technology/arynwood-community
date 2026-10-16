"""Reusable producer/client workspace content. No accounts, dates or money are invented."""
import csv
import io

FESTIVAL_LISTS = {
 'Producer launch & approvals': ('Producer', ['Confirm festival dates, venues, audience and capacity', 'Appoint department leads and a backup decision maker', 'Approve goals, spending authority and purchase approval process', 'Confirm master calendar, meeting cadence and reporting deadlines', 'Invite each team into the appropriate space', 'Approve launch readiness and keep a decision log']),
 'Submissions intake': ('Submissions coordinator', ['Confirm submission platform, categories and eligibility', 'Approve opening, early, regular and final deadlines', 'Approve fees, waiver policy and submission copy', 'Import submissions into submissions.csv with stable film IDs', 'Check runtime, country, language, premiere status and contact details', 'Check screener access and captions; request missing materials', 'Record receipt and follow-up without storing screener passwords in shared notes', 'Reconcile paid fees and approved waivers with finance']),
 'Review & jury': ('Programming lead', ['Recruit reviewers and record conflicts of interest', 'Assign eligible screeners and set review deadlines', 'Publish scoring rubric and jury confidentiality expectations', 'Track reviews in reviews.csv using film IDs', 'Resolve conflicting reviews and prepare shortlist', 'Approve selections, waitlist and decline decisions', 'Send approved notifications and record replies', 'Confirm jury attendance, deliberation and award handoff']),
 'Film delivery & rights': ('Technical lead', ['Collect screening permission and filmmaker agreement', 'Verify credits, runtime, synopsis and pronunciation', 'Collect masters, captions, subtitles and technical specifications', 'Check playback, audio levels, aspect ratio and caption sync', 'Record file checksums, backup locations and delivery status', 'Collect poster, stills, trailer, headshot and publicity permission', 'Approve public assets and verify image credits', 'Confirm master delivery cutoff and contingency copy']),
 'Programming & screening schedule': ('Programming lead', ['Group selected films into screening blocks', 'Check runtimes including introductions, Q&A and turnover', 'Reserve venue slots and avoid audience and filmmaker conflicts', 'Confirm moderators, filmmaker attendance and accessibility needs', 'Enter confirmed screening blocks in Calendar', 'Get programming and venue sign-off before publishing', 'Freeze a versioned schedule and communicate later changes']),
 'Venues & technical production': ('Venue lead', ['Confirm venue agreement, capacity, access times and contact', 'Survey projection, audio, microphones, power and internet', 'Confirm accessible routes, seating and assistive services', 'Plan box office, signage, backstage and queue management', 'Confirm equipment rental, delivery and return', 'Conduct technical rehearsal with approved screening files', 'Prepare show-stop, backup playback and escalation instructions']),
 'Budget & purchasing': ('Finance lead', ['Set currency and approved budget baseline', 'Enter estimates and actuals in budget.csv', 'Approve each commitment before ordering', 'Log vendor quotes, purchase orders and payment due dates', 'Reconcile submission fees, ticket revenue and sponsor receipts', 'File invoices and receipts using the budget reference ID', 'Review forecast variance and remaining cash weekly', 'Close outstanding invoices and prepare producer financial report']),
 'Sponsors, grants & partners': ('Partnership lead', ['Build prospect list and contact plan', 'Approve sponsorship tiers, benefits and inventory', 'Track approaches and signed commitments in sponsors.csv', 'Collect approved logos, brand rules and payment schedule', 'Assign fulfillment owners for tickets, signage and mentions', 'Confirm sponsor copy and placement proofs', 'Deliver attendance and fulfillment report', 'Send thanks and record renewal opportunities']),
 'Marketing, press & image assets': ('Publicity lead', ['Approve brand kit, naming rules and release workflow', 'Collect key art, stills, headshots, logos and image permissions', 'Track versions, credits, alt text and approval in assets.csv', 'Prepare press release, media kit and contact list', 'Plan email, social, print and local outreach in communications.csv', 'Approve campaign copy and ticket links', 'Schedule approved content around confirmed milestones', 'Archive coverage, campaign results and final artwork']),
 'Website & webmaster publishing': ('Webmaster', ['Inventory pages and owners in website-pages.csv', 'Review festival, submissions, film fans, team and contact pages', 'Check film pages, schedule, venue map and ticket links', 'Use Webmaster tools to import an existing site into Files', 'Edit approved working files; preview before release', 'Check mobile layout, headings, image alt text and navigation', 'Check form routing, external links and page metadata', 'Obtain producer approval and record release and rollback location', 'Publish through the agreed hosting workflow and verify the live pages']),
 'Ticketing & audience services': ('Box office lead', ['Approve pass types, prices, capacity allocations and comps', 'Configure ticket platform and test purchase confirmation', 'Confirm refund, transfer and customer response process', 'Prepare front desk, scanning, guest list and cash procedures', 'Allocate sponsor, filmmaker, press and volunteer passes', 'Reconcile attendance, comps, refunds and settlements', 'Collect audience feedback and accessibility requests']),
 'Guests, travel & hospitality': ('Hospitality lead', ['Confirm invited filmmakers, jury, speakers and VIPs', 'Track invitations and attendance in guests.csv', 'Approve travel, lodging, reimbursement and per diem limits', 'Confirm arrival, ground transport and host contact', 'Collect dietary and access needs through a restricted channel', 'Prepare welcome packets, badges and green room', 'Confirm moderator briefing, Q&A timing and guest departure']),
 'Volunteer & staffing': ('Volunteer lead', ['Define roles, shift lengths and minimum coverage', 'Recruit and confirm volunteers', 'Track shifts and check-ins in volunteer-shifts.csv', 'Prepare training, venue orientation and escalation contacts', 'Confirm breaks, meals, accessibility and backup coverage', 'Issue role-specific access and equipment', 'Close shifts, collect equipment and thank volunteers']),
 'Agreements & operational readiness': ('Producer', ['Track venue, vendor, screening and partner agreements', 'Confirm insurance, permits and required local approvals with the responsible adviser', 'Keep restricted contracts and personal records in a separate space', 'Confirm emergency contacts and venue response procedures', 'Document incident reporting and escalation contacts', 'Review readiness with all department leads', 'Approve opening-day go/no-go and contingency plan']),
 'Festival day & show calling': ('Show caller', ['Open command desk and confirm duty contacts', 'Check each venue, box office and technical station', 'Confirm film masters, playback order and backup media', 'Brief hosts, moderators, volunteers and guest handlers', 'Run doors, introductions, screenings and Q&A to the run of show', 'Record incidents, timing changes and producer decisions', 'Reconcile audience counts and lock up each night']),
 'Awards & closing': ('Awards lead', ['Confirm award categories, eligibility and voting rules', 'Prepare jury and audience voting materials', 'Validate results with authorized decision makers', 'Approve recipient names, pronunciations and presentation order', 'Prepare certificates, prizes and award announcements', 'Confirm acceptance and delivery details', 'Archive final results and approved publicity']),
 'Post-festival closeout': ('Producer', ['Reconcile revenue, expenses, deposits and outstanding payments', 'Complete sponsor and grant reporting', 'Send filmmaker, volunteer, guest and partner thanks', 'Collect feedback and record lessons learned', 'Archive approved photos, coverage, masters and operating documents', 'Review access and retention with department leads', 'Prepare next-edition recommendations and handover'])
}

FESTIVAL_DOCS = {
 'Start here — producer handbook': '''This workspace is a working starter for {client}. Assign real people, confirm dates and approve the budget before launch.

LISTS: department checklists. Each list names the proposed responsible role; checklist items begin open. Use Tasks for accountable actions with an assignee and deadline.
FILES: Festival Operations contains editable documents, empty operational trackers and categorized asset folders. The trackers are CSV files: download one, edit it in a spreadsheet program such as LibreOffice Calc, Excel or Google Sheets, and upload it with the same name as a new version. Earlier versions are kept.
CALENDAR: add confirmed screenings, deadlines, rehearsals, Q&As, meetings, load-in and load-out. Dates staged from a supplied opening date are PROPOSED and need approval. Without a date, scheduling work remains a checklist.
BOARD: publish approved decisions and weekly department updates. The space log (Updates, or the name your Grove gives it) carries short news for everyone; Public chat, where your Grove has it, is for conversation.
WEBMASTER TOOLS: owners/managers can import a public site, then edit and preview files. Importing or editing a file does not publish it to external hosting.

First producer meeting: confirm scope; assign leads; confirm submission platform and deadlines; approve financial baseline; confirm screening venues; set access boundaries; agree the next review date.

Everything in a space's shared Files and trackers is visible to its members. Use a separate restricted space for confidential jury deliberation, finance, contracts and personal records; a folder name does not restrict access. No accounts, payments, external imports or invitations were created by this starter.''',
 'Submission workflow & review rubric': '''One film ID follows a submission through all trackers. Keep the submission platform as the source for intake and fee collection; this workspace coordinates the team.
States: received → eligibility check → ready for review → in review → shortlist / waitlist / declined → selected → accepted → delivery complete → scheduled → screened.
Record a coordinator, contact, category, runtime, language, caption status, reviewer assignment, notification and agreement status. Do not paste screener passwords or private viewing tokens into shared trackers.
Reviewers declare conflicts before assignment. Suggested rubric for producer approval: storytelling, craft, originality and audience/program fit, scored 1–5 with written reasons. Scores support a decision; they do not automate selection. Jury deliberation belongs in a restricted space.
Confirm permissions and delivery before promising a public screening. A checklist completion is an internal status, not a signed screening agreement.''',
 'Budget guide': '''Set one reporting currency in budget.csv; separate budgets if multiple currencies are needed. Blank amounts mean not entered. Zero means a confirmed zero.
Use one row per expense or income line. Type is Expense or Income. Planned and Actual are plain numeric amounts, without currency symbols. Reference ties the row to an approval, invoice or settlement file. Status tracks estimate, approved, committed, paid or reconciled. Do not double-count an invoice and its payment.
Total expenses and income separately for planned and actual amounts, and for each currency; net is income minus expenses, and an expense overrun is actual minus planned. These are operational totals, not accounting or tax calculations. Reconcile to the bookkeeper's records.
budget.csv is a CSV file. Download it, edit it in your spreadsheet program and upload it with the same name as a new version; earlier versions are kept. Save it as CSV, which keeps values but not formulas or formatting. Agree who updates the budget: when two people upload, the later upload becomes the current version.''',
 'File, image & document conventions': '''Use stable film and reference IDs: FILM-0001, VENUE-01, PO-0001. Example artwork name: FILM-0001_poster_en_v01_approved.jpg.
Separate working, approved and archive material. Track each image's owner, permission, credit, alt text, intended use and approval in assets.csv. Keep original files and upload revisions as new versions.
Film Delivery holds masters, captions, subtitles and technical records. Publicity holds approved posters, stills, logos, headshots and press kits. Website holds source pages and release records. Documents holds briefs, meeting notes, approvals and run-of-show files.
Avoid sensitive information in filenames. Do not store payment card data, screener passwords, personal travel documents or private access tokens in shared files. Choose space membership to match who should see the records. Confirm storage capacity before accepting screening masters.''',
 'Meeting notes & decision log template': '''Meeting: [title]
Date and time: [confirm timezone]
Chair / notes owner: [assign]
Attendees: [names]
Progress since last meeting: [department updates]
Decisions: [decision ID / agreed wording / approver / date]
Actions: [action / owner / deadline / linked Task]
Budget implications: [reference / amount / approval]
Risks or blockers: [impact / mitigation / escalation owner]
Next review: [date]
Publish the approved summary on the Board and keep this source with the meeting documents.''',
 'Website page brief & release checklist': '''Page: [URL / title]
Audience and desired action: [purpose]
Content owner / webmaster / approver: [names]
Copy, images, credits and alt text: [approved file paths]
Ticket, submission and contact destinations: [confirmed URLs]
Event dates, venues and screening details: [approved source]
Review: desktop and mobile; keyboard navigation; headings; readable contrast; image loading; link behavior; form destination; metadata.
Release record: approved version / approver / date / hosting destination / rollback copy / live verification.
Use Webmaster tools for imports and Files for edits and previews. Preview is temporary; use the agreed hosting process to publish. Do not treat a local preview as a live release.''',
 'Screening run of show template': '''Screening/block ID: [ID]
Confirmed date / timezone / venue: [details]
Show caller / technical operator / front of house / moderator: [contacts]
Capacity / access arrangements: [approved details]
Load / tech check / doors / intro / film / Q&A / reset: [times]
Playback files and version / captions / runtime / tested backup: [references]
Guest call times and pronunciation: [briefing]
Ticket and late-seating instructions: [briefing]
Show-stop authority and fallback plan: [contact / process]
Actual timings / incidents / follow-ups: [complete after show]''',
 'Risk & handover register guide': '''Keep risks.csv current: record probability, impact, mitigation, owner and review date. Escalate unresolved show-critical risks to the producer.
Cover late film delivery, unavailable venue or guest, technical failure, low sales, supplier delays, weather, accessibility gaps and volunteer no-shows. A template is not an approved emergency plan; confirm venue procedures with the responsible lead.
At handover, record outstanding decisions, approved versions, account owners, vendor commitments, upcoming deadlines, budgets and where the authoritative files live. Do not put passwords into the handover document.'''
}

# Header-only trackers are deliberately empty: a producer should never mistake sample people,
# films, ticket sales or expenses for operational records.
TRACKERS = {
 'Submissions/submissions.csv': ['Film ID','Title','Category','Runtime minutes','Country','Language','Contact name','Contact email','Submission platform reference','Received date','Fee status','Eligibility','Screener access status','Caption status','Coordinator','Review deadline','Decision','Notification date','Acceptance status','Agreement status','Delivery status','Screening block ID','Notes'],
 'Programming/reviews.csv': ['Film ID','Reviewer','Conflict declared','Status','Storytelling 1-5','Craft 1-5','Originality 1-5','Program fit 1-5','Recommendation','Comments','Review due'],
 'Programming/screening-blocks.csv': ['Block ID','Title','Film IDs','Venue','Date','Doors time','Start time','End time','Timezone','Q&A minutes','Turnover minutes','Moderator','Tech owner','Capacity','Caption arrangement','Approval status','Calendar reference','Notes'],
 'Finance/budget.csv': ['Reference','Department','Category','Description','Type','Currency','Planned','Actual','Variance','Status','Owner','Vendor or payer','Due date','Approval reference','Receipt path','Notes'],
 'Finance/purchase-orders.csv': ['Reference','Vendor','Description','Currency','Amount','Requested by','Approver','Approval date','Invoice reference','Due date','Payment status','Receipt path'],
 'Partnerships/sponsors.csv': ['Sponsor ID','Organization','Contact','Email','Stage','Tier','Currency','Cash commitment','In-kind description','Agreement status','Invoice status','Payment status','Benefits promised','Fulfillment owner','Logo path','Next action','Due date'],
 'Publicity/assets.csv': ['Asset ID','Film ID','Asset type','File path','Version','Rights owner','Permission status','Credit','Alt text','Intended use','Approval status','Approver','Approved date','Expiry or restrictions'],
 'Publicity/communications.csv': ['Campaign ID','Channel','Audience','Copy or document path','Asset IDs','Destination URL','Owner','Approver','Status','Publish date','Timezone','Published URL','Results'],
 'Website/website-pages.csv': ['Page ID','URL or slug','Purpose','Audience','Content owner','Webmaster','Copy path','Asset IDs','Approval status','Approver','Target date','Last reviewed','Published version','Live verification','Rollback path'],
 'Hospitality/guests.csv': ['Guest ID','Name','Film ID or role','Contact','Invitation status','Attendance status','Session IDs','Arrival date','Departure date','Travel owner','Hospitality owner','Badge type','Briefing status','Notes'],
 'Volunteers/volunteer-shifts.csv': ['Shift ID','Date','Timezone','Venue','Role','Start time','End time','Volunteer','Lead','Training status','Check-in status','Backup','Notes'],
 'Production/vendors.csv': ['Vendor ID','Company','Service','Contact','Agreement path','Delivery date','Return date','Owner','Payment reference','Status','Notes'],
 'Production/risks.csv': ['Risk ID','Risk','Probability','Impact','Mitigation','Owner','Review date','Status','Escalation'],
 'Production/run-of-show.csv': ['Cue ID','Block ID','Date','Timezone','Venue','Planned time','Duration minutes','Action','Owner','Asset or file path','Backup','Actual time','Notes'],
 'Audience/ticketing.csv': ['Date','Ticket product','Channel','Currency','Capacity allocated','Sold','Comps','Refunded','Gross revenue','Fees','Net settlement','Settlement reference','Owner'],
 'Closeout/reporting.csv': ['Report ID','Recipient','Requirement','Owner','Due date','Evidence path','Approval status','Sent date','Notes']
}
FOLDERS = ['Documents','Documents/Meeting Notes','Documents/Approvals','Submissions','Programming','Film Delivery','Film Delivery/Masters','Film Delivery/Captions','Film Delivery/Technical Checks','Publicity','Publicity/Working','Publicity/Approved','Publicity/Posters','Publicity/Stills','Publicity/Logos','Publicity/Headshots','Publicity/Press Kit','Website','Website/Working','Website/Approved','Website/Release Records','Finance','Finance/Invoices','Finance/Receipts','Partnerships','Hospitality','Volunteers','Production','Audience','Closeout','Archive']
MILESTONES = [(-180,'Producer kickoff & department lead briefing'),(-150,'Submissions opening readiness review'),(-90,'Submission deadline & review progress check'),(-60,'Selection & notification approval'),(-45,'Schedule, venue & accessibility review'),(-30,'Public program & ticketing readiness review'),(-14,'Film delivery & playback readiness review'),(-7,'Producer go/no-go & team briefing'),(-1,'Venue load-in & technical rehearsal'),(0,'Opening-day production briefing'),(1,'Festival-day production briefing'),(2,'Closing-day production briefing & awards'),(3,'Load-out & equipment returns'),(14,'Finance, partner reporting & retrospective')]

PROJECT_LISTS = {
 'Client onboarding & scope': ('Project lead', ['Confirm client goals, audience, success measures and deliverables','Assign decision maker and department leads','Confirm budget, milestones and approval process','Agree space membership and restricted record locations']),
 'Delivery & approvals': ('Delivery lead', ['Break deliverables into assigned tasks','Record dependencies, risks and acceptance criteria','Review progress and resolve blockers','Obtain written approval before release','Record handover and outstanding actions']),
 'Documents & assets': ('Content lead', ['Collect approved documents and source assets','Record ownership, usage permissions and versions','Review copy, accessibility and image credits','Archive final materials and handover instructions']),
 'Website & communications': ('Webmaster', ['Inventory pages and content owners','Import working website files with Webmaster tools','Edit and preview approved changes','Record release approval and verify published pages']),
 'Finance & closeout': ('Finance lead', ['Confirm currency and spending authority','Record budget estimates and actual expenses','Reconcile invoices and receipts','Prepare client report and retrospective'])
}


def csv_text(headers):
    buffer = io.StringIO(newline='')
    csv.writer(buffer).writerow(headers)
    return buffer.getvalue()


def kit_content(key, client):
    if key == 'film-festival':
        return {'lists': FESTIVAL_LISTS, 'docs': FESTIVAL_DOCS, 'folders': FOLDERS, 'trackers': TRACKERS, 'root': 'Festival Operations', 'milestones': MILESTONES}
    return {'lists': PROJECT_LISTS, 'docs': {'Client handover & workspace guide': 'Workspace for {client}. Confirm scope, owners, budget and dates with the client. Use Lists for delivery checklists, Tasks for accountable actions, Notes for decisions, Calendar for confirmed milestones and Files for documents and assets. Shared files are visible to every member of this space. Use separate restricted spaces for confidential records. Budget and tracker CSV files open in any spreadsheet program: download, edit and upload them with the same name as a new version. Financial figures and dates start blank. Webmaster imports and previews require a separate hosting release to publish.'}, 'folders': ['Documents','Assets','Assets/Working','Assets/Approved','Finance','Website','Handover'], 'trackers': {'Finance/budget.csv': TRACKERS['Finance/budget.csv'], 'Website/website-pages.csv': TRACKERS['Website/website-pages.csv'], 'Assets/assets.csv': TRACKERS['Publicity/assets.csv']}, 'root': 'Client Operations', 'milestones': []}

CATALOG = {'film-festival': ('Independent film festival', 'Producer operations from submissions and jury review through screenings, publicity, finance and closeout.'), 'client-project': ('Client project', 'A reusable starting point for client delivery, documents, budgets, website work and handover.')}
