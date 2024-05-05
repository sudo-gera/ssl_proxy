import asyncio
import sys
import re
import ssl
from functools import *
from itertools import *
from operator import *
import aiohttp
import http.server
import io
import traceback
import pathlib
import logging
import functools
import os
import argparse

import stream
# import timeout

LOGLEVEL = os.environ.get('LOGLEVEL', 'INFO').upper()
logging.basicConfig(
    level=LOGLEVEL,
    format='%(asctime)s %(levelname)s: %(message)s'
)


def err(func):
    async def awaiter(r):
        try:
            r = await r
            return r
        except Exception:
            logging.debug(f'{func}:\n{traceback.format_exc()}')
    @functools.wraps(func)
    def wrapper(*a,**s):
        try:
            r=func(*a,**s)
            if asyncio.iscoroutine(r):
                return awaiter(r)
            return r
        except Exception:
            logging.debug(f'{func}:\n{traceback.format_exc()}')
    return wrapper

def host_port(url, default_port='-'):
    r = itemgetter(slice(None, None, -1))
    host, port = (r(list(map(r, r(url).split(':' if isinstance(url, str) else b':', 1)))) + [default_port])[:2]
    return host, int(port)

@err
async def copy(r: asyncio.StreamReader, w: asyncio.StreamWriter, http=False):
    while (data:=await r.read(2**16)):
        w.write(data)
        if w.transport.get_write_buffer_size() > 2**16:
            continue
        await w.drain()

@err
async def on_ssl_connect(url: str, is_ssl: bool, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    async with stream.Stream(reader, writer) as local_sock:
        host, port = host_port(url, 443)
        ssl_context = ssl._create_unverified_context() if is_ssl else None
        async with stream.Stream(*await asyncio.open_connection(host, port, ssl=ssl_context)) as remote_sock:
            await asyncio.gather(copy(local_sock, remote_sock), copy(remote_sock, local_sock))

@err
async def run(*command, input=None):
    process = await asyncio.subprocess.create_subprocess_exec(*command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, stdin=asyncio.subprocess.PIPE)
    stdout, stderr = await process.communicate(input=input)
    assert not await process.wait()


@err
async def cert_init():
    certs = pathlib.Path(__file__).with_name('.certs')
    root_key = certs / 'ssl_proxy_root_CA.key'
    root_pem = certs / 'ssl_proxy_root_CA.pem'
    if not (root_key.exists()
        and root_pem.exists()):
        await run('openssl', 'genrsa', '-out', root_key, '2048')
        await run('openssl', 'req', '-x509', '-new', '-nodes','-key', root_key,
                  '-sha256', '-days', '9999', '-out', root_pem, '-subj', '/CN=ssl_proxy')
        logging.info(f'Created new root CA. You have to install {root_pem} as trusted in your system.')
    return root_key, root_pem

@cache
def lock_domain(domain):
    return asyncio.Lock()

@err
async def cert_make(domain):
    async with lock_domain(domain):
        certs = pathlib.Path(__file__).with_name('.certs')
        root_key = certs / 'ssl_proxy_root_CA.key'
        root_pem = certs / 'ssl_proxy_root_CA.pem'
        if isinstance(domain, bytes):
            domain = domain.decode()
        domain_key = root_key.with_stem(domain)
        domain_csr = domain_key.with_suffix('.csr')
        domain_ext = domain_key.with_suffix('.ext')
        domain_crt = domain_key.with_suffix('.crt')
        if not (domain_key.exists() and domain_crt.exists() and domain_csr.exists() and domain_ext.exists()):
            await run('openssl', 'genrsa', '-out', domain_key, '2048')
            await run('openssl', 'req', '-new', '-key', domain_key, '-out', domain_csr, '-subj', '/CN=ssl_proxy')
            with domain_ext.open('w') as file:
                print('authorityKeyIdentifier=keyid,issuer', file=file)
                print('basicConstraints=CA:FALSE', file=file)
                print('keyUsage = digitalSignature, nonRepudiation, keyEncipherment, dataEncipherment', file=file)
                print('subjectAltName = @alt_names', file=file)
                print('', file=file)
                print('[alt_names]', file=file)
                print(f'DNS.1 = {domain}', file=file)
            await run('openssl', 'x509', '-req', '-in', domain_csr, '-CA', root_pem, '-CAkey', root_key,
                        '-CAcreateserial', '-out', domain_crt, '-days', '9999', '-sha256', '-extfile', domain_ext)
        return domain_crt, domain_key

@err
async def on_connect(args, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    async with stream.Stream(reader, writer) as local_sock:
        data = bytearray()
        while 1:
            new_data = await local_sock.read(1)
            data += new_data
            if not new_data or data.endswith(b'\r\n\r\n') or data.endswith(b'\n\n'):
                break
            if len(data) > 2**16:
                return
        match = re.match(r'([^ ]+)\s+([^ ]+)\s+(.*)'.encode(), data, re.S)
        method, url, other = match.groups()
        if method == b'CONNECT':
            local_sock.write(b'HTTP/1.1 200 Connection established\r\n\r\n')
            await local_sock.drain()
            data = await local_sock.readexactly(1)
            is_ssl = data[0]==0x16
            host, port = host_port(url, 443)
            if is_ssl:
                ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                ssl_context.load_cert_chain(*await cert_make(host))
                ssl_context.check_hostname = False
            else:
                ssl_context = None
            async with await asyncio.start_server(partial(on_ssl_connect, url, is_ssl), '127.0.0.1', ssl=ssl_context) as server:
                async with stream.Stream(*await asyncio.open_connection(*server.sockets[0].getsockname())) as remote_sock:
                    remote_sock.write(data)
                    await asyncio.gather(copy(local_sock, remote_sock), copy(remote_sock, local_sock))
        else:
            async with stream.Stream(*await asyncio.open_connection(*args.forward)) as remote_sock:
                remote_sock.write(data)
                await asyncio.gather(copy(local_sock, remote_sock), copy(remote_sock, local_sock))


@err
async def main(args):
    try:
        await cert_init()
        async with await asyncio.start_server(partial(on_connect, args), *args.listen) as server:
            await server.serve_forever()
    finally:
        await asyncio.sleep(0.1)

parser = argparse.ArgumentParser()
parser.add_argument('--listen', type=host_port, help='host:port to proxy for listening')
parser.add_argument('--forward', type=host_port, help='host:port of http proxy to forward http requests')
args = parser.parse_args()
try:
    asyncio.run(main(args))
except KeyboardInterrupt:
    pass


