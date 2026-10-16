from __future__ import annotations

import argparse
import json
import os
import re
import hashlib
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from core import BACKENDS, Engine, REGISTRY, ROOT


def serve(port: int):
    engine = Engine()
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def send(self, status, data, content_type='application/json; charset=utf-8', headers=None):
            body = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

        def local_origin(self):
            host = self.headers.get('Host', '')
            if host not in (f'127.0.0.1:{port}', f'localhost:{port}'):
                return False
            origin = self.headers.get('Origin')
            return origin is None or origin in (f'http://127.0.0.1:{port}', f'http://localhost:{port}')

        def do_GET(self):
            if not self.local_origin():
                self.send(403, {'error': '仅接受本机访问'})
                return
            if self.path == '/':
                self.send(200, (ROOT / 'ui.html').read_bytes(), 'text/html; charset=utf-8')
            elif self.path == '/v1/status':
                self.send(200, {'version': engine.config['version'],
                               'decision_model': engine.config['decision_model'],
                               'offline_mode': engine.config.get('offline_mode', False),
                               'decision_model_ready': engine.model_ready('decision'),
                               'retrieval_model_ready': engine.model_ready('retrieval'),
                               'remote_key_ready': bool(os.environ.get(engine.config['remote_key_env'])),
                               'jev_key_ready': bool(os.environ.get(engine.config['jev_key_env'])),
                               'threshold_calibrated': engine.config['threshold_calibrated'],
                               'model_lock': engine.model_lock()})
            elif self.path == '/v1/capabilities':
                from dataclasses import asdict
                self.send(200, {'capabilities': [asdict(c) for c in REGISTRY],
                    'agent': {'mode': 'agent', 'planner': 'local Qwen', 'selector': 'AnyJev + Qwen',
                        'services': ['calculator', 'text_stats', 'local_text', 'retrieve', 'knowledge_qa'],
                        'limits': {'initial_subtasks': 4, 'total_subtasks': 6, 'replans': 1, 'stop_reviews': 1},
                        'remote_enabled': False, 'semantic_validation': 'requires independent review'},
                    'workflows': {'dataset_report': {'input_root': 'workspace/inbox', 'output_root': 'workspace/runs',
                    'tools': ['inspect', 'read_csv', 'statistics', 'threshold', 'compare', 'local_model_suggestions', 'write_report', 'verify', 'finish', 'stop'],
                    'limits': {'csv_files': 2, 'bytes_per_csv': 1000000, 'rows_per_csv': 5000}}}})
            elif re.fullmatch(r'/v1/artifacts/[a-f0-9]{32}/report\.(md|json)', self.path):
                _, _, _, run_id, filename = self.path.split('/')
                base = ROOT / 'workspace/runs'
                target = base / run_id / filename
                if not base.resolve().is_relative_to(ROOT.resolve()) or not target.resolve().is_relative_to(base.resolve()) or not target.is_file():
                    self.send(404, {'error': '没有此任务成果'})
                    return
                try:
                    receipt = json.loads((target.parent / 'delivery.json').read_text('utf-8'))
                except (OSError, ValueError):
                    self.send(404, {'error': '本轮成果尚未完成交付核验'})
                    return
                content = target.read_bytes()
                if receipt.get('run_id') != run_id or receipt.get('files', {}).get(filename) != hashlib.sha256(content).hexdigest():
                    self.send(409, {'error': '成果文件已变化，请重新运行任务'})
                    return
                self.send(200, content, 'text/plain; charset=utf-8',
                    {'Content-Disposition': f'attachment; filename="{run_id}-{filename}"'})
            else:
                self.send(404, {'error': '没有这个接口'})

        def do_POST(self):
            if not self.local_origin():
                self.send(403, {'error': '仅接受本机访问'})
                return
            if self.path != '/v1/run':
                self.send(404, {'error': '没有这个接口'})
                return
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 32_768:
                    raise ValueError('请求大小须为 1 至 32768 字节')
                task = json.loads(self.rfile.read(size))
            except (ValueError, json.JSONDecodeError) as exc:
                self.send(400, {'error': str(exc)})
                return
            if not lock.acquire(blocking=False):
                self.send(409, {'error': '已有处理正在运行，请等本次结束'})
                return
            try:
                self.send(200, engine.run(task))
            except ValueError as exc:
                self.send(400, {'error': str(exc)})
            except Exception as exc:
                self.send(500, {'error': type(exc).__name__ + ': ' + str(exc)[:500]})
            finally:
                lock.release()

    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    print(f'初版页面：http://127.0.0.1:{port}', flush=True)
    print('本地决策：AnyJev；规则模式仅是对照，不冒充 Jev。', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        engine.close()


def main():
    parser = argparse.ArgumentParser(description='端侧协同决策初版')
    commands = parser.add_subparsers(dest='command', required=True)
    web = commands.add_parser('serve', help='启动本机操作页面')
    web.add_argument('--port', type=int, default=8765)
    run = commands.add_parser('run', help='处理一份显式任务文件')
    run.add_argument('--task', type=Path, required=True)
    run.add_argument('--backend', choices=BACKENDS, default='anyjev')
    run.add_argument('--allow-remote', action='store_true')
    args = parser.parse_args()
    if args.command == 'serve':
        serve(args.port)
    else:
        task = json.loads(args.task.read_text(encoding='utf-8'))
        task['backend'] = args.backend
        task['allow_remote'] = args.allow_remote
        task['network_available'] = args.allow_remote
        engine = Engine()
        try:
            print(json.dumps(engine.run(task), ensure_ascii=False, indent=2))
        finally:
            engine.close()


if __name__ == '__main__':
    main()
