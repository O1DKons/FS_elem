import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import ts from 'typescript';
import { createAnalysisClient } from './analysis-client.mjs';
import errorFixture from './analysis-error-fixture.json' with { type: 'json' };

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
        /from ["']([^"']+)["']/g,
        (_, specifier) =>
          `from ${JSON.stringify(specifier.endsWith('analysis-session.mjs') ? new URL('./analysis-session.mjs', import.meta.url).href : pathToFileURL(harnessPath).href)}`,
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

async function savedComponent(client, action) {
  const directory = await mkdtemp(join(tmpdir(), 'fs-elem-ui-restore-'));
  const previousWindow = globalThis.window;
  let harness;
  try {
    const id = 'f042611d-5aeb-4548-b3ab-43b2df89ad74';
    const storage = new Map();
    const location = new URL('http://localhost:5174/analysis?job=' + id);
    globalThis.window = {
      location,
      localStorage: {
        getItem: (k) => storage.get(k) ?? null,
        setItem: (k, v) => storage.set(k, v),
      },
      history: {
        replaceState(state, title, url) {
          globalThis.window.location = new URL(url, globalThis.window.location);
        },
      },
    };
    const harnessPath = join(directory, 'hooks.mjs');
    await writeFile(harnessPath, hooks);
    harness = await import(pathToFileURL(harnessPath).href);
    harness.configure(client);
    const source = await readFile(
      new URL('../components/analysis/AnalysisWorkbench.tsx', import.meta.url),
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
      /from ["']([^"']+)["']/g,
      (_, specifier) =>
        `from ${JSON.stringify(specifier.endsWith('analysis-session.mjs') ? new URL('./analysis-session.mjs', import.meta.url).href : pathToFileURL(harnessPath).href)}`,
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
    await action({ render, id, storage });
  } finally {
    harness?.cleanup();
    globalThis.window = previousWindow;
    await rm(directory, { recursive: true, force: true });
  }
}
const savedJob = {
  id: 'f042611d-5aeb-4548-b3ab-43b2df89ad74',
  status: 'completed',
  stage: 'completed',
  progress: 100,
  currentFrame: null,
  totalFrames: null,
  sourceSha256: 'a'.repeat(64),
  filename: 'program.mp4',
  sizeBytes: 1234,
  createdAt: '2026-10-03T12:00:00Z',
  updatedAt: '2026-10-03T12:01:30Z',
};

test('reload opens completed original video and nominal cards without uploading', async () => {
  let mutations = 0;
  const client = {
    health: async () => ({ inferenceAvailable: false, issues: [] }),
    job: async () => savedJob,
    upload: async () => {
      mutations++;
      throw Error('must not upload');
    },
    cancel: async () => {
      mutations++;
    },
    result: async () => ({
      sourceSha256: savedJob.sourceSha256,
      warnings: [],
      events: [
        {
          id: 'event1',
          start: 1,
          end: 1.4,
          label: '1A',
          nominalRevolutions: 1.5,
        },
      ],
    }),
    pose: async () => ({
      geometry: { width: 1280, height: 720, rotation: 0 },
      frames: [],
      links: [],
      minConfidence: 0.3,
      maxTimeDelta: 0.065,
    }),
  };
  await savedComponent(client, async ({ render, id }) => {
    render();
    await flush();
    render();
    await flush();
    const tree = render();
    assert.equal(
      nodes(tree, (n) => n.type === 'video')[0]?.props.src,
      '/api/analysis/jobs/' + id + '/media',
    );
    assert.ok(text(tree).includes('program.mp4'));
    assert.match(text(tree), /Номинально 1,5 оборота/);
    assert.match(text(tree), /1:30/);
    assert.equal(
      nodes(
        tree,
        (n) =>
          n.type === 'button' &&
          n.props.className === 'analysis-primary-button',
      )[0].props.disabled,
      true,
      'a restored source is not a File for rerun',
    );
    assert.equal(mutations, 0);
  });
});

test('missing saved job reports the error instead of silently starting inference', async () => {
  let mutations = 0;
  await savedComponent(
    {
      health: async () => ({ inferenceAvailable: true, issues: [] }),
      job: async () => {
        const e = Error('Job not found');
        e.status = 404;
        throw e;
      },
      upload: async () => {
        mutations++;
      },
      cancel: async () => {
        mutations++;
      },
    },
    async ({ render }) => {
      render();
      await flush();
      const tree = render();
      assert.equal(nodes(tree, (n) => n.type === 'video').length, 0);
      assert.ok(
        nodes(tree, (n) => n.props?.role === 'alert').length > 0,
        'missing job must be visible',
      );
      assert.equal(mutations, 0);
    },
  );
});

for (const response of ['completed', 'missing'])
  test(`late saved job ${response} cannot replace a newly selected source`, async () => {
    const old = defer();
    old.promise.catch(() => {});
    let reads = 0;
    await savedComponent(
      {
        health: async () => ({ inferenceAvailable: true, issues: [] }),
        job: () => {
          reads++;
          return old.promise;
        },
      },
      async ({ render }) => {
        let tree = render();
        await flush();
        tree = render();
        nodes(
          tree,
          (n) => n.type === 'input' && n.props.type === 'file',
        )[0].props.onChange({
          target: { files: [new File(['fixture'], 'B.mp4')], value: 'B.mp4' },
        });
        tree = render();
        await flush();
        if (response === 'completed') old.resolve(savedJob);
        else {
          const e = Error('Old missing A');
          e.status = 404;
          old.reject(e);
        }
        await flush();
        tree = render();
        await flush();
        tree = render();
        assert.ok(text(tree).includes('B.mp4'));
        assert.equal(
          nodes(tree, (n) => n.props?.className === 'analysis-status').length,
          0,
        );
        assert.equal(
          nodes(tree, (n) => n.props?.className === 'analysis-error').length,
          0,
        );
        assert.equal(globalThis.window.location.search, '');
        assert.equal(reads, 1, 'old restore must not begin a new polling loop');
      },
    );
  });


test('restored failed job shows count explanation without predictions, pose or another upload', async () => {
  const calls = [];
  const client = createAnalysisClient(async (url, options) => {
    calls.push([url, options.method ?? 'GET']);
    if (url === '/api/analysis/health')
      return Response.json({inferenceAvailable:true,issues:[],activeJobId:null});
    if (url === '/api/analysis/jobs/' + savedJob.id)
      return Response.json({
        schemaVersion:1,jobId:savedJob.id,...errorFixture,
        source:{sha256:savedJob.sourceSha256,filename:'synthetic-program.mp4',sizeBytes:1234},
        progress:{stage:'failed',percent:null,currentFrame:null,totalFrames:null},
        createdAt:savedJob.createdAt,updatedAt:savedJob.updatedAt,elapsedSeconds:1,
      });
    throw Error('Unexpected result/pose/upload request');
  });
  await savedComponent(client, async ({render}) => {
    render(); await flush(); render(); await flush();
    const tree=render();
    assert.match(text(tree), /Количество прочитанных кадров.*337 вместо 357.*Анализ остановлен/);
    assert.equal(nodes(tree,n=>n.props?.className==='analysis-event-card').length,0);
    assert.ok(nodes(tree,n=>n.type==='pose-overlay').every(n=>n.props.pose===null));
    assert.doesNotMatch(text(tree), /Аксели не обнаружены|Номинально|Traceback|Source frame/);
    assert.ok(calls.length>0 && calls.every(([url,method])=>method==='GET' && !url.endsWith('/result') && !url.endsWith('/pose')));
    assert.equal(nodes(tree,n=>n.type==='button' && n.props.className==='analysis-primary-button')[0].props.disabled,true);
  });
});


test('malformed object diagnostic code restores the failed job with a safe reason', async () => {
  const fixture = structuredClone(errorFixture);
  fixture.error.diagnostics.code = {toString:null};
  const client = createAnalysisClient(async url => {
    if (url === '/api/analysis/health')
      return Response.json({inferenceAvailable:true,issues:[],activeJobId:null});
    if (url === '/api/analysis/jobs/' + savedJob.id)
      return Response.json({
        schemaVersion:1,jobId:savedJob.id,...fixture,
        source:{sha256:savedJob.sourceSha256,filename:'synthetic-program.mp4',sizeBytes:1234},
        progress:{stage:'failed',percent:null,currentFrame:null,totalFrames:null},
        createdAt:savedJob.createdAt,updatedAt:savedJob.updatedAt,elapsedSeconds:1,
      });
    throw Error('Unexpected result/pose/upload request');
  });
  await savedComponent(client, async ({render,id}) => {
    render(); await flush(); render(); await flush();
    const tree=render();
    assert.equal(nodes(tree,n=>n.type==='video')[0]?.props.src,'/api/analysis/jobs/'+id+'/media');
    assert.match(text(tree), /Обработка остановлена из-за ошибки. Подробная причина недоступна/);
    assert.doesNotMatch(text(tree), /primitive|TypeError|Traceback|337 вместо 357/);
    assert.equal(nodes(tree,n=>n.props?.className==='analysis-event-card').length,0);
    assert.ok(nodes(tree,n=>n.type==='pose-overlay').every(n=>n.props.pose===null));
  });
});
