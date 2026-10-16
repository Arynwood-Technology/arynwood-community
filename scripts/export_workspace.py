#!/usr/bin/env python3
"""Export a reviewable workspace kit without connecting to or changing a Grove."""
import argparse
import json
from pathlib import Path
import sys
import zipfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.community.workspace_setup import SetupBody, plan, summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kit', choices=['film-festival','client-project'], default='film-festival')
    parser.add_argument('--client', required=True)
    parser.add_argument('--opening-date', help='Optional ISO date; generates proposed calendar milestones')
    parser.add_argument('--output', type=Path, required=True, help='Destination ZIP (must not exist)')
    args = parser.parse_args()
    body = SetupBody(kit=args.kit, client=args.client, opening_date=args.opening_date)
    content = plan(body)
    checklist = f'# {body.client} — producer workspace\n\nDates and budgets await confirmation. Stage this kit from Workspace setup in your Grove.\n\n'
    for e in content['entries']:
        if e['kind'] == 'list': checklist += f"\n## {e['title']}\n\n{e.get('body','')}\n\n"
        elif e['kind'] == 'item': checklist += f"- [ ] {e['title']}\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.output, 'x', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('PRODUCER-CHECKLISTS.md', checklist)
        archive.writestr('workspace-plan.json', json.dumps({'request': body.model_dump(mode='json'), 'summary':summary(body), **content}, indent=2))
        for folder in content['folders']: archive.writestr(folder+'/', '')
        for path, text in content['documents'].items(): archive.writestr(path, text)
    print(json.dumps({'archive':str(args.output), **summary(body)}, indent=2))

if __name__ == '__main__': main()
