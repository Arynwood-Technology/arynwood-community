# Producer and client workspaces

A space owner opens **Workspace setup** in the community header, selects **Independent film festival**, enters the client name (for example, RogueFest), previews the contents and selects **Stage workspace**. This adds content to the selected space; it keeps existing records. A kit may be applied only once per space, even if its generated records are later deleted. Use a new space for a new edition. Existing kit-root folders block installation rather than silently mixing files.

The festival kit includes 17 department lists, suggested responsible roles, open checklist items, eight shared operating notes, four producer setup tasks, a decisions board, organized file folders, eight editable document files (including the start guide) and 16 header-only CSV trackers. No real submissions, contacts, vendors, spending or account assignments are invented. It does not connect to a submission platform, collect fees, send invitations, import a website, or publish pages.

The lists cover producer approvals; intake; reviews and jury; film delivery and rights; programming; venues and technical production; budgets; sponsors; marketing and images; website publishing; ticketing; hospitality; staffing; operational readiness; show calling; awards; and closeout. The trackers give the producer a shared structure for film IDs, screening blocks, asset approvals, website pages, purchases, budgets, sponsorship, guests, volunteer shifts, vendors, risks, run of show, ticket settlements and reports.

Keep the opening date empty until confirmed. An optional opening date stages 14 explicitly **PROPOSED** milestones at 9 AM, from six months before opening through closeout. Closing-day placeholders assume a three-day festival. Confirm each date, local time, timezone, venue and duration in Calendar. Scheduling with no confirmed date stays in the producer setup tasks and department checklists.

After staging:

1. Assign the four setup tasks to actual team members and give them confirmed deadlines.
2. Review each department checklist with its lead. Use Tasks for separately accountable actions; use Calendar for confirmed deadline reviews, screening blocks, rehearsals, guest sessions and production calls.
3. Put submission data into `Festival Operations/Submissions/submissions.csv` and keep the intake platform reference. Use the same film IDs in reviews, screening blocks and assets.
4. Open `Files → Festival Operations → Finance → budget.csv → Open spreadsheet`. Add real estimates, approvals and actuals; link invoices and receipts by reference.
5. Upload assets into the appropriate working/approved folders. Track image rights, credits, alt text and approval in `Publicity/assets.csv`.
6. Use Notes for working briefs and decisions, Board for approved updates, and Files for editable documents. Files also offers **New spreadsheet** and **New document** for other client workflows.
7. Owners/managers can use Webmaster tools to import an existing public site into Files. Edits and temporary previews are followed by the team's existing hosting release process. They do not automatically publish to the festival website.

Every member of a space can read its shared files and trackers. A folder called Finance or Jury has no extra access control. Create separate spaces with appropriate membership for confidential financial records, personal information, contracts or deliberation. Grove owners/managers have the administrative visibility described by the app.

## Spreadsheet behavior

CSV tables support editable column headings and multiline cells, row/column addition, row removal, versioned saves and existing file download/history. Table limits are 1,000 data rows, 40 columns and 20,000 cells; larger or malformed files remain available through the source editor or download. Formula strings remain text: there is no formula engine or macro execution.

A table with `Type`, `Currency`, `Planned` and `Actual` headings shows income, expense and net totals per currency. `Type` is `Income` or `Expense`; amounts are plain numbers with up to two decimals. No conversion occurs between currencies. Invalid rows are identified and excluded from totals. Blank amounts are not entered; confirmed zero is `0`. If present, `Variance` is calculated as Actual minus Planned when both amounts exist and is saved as a plain value. Budget totals treat blank amounts as zero contributions; they are not forecasts. These operational summaries supplement the team's accounting records.

A conflicting save keeps unsaved cells and reports that another version exists. Copy the draft before reopening; there is no automatic merge. Files continue to use the app's existing member editing and version history behavior.

## Reuse and handoff

The **Client project** kit supplies a general client onboarding, delivery, assets, website and finance workflow with the same tools. Kits live in `backend/community/workspace_kits.py`; the generic preview/application service is in `workspace_setup.py`. Adding a kit means adding catalog content and extending the content factory; the application service remains shared. Staging is owner-only and transactional, including its receipt and activity records, so retries cannot duplicate a workspace.

Create a portable producer handoff without changing a Grove:

```bash
python3 scripts/export_workspace.py --client RogueFest --output /tmp/roguefest-producer-workspace.zip
```

This ZIP contains readable checklists, operating documents, folders, empty CSV trackers and the complete JSON plan. It is a handoff artifact, not an automatic import package. After installing this application version on the target Grove, use Workspace setup to create the live records.

API paths, beneath `/community-api/community/spaces/{space_id}`:

- `GET /workspace-setup`: available kits and previously staged kits (space owner).
- `POST /workspace-setup/preview`: preview `{ "kit": "film-festival", "client": "RogueFest", "opening_date": null }`.
- `POST /workspace-setup`: apply the same request once; emits the normal space refresh signal and writes an activity receipt.

Existing sessions, entries and files need no conversion. Startup creates the additional `workspace_setups` receipt table. Back up the target Grove before updating by the usual deployment process.
