import {test} from 'node:test';
import assert from 'node:assert/strict';
import {existsSync, readFileSync, statSync} from 'node:fs';
import {createRequire} from 'node:module';
import {dirname, extname, join, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';

const labRoot = fileURLToPath(new URL('../', import.meta.url));
const sourceRoot = resolve(process.env.FS_ELEM_RELEASE_ROOT || labRoot);
// Parsing uses the existing test compiler. This never installs/builds or executes
// candidate application modules; it is not fresh-install or runtime evidence.
const ts = createRequire(join(labRoot, 'apps/web/package.json'))('typescript');

test('packaged UI routes retain their transitive static local imports', () => {
  const pending = ['layout.tsx', 'page.tsx', 'analysis/page.tsx', 'axel-review/page.tsx']
    .map(p => join(sourceRoot, 'apps/web/app', p));
  const seen = new Set(), missing = [];
  while (pending.length) {
    const file = pending.pop();
    if (seen.has(file)) continue;
    seen.add(file);
    if (!existsSync(file)) { missing.push(file); continue; }
    if (!/\.(?:[cm]?js|jsx|tsx?|mts|cts)$/.test(file)) continue;
    const tree = ts.createSourceFile(file, readFileSync(file, 'utf8'), ts.ScriptTarget.Latest, true);
    const references = [];
    const visit = node => {
      if (ts.isImportDeclaration(node) && !node.importClause?.isTypeOnly)
        references.push(node.moduleSpecifier);
      if (ts.isExportDeclaration(node) && !node.isTypeOnly && node.moduleSpecifier)
        references.push(node.moduleSpecifier);
      if (ts.isCallExpression(node) && node.expression.kind === ts.SyntaxKind.ImportKeyword)
        references.push(node.arguments[0]);
      ts.forEachChild(node, visit);
    };
    visit(tree);
    for (const literal of references) {
      if (!literal || !ts.isStringLiteral(literal)) continue;
      const specifier = literal.text;
      const target = specifier.startsWith('.') ? resolve(dirname(file), specifier)
        : specifier.startsWith('@/') ? join(sourceRoot, 'apps/web', specifier.slice(2)) : null;
      if (!target) continue; // External package availability is the installer's gate.
      const choices = extname(target) ? [target]
        : ['', '.tsx', '.ts', '.mjs', '.js', '/index.tsx', '/index.ts', '/index.mjs', '/index.js']
          .map(suffix => target + suffix);
      const found = choices.find(path => existsSync(path) && statSync(path).isFile());
      if (found) pending.push(found);
      else missing.push(`${file.slice(sourceRoot.length + 1)} imports ${specifier}`);
    }
  }
  assert.deepEqual(missing, [], 'A public package must contain UI local import dependencies');
});
