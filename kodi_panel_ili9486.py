#
# MIT License -- see LICENSE.rst for details
# Copyright (c) 2020-21 Matthew Lovell and contributors
#
# ----------------------------------------------------------------------------
#
# kodi_panel for a SPI-attached ili9486 display
#
# ----------------------------------------------------------------------------

from luma.core.interface.serial import spi
from luma.core.render import canvas
from luma.lcd.device import ili9486

# kodi_panel modules
import config
import kodi_panel_display

# ----------------------------------------------------------------------------

# SPI interface & LCD display
#
#   GPIO pin connectivity is essentially the same as what is
#   documented in the ili9341 version of this script, except
#   for the touch interrupt pin.
#
#                 |  BCM /           |
#     LCD pin     |  RPi.GPIO name   |  Physical pin #
#     ------------|------------------|-----------------
#     CS          |  GPIO8           |  24
#     RST / RESET |  GPIO25          |  22
#     DC          |  GPIO24          |  18
#     MOSI        |  GPIO10 (MOSI)   |  19
#     SCLK / CLK  |  GPIO11 (SCLK)   |  23
#     LED (*)     |  GPIO18          |  12 
#     ------------|------------------|-----------------
#
#   The display I used, a 3.5-inch Waveshare IPS LCD (B)
#   panel, has a header on the back that is meant to directly
#   connect to an RPi's GPIO header.  Unless one wishes
#   to use jumper wires, there isn't a lot of choice for
#   the pin assignments.  It does permit for use of
#   a nice ribbon cable connector, though!
#
#   (*) As shipped, the Waveshare 3.5-inch (B) display turns
#       on the backlight whenever the display has power.
#       A small soldering change is required to let
#       GPIO18 control the backlight (whether on/off or
#       PWM).
#

serial = spi(port=0, device=0, gpio_DC=24, gpio_RST=25,
             reset_hold_time=0.2, reset_release_time=0.2)

device = ili9486(serial, active_low=False, width=320, height=480,
                 rotate=1, bus_speed_hz=50000000)

if __name__ == "__main__":
    try:
        kodi_panel_display.main(device)
    except KeyboardInterrupt:
        kodi_panel_display.shutdown()
        pass
