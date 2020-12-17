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
#
# ----------------------------------------------------------------------------
#
# kodi_panel for an ili9341 display
#
# ----------------------------------------------------------------------------

from luma.core.interface.serial import spi
from luma.core.render import canvas
from luma.lcd.device import ili9341

# kodi_panel modules
import config
import kodi_panel_display

# ----------------------------------------------------------------------------

# SPI interface
serial = spi(port=0, device=0, gpio_DC=24, gpio_RST=25,
             reset_hold_time=0.2, reset_release_time=0.2)


# LCD display
#
# Create a handle to the ILI9341-driven SPI panel via luma.lcd.
#
# The backlight signal (with inline resistor possibly needed) is
# connected to GPIO18, physical pin 12.  Recall that the GPIOx number
# is using RPi.GPIO's scheme!
#
# Below is how I've connected the ILI9341, which is *close* to the
# recommended wiring in luma.lcd's online documentation.  Again,
# recall the distinction between RPi.GPIO pin naming and physical pin
# numbers.
#
# As you can provide RPi.GPIO numbers as arguments to the spi()
# constructor, you do have some flexibility.
#
#               |  BCM /           |
#   LCD pin     |  RPi.GPIO name   |  Physical pin #
#   ------------|------------------|-----------------
#   VCC         |  3V3             |  1 or 17
#   GND         |  GND             |  9 or 25 or 39
#   CS          |  GPIO8           |  24
#   RST / RESET |  GPIO25          |  22
#   DC          |  GPIO24          |  18
#   MOSI        |  GPIO10 (MOSI)   |  19
#   SCLK / CLK  |  GPIO11 (SCLK)   |  23
#   LED         |  GPIO18          |  12 
#   ------------|------------------|-----------------
#
# Originally, the constructor for ili9341 also included a
# framebuffer="full_frame" argument.  That proved unnecessary
# once non-zero reset hold and release times were specified
# for the device.
#
# The USE_PWM option that exists below is, unfortunately, not all that
# useful as of this writing (in late 2020).  RPi.GPIO-Odroid, like
# RPi.GPIO itself, uses a pthreads software implementation for PWM.
# As Linux is not a real-time OS, the scheduling of that thread is not
# guaranteed and flickering can result.
#
# The GPIO18 pin is PWM-capable.  See kodi_panel_fb.py for an example 
# of using sysfs directly for hardware PWM on an RPi (after loading 
# the pwm-2chan overlay in the Pi's /boot/config.txt file).
#
serial = spi(port=0, device=0, gpio_DC=24, gpio_RST=25,
             reset_hold_time=0.2, reset_release_time=0.2)

if kodi_panel_display.USE_PWM:
    device = ili9341(serial, active_low=False, width=320, height=240,
                     bus_speed_hz=32000000,
                     gpio_LIGHT=18,
                     pwm_frequency=PWM_FREQ
    )
else:
    device = ili9341(serial, active_low=False, width=320, height=240,
                     bus_speed_hz=32000000,
                     gpio_LIGHT=18
    )


    
if __name__ == "__main__":
    try:
        kodi_panel_display.main(device)
    except KeyboardInterrupt:
        kodi_panel_display.shutdown()
        pass

    
