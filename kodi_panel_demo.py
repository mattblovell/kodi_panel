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
# This script is intended to aid in development since, using pygame as
# a device emulator with luma.lcd, one can prototype layout choices,
# play with different fonts, etc.
#
# As currently written, the script (and font and image subdirectories)
# must be copied to the
#
#   luma.examples/examples
#
# directory (after cloning it from github) and executed via a command
# like the following:
#
#   python kodi_panel_demo.py --display pygame --width 320 --height 240 --scale 1
#
# Screen touches are somewhat emulated within the main() update loop
# of kodi_panel_display by checking for a pressed key via pygame's
# state.  The state is polled only once per update loop, though, so
# one must hold the button for a bit.
#
# Since this script is usually running on a desktop machine, you MUST
# also specify the correct base_url via the settings TOML file.
#
# ----------------------------------------------------------------------------

from demo_opts import get_device      # from luma.examples (REQUIRED FOR EMULATION)

# kodi_panel modules
import config
import kodi_panel_display

# ----------------------------------------------------------------------------

# Handle to pygame emulator
device = get_device()

if __name__ == "__main__":
    kodi_panel_display.DEMO_MODE = True
    try:
        kodi_panel_display.main(device)
    except KeyboardInterrupt:
        kodi_panel_display.shutdown()
        pass
