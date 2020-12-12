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
# This file is a variant of kodi_panel.py that copies the Pillow image,
# via luma.lcd, to a framebuffer.
#
# The first version of this file make use of Pytorinox's
# framebuffer.py.  However, the 2.0.0 release of luma.core includes a
# new linux_framebuffer class.  Using it permits for fewer changes.
#
# ----------------------------------------------------------------------------
#
from luma.core import device

# kodi_panel modules
import config
import kodi_panel_display

# ----------------------------------------------------------------------------

# Use a Linux framebuffer via luma.core.device
device = device.linux_framebuffer("/dev/fb0",bgr=1)

# Don't try to use luma.lcd's backlight control
kodi_panel_display.USE_BACKLIGHT = False

if __name__ == "__main__":
    try:
        kodi_panel_display.main(device)
    except KeyboardInterrupt:
        kodi_panel_display.shutdown()
        pass
