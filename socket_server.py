from tornado import web, ioloop
from sockjs.tornado import SockJSRouter, SockJSConnection

import json
import logging
import re
import settings

rooms = dict()

logger = logging.getLogger('socketserver')
logger.setLevel(logging.ERROR)

def connectionsCleanup():
    for room_name in rooms.keys():
        logger.debug("Found room %s" % room_name)
        for conn in rooms[room_name]:
            logger.debug("Found connection in room %s" % room_name)
            if conn.is_closed:
                conn.on_close()

class IndexHandler(web.RequestHandler):
    def get(self):
        self.render("index.html")

class SocketHandler(SockJSConnection):
    def on_open(self, info):
        return

    def on_message(self, msg):
            try:
                message = json.loads(msg)
            except ValueError:
                logger.error("Received bad json message")
                return

            if not message['action']:
                logger.error("Received a message with no action")
                return

            if not 'data' in message:
                logger.error("Subscription message with no data")
                return

            if message['action'] == 'sub':
                logger.debug("Received a subscribe message")
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
                    return

                if not 'username' in user:
                    logger.error("Subscription message without username")
                    return

                # create the room
                if not room in rooms:
                    rooms[room] = set()

                # find the users who are already in the room
                room_users = []
                logger.debug("Checking if there are other users in the room %s" % room)
                for conn in rooms[room]:
                    room_client = getattr(conn, 'client')
                    logger.debug("Found %s in the room %s" % (room_client['username'], room))
                    room_users.append(room_client)

                # add client to the room
                logger.debug("Checking if %s is already in the room %s" % (user['username'], room))
                if self not in rooms[room]:
                    logger.debug("Adding %s to the room %s" % (user['username'], room))
                    client = {
                        'username': user['username'],
                        'window_id': window_id,
                        'room': room,                # TODO: we should get rid of this attribute here
                        'room_objs': []
                    }
                    setattr(self, 'client', client)
                    setattr(self, 'room', room)
                    rooms[room].add(self)
                else:
                    logger.error("%s is trying to subscribe more than once" % user['username'])
                    return

                # let the joining user know about the other users in the room
                message['data']['users'] = room_users
                self.send(json.dumps(message))

                # notify the room about the joining user
                self.broadcast(rooms[room], json.dumps({
                    'action': 'message',
                    'data': {
                        'type': 'userjoin',
                        'user': client
                    }
                }))
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
                    self.broadcast(rooms[room], msg)
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

        if room and self in rooms[room]:
            rooms[room].remove(self)
            if len(rooms[room]) == 0:
                del rooms[room]

            # notify the room
            self.broadcast(rooms[room], json.dumps({
                'action': 'message',
                'data': {
                    'type': 'userleave',
                    'user': client
                }
            }))
        else:
            logger.error("The user already left the room")


if __name__ == '__main__':
    router = SockJSRouter(SocketHandler, '/sockjs')

    app = web.Application(
        [(r"/index", IndexHandler)] + router.urls
    )

    app.listen(settings.SOCKET_SERVER_PORT)

    #ioloop.PeriodicCallback(connectionsCleanup, 20000).start()

    logging.info('Socket server starting on port ' + str(settings.SOCKET_SERVER_PORT))
    ioloop.IOLoop.instance().start()

