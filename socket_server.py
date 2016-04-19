from tornado import web, ioloop
from sockjs.tornado import SockJSRouter, SockJSConnection

import settings

cl = []

class IndexHandler(web.RequestHandler):
    def get(self):
        self.render("index.html")

class SocketHandler(SockJSConnection):
    def on_open(self, info):
        if self not in cl:
            cl.append(self)

    def on_message(self, msg):
            for c in cl:
                c.send(msg)

    def on_close(self):
        if self in cl:
            cl.remove(self)

if __name__ == '__main__':
    router = SockJSRouter(SocketHandler, '/sockjs')

    app = web.Application(
        [(r"/index", IndexHandler)] + router.urls
    )
    app.listen(settings.SOCKET_SERVER_PORT)
    ioloop.IOLoop.instance().start()

