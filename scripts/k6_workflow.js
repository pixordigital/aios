import http from 'k6/http';
import { check, sleep } from 'k6';
export let options = { vus: 20, duration: '3m', thresholds: { http_req_duration: ['p(95)<5000'], http_req_failed: ['rate<0.02'] } };
const BASE = __ENV.BASE_URL || 'http://localhost:8777';
const TOKEN = __ENV.TOKEN || '';
export default function () {
  let h = { headers: { Authorization: `Bearer ${TOKEN}` } };
  http.get(`${BASE}/health/ready`);
  let r1 = http.get(`${BASE}/api/agents`, h);
  check(r1, { 'agents 200': (x) => x.status === 200 });
  sleep(1);
  let r2 = http.post(`${BASE}/api/conversations`, JSON.stringify({ channel: 'web', text: 'hello' }), { headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${TOKEN}` } });
  check(r2, { 'conv': (x) => x.status === 200 || x.status === 201 });
  sleep(1);
  let r3 = http.get(`${BASE}/api/workflows`, h);
  check(r3, { 'wf list': (x) => x.status === 200 });
  if (r3.json() && r3.json().length) {
    let wfId = r3.json()[0].id;
    let r4 = http.post(`${BASE}/api/workflows/${wfId}/run`, JSON.stringify({ input: 'load test', async: true }), { headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${TOKEN}` } });
    check(r4, { 'wf run 200': (x) => x.status === 200 });
  }
}
