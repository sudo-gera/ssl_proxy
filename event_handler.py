import ssl

from ssl_proxy import Connection

class EventHandler:
    def __init__(self, connection: Connection):
        # EventHandler is initiated for every connection with a Connection instance as argument
        self.connection = connection

    async def create_ssl_context_for_remote_connection(self):
        if self.connection.is_ssl:
            return ssl.create_default_context()
        return None

    async def data_from_client(self, data: bytes):
        print('from client', id(self.connection), self.connection.url, data)
        await self.connection.write_to_server(data)

    async def data_from_server(self, data: bytes):
        print('from server', id(self.connection), self.connection.url, data)
        await self.connection.write_to_client(data)



