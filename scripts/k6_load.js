import http from 'k6/http';
import { check, sleep } from 'k6';
export let options = { vus: 50, duration: '2m', thresholds: { http_req_duration: ['p(95)<3000'], http_req_failed: ['rate<0.01'] } };
export default function () {
  let r = http.get('http://localhost:8777/health/ready');
  check(r, { '200': (x) => x.status === 200 });
  sleep(0.5);
  let r2 = http.get('http://localhost:8777/health');
  check(r2, { 'health ok': (x) => x.json('status') === 'ok' });
  sleep(0.5);
  let r3 = http.get('http://localhost:8777/api/agents', { headers: { Authorization: `Bearer ${__ENV.TOKEN || ''}` } });
  check(r3, { 'agents ok': (x) => x.status === 200 || x.status === 401 });
}
