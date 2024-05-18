import asyncio
import sys
import re
import ssl
from functools import *
from itertools import *
from operator import *
import http.server
import io
import traceback
import pathlib
import logging
import functools
import os
import argparse

import stream
# import event_handler

def socket(socket_address):
    r = itemgetter(slice(None, None, -1))
    host, port = (r(list(map(r, r(socket_address).split(':' if isinstance(socket_address, str) else b':', 1)))))[:2]
    return host, int(port)

import event_handler

from error_logger import error_logger
import ssl_cert


class Connection:
    @error_logger
    async def write_to_stream(self, stream_to_write: stream.Stream, data: bytes):
        stream_to_write.write(data)
        if stream_to_write.transport.get_write_buffer_size() > 2**16:
            await stream_to_write.drain()

    @error_logger
    async def write_to_client(self, data: bytes):
        return await self.write_to_stream(self.client, data)

    @error_logger
    async def write_to_server(self, data: bytes):
        return await self.write_to_stream(self.server, data)

    @error_logger
    async def stream_reader(self, stream_to_read: stream.Stream, handler):
        while (data:=await stream_to_read.read(2**16)):
            await handler(data)

    @error_logger
    async def client_reader(self):
        await self.stream_reader(self.client, self.event_handler.data_from_client)

    @error_logger
    async def server_reader(self):
        await self.stream_reader(self.server, self.event_handler.data_from_server)

@error_logger
async def copy(r: asyncio.StreamReader, w: asyncio.StreamWriter):
    while (data:=await r.read(2**16)):
        w.write(data)
        await w.drain()

@error_logger
async def on_ssl_connect(connection: Connection, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    async with stream.Stream(reader, writer) as local_sock:
        connection.client = local_sock
        host, port = socket(connection.socket_address)
        ssl_context = await connection.event_handler.create_ssl_context_for_remote_connection()
        async with stream.Stream(*await asyncio.open_connection(host, port, ssl=ssl_context)) as remote_sock:
            connection.server = remote_sock
            await asyncio.gather(connection.client_reader(), connection.server_reader())

@error_logger
async def on_connect(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    async with stream.Stream(reader, writer) as local_sock:
        connection = Connection()
        connection.event_handler = event_handler.EventHandler(connection)
        connection.data = bytearray()
        while 1:
            new_data = await local_sock.read(1)
            connection.data += new_data
            if not new_data or connection.data.endswith(b'\r\n\r\n') or connection.data.endswith(b'\n\n'):
                break
            if len(connection.data) > 2**16:
                return
        connection.method, connection.url = re.match(r'([^ ]+)\s+([^ ]+)\s+'.encode(), connection.data, re.S).groups()
        # await connection.event_handler.new_connection()
        if connection.method == b'CONNECT':
            connection.socket_address = connection.url
            local_sock.write(b'HTTP/1.1 200 Connection established\r\n\r\n')
            await local_sock.drain()
            connection.data = await local_sock.readexactly(1)
            print(connection.data)
            connection.is_ssl = connection.data[0]==0x16
            host, port = socket(connection.socket_address)
            if connection.is_ssl:
                ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                ssl_context.load_cert_chain(*await ssl_cert.cert_make(host))
                ssl_context.check_hostname = False
            else:
                ssl_context = None
            async with await asyncio.start_server(partial(on_ssl_connect, connection), '127.0.0.1', ssl=ssl_context) as server:
                async with stream.Stream(*await asyncio.open_connection(*server.sockets[0].getsockname())) as remote_sock:
                    remote_sock.write(connection.data)
                    await asyncio.gather(copy(local_sock, remote_sock), copy(remote_sock, local_sock))
        else:
            async with stream.Stream(*await asyncio.open_connection(*args.forward)) as remote_sock:
                connection.client = local_sock
                connection.server = remote_sock
                await connection.event_handler.data_from_client(connection.data)
                await asyncio.gather(connection.client_reader(), connection.server_reader())


@error_logger
async def main():
    try:
        await ssl_cert.cert_init()
        async with await asyncio.start_server(partial(on_connect), *args.listen) as server:
            await server.serve_forever()
    finally:
        await asyncio.sleep(0.1)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--listen', type=socket, help='host:port to proxy for listening', required=True)
    parser.add_argument('--forward', type=socket, help='host:port of http proxy to forward http requests', required=True)
    args = parser.parse_args()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass


