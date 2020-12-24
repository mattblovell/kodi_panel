#
# MIT License
#
# Copyright (c) 2020  Matthew Lovell
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

# ----------------------------------------------------------------------------
#
# This file is a variant of kodi_panel that copies the Pillow image,
# via luma.lcd, to a framebuffer.
#
# The first version of this file made use of Pytorinox's
# framebuffer.py.  However, the 2.0.0 release of luma.core includes a
# new linux_framebuffer class.  Using it permits for fewer changes.
#
# ----------------------------------------------------------------------------
#
from luma.core import device

import os
from time import sleep

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
        if config.settings["USE_HW_PWM"]:
            os.system("echo 0 > /sys/class/pwm/pwmchip0/unexport")

        pass
