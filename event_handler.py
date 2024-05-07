import ssl

from ssl_proxy import Connection

class EventHandler:
    def __init__(self, connection: Connection):
        # EventHandler is initiated for every connection with a Connection instance as argument
        self.connection = connection

    async def create_ssl_context_for_remote_connection(self):
        if self.connection.is_ssl:
            if self.connection.socket_address == b'w1145.vdi.mipt.ru:443':
                return ssl._create_unverified_context()
            else:
                return ssl.create_default_context()
        return None

    async def data_from_client(self, data: bytes):
        # print(data)
        await self.connection.write_to_server(data)

    async def data_from_server(self, data: bytes):
        # print(data)
        await self.connection.write_to_client(data)



