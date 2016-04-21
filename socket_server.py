from tornado import web, ioloop
from sockjs.tornado import SockJSRouter, SockJSConnection
from tornado.httpclient import HTTPRequest, AsyncHTTPClient

import json
import logging
import re
import functools
import settings

logger = logging.getLogger('socketserver')
logger.setLevel(logging.ERROR)

class IndexHandler(web.RequestHandler):
    def get(self):
        self.render("index.html")

class SocketHandler(SockJSConnection):
    rooms = dict()

    def __init__(self, session):
        self.session = session
        self.http_client = AsyncHTTPClient(force_instance=True, defaults=dict(
            user_agent    = "BF-cms-websocket-server",
            auth_username = settings.WEB_APP_AUTH_USER,
            auth_password = settings.WEB_APP_AUTH_PASS
        ))

    def on_open(self, info):
        return

    def validate_auth_token(self, response, **kwargs):
        if response.error:
            logger.error("A problem with the auth request: %s" % response.error)
            self.close(4500, "Server error");
            return
        else:
            try:
                res_body = json.loads(response.body)
            except ValueError:
                logger.error("Received a bad json message")
                self.close(4500, "Server error");
                return

            if res_body and 'validated' in res_body and res_body['validated']:
                # auth accepted
                logger.debug("Token was accepted")
                room      = kwargs['room']
                user      = kwargs['user']
                window_id = kwargs['window_id']
                message   = kwargs['message']
                self.register_user(room, user, window_id, message)
            else:
                # auth rejected
                logger.debug("Token was accepted")
                socket.close(4001, "Invalid authentication token");
        return

    def register_user(self, room, user, window_id, message):
        # create the room
        if not room in self.rooms:
            self.rooms[room] = set()

        # find the users who are already in the room
        room_users = []
        logger.debug("Checking if there are other users in the room %s" % room)
        for conn in self.rooms[room]:
            room_client = getattr(conn, 'client')
            logger.debug("Found %s in the room %s" % (room_client['username'], room))
            room_users.append(room_client)

        # add client to the room
        logger.debug("Checking if %s is already in the room %s" % (user['username'], room))
        if self not in self.rooms[room]:
            logger.debug("Adding %s to the room %s" % (user['username'], room))
            client = {
                'username': user['username'],
                'window_id': window_id,
                'room': room,                # TODO: we should get rid of this attribute here
                'room_objs': []
            }
            setattr(self, 'client', client)
            setattr(self, 'room', room)
            self.rooms[room].add(self)
        else:
            logger.error("%s is trying to subscribe more than once" % user['username'])
            return

        # let the joining user know about the other users in the room
        message['data']['users'] = room_users
        self.send(json.dumps(message))

        # notify the room about the joining user
        self.broadcast(self.rooms[room], json.dumps({
            'action': 'message',
            'data': {
                'type': 'userjoin',
                'user': client
            }
        }))
        return

    def on_message(self, msg):
            try:
                message = json.loads(msg)
            except ValueError:
                logger.error("Received a bad json message")
                return

            if not message['action']:
                logger.error("Received a message with no action")
                return

            if not 'data' in message:
                logger.error("Received a message with no data")
                return

            if message['action'] == 'sub':
                logger.debug("Received a subscription message")
                #
                # Subscribe
                #

                # mandatory params check
                for param in ['room', 'user', 'window_id', 'auth_token']:
                    if not param in message['data']:
                        logger.error("Subscription message without %s" % param)
                        return

                room       = message['data']['room']
                user       = message['data']['user']
                window_id  = message['data']['window_id']
                auth_token = message['data']['auth_token']

                # we serve only cms CE requests
                if not re.match('^superposter-edit-\d+$', room):
                    logger.error("Subscription message with an unknown room pattern")
                    return

                if not 'username' in user:
                    logger.error("Subscription message without username")
                    return

                # Authenticate the subscription request against the webapp
                auth_url = settings.WEB_APP_AUTH_URL + auth_token
                auth_request = HTTPRequest(auth_url)
                auth_callback = functools.partial(self.validate_auth_token,
                    room=room,
                    user=user,
                    window_id=window_id,
                    message=message
                )
                self.http_client.fetch(auth_request, auth_callback)
                return

            elif message['action'] == 'unsub':
                logger.debug("Received an unsubscribe message")
                #
                # Unsubscribe
                #
                self.on_close()

            elif message['action'] == 'message':
                #
                # Message 
                #
                logger.debug("Received a message")
                if not hasattr(self, 'room'):
                    logger.error("Unsubscribed user is trying to send a message")
                    return

                room = getattr(self, 'room')
                logger.debug("Received a message with room %s" % room)

                if not ('data' in message and 'data' in message['data']):
                    logger.error("Message with no data")
                    return
                
                # mandatory params check
                for param in ['type', 'el_key']:
                    if not param in message['data']['data']:
                        logger.error("Subscription message without %s" % param)
                        return

                cms_data = message['data']['data']
                if cms_data['type'] == 'superposter:lock:element':
                    logger.debug("Received a lock:element message %s" % cms_data['el_key'])
                    client = getattr(self, 'client')
                    client['room_objs'].append(cms_data['el_key'])
                    setattr(self, 'client', client)
                elif cms_data['type'] == 'superposter:release:element':
                    logger.debug("Received a release:element message %s" % cms_data['el_key'])
                    client = getattr(self, 'client')
                    client['room_objs'].pop(client['room_objs'].index(cms_data['el_key']))
                    setattr(self, 'client', client)
                else:
                    logger.error("Unknown message type")
                    return

                # broadcast message to the room
                if room:
                    self.broadcast(self.rooms[room], msg)
                else:
                    logger.error("Somehow we ended up with a blank room name")
                
                return

            else:
                #
                # Unknown action
                #
                logger.error("A message with unknown action")
                return

    def on_close(self):
        if not hasattr(self, 'room'):
            log.error("A user is leaving without a room name")
            return
        room = getattr(self, 'room')

        if hasattr(self, 'client'):
            client = getattr(self, 'client')
            username = client['username']
        else:
            log.error("A user is leaving without a client information")
            return

        if not room:
            logger.error("Somehow we ended up with a blank room name")
            return

        logger.debug("The user %s is leaving the %s room now" % (username, room))

        if room and self in self.rooms[room]:
            self.rooms[room].remove(self)
            if len(self.rooms[room]) == 0:
                del self.rooms[room]

            # notify the room
            self.broadcast(self.rooms[room], json.dumps({
                'action': 'message',
                'data': {
                    'type': 'userleave',
                    'user': client
                }
            }))
        else:
            logger.error("The user already left the room")

    def connectionsCleanup(self):
        logger.debug("Cleaning up closed connections")
        for room_name in self.rooms.keys():
            logger.debug("Found room %s" % room_name)
            for conn in self.rooms[room_name]:
                logger.debug("Found connection in room %s" % room_name)
                if conn.is_closed:
                    conn.on_close()

if __name__ == '__main__':
    router = SockJSRouter(SocketHandler, '/sockjs')

    app = web.Application(
        [(r"/index", IndexHandler)] + router.urls
    )

    app.listen(settings.SOCKET_SERVER_PORT)

    # data of dead connections is removed by on_close() but to be on the safe side
    grabage_collector = SocketHandler('dummy-session')
    ioloop.PeriodicCallback(grabage_collector.connectionsCleanup, 120000).start()

    # start main loop
    ioloop.IOLoop.instance().start()

