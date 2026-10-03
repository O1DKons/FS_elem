import {test} from 'node:test';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {createServer} from 'node:http';
import {once} from 'node:events';
import {createInterface} from 'node:readline';
import {join, resolve} from 'node:path';
import {existsSync} from 'node:fs';
import {mkdtemp, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {fileURLToPath, pathToFileURL} from 'node:url';

// This boundary test needs no model, decoder, installed web dependencies or old data.
// The fixture exercises the exported API and Python HTTP service, never a fake handler.
const sourceRoot = process.env.FS_ELEM_RELEASE_ROOT
  ? resolve(process.env.FS_ELEM_RELEASE_ROOT)
  : fileURLToPath(new URL('../', import.meta.url));
const sciencePython = join(sourceRoot, '.runtime/venv-science/bin/python');
const python = process.env.FS_RELEASE_TEST_PYTHON
  || (existsSync(sciencePython) ? sciencePython : 'python3');

test('release HTTP boundary: truthful readiness and invalid upload rejection before inference',
  {timeout: 15000}, async t => {
    const {createApi} = await import(pathToFileURL(join(sourceRoot, 'server/api.mjs')));
    const isolated = await mkdtemp(join(tmpdir(), 'fs-release-invalid-upload-'));
    t.after(() => rm(isolated, {recursive: true, force: true}));
    const args = [join(sourceRoot, 'services/analysis/server.py'), '--port', '0'];
    // The old public readiness-only service has no storage arguments. Keep the
    // original RED comparison runnable; new service jobs/config are always isolated.
    if (existsSync(join(sourceRoot, 'services/analysis/jobs.py')))
      args.push('--jobs', join(isolated, 'jobs'), '--config', join(isolated, 'missing.json'));
    const service = spawn(python, args,
      {cwd: sourceRoot, stdio: ['ignore', 'pipe', 'pipe']});
    let stderr = '';
    service.stderr.on('data', chunk => { stderr = (stderr + chunk).slice(-4000); });
    const lines = createInterface({input: service.stdout});
    t.after(async () => {
      lines.close();
      if (service.exitCode !== null || service.signalCode !== null) return;
      const ended = once(service, 'exit');
      service.kill('SIGTERM');
      const timer = setTimeout(() => service.kill('SIGKILL'), 3000);
      await ended;
      clearTimeout(timer);
    });
    const port = await new Promise((accept, reject) => {
      const timer = setTimeout(() => reject(new Error('Analysis startup did not report a port')), 5000);
      const fail = message => { clearTimeout(timer); reject(new Error(message)); };
      service.once('error', error => fail(error.message));
      service.once('exit', code => fail('Analysis startup exited ' + code + ': ' + stderr));
      lines.on('line', line => {
        try {
          const value = JSON.parse(line);
          if (!Number.isInteger(value.port) || value.port <= 0) return;
          clearTimeout(timer);
          accept(value.port);
        } catch { /* other log lines are not readiness */ }
      });
    });
    const api = createApi({}, {analysisPort: port});
    const web = createServer((req, res) => api(req, res, () => {
      res.writeHead(404, {'Content-Type': 'application/json'});
      res.end(JSON.stringify({error: 'Route unavailable'}));
    }));
    await new Promise(accept => web.listen(0, '127.0.0.1', accept));
    t.after(async () => {
      web.closeAllConnections();
      await new Promise(accept => web.close(accept));
    });
    const base = 'http://127.0.0.1:' + web.address().port;
    const request = (path, options = {}) => fetch(base + path, {
      ...options, headers: {Origin: base, ...options.headers},
    });

    // Break caught: health says runtime is unavailable but supplies no actionable issues
    // or loses active-job identity at the public proxy boundary.
    await t.test('health exposes issues and activeJobId when inference is unavailable', async () => {
      const response = await request('/api/analysis/health');
      assert.equal(response.status, 200);
      const health = await response.json();
      assert.equal(health.service, 'fs-elem-analysis');
      assert.equal(typeof health.inferenceAvailable, 'boolean');
      assert.ok(Array.isArray(health.issues), 'health.issues must be an array');
      assert.equal(health.activeJobId, null);
      if (!health.inferenceAvailable)
        assert.ok(health.issues.length > 0, 'unavailable inference must explain missing prerequisites');
    });

    // Break caught: new raw upload is absent or accepts unsupported media for a job.
    await t.test('unsupported extension is rejected with 415 before any inference', async () => {
      const response = await request('/api/analysis/jobs', {
        method: 'POST',
        headers: {'Content-Type': 'application/octet-stream', 'X-Filename': 'fixture.txt'},
        body: Buffer.from('synthetic invalid-upload fixture'),
      });
      assert.equal(response.status, 415);
    });

    // Break caught: empty video is queued, misreported as success or loses its 400 response.
    await t.test('empty raw video is rejected with 400 before any inference', async () => {
      const response = await request('/api/analysis/jobs', {
        method: 'POST',
        headers: {'Content-Type': 'application/octet-stream', 'X-Filename': 'empty.mp4'},
        body: Buffer.alloc(0),
      });
      assert.equal(response.status, 400);
    });
  });
