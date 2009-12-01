import uuid
import simplejson
from django.shortcuts import render_to_response
from django.template.loader import render_to_string
from django.http import HttpResponse
from gevent.event import Event
from django.conf import settings

from chat.models import Map

class ChatRoom(object):

    def __init__(self, room_id):
        self.pk = room_id
        self.last_message = []
        self.players = []
        self.cache = []
        self.room_event = Event()
        self.event_cursor = 0
        self.event_buffer = []
        for v in range(0, 9):
            self.event_buffer.append(None)

    def main(self, request):
        room_map = Map.objects.get(pk=self.pk)
        content = room_map.content.replace("\n", "")
        return render_to_response(
            'index.html',
            {
                'map_content':content,
                'MEDIA_URL': settings.MEDIA_URL
            }
        )

    def new_room_event(self, value):
        self.event_cursor += 1
        if self.event_cursor >= len(self.event_buffer):
            self.event_cursor = 0
        self.event_buffer[self.event_cursor] = value
        self.room_event.set()
        self.room_event.clear()

    def get_player(self, key):
        for p in self.players:
            if p['key'] == key:
                return p
        return None

    def player_new(self, request):
        key = request.COOKIES.get('rpg_key', False)
        new_player = self.get_player(key)
        if  not new_player:
            key = str(uuid.uuid4())
            name = request.POST['body']
            new_player = {'name':name, 'key':key}
        event_list = []
        # send all the other player
        for player in self.players:
            event_list.append(['new_player', player])
        self.players.append(new_player)
        self.new_room_event(['new_player', new_player])
        response = json_response({'you':new_player, 'events':event_list})
        response.set_cookie('rpg_key', key)
        return response

    def player_update_position(self, request):
        key = request.COOKIES['rpg_key']
        player = self.get_player(key)
        position = request.POST['body']
        player['position'] = position
        self.new_room_event(['update_player_position', [key, position]])
        return json_response([1])

    def message_new(self, request):
        key = request.COOKIES['rpg_key']
        msg = request.POST['body']
        player = self.get_player(key)
        player['last_message'] = msg
        self.new_room_event(['last_message', [key, msg]])
        return json_response([1])

    def room_updates(self, request):

        self.room_event.wait()
        
        cursor = int(request.POST.get('cursor', False))
        # up to date
        if cursor == self.event_cursor:
            return json_response([1])
        if cursor == False:
            cursor = self.event_cursor
        # increment to be at the same level that the last event
        cursor += 1
        if cursor >= len(self.event_buffer):
            cursor = 0
        
        event_list = []
        # if there is more than just on event
        while(cursor != self.event_cursor):
            event = self.event_buffer[cursor]
            if event:
                event_list.append(self.event_buffer[cursor])
            cursor += 1
            if cursor >= len(self.event_buffer):
                cursor = 0

        event_list.append(self.event_buffer[self.event_cursor])
        event_list.append(['update_cursor', self.event_cursor])

        return json_response(event_list)

    def change_room(self, request):
        key = request.COOKIES['rpg_key']
        x, y = request.POST.get('direction').split(',')
        x = int(x); y = int(y)
        old_map = Map.objects.get(pk=self.pk)
        room_map, created = Map.objects.get_or_create(x=old_map.x+x, y=old_map.y+y)
        player = self.get_player(key)
        new_room = get_room(room_map.id)
        new_room.players.append(player)
        new_room.new_room_event(['new_player', player])
        response = json_response({'change_room':room_map.serialized()})
        response.set_cookie('room_id', new_room.pk)
        return response

rooms = {}
def get_room(room_id):
    if rooms.has_key(room_id):
        room = rooms[room_id]
    else:
        room = ChatRoom(room_id)
        rooms[room_id] = room
    return room

def room_dispacher(method):
    def _method(request):
        room_id = int(request.COOKIES.get('room_id', 1))
        print room_id
        if rooms.has_key(room_id):
            room = rooms[room_id]
        else:
            room = ChatRoom(room_id)
            rooms[room_id] = room
        return getattr(room, method)(request)
    return _method

main = room_dispacher('main')
message_new = room_dispacher('message_new')
player_new = room_dispacher('player_new')
player_update_position = room_dispacher('player_update_position')
room_updates = room_dispacher('room_updates')
change_room = room_dispacher('change_room')

def create_message(from_, body):
    data = {'id': str(uuid.uuid4()), 'from': from_, 'body': body}
    data['html'] = render_to_string('message.html', dictionary={'message': data})
    return data

def json_response(value, **kwargs):
    kwargs.setdefault('content_type', 'text/javascript; charset=UTF-8')
    return HttpResponse(simplejson.dumps(value), **kwargs)

