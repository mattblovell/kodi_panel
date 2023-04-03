from ws_multitouch import Touchscreen, TS_PRESS, TS_RELEASE, TS_MOVE
import threading
import time
import copy

ts = Touchscreen("WaveShare WaveShare")

screen_press = threading.Event()
last_press = None

def touch_handler(event, touch):
    global last_press
    if event == TS_PRESS:
        print(f"{time.ctime()} Got Press: ", touch)
        last_press = copy.deepcopy(touch)
        screen_press.set()
    if event == TS_RELEASE:
        print(f"{time.ctime()} Got release: ", touch)
    if event == TS_MOVE:
        print(f"{time.ctime()} Got move: ", touch)

for touch in ts.touches:
    touch.on_press = touch_handler
    touch.on_release = touch_handler
    touch.on_move = touch_handler


print("Hello.")            
print("Just prior to ts.run() invocation")    
ts.run()
print("Just after to ts.run() invocation")    

try:
    while True:
        if screen_press.is_set():
            print("Press event occurred!")
            print("  press event was ", last_press)
            print("Going back to sleep...")
            screen_press.clear()
        print(f"{time.ctime()} Hello from main -- last_press was", last_press)
        screen_press.wait(5)
except KeyboardInterrupt:
    print("Stopping ts instance")
    ts.stop()
    pass
print("Goodbye.")    
