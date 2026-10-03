import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import ts from 'typescript';

// Execute the actual TSX component with deterministic hooks and transport.
// This is a component logic regression, not browser/React DOM or inference evidence.
const hooks = `
let cursor=0,slots=[],pending=[],client;
export function configure(value){client=value;}
export function createAnalysisClient(){return client;}
export function begin(){cursor=0;}
export function useState(value){const index=cursor++;if(!slots[index])slots[index]={value};return [slots[index].value,next=>{slots[index].value=typeof next==='function'?next(slots[index].value):next;}];}
export function useRef(value){const index=cursor++;if(!slots[index])slots[index]={current:value};return slots[index];}
export function useEffect(callback,deps){const index=cursor++,old=slots[index];if(!old||!deps||deps.some((value,i)=>value!==old.deps[i])){old?.cleanup?.();slots[index]={deps};pending.push(()=>{slots[index].cleanup=callback();});}}
export function effects(){const work=pending;pending=[];for(const effect of work)effect();}
export function cleanup(){for(const slot of slots)slot?.cleanup?.();}
export function jsx(type,props){return {type,props};}
export const jsxs=jsx;
export const Fragment='fragment';
export const ArrowUpRight='icon',Check='icon',ChevronRight='icon',FileVideo='icon',LoaderCircle='icon',Pause='icon',Play='icon',RefreshCw='icon',Upload='icon',X='icon';
export default 'pose-overlay';
`;
const defer = () => {
  let resolve, reject;
  const promise = new Promise((a, b) => {
    resolve = a;
    reject = b;
  });
  return { promise, resolve, reject };
};
const flush = () => new Promise((resolve) => setImmediate(resolve));
function nodes(tree, predicate) {
  const found = [];
  function visit(node) {
    if (!node || typeof node !== 'object') return;
    if (Array.isArray(node)) {
      node.forEach(visit);
      return;
    }
    if (predicate(node)) found.push(node);
    visit(node.props?.children);
  }
  visit(tree);
  return found;
}
function text(tree) {
  if (tree === null || tree === undefined || typeof tree === 'boolean')
    return '';
  if (Array.isArray(tree)) return tree.map(text).join('');
  if (typeof tree === 'object') return text(tree.props?.children);
  return String(tree);
}

for (const response of ['cancelled', 'error'])
  test(`late DELETE ${response} cannot change a newly selected video`, async () => {
    const directory = await mkdtemp(join(tmpdir(), 'fs-elem-ui-cancel-'));
    let harness;
    try {
      const harnessPath = join(directory, 'hooks.mjs');
      await writeFile(harnessPath, hooks);
      harness = await import(pathToFileURL(harnessPath).href);
      const status = defer(),
        cancel = defer();
      let jobReads = 0;
      const job = {
        id: 'job-A',
        status: 'running',
        stage: 'sparse',
        progress: null,
        currentFrame: null,
        totalFrames: null,
        sourceSha256: 'a'.repeat(64),
      };
      harness.configure({
        health: async () => ({ inferenceAvailable: true, issues: [] }),
        upload: async () => job,
        job: () => {
          jobReads++;
          return jobReads === 1
            ? status.promise
            : Promise.resolve({
                ...job,
                status: 'cancelled',
                stage: 'cancelled',
              });
        },
        cancel: () => cancel.promise,
        result: async () => ({
          events: [],
          warnings: [],
          sourceSha256: job.sourceSha256,
        }),
        pose: async () => ({
          geometry: { width: 540, height: 960, rotation: 0 },
          frames: [],
          links: [],
          minConfidence: 0.3,
          maxTimeDelta: 0.065,
        }),
      });
      const source = await readFile(
        new URL(
          '../components/analysis/AnalysisWorkbench.tsx',
          import.meta.url,
        ),
        'utf8',
      );
      const compiled = ts.transpileModule(source, {
        compilerOptions: {
          jsx: ts.JsxEmit.ReactJSX,
          module: ts.ModuleKind.ESNext,
          target: ts.ScriptTarget.ES2022,
        },
      }).outputText;
      const wired = compiled.replace(
        /from ["'][^"']+["']/g,
        `from ${JSON.stringify(pathToFileURL(harnessPath).href)}`,
      );
      const componentPath = join(directory, 'component.mjs');
      await writeFile(componentPath, wired);
      const { default: Component } = await import(
        pathToFileURL(componentPath).href
      );
      const render = () => {
        harness.begin();
        const tree = Component();
        harness.effects();
        return tree;
      };
      const choose = (tree, name) =>
        nodes(
          tree,
          (node) => node.type === 'input' && node.props.type === 'file',
        )[0].props.onChange({
          target: { files: [new File(['fixture'], name)], value: name },
        });
      const button = (tree, label) =>
        nodes(
          tree,
          (node) => node.type === 'button' && text(node).trim() === label,
        )[0];
      let tree = render();
      await flush();
      tree = render();
      choose(tree, 'A.mp4');
      tree = render();
      await flush();
      tree = render();
      button(tree, 'Начать анализ').props.onClick();
      await flush();
      tree = render();
      assert.equal(jobReads, 1);
      button(tree, 'Отменить').props.onClick();
      tree = render();
      status.resolve({ ...job, status: 'completed', stage: 'completed' });
      await flush();
      tree = render();
      choose(tree, 'B.mp4');
      tree = render();
      assert.ok(text(tree).includes('B.mp4'));
      if (response === 'cancelled')
        cancel.resolve({ ...job, status: 'cancelled', stage: 'cancelled' });
      else cancel.reject(Error('Old A cancellation failed'));
      await flush();
      tree = render();
      await flush();
      tree = render();
      assert.ok(text(tree).includes('B.mp4'));
      assert.equal(
        nodes(tree, (node) => node.props?.className === 'analysis-status')
          .length,
        0,
        'old job status must not appear for B',
      );
      assert.equal(
        nodes(tree, (node) => node.props?.className === 'analysis-error')
          .length,
        0,
        'old cancellation error must not appear for B',
      );
      assert.equal(
        jobReads,
        1,
        'old job must not restart polling after selecting B',
      );
    } finally {
      harness?.cleanup();
      await rm(directory, { recursive: true, force: true });
    }
  });
