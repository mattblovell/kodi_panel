#
# Touch screen driver for WaveShare hid-multitouch USB capacitive touchscreen
#
# Uses python3-evdev, https://python-evdev.readthedocs.io/en/latest/index.html
#
# Leveraged from Istvan Kovac's work to provide asyncio implementation for
# 4Dsystem's EP0510M09 touchscreen,
#
#  https://github.com/istvanzk/python-multitouch
#
# which was leveraged from ft5406.py from Pimoroni.  The asyncio
# implementation was not quite correct, so I switched back to a
# threaded approach, referencing Pimoroni's hp4ts.py, which is also
# from
#
#  https://github.com/pimoroni/python-multitouch
#
# All of those works are licensed under the MIT License.
# Based on ep0510m09.py, Copyright (c) 2019 Istvan Z. Kovacs
# Based on pimoroni/python-multitouch, Copyright (c) 2014 Pimoroni
#
#
# MIT License
#
# Copyright (c) 2023  Matthew Lovell and contributors
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
#
# ----------------------------------------------------------------------------

import glob
import io
import os
import errno
import struct
from collections import namedtuple
import threading
import time
import select
import queue

from evdev import InputDevice, categorize, ecodes

import logging
#logging.basicConfig(level=logging.DEBUG)

TOUCH_X = 0
TOUCH_Y = 1

TouchEvent = namedtuple('TouchEvent', ('timestamp', 'type', 'code', 'value'))

# Touch class codes
TS_PRESS = 1
TS_RELEASE = 0
TS_MOVE = 2

# Each Touch instance maintains its own list of events that
# have occurred since the last handle_events() invocation.
#
# Upon evdev finding an EV_SYN synchronization event, the Touchscreen
# class' poll() or poll_once() methods then trigger execution of the
# various on_* callback functions present in this class.
#
# However, note that EACH SLOT invokes those callbacks independently!
# Each Touch instance traverses its list of events, invoking the
# relevant on_* callback and then clearing the event list afterwards.
#
# If the "parent" thread instead wishes to receive all events for all
# slots that are part of an EV_SYN via a single, atomic mechanism, one
# should instead make use of the Touch class' on_sync callback
# mechanism.

class Touch(object):
    def __init__(self, slot, x, y):
        self.slot = slot

        self._x = x
        self._y = y
        self.last_x = -1
        self.last_y = -1

        self._id = -1
        self.events = []
        self.on_move = None
        self.on_press = None
        self.on_release = None
        
    @property
    def position(self):
        return (self.x, self.y)

    @property
    def last_position(self):
        return (self.last_x, self.last_y)

    @property
    def valid(self):
        return self.id > -1

    @property
    def id(self):
        return self._id

    @id.setter
    def id(self, value):
        if value != self._id:
            if value == -1 and not TS_RELEASE in self.events:
                self.events.append(TS_RELEASE)    
            elif not TS_PRESS in self.events:
                self.events.append(TS_PRESS)

        self._id = value

    @property
    def x(self):
        return self._x

    @x.setter
    def x(self, value):
        if value != self._x and not TS_MOVE in self.events:
            self.events.append(TS_MOVE)
        self.last_x = self._x
        self._x = value

    @property
    def y(self):
        return self._y

    @y.setter
    def y(self, value):
        if value != self._y and not TS_MOVE in self.events:
            self.events.append(TS_MOVE)
        self.last_y = self._y
        self._y = value

    def __str__(self):
        details = ""
        for event in self.events:
            details += ["Release", "Press", "Move"][event]
            details += repr(self.position) + " "
        return details
        
    def handle_events(self):
        """Invoke (per-slot/touch) callbacks for outstanding press/release/move events"""
        for event in self.events:
            if event == TS_MOVE and callable(self.on_move):
                self.on_move(event, self)
            if event == TS_PRESS and callable(self.on_press):
                self.on_press(event, self)
            if event == TS_RELEASE and callable(self.on_release):
                self.on_release(event, self)

        self.events = []


        
class Touches(list):
    @property
    def valid(self):
        return [touch for touch in self if touch.valid]

    
class Touchscreen(object):
    """Use evdev to collect touch events"""

    TOUCHSCREEN_EVDEV_NAME = 'WaveShare WaveShare'

    def __init__(self, device_name=None):
        self._device_name = self.TOUCHSCREEN_EVDEV_NAME if device_name is None else device_name
        self._running = False
        self._thread = None
        self.on_sync = None
        self._device = self._input_device()
        
        self.position = Touch(0, 0, 0)
        self.touches = Touches([Touch(x, 0, 0) for x in range(10)])
        self._touch_slot = 0

    def _poll_loop(self):
        logging.debug('Starting _pool_loop')
        self._running = True;
        while self._running:
            self.poll_once(self._device)
            time.sleep(0.001)
        logging.debug('Exiting _pool_loop')            
        
    def run(self):
        if self._thread is not None:
            return

        self._thread = threading.Thread(target=self._poll_loop,daemon=True)
        self._thread.start()


    def stop(self):
        if self._thread is None:
            return 
        self._running = False
        self._thread.join()
        self._thread = None

    # Send a tuple consisting of all active touches (i.e., touches
    # that have a non-empty event list) via a callback function.
    #
    # Recall that this callback function executes within the context
    # of this Touch object's thread!  If the callback destination
    # wishes to do anything non-trivial with this tuple of events, it
    # should make a deepcopy of it and send it through a queue to one
    # of its threads.
    #
    def handle_sync(self):
        """Invoke callback once for all accumulated events, all slots following an EV_SYN"""
        if callable(self.on_sync):
            logging.debug('Invoking on_sync callback')            
            active_events = list(i for i in self.touches if len(i.events))
            if len(active_events):
                self.on_sync(tuple(active_events))
        
 
    @property
    def _current_touch(self):
        return self.touches[self._touch_slot]

    def close(self):
        self._device = None
        self.stop()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, exc_tb):
        self.close()

    def __iter__(self):
        pass

    def poll_once(self, dev):
        """
        Use evdev to read a single touch event
        Save events from EV_ABS
        Handle events after reading an EV_SYN
        evdev seems to handle returning ABS_MT_SLOT to 0
        """
        event = dev.read_one()
        if not event:
            return
        
        if event.type == ecodes.EV_SYN: # Sync
            self.handle_sync()
            for touch in self.touches:
                touch.handle_events()
                    
        if event.type == ecodes.EV_ABS: # Absolute cursor position
            absevent = categorize(event)
            if absevent.event.code == ecodes.ABS_MT_SLOT:
                self._touch_slot = absevent.event.value
                        
            if absevent.event.code == ecodes.ABS_MT_TRACKING_ID:
                self._current_touch.id = absevent.event.value
                    
            if absevent.event.code == ecodes.ABS_MT_POSITION_X:
                self._current_touch.x = absevent.event.value
                    
            if absevent.event.code == ecodes.ABS_MT_POSITION_Y:
                self._current_touch.y = absevent.event.value
                    
            if absevent.event.code == ecodes.ABS_X:
                self.position.x = absevent.event.value
                    
            if absevent.event.code == ecodes.ABS_Y:
                self.position.y = absevent.event.value

                
    def poll_forever(self, dev):
        """
        Use evdev read_loop() to read touch events forever
        Save events from EV_ABS
        Handle events after reading an EV_SYN
        evdev seems to handle returning ABS_MT_SLOT to 0
        """
        for event in dev.read_loop():
            if event.type == ecodes.EV_SYN: # Sync
                for touch in self.touches:
                    touch.handle_events()
                    
            if event.type == ecodes.EV_ABS: # Absolute cursor position
                absevent = categorize(event)
                if absevent.event.code == ecodes.ABS_MT_SLOT:
                    self._touch_slot = absevent.event.value
                        
                if absevent.event.code == ecodes.ABS_MT_TRACKING_ID: 
                    self._current_touch.id = absevent.event.value
                    
                if absevent.event.code == ecodes.ABS_MT_POSITION_X:
                    self._current_touch.x = absevent.event.value
                    
                if absevent.event.code == ecodes.ABS_MT_POSITION_Y:
                    self._current_touch.y = absevent.event.value
                    
                if absevent.event.code == ecodes.ABS_X:
                    self.position.x = absevent.event.value
                    
                if absevent.event.code == ecodes.ABS_Y:
                    self.position.y = absevent.event.value


    def _input_device(self):
        """Returns the evdev device class (not the path to input device!)"""
        for evdev in glob.glob("/sys/class/input/event*"):
            try:
                with io.open(os.path.join(evdev, 'device', 'name'), 'r') as f:
                    if f.read().strip() == self._device_name:
                        return InputDevice(os.path.join('/dev','input',os.path.basename(evdev)))
            except IOError as e:
                if e.errno != errno.ENOENT:
                    raise
        raise RuntimeError('Unable to locate touchscreen device: {}'.format(self._device_name))

    def read(self):
        return next(iter(self))


if __name__ == "__main__":
    import signal

    ts = Touchscreen()

    def handle_event(event, touch):
        print(["Release","Press","Move"][event],
            touch.slot,
            touch.x,
            touch.y)

    def handle_sync(events_tuple):
        print("   handle_sync called!")
        for event in events_tuple:
            print("    Event:",event)
        return
                      
    for touch in ts.touches:
        touch.on_press = handle_event
        touch.on_release = handle_event
        touch.on_move = handle_event

    ts.on_sync = handle_sync
        
    logging.debug('Invoking ts.run()')
    ts.run()
    logging.debug('After ts.run() call')    

    try:
        signal.pause()
    except KeyboardInterrupt:
        logging.debug('Stopping driver...')
        ts.stop()
        exit()
