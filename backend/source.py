"""Public corresponding-source offer (AGPL-3.0 section 13) with an explicit file allowlist."""
import io
from pathlib import Path
import zipfile
from fastapi.responses import Response
ROOT=Path(__file__).resolve().parents[1]

def archive():
    files=[ROOT/name for name in ('LICENSE','README.md','requirements.txt','requirements-dev.txt','setup.sh','start.sh','.env.example')]
    for dirname,suffixes in [('backend',{'.py'}),('frontend/src',{'.ts','.tsx','.css'}),('tests',{'.py'}),('scripts',{'.py','.sh'}),
                             ('deploy',{'.sh','.service','.timer','.conf','.md',''}),('docs',{'.md'}),('desktop',{'.sh',''})]:
        files.extend(p for p in (ROOT/dirname).rglob('*') if p.is_file() and p.suffix in suffixes and 'node_modules' not in p.parts and '__pycache__' not in p.parts)
    files.extend(ROOT/'frontend'/name for name in ('package.json','package-lock.json','index.html','vite.config.ts','vitest.config.ts',
                                                   'tsconfig.json','tsconfig.app.json','tsconfig.node.json','eslint.config.js'))
    files.extend(p for p in (ROOT/'frontend/public').rglob('*') if p.is_file())
    result=io.BytesIO()
    with zipfile.ZipFile(result,'w',zipfile.ZIP_DEFLATED) as z:
        for path in sorted(set(files)):
            # Never follow source-directory or file symlinks outside the package.
            if path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(ROOT):
                z.write(path,'arynwood-grove/'+str(path.relative_to(ROOT)))
    return Response(result.getvalue(),media_type='application/zip',headers={'Content-Disposition':'attachment; filename="arynwood-grove-source.zip"','Cache-Control':'no-store'})
