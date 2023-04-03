#
# MIT License -- see LICENSE.rst for details
# Copyright (c) 2020-23 Matthew Lovell and contributors
#
# ----------------------------------------------------------------------------
#
# This file is a variant of kodi_panel that copies the Pillow image,
# via luma.lcd, to a framebuffer.  In addition, it also makes use of
# evdev to support a multi-touch USB touchscreen, such as that in
# Waveshare's 7.9 inch capacitive touchscreen HDMI display:
#
#   https://www.waveshare.com/7.9inch-hdmi-lcd.htm
#
# The remainder of this file was originally copied from kodi_panel_fb.py
#
# After kodi_panel launches, the blinking cursor from the console may
# still be visible.  On RPI systems adding
#
#   vt.global_cursor_default=0
#
# to the end of /boot/cmdline.txt will turn off that cursor.
# Note that the cmdline.txt file must be just a single line of text.
#
# ----------------------------------------------------------------------------
#
from luma.core import device

import os
from time import sleep
from datetime import datetime

# evdev-based multitouch
from ws_multitouch import Touchscreen, TS_PRESS, TS_RELEASE, TS_MOVE
import threading

# kodi_panel modules
import config
import kodi_panel_display

# ----------------------------------------------------------------------------

# Use a Linux framebuffer via luma.core.device
device = device.linux_framebuffer("/dev/fb0",bgr=1)

# Don't try to use luma.lcd's backlight control ...
kodi_panel_display.USE_BACKLIGHT = False

# ... instead, lets make use of the sysfs interface for hardware PWM.
# The current form of this code assumes that one has loaded an
# RPi overlay such as pwm_2chan and that the backlight is
# controlled via GPIO18 / PWM0.
#
# This is a (hopefully) temporary form for this code.

screen_state = 0

def screen_on_pwm():
    global screen_state
    if screen_state == 0:
        result = os.system("echo 1 > /sys/class/pwm/pwmchip0/pwm0/enable")
        screen_state = 1

def screen_off_pwm():
    global screen_state
    if screen_state == 1:
        result = os.system("echo 0 > /sys/class/pwm/pwmchip0/pwm0/enable")
        screen_state = 0


#
# Create instance of Touchscreen class from ws_multitouch and set up
# a callback for Slot 0 press events into kodi_panel.
#

print(datetime.now(), "Setting up multitouch class")
ts = Touchscreen("WaveShare WaveShare")

def press_handler(event, touch):
    if event == TS_PRESS:
        print(datetime.now(), "Received TS_PRESS from touchscreen")
        # TODO: Capture coordinates of screen press
        # Inform kodi_panel via a threading.Event it declares
        kodi_panel_display._screen_press.set()

# Install callback just for Slot 0, since current needs are simple        
ts.touches[0].on_press = press_handler

print(datetime.now(), "Starting touchscreen thread")
ts.run()
        

if __name__ == "__main__":
    # Setup PWM
    if config.settings["USE_HW_PWM"]:
        os.system("echo 0 > /sys/class/pwm/pwmchip0/export")
        sleep(0.150)
        freq_cmd   = "echo " + str(config.settings["HW_PWM_FREQ"]) + " > /sys/class/pwm/pwmchip0/pwm0/period"
        period_cmd = "echo " + str(int(config.settings["HW_PWM_FREQ"] *
                                       config.settings["HW_PWM_LEVEL"])) + " > /sys/class/pwm/pwmchip0/pwm0/duty_cycle"
        os.system(freq_cmd)
        os.system(period_cmd)
        screen_on_pwm()
        kodi_panel_display.screen_on  = screen_on_pwm
        kodi_panel_display.screen_off = screen_off_pwm

    try:
        kodi_panel_display.main(device)
    except KeyboardInterrupt:
        kodi_panel_display.shutdown()        
        screen_on_pwm()
        print(datetime.now(), "Stopping touchscreen thread")
        ts.stop()
        if config.settings["USE_HW_PWM"]:
            os.system("echo 0 > /sys/class/pwm/pwmchip0/unexport")
